"""Private company-scoped employee profile-image storage.

Security and consistency rules:
- Uploaded filenames are never used as filesystem paths.
- Only PNG/JPG/JPEG uploads are accepted and decoded with Pillow.
- Images are EXIF-normalized, center-cropped, resized, and re-encoded as PNG.
- Files live below company/employee directories and are never exposed directly.
- Replace/remove operations can be rolled back when the matching DB write fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError


@dataclass(slots=True)
class ProfileImageFileMutation:
    """One reversible filesystem mutation coordinated with a DB transaction."""

    final_path: Path
    backup_path: Path | None
    created_directories: tuple[Path, ...] = ()

    def _cleanup_empty_directories(self) -> None:
        """Remove only empty employee/company directories inside this mutation."""

        for directory in self.created_directories:
            try:
                directory.rmdir()
            except OSError:
                pass

    def rollback(self) -> None:
        """Restore the previous image after a database rollback/failure."""

        self.final_path.unlink(missing_ok=True)
        if self.backup_path is not None and self.backup_path.is_file():
            self.final_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.backup_path, self.final_path)
        self._cleanup_empty_directories()

    def finalize(self) -> None:
        """Delete the temporary backup after a successful database commit."""

        if self.backup_path is not None:
            try:
                self.backup_path.unlink(missing_ok=True)
            except OSError:
                # The database is already committed at this point. Do not
                # report a false save/delete failure because cleanup of an
                # internal backup file was temporarily blocked by the OS.
                pass
        self._cleanup_empty_directories()


class EmployeeProfileImageStorage:
    """Validate and store one canonical profile image per employee."""

    CANONICAL_FILENAME = "profile.png"
    ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
    ALLOWED_FORMATS = {"PNG", "JPEG"}
    ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg"}
    MAX_SOURCE_PIXELS = 20_000_000
    OUTPUT_SIZE = 512

    def __init__(self, root_dir: str | Path, *, max_mb: int = 5) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.max_bytes = max(1, int(max_mb)) * 1024 * 1024

    @staticmethod
    def _positive_id(value: int, *, label: str) -> int:
        normalized = int(value)
        if normalized <= 0:
            raise ValueError(f"A valid {label} is required.")
        return normalized

    def _employee_directory(self, *, company_id: int, employee_id: int) -> Path:
        safe_company_id = self._positive_id(company_id, label="company ID")
        safe_employee_id = self._positive_id(employee_id, label="employee ID")
        return self.root_dir / f"company_{safe_company_id}" / f"employee_{safe_employee_id}"

    def _profile_path(
        self,
        *,
        company_id: int,
        employee_id: int,
        filename: str | None = None,
    ) -> Path:
        safe_filename = Path(filename or self.CANONICAL_FILENAME).name
        if safe_filename != self.CANONICAL_FILENAME:
            raise ValueError("The stored employee profile-image filename is invalid.")

        path = (
            self._employee_directory(company_id=company_id, employee_id=employee_id)
            / safe_filename
        ).resolve()
        if self.root_dir not in path.parents:
            raise ValueError("Invalid employee profile-image path.")
        return path

    def prepare_png(
        self,
        *,
        file_name: str,
        content: bytes,
        content_type: str | None = None,
    ) -> bytes:
        """Decode, validate, center-crop, resize, and canonicalize an upload."""

        if not content:
            raise ValueError("Select a profile photo before saving.")
        if len(content) > self.max_bytes:
            raise ValueError(
                "The profile photo exceeds the configured file-size limit."
            )

        suffix = Path(file_name or "").suffix.lower()
        if suffix not in self.ALLOWED_EXTENSIONS:
            raise ValueError("Profile photo must be JPG, JPEG, or PNG.")

        normalized_type = (content_type or "").strip().lower()
        if normalized_type and normalized_type not in self.ALLOWED_CONTENT_TYPES:
            raise ValueError("The uploaded file is not a supported profile image.")

        try:
            with Image.open(BytesIO(content)) as source:
                image_format = str(source.format or "").upper()
                if image_format not in self.ALLOWED_FORMATS:
                    raise ValueError("Profile photo must be JPG, JPEG, or PNG.")

                # Do not accept a file merely renamed to a supported extension.
                if suffix == ".png" and image_format != "PNG":
                    raise ValueError("The uploaded .png file is not a valid PNG image.")
                if suffix in {".jpg", ".jpeg"} and image_format != "JPEG":
                    raise ValueError("The uploaded JPG/JPEG file is not a valid JPEG image.")

                width, height = source.size
                if width <= 0 or height <= 0 or width * height > self.MAX_SOURCE_PIXELS:
                    raise ValueError("The profile photo dimensions are too large.")

                source.load()
                image = ImageOps.exif_transpose(source).copy()
        except ValueError:
            raise
        except (UnidentifiedImageError, OSError, SyntaxError) as error:
            raise ValueError("The uploaded profile photo is not a valid image.") from error

        has_transparency = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        image = image.convert("RGBA" if has_transparency else "RGB")
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image = ImageOps.fit(
            image,
            (self.OUTPUT_SIZE, self.OUTPUT_SIZE),
            method=resampling,
            centering=(0.5, 0.5),
        )

        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    def read(
        self,
        *,
        company_id: int,
        employee_id: int,
        filename: str | None,
    ) -> bytes | None:
        """Read an authorized canonical image without exposing a path."""

        if not filename:
            return None
        try:
            path = self._profile_path(
                company_id=company_id,
                employee_id=employee_id,
                filename=filename,
            )
        except ValueError:
            return None
        if not path.is_file():
            return None
        return path.read_bytes()

    def stage_replace(
        self,
        *,
        company_id: int,
        employee_id: int,
        prepared_png: bytes,
    ) -> ProfileImageFileMutation:
        """Install a new image while keeping a rollback backup of the old one."""

        final_path = self._profile_path(company_id=company_id, employee_id=employee_id)
        employee_directory = final_path.parent
        company_directory = employee_directory.parent
        company_directory.mkdir(parents=True, exist_ok=True)
        employee_directory.mkdir(parents=True, exist_ok=True)

        backup_path: Path | None = None
        temporary_path = employee_directory / f".{uuid4().hex}.tmp"
        try:
            if final_path.is_file():
                backup_path = employee_directory / f".{uuid4().hex}.bak"
                os.replace(final_path, backup_path)

            temporary_path.write_bytes(prepared_png)
            os.replace(temporary_path, final_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            if backup_path is not None and backup_path.is_file():
                os.replace(backup_path, final_path)
            raise

        return ProfileImageFileMutation(
            final_path=final_path,
            backup_path=backup_path,
            created_directories=(employee_directory, company_directory),
        )

    def stage_remove(
        self,
        *,
        company_id: int,
        employee_id: int,
        filename: str | None,
    ) -> ProfileImageFileMutation:
        """Move an existing image aside until the DB removal commits."""

        final_path = self._profile_path(
            company_id=company_id,
            employee_id=employee_id,
            filename=filename or self.CANONICAL_FILENAME,
        )
        backup_path: Path | None = None
        if final_path.is_file():
            backup_path = final_path.parent / f".{uuid4().hex}.remove"
            os.replace(final_path, backup_path)

        return ProfileImageFileMutation(
            final_path=final_path,
            backup_path=backup_path,
            created_directories=(final_path.parent, final_path.parent.parent),
        )

    def delete_orphaned_employee_directory(
        self,
        *,
        company_id: int,
        employee_id: int,
    ) -> None:
        """Best-effort cleanup used after a permanent employee deletion."""

        employee_directory = self._employee_directory(
            company_id=company_id,
            employee_id=employee_id,
        )
        if not employee_directory.exists():
            return

        # This directory is dedicated exclusively to one employee's canonical
        # profile photo and internal transaction backups. Cleanup is best
        # effort because the database delete has already committed.
        try:
            children = list(employee_directory.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_file():
                continue
            try:
                child.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            employee_directory.rmdir()
        except OSError:
            return
        try:
            employee_directory.parent.rmdir()
        except OSError:
            pass
