"""Business logic for the editable Employee Master Record.

Flow:
Employees page -> validation schema -> service -> repositories -> database

The legacy role table is hidden from administrators. Clearance is the
user-facing access rule:
- 1 = Admin
- 2 = User
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from authentication.password_manager import PasswordManager
from core.constants import CLEARANCE_ADMIN, CLEARANCE_USER
from models.department import Department
from models.employee import Employee
from models.employee_history import EmployeeHistory
from models.employee_training import EmployeeTraining
from models.hr_policy import HRPolicy
from models.hr_policy_document import HRPolicyDocument
from models.password_reset_token import PasswordResetToken
from models.user import User
from repositories.department_repository import DepartmentRepository
from repositories.employee_repository import EmployeeRepository
from repositories.employee_history_repository import EmployeeHistoryRepository
from repositories.employee_training_repository import (
    EmployeeTrainingRepository,
)
from repositories.role_repository import RoleRepository
from repositories.user_repository import UserRepository
from schemas.admin_management_schema import (
    EmployeeAccountCreate,
    EmployeeDeleteRequest,
    EmployeeMasterUpdate,
)
from schemas.user_schema import EmployeeCreate, UserCreate
from services.employee_service import EmployeeService
from services.audit_trail_service import AuditTrailService
from services.edit_conflict import EditConflictError
from services.user_service import UserService



@dataclass(frozen=True, slots=True)
class EmployeeDeletionResult:
    """Summary returned after a permanent employee deletion."""

    employee_id: int
    employee_number: str
    full_name: str
    deleted_user_id: int | None
    cleared_manager_assignments: int


class AdminManagementService:

    """Coordinate company-scoped employee and account operations."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.employee_repository = EmployeeRepository(session)
        self.employee_history_repository = EmployeeHistoryRepository(session)
        self.training_repository = EmployeeTrainingRepository(session)
        self.role_repository = RoleRepository(session)
        self.department_repository = DepartmentRepository(session)
        self.password_manager = PasswordManager()

    def list_users(self, company_id: int) -> list[User]:
        """Compatibility helper for older integrations."""

        return self.user_repository.list_with_details(company_id)

    def list_employees(
        self,
        company_id: int,
    ) -> list[Employee]:
        """Return active employee master records for the main workspace."""

        return self.employee_repository.list_with_details(
            company_id,
            archived=False,
        )

    def list_archived_employees(self, company_id: int) -> list[Employee]:
        """Return resigned employees retained for archive and restoration."""

        return self.employee_repository.list_with_details(
            company_id,
            archived=True,
        )

    def list_employee_history(self, company_id: int) -> list[EmployeeHistory]:
        """Return newest-first employee workspace audit events."""

        return self.employee_history_repository.list_for_company(company_id)

    @staticmethod
    def _employee_snapshot(employee: Employee) -> dict[str, object]:
        """Return safe audit values without password data."""

        return {
            "employee_number": employee.employee_number,
            "first_name": employee.first_name,
            "middle_name": employee.middle_name,
            "last_name": employee.last_name,
            "suffix": employee.suffix,
            "work_email": employee.work_email,
            "telephone_mobile_no": employee.telephone_mobile_no,
            "job_title": employee.job_title,
            "department_id": employee.department_id,
            "manager_id": employee.manager_id,
            "leader_id": employee.leader_id,
            "hire_date": employee.hire_date.isoformat() if employee.hire_date else None,
            "date_of_birth": employee.date_of_birth.isoformat() if employee.date_of_birth else None,
            "gender": employee.gender,
            "civil_status": employee.civil_status,
            "employment_status": employee.employment_status,
            "username": employee.user.username if employee.user else None,
            "clearance": employee.user.clearance if employee.user else None,
            "account_active": employee.user.is_active if employee.user else None,
        }

    def _record_employee_history(
        self,
        *,
        employee: Employee,
        performed_by_user_id: int | None,
        action_type: str,
        summary: str,
        source: str = "manual",
        old_values: dict[str, object] | None = None,
        new_values: dict[str, object] | None = None,
        upload_batch_id: str | None = None,
        upload_filename: str | None = None,
    ) -> None:
        """Stage one immutable audit entry; caller controls the commit."""

        self.session.add(
            EmployeeHistory(
                company_id=employee.company_id,
                employee_id=employee.id,
                employee_number=employee.employee_number,
                employee_name=employee.full_name,
                performed_by_user_id=performed_by_user_id,
                action_type=action_type,
                source=source,
                summary=summary,
                old_values_json=(json.dumps(old_values, sort_keys=True) if old_values else None),
                new_values_json=(json.dumps(new_values, sort_keys=True) if new_values else None),
                upload_batch_id=upload_batch_id,
                upload_filename=upload_filename,
            )
        )

    def list_roles(self, company_id: int):
        """Compatibility helper; roles are no longer shown in the UI."""

        return self.role_repository.list_active(company_id)

    def list_departments(self, company_id: int):
        """Return active departments."""

        return self.department_repository.list_active(company_id)

    def list_managers(self, company_id: int):
        """Return employed workers available as managers."""

        return self.employee_repository.list_available_managers(
            company_id
        )

    def get_employee(
        self,
        *,
        company_id: int,
        employee_id: int,
    ) -> Employee:
        """Return one editable employee or raise a readable error."""

        employee = self.employee_repository.get_with_details(
            company_id=company_id,
            employee_id=employee_id,
        )

        if employee is None:
            raise ValueError(
                "The selected employee does not exist in this company."
            )

        return employee

    def _get_internal_role(
        self,
        *,
        company_id: int,
        clearance: int,
        legacy_role_id: int | None = None,
    ):
        """Map simple clearance to one hidden compatibility role."""

        if legacy_role_id is not None:
            role = self.role_repository.get_by_id(
                record_id=legacy_role_id,
                company_id=company_id,
            )
            if role is not None:
                return role

        role_name = (
            "company_admin"
            if clearance == CLEARANCE_ADMIN
            else "employee"
        )

        role = self.role_repository.get_by_name(
            company_id,
            role_name,
        )

        if role is None:
            raise ValueError(
                "Internal account access mapping is unavailable. "
                "Run: python scripts\\create_initial_data.py"
            )

        # Roles are internal compatibility records in this version.
        if not role.is_active:
            role.is_active = True
            self.session.commit()

        return role

    def _resolve_department(
        self,
        *,
        company_id: int,
        department_name: str | None,
        department_id: int | None = None,
    ) -> Department | None:
        """Return an existing department or create a typed department name."""

        if department_name and department_name.strip():
            normalized_name = department_name.strip()

            existing = next(
                (
                    department
                    for department in self.department_repository.list_all(
                        company_id
                    )
                    if department.name.strip().lower()
                    == normalized_name.lower()
                ),
                None,
            )

            if existing is not None:
                if not existing.is_active:
                    existing.is_active = True
                    self.session.commit()
                return existing

            return self.department_repository.create(
                {
                    "company_id": company_id,
                    "name": normalized_name,
                    "code": None,
                    "is_active": True,
                }
            )

        if department_id is not None:
            return self.department_repository.get_by_id(
                record_id=department_id,
                company_id=company_id,
            )

        return None

    @staticmethod
    def _account_is_active_for_status(
        employment_status: str,
    ) -> bool:
        """Map employment status to login-account availability.

        Business rule:
        - employed -> active account
        - resigned -> inactive account
        """

        normalized_status = employment_status.strip().lower()

        if normalized_status == "employed":
            return True

        if normalized_status == "resigned":
            return False

        raise ValueError(
            "Employment status must be Employed or Resigned."
        )

    def _sync_account_status(
        self,
        *,
        user: User,
        employment_status: str,
    ) -> None:
        """Synchronize one account with the employee's status."""

        user.is_active = self._account_is_active_for_status(
            employment_status
        )

    @staticmethod
    def _training_payload(values) -> list[dict[str, object]]:
        """Convert validated training inputs into repository values."""

        return [
            {
                "title": item.title.strip(),
                "is_completed": item.is_completed,
            }
            for item in values
            if item.title.strip()
        ]

    def create_employee_with_optional_account(
        self,
        values: EmployeeAccountCreate,
        *,
        current_user_id: int | None = None,
        source: str = "manual",
    ) -> Employee:
        """Create employee, account, department, and training checklist."""

        new_user: User | None = None
        department = self._resolve_department(
            company_id=values.company_id,
            department_name=values.department_name,
            department_id=values.department_id,
        )

        if values.create_login_account:
            role = self._get_internal_role(
                company_id=values.company_id,
                clearance=values.clearance,
                legacy_role_id=values.role_id,
            )

            new_user = UserService(self.session).create_user(
                UserCreate(
                    company_id=values.company_id,
                    role_id=role.id,
                    clearance=values.clearance,
                    username=str(values.username).strip(),
                    email=str(values.login_email),
                    password=str(values.temporary_password),
                ),
                must_change_password=True,
            )

        try:
            employee = EmployeeService(
                self.session
            ).create_employee(
                EmployeeCreate(
                    company_id=values.company_id,
                    user_id=(
                        new_user.id
                        if new_user
                        else None
                    ),
                    department_id=(
                        department.id
                        if department
                        else None
                    ),
                    manager_id=values.manager_id,
                    leader_id=values.leader_id,
                    employee_number=(
                        values.employee_number.strip()
                    ),
                    first_name=values.first_name.strip(),
                    middle_name=(
                        values.middle_name.strip()
                        if values.middle_name
                        else None
                    ),
                    last_name=values.last_name.strip(),
                    suffix=(
                        values.suffix.strip()
                        if values.suffix
                        else None
                    ),
                    work_email=values.work_email,
                    telephone_mobile_no=(
                        values.telephone_mobile_no.strip()
                        if values.telephone_mobile_no
                        else None
                    ),
                    job_title=(
                        values.job_title.strip()
                        if values.job_title
                        else None
                    ),
                    hire_date=values.hire_date,
                    date_of_birth=values.date_of_birth,
                    gender=(
                        values.gender.strip()
                        if values.gender
                        else None
                    ),
                    civil_status=(
                        values.civil_status.strip()
                        if values.civil_status
                        else None
                    ),
                    employment_status=(
                        values.employment_status
                    ),
                )
            )

            self.training_repository.replace_for_employee(
                company_id=values.company_id,
                employee_id=employee.id,
                items=self._training_payload(
                    values.trainings
                ),
            )

            # Employment status is the source of truth for account access.
            # Resigned records remain stored but cannot log in.
            if new_user is not None:
                self._sync_account_status(
                    user=new_user,
                    employment_status=(
                        values.employment_status
                    ),
                )
                self.session.commit()

            self._record_employee_history(
                employee=employee,
                performed_by_user_id=current_user_id,
                action_type=("archived" if values.employment_status == "resigned" else "created"),
                source=source,
                summary=("Employee created and archived as Resigned." if values.employment_status == "resigned" else "Employee and login account created."),
                new_values=self._employee_snapshot(employee),
            )
            if values.employment_status == "resigned":
                employee.archived_at = datetime.now(timezone.utc)
                employee.archived_by_user_id = current_user_id
            self.session.commit()

            # Expire cached relationships before returning the complete
            # newly created master record.
            self.session.expire_all()

            return self.get_employee(
                company_id=values.company_id,
                employee_id=employee.id,
            )

        except Exception:
            if new_user is not None:
                self.session.delete(new_user)
                self.session.commit()
            raise

    def update_employee_master_record(
        self,
        values: EmployeeMasterUpdate,
        *,
        current_user_id: int,
    ) -> Employee:
        """Update all editable employee, training, and account information."""

        employee = self.get_employee(
            company_id=values.company_id,
            employee_id=values.employee_id,
        )

        if employee.edit_version != values.expected_edit_version:
            self._record_employee_edit_conflict(
                employee=employee,
                current_user_id=current_user_id,
                submitted_version=values.expected_edit_version,
            )
        old_snapshot = self._employee_snapshot(employee)
        old_status = employee.employment_status

        duplicate_number = (
            self.employee_repository
            .get_by_employee_number_excluding(
                company_id=values.company_id,
                employee_number=(
                    values.employee_number.strip()
                ),
                employee_id=values.employee_id,
            )
        )

        if duplicate_number is not None:
            raise ValueError(
                f"Employee number '{values.employee_number}' "
                "already exists inside this company."
            )

        current_name = self.employee_repository.normalized_person_name(
            employee.first_name,
            employee.middle_name,
            employee.last_name,
            employee.suffix,
        )
        submitted_name = self.employee_repository.normalized_person_name(
            values.first_name,
            values.middle_name,
            values.last_name,
            values.suffix,
        )
        duplicate_names = (
            self.employee_repository.find_normalized_name_matches(
                company_id=values.company_id,
                first_name=values.first_name,
                middle_name=values.middle_name,
                last_name=values.last_name,
                suffix=values.suffix,
                exclude_employee_id=values.employee_id,
            )
            if submitted_name != current_name
            else []
        )
        if duplicate_names:
            duplicate = duplicate_names[0]
            raise ValueError(
                "Possible duplicate employee record: "
                f"{duplicate.employee_number} — {duplicate.full_name}. "
                "Review the existing employee record before saving."
            )

        if (
            values.manager_id is not None
            and values.manager_id == values.employee_id
        ):
            raise ValueError(
                "An employee cannot be assigned as their own manager."
            )

        if (
            values.leader_id is not None
            and values.leader_id == values.employee_id
        ):
            raise ValueError(
                "An employee cannot be assigned as their own leader."
            )

        department = self._resolve_department(
            company_id=values.company_id,
            department_name=values.department_name,
        )

        user = employee.user

        if user is None:
            if not values.new_temporary_password:
                raise ValueError(
                    "A temporary password is required because this "
                    "employee does not have a login account yet."
                )

            role = self._get_internal_role(
                company_id=values.company_id,
                clearance=values.clearance,
            )

            user = UserService(self.session).create_user(
                UserCreate(
                    company_id=values.company_id,
                    role_id=role.id,
                    clearance=values.clearance,
                    username=values.username.strip(),
                    email=str(values.work_email),
                    password=values.new_temporary_password,
                ),
                must_change_password=True,
            )

            employee.user_id = user.id

        else:
            duplicate_username = (
                self.user_repository.get_by_username_excluding(
                    company_id=values.company_id,
                    username=values.username.strip(),
                    user_id=user.id,
                )
            )

            if duplicate_username is not None:
                raise ValueError(
                    f"Username '{values.username}' already exists "
                    "inside this company."
                )

            duplicate_email = (
                self.user_repository.get_by_email_excluding(
                    company_id=values.company_id,
                    email=str(values.work_email),
                    user_id=user.id,
                )
            )

            if duplicate_email is not None:
                raise ValueError(
                    f"Email '{values.work_email}' already exists "
                    "inside this company."
                )

            role = self._get_internal_role(
                company_id=values.company_id,
                clearance=values.clearance,
            )

            user.username = values.username.strip()
            user.email = str(values.work_email)
            user.clearance = values.clearance
            user.role_id = role.id

            if values.new_temporary_password:
                user.password_hash = (
                    self.password_manager.hash_password(
                        values.new_temporary_password
                    )
                )
                user.must_change_password = True

        # Prevent an administrator from removing their own current access.
        if user.id == current_user_id:
            if values.clearance != CLEARANCE_ADMIN:
                raise ValueError(
                    "You cannot change your own active clearance to User."
                )
            if values.employment_status == "resigned":
                raise ValueError(
                    "You cannot mark your own active account as resigned."
                )

        employee.employee_number = (
            values.employee_number.strip()
        )
        employee.first_name = values.first_name.strip()
        employee.middle_name = (
            values.middle_name.strip()
            if values.middle_name
            else None
        )
        employee.last_name = values.last_name.strip()
        employee.suffix = (
            values.suffix.strip()
            if values.suffix
            else None
        )
        employee.work_email = str(values.work_email)
        employee.telephone_mobile_no = (
            values.telephone_mobile_no.strip()
            if values.telephone_mobile_no
            else None
        )
        employee.job_title = (
            values.job_title.strip()
            if values.job_title
            else None
        )
        employee.hire_date = values.hire_date
        employee.date_of_birth = values.date_of_birth
        employee.gender = (
            values.gender.strip()
            if values.gender
            else None
        )
        employee.civil_status = (
            values.civil_status.strip()
            if values.civil_status
            else None
        )
        employee.employment_status = (
            values.employment_status
        )
        if values.employment_status == "resigned":
            employee.archived_at = employee.archived_at or datetime.now(timezone.utc)
            employee.archived_by_user_id = current_user_id
        elif old_status == "resigned":
            employee.archived_at = None
            employee.archived_by_user_id = None
        employee.department_id = (
            department.id
            if department
            else None
        )
        # Assign the relationship as well as the foreign key so the same
        # SQLAlchemy session does not return a stale cached value.
        employee.department = department
        employee.manager_id = values.manager_id
        employee.leader_id = values.leader_id

        # Synchronize in both directions:
        # Employed activates, Resigned deactivates.
        self._sync_account_status(
            user=user,
            employment_status=values.employment_status,
        )

        # Force one Employee-row write even when only account or training
        # values changed. SQLAlchemy includes the previous edit_version in the
        # UPDATE predicate, providing an atomic second guard for simultaneous
        # saves that passed the earlier friendly comparison at the same time.
        employee.last_edited_by_user_id = current_user_id
        employee.edit_version += 1

        try:
            self.session.commit()
        except StaleDataError:
            self.session.rollback()
            latest = self.get_employee(
                company_id=values.company_id,
                employee_id=values.employee_id,
            )
            self._record_employee_edit_conflict(
                employee=latest,
                current_user_id=current_user_id,
                submitted_version=values.expected_edit_version,
            )

        self.training_repository.replace_for_employee(
            company_id=values.company_id,
            employee_id=employee.id,
            items=self._training_payload(
                values.trainings
            ),
        )

        self.session.expire_all()
        refreshed = self.get_employee(
            company_id=values.company_id,
            employee_id=employee.id,
        )
        new_snapshot = self._employee_snapshot(refreshed)
        changed_old = {
            key: value
            for key, value in old_snapshot.items()
            if new_snapshot.get(key) != value
        }
        changed_new = {
            key: value
            for key, value in new_snapshot.items()
            if old_snapshot.get(key) != value
        }
        action_type = "updated"
        summary = "Employee information or account settings updated."
        if old_status != "resigned" and values.employment_status == "resigned":
            action_type = "archived"
            summary = "Employment status changed to Resigned; account deactivated and record archived."
        elif old_status == "resigned" and values.employment_status == "employed":
            action_type = "restored"
            summary = "Archived employee restored to Employed and account reactivated."
        self._record_employee_history(
            employee=refreshed,
            performed_by_user_id=current_user_id,
            action_type=action_type,
            summary=summary,
            old_values=changed_old or None,
            new_values=changed_new or None,
        )
        self.session.commit()

        # Reload all joined relationships after profile, account,
        # department, manager, and training updates.
        self.session.expire_all()

        return self.get_employee(
            company_id=values.company_id,
            employee_id=employee.id,
        )

    @staticmethod
    def _employee_conflict_snapshot(employee: Employee) -> dict[str, object]:
        """Return readable latest values for the Admin comparison panel."""

        return {
            "Employee Number": employee.employee_number,
            "Last Name": employee.last_name,
            "First Name": employee.first_name,
            "Middle Name": employee.middle_name,
            "Suffix": employee.suffix,
            "Email": employee.work_email,
            "Telephone / Mobile No.": employee.telephone_mobile_no,
            "Job Title / Position": employee.job_title,
            "Department": employee.department.name if employee.department else None,
            "Manager": employee.manager.full_name if employee.manager else None,
            "Leader": employee.leader.full_name if employee.leader else None,
            "Gender": employee.gender,
            "Civil Status": employee.civil_status,
            "Date of Birth": (
                employee.date_of_birth.isoformat()
                if employee.date_of_birth
                else None
            ),
            "Employment Status": employee.employment_status,
            "Hired Date": employee.hire_date.isoformat() if employee.hire_date else None,
            "Training": "\n".join(
                f"[{'x' if item.is_completed else ' '}] {item.title}"
                for item in employee.trainings
            ),
            "User Name": employee.user.username if employee.user else None,
            "Clearance": employee.user.clearance if employee.user else None,
        }

    def _record_employee_edit_conflict(
        self,
        *,
        employee: Employee,
        current_user_id: int,
        submitted_version: int,
    ) -> None:
        """Commit the blocked attempt, then raise a structured UI conflict."""

        latest_history = self.employee_history_repository.get_latest_for_employee(
            company_id=employee.company_id,
            employee_id=employee.id,
        )
        updated_by_user_id = employee.last_edited_by_user_id
        if updated_by_user_id is None and latest_history is not None:
            updated_by_user_id = latest_history.performed_by_user_id
        updated_at = (
            latest_history.created_at
            if latest_history is not None
            else employee.updated_at
        )
        updated_by = "another administrator"
        if updated_by_user_id is not None:
            user = self.user_repository.get_for_password_change(
                employee.company_id,
                updated_by_user_id,
            )
            if user is not None:
                updated_by = (
                    user.employee.full_name
                    if user.employee is not None
                    else user.username
                )

        latest_values = self._employee_conflict_snapshot(employee)
        AuditTrailService(self.session).record_event(
            company_id=employee.company_id,
            actor_user_id=current_user_id,
            module="Employees",
            action="Save Blocked",
            entity_type="Employee",
            entity_id=employee.id,
            entity_label=f"{employee.employee_number} — {employee.full_name}",
            result="conflict_blocked",
            summary=(
                "An outdated Employee edit was blocked before it could "
                "overwrite a newer administrator change."
            ),
            new_values=latest_values,
            metadata={
                "submitted_edit_version": submitted_version,
                "latest_edit_version": employee.edit_version,
                "latest_updated_by": updated_by,
                "latest_updated_at": (
                    updated_at.isoformat() if updated_at is not None else None
                ),
            },
        )
        raise EditConflictError(
            module="Employees",
            entity_label=f"{employee.employee_number} — {employee.full_name}",
            latest_version=employee.edit_version,
            latest_values=latest_values,
            updated_by=updated_by,
            updated_at=updated_at,
        )

    def restore_archived_employee(
        self,
        *,
        company_id: int,
        employee_id: int,
        current_user_id: int,
    ) -> Employee:
        """Restore one resigned employee without creating duplicate records."""

        employee = self.get_employee(
            company_id=company_id,
            employee_id=employee_id,
        )
        if employee.employment_status != "resigned":
            raise ValueError("The selected employee is not archived.")
        old_snapshot = self._employee_snapshot(employee)
        employee.employment_status = "employed"
        employee.last_edited_by_user_id = current_user_id
        employee.edit_version += 1
        employee.archived_at = None
        employee.archived_by_user_id = None
        if employee.user is not None:
            employee.user.is_active = True
        self.session.flush()
        new_snapshot = self._employee_snapshot(employee)
        self._record_employee_history(
            employee=employee,
            performed_by_user_id=current_user_id,
            action_type="restored",
            summary="Archived employee restored to Employed; linked login account reactivated.",
            old_values={key: value for key, value in old_snapshot.items() if new_snapshot.get(key) != value},
            new_values={key: value for key, value in new_snapshot.items() if old_snapshot.get(key) != value},
        )
        self.session.commit()
        self.session.expire_all()
        return self.get_employee(company_id=company_id, employee_id=employee_id)

    def _count_policy_history_for_user(
        self,
        *,
        company_id: int,
        user_id: int,
    ) -> int:
        """Count policy records that must retain their user identity."""

        policy_count = self.session.scalar(
            select(func.count(HRPolicy.id)).where(
                HRPolicy.company_id == company_id,
                HRPolicy.created_by_user_id == user_id,
            )
        ) or 0

        document_count = self.session.scalar(
            select(func.count(HRPolicyDocument.id)).where(
                HRPolicyDocument.company_id == company_id,
                HRPolicyDocument.uploaded_by_user_id == user_id,
            )
        ) or 0

        return int(policy_count) + int(document_count)

    def delete_employee_master_record(
        self,
        request: EmployeeDeleteRequest,
        *,
        current_user_id: int,
    ) -> EmployeeDeletionResult:
        """Permanently delete an employee and its linked login account.

        The operation is blocked for the signed-in administrator and for
        accounts referenced by policy history. Direct reports remain but
        their manager assignment is cleared. Departments are preserved.
        """

        employee = self.get_employee(
            company_id=request.company_id,
            employee_id=request.employee_id,
        )

        employee_id = employee.id
        employee_number = employee.employee_number.strip()
        full_name = employee.full_name
        linked_user_id = (
            employee.user.id
            if employee.user is not None
            else None
        )

        if linked_user_id == current_user_id:
            raise ValueError(
                "You cannot permanently delete your own active "
                "administrator account."
            )

        if (
            linked_user_id is not None
            and self._count_policy_history_for_user(
                company_id=request.company_id,
                user_id=linked_user_id,
            )
            > 0
        ):
            raise ValueError(
                "This account is referenced by policy history and "
                "cannot be permanently deleted. Change the employee "
                "status to Resigned instead."
            )

        self._record_employee_history(
            employee=employee,
            performed_by_user_id=current_user_id,
            action_type="permanently_deleted",
            summary="Employee profile and eligible linked login account permanently deleted.",
            old_values=self._employee_snapshot(employee),
        )
        self.session.flush()

        direct_report_ids = list(
            self.session.scalars(
                select(Employee.id).where(
                    Employee.company_id == request.company_id,
                    Employee.manager_id == employee_id,
                )
            ).all()
        )

        if direct_report_ids:
            self.session.execute(
                update(Employee)
                .where(
                    Employee.company_id == request.company_id,
                    Employee.manager_id == employee_id,
                )
                .values(manager_id=None)
                .execution_options(
                    synchronize_session=False
                )
            )

        self.session.execute(
            delete(EmployeeTraining)
            .where(
                EmployeeTraining.company_id
                == request.company_id,
                EmployeeTraining.employee_id
                == employee_id,
            )
            .execution_options(
                synchronize_session=False
            )
        )

        self.session.execute(
            delete(Employee)
            .where(
                Employee.company_id == request.company_id,
                Employee.id == employee_id,
            )
            .execution_options(
                synchronize_session=False
            )
        )

        if linked_user_id is not None:
            self.session.execute(
                delete(PasswordResetToken)
                .where(
                    PasswordResetToken.company_id
                    == request.company_id,
                    PasswordResetToken.user_id
                    == linked_user_id,
                )
                .execution_options(
                    synchronize_session=False
                )
            )

            self.session.execute(
                delete(User)
                .where(
                    User.company_id == request.company_id,
                    User.id == linked_user_id,
                )
                .execution_options(
                    synchronize_session=False
                )
            )

        self.session.commit()
        self.session.expire_all()

        return EmployeeDeletionResult(
            employee_id=employee_id,
            employee_number=employee_number,
            full_name=full_name,
            deleted_user_id=linked_user_id,
            cleared_manager_assignments=len(
                direct_report_ids
            ),
        )

    def set_user_active_status(
        self,
        *,
        company_id: int,
        user_id: int,
        is_active: bool,
        current_user_id: int,
    ) -> User:
        """Compatibility helper retained for older integrations."""

        if user_id == current_user_id and not is_active:
            raise ValueError(
                "You cannot deactivate your own active session."
            )

        user = self.user_repository.update_active_status(
            company_id=company_id,
            user_id=user_id,
            is_active=is_active,
        )

        if user is None:
            raise ValueError(
                "The selected user does not exist inside this company."
            )

        return user
