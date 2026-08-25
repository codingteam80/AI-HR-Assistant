"""Employee profile-photo business logic and authorization.

The image itself is stored on disk. The Employee row stores only the
canonical filename reference. Disk mutations are reversible until the
matching database transaction commits, which avoids stale/orphaned files
when a save fails.
"""

from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from config.settings import get_settings
from core.constants import CLEARANCE_ADMIN
from models.employee import Employee
from models.employee_history import EmployeeHistory
from modules.employees.profile_image_storage import EmployeeProfileImageStorage


class EmployeeProfileImageService:
    """Manage one company-scoped profile image per employee."""

    def __init__(self, session: Session) -> None:
        self.session = session
        settings = get_settings()
        self.storage = EmployeeProfileImageStorage(
            settings.employee_profile_image_dir,
            max_mb=settings.employee_profile_image_max_mb,
        )

    def _employee(
        self,
        *,
        company_id: int,
        employee_id: int,
    ) -> Employee:
        employee = self.session.scalar(
            select(Employee).where(
                Employee.company_id == int(company_id),
                Employee.id == int(employee_id),
            )
        )
        if employee is None:
            raise ValueError("The selected employee does not exist in this company.")
        return employee

    @staticmethod
    def _authorize(
        employee: Employee,
        *,
        actor_user_id: int,
        actor_clearance: int,
    ) -> None:
        """Allow administrators or the employee's own linked account only."""

        if int(actor_clearance) == CLEARANCE_ADMIN:
            return
        if employee.user_id is None or int(employee.user_id) != int(actor_user_id):
            raise PermissionError("You may only manage your own profile photo.")

    @staticmethod
    def _history(
        *,
        employee: Employee,
        actor_user_id: int,
        action_type: str,
        summary: str,
        old_present: bool,
        new_present: bool,
    ) -> EmployeeHistory:
        return EmployeeHistory(
            company_id=employee.company_id,
            employee_id=employee.id,
            employee_number=employee.employee_number,
            employee_name=employee.full_name,
            performed_by_user_id=actor_user_id,
            action_type=action_type,
            source="profile_photo",
            summary=summary,
            old_values_json=json.dumps(
                {"profile_photo": "Present" if old_present else "None"},
                sort_keys=True,
            ),
            new_values_json=json.dumps(
                {"profile_photo": "Present" if new_present else "None"},
                sort_keys=True,
            ),
        )

    def prepare_preview(
        self,
        *,
        file_name: str,
        content: bytes,
        content_type: str | None,
    ) -> bytes:
        """Validate and normalize an upload without storing it."""

        return self.storage.prepare_png(
            file_name=file_name,
            content=content,
            content_type=content_type,
        )

    def get_profile_image_bytes(
        self,
        *,
        company_id: int,
        employee_id: int,
        actor_user_id: int,
        actor_clearance: int,
    ) -> bytes | None:
        """Return a private image only to an admin or the employee themself."""

        employee = self._employee(company_id=company_id, employee_id=employee_id)
        self._authorize(
            employee,
            actor_user_id=actor_user_id,
            actor_clearance=actor_clearance,
        )
        return self.storage.read(
            company_id=employee.company_id,
            employee_id=employee.id,
            filename=employee.profile_image_filename,
        )

    def save_profile_image(
        self,
        *,
        company_id: int,
        employee_id: int,
        actor_user_id: int,
        actor_clearance: int,
        file_name: str,
        content: bytes,
        content_type: str | None,
    ) -> str:
        """Validate and save a profile image with DB/filesystem rollback safety."""

        employee = self._employee(company_id=company_id, employee_id=employee_id)
        self._authorize(
            employee,
            actor_user_id=actor_user_id,
            actor_clearance=actor_clearance,
        )
        prepared = self.prepare_preview(
            file_name=file_name,
            content=content,
            content_type=content_type,
        )
        old_present = bool(employee.profile_image_filename)
        mutation = self.storage.stage_replace(
            company_id=company_id,
            employee_id=employee_id,
            prepared_png=prepared,
        )

        try:
            self.session.execute(
                update(Employee)
                .where(
                    Employee.company_id == int(company_id),
                    Employee.id == int(employee_id),
                )
                .values(
                    profile_image_filename=self.storage.CANONICAL_FILENAME,
                )
                .execution_options(synchronize_session=False)
            )
            self.session.add(
                self._history(
                    employee=employee,
                    actor_user_id=actor_user_id,
                    action_type=(
                        "profile_photo_replaced" if old_present else "profile_photo_uploaded"
                    ),
                    summary=(
                        "Employee profile photo replaced."
                        if old_present
                        else "Employee profile photo uploaded."
                    ),
                    old_present=old_present,
                    new_present=True,
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            mutation.rollback()
            raise

        mutation.finalize()
        return self.storage.CANONICAL_FILENAME

    def remove_profile_image(
        self,
        *,
        company_id: int,
        employee_id: int,
        actor_user_id: int,
        actor_clearance: int,
    ) -> bool:
        """Remove a profile image and return whether a stored reference existed."""

        employee = self._employee(company_id=company_id, employee_id=employee_id)
        self._authorize(
            employee,
            actor_user_id=actor_user_id,
            actor_clearance=actor_clearance,
        )
        old_present = bool(employee.profile_image_filename)
        if not old_present:
            return False

        mutation = self.storage.stage_remove(
            company_id=company_id,
            employee_id=employee_id,
            filename=employee.profile_image_filename,
        )
        try:
            self.session.execute(
                update(Employee)
                .where(
                    Employee.company_id == int(company_id),
                    Employee.id == int(employee_id),
                )
                .values(profile_image_filename=None)
                .execution_options(synchronize_session=False)
            )
            self.session.add(
                self._history(
                    employee=employee,
                    actor_user_id=actor_user_id,
                    action_type="profile_photo_removed",
                    summary="Employee profile photo removed; default initials avatar restored.",
                    old_present=True,
                    new_present=False,
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            mutation.rollback()
            raise

        mutation.finalize()
        return True

    def purge_profile_image_files_after_employee_delete(
        self,
        *,
        company_id: int,
        employee_id: int,
    ) -> None:
        """Remove the dedicated profile-image directory after permanent delete."""

        self.storage.delete_orphaned_employee_directory(
            company_id=company_id,
            employee_id=employee_id,
        )
