"""Private company-logo validation and file storage.

Flow:
Company Profile UI -> OrganizationService -> CompanyLogoStorage -> disk

Security rules:
- Every logo is stored below a company_id directory.
- User-supplied filenames are never used as filesystem paths.
- Accepted images are decoded and re-encoded as a canonical PNG.
- Aspect ratio is preserved and oversized images are reduced safely.
"""

from io import BytesIO
import colorsys
import math
import os
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


def extract_logo_theme_colors(
    image_bytes: bytes,
    *,
    max_colors: int = 4,
) -> list[str]:
    """Return useful accent-color suggestions sampled from a logo.

    Transparent, nearly white, nearly black, and low-saturation pixels are
    de-prioritized so the result favors actual brand colors instead of the
    logo canvas or text. The function never stores the image.
    """

    if not image_bytes or max_colors <= 0:
        return []

    try:
        with Image.open(BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            image.thumbnail((240, 240), resampling)
            pixels = []

            pixel_data = (
                image.get_flattened_data()
                if hasattr(image, "get_flattened_data")
                else image.getdata()
            )

            for red, green, blue, alpha in pixel_data:
                if alpha < 48:
                    continue

                maximum = max(red, green, blue)
                minimum = min(red, green, blue)
                brightness = (red + green + blue) / 3
                saturation = (
                    (maximum - minimum) / maximum
                    if maximum
                    else 0.0
                )

                if brightness >= 245 and saturation < 0.15:
                    continue

                if brightness <= 22 and saturation < 0.20:
                    continue

                pixels.append((red, green, blue))

    except (UnidentifiedImageError, OSError, SyntaxError):
        return []

    if not pixels:
        return []

    sample = Image.new("RGB", (len(pixels), 1))
    sample.putdata(pixels)
    quantized = sample.quantize(
        colors=min(16, max(6, max_colors * 3)),
        method=Image.Quantize.MEDIANCUT,
    )
    palette = quantized.getpalette() or []
    ranked = sorted(
        quantized.getcolors() or [],
        key=lambda item: item[0],
        reverse=True,
    )

    candidates: list[tuple[float, tuple[int, int, int]]] = []

    for count, palette_index in ranked:
        offset = palette_index * 3

        if offset + 2 >= len(palette):
            continue

        rgb = tuple(palette[offset:offset + 3])
        red, green, blue = rgb
        _, saturation, value = colorsys.rgb_to_hsv(
            red / 255,
            green / 255,
            blue / 255,
        )

        # Brand accents should be visible on both light and dark surfaces.
        if saturation < 0.16 or value < 0.16 or value > 0.97:
            continue

        score = count * (0.55 + saturation)
        candidates.append((score, rgb))

    if not candidates:
        for count, palette_index in ranked:
            offset = palette_index * 3

            if offset + 2 < len(palette):
                candidates.append(
                    (float(count), tuple(palette[offset:offset + 3]))
                )

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected: list[tuple[int, int, int]] = []

    for _, rgb in candidates:
        if any(
            math.dist(rgb, existing) < 52
            for existing in selected
        ):
            continue

        selected.append(rgb)

        if len(selected) >= max_colors:
            break

    return [
        "#{:02X}{:02X}{:02X}".format(*rgb)
        for rgb in selected
    ]


class CompanyLogoStorage:
    """Validate and store one canonical logo per company."""

    CANONICAL_FILENAME = "company_logo.png"
    ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
    ALLOWED_CONTENT_TYPES = {
        "image/png",
        "image/jpeg",
        "image/webp",
    }
    MAX_SOURCE_PIXELS = 20_000_000
    MAX_OUTPUT_WIDTH = 1600
    MAX_OUTPUT_HEIGHT = 800

    def __init__(
        self,
        root_dir: str | Path,
        *,
        max_mb: int = 5,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.max_bytes = max(1, int(max_mb)) * 1024 * 1024

    def _company_directory(self, company_id: int) -> Path:
        """Return a company-isolated storage directory."""

        safe_company_id = int(company_id)

        if safe_company_id <= 0:
            raise ValueError("A valid company ID is required.")

        return self.root_dir / str(safe_company_id)

    def _logo_path(
        self,
        company_id: int,
        filename: str | None = None,
    ) -> Path:
        """Return only the canonical company-logo path."""

        safe_filename = Path(
            filename or self.CANONICAL_FILENAME
        ).name

        if safe_filename != self.CANONICAL_FILENAME:
            raise ValueError("The stored company-logo filename is invalid.")

        return self._company_directory(company_id) / safe_filename

    def _prepare_png(
        self,
        *,
        file_name: str,
        content: bytes,
        content_type: str | None,
    ) -> bytes:
        """Decode, validate, resize, and re-encode an uploaded image."""

        if not content:
            raise ValueError("Select a company logo before saving.")

        if len(content) > self.max_bytes:
            raise ValueError(
                "The company logo exceeds the configured file-size limit."
            )

        suffix = Path(file_name or "").suffix.lower()

        if suffix not in self.ALLOWED_EXTENSIONS:
            raise ValueError(
                "Company logo must be PNG, JPG, JPEG, or WEBP."
            )

        normalized_type = (content_type or "").strip().lower()

        if (
            normalized_type
            and normalized_type not in self.ALLOWED_CONTENT_TYPES
        ):
            raise ValueError("The uploaded file is not a supported image.")

        try:
            with Image.open(BytesIO(content)) as source:
                image_format = str(source.format or "").upper()

                if image_format not in self.ALLOWED_FORMATS:
                    raise ValueError(
                        "Company logo must be PNG, JPG, JPEG, or WEBP."
                    )

                width, height = source.size

                if (
                    width <= 0
                    or height <= 0
                    or width * height > self.MAX_SOURCE_PIXELS
                ):
                    raise ValueError(
                        "The company logo dimensions are too large."
                    )

                source.load()
                prepared = ImageOps.exif_transpose(source).copy()

        except ValueError:
            raise
        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
        ) as error:
            raise ValueError(
                "The uploaded company logo is not a valid image."
            ) from error

        has_transparency = (
            prepared.mode in {"RGBA", "LA"}
            or "transparency" in prepared.info
        )
        prepared = prepared.convert(
            "RGBA" if has_transparency else "RGB"
        )

        resampling = getattr(
            Image,
            "Resampling",
            Image,
        ).LANCZOS
        prepared.thumbnail(
            (
                self.MAX_OUTPUT_WIDTH,
                self.MAX_OUTPUT_HEIGHT,
            ),
            resampling,
        )

        output = BytesIO()
        prepared.save(
            output,
            format="PNG",
            optimize=True,
        )

        return output.getvalue()

    def save(
        self,
        *,
        company_id: int,
        file_name: str,
        content: bytes,
        content_type: str | None = None,
    ) -> str:
        """Atomically save and return the canonical database filename."""

        prepared = self._prepare_png(
            file_name=file_name,
            content=content,
            content_type=content_type,
        )
        company_directory = self._company_directory(company_id)
        company_directory.mkdir(
            parents=True,
            exist_ok=True,
        )
        final_path = self._logo_path(company_id)
        temporary_path = final_path.with_suffix(".tmp")
        temporary_path.write_bytes(prepared)
        os.replace(temporary_path, final_path)

        return self.CANONICAL_FILENAME

    def read(
        self,
        *,
        company_id: int,
        filename: str | None,
    ) -> bytes | None:
        """Return the private logo bytes when the canonical file exists."""

        if not filename:
            return None

        try:
            logo_path = self._logo_path(
                company_id,
                filename,
            )
        except ValueError:
            return None

        if not logo_path.is_file():
            return None

        return logo_path.read_bytes()

    def delete(
        self,
        *,
        company_id: int,
        filename: str | None,
    ) -> None:
        """Delete the canonical logo and its empty company directory."""

        if not filename:
            return

        try:
            logo_path = self._logo_path(
                company_id,
                filename,
            )
        except ValueError:
            return

        logo_path.unlink(missing_ok=True)
        company_directory = self._company_directory(company_id)

        try:
            company_directory.rmdir()
        except OSError:
            # Keep a non-empty directory; no other files are deleted.
            pass
