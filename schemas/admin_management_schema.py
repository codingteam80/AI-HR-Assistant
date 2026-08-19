"""Validation schemas for employee master-record create and edit forms."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


class TrainingItemInput(BaseModel):
    """One checklist item entered in the employee form."""

    title: str = Field(min_length=1, max_length=255)
    is_completed: bool = False


class EmployeeAccountCreate(BaseModel):
    """Validated employee, training, and login-account values."""

    company_id: int
    employee_number: str = Field(min_length=1, max_length=80)
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    suffix: str | None = Field(default=None, max_length=30)
    work_email: EmailStr | None = None
    telephone_mobile_no: str | None = Field(
        default=None,
        max_length=50,
    )
    job_title: str | None = Field(default=None, max_length=150)
    hire_date: date | None = None
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=50)
    civil_status: str | None = Field(default=None, max_length=50)
    employment_status: Literal["employed", "resigned"] = "employed"

    # Direct department entry is supported. Existing callers may still pass
    # department_id during the transition.
    department_name: str | None = Field(default=None, max_length=150)
    department_id: int | None = None
    manager_id: int | None = None
    leader_id: int | None = None

    trainings: list[TrainingItemInput] = Field(default_factory=list)

    # Normal UI onboarding creates an account. The false value remains
    # available for imports and legacy profile-only tests.
    create_login_account: bool = False
    username: str | None = Field(default=None, max_length=100)
    login_email: EmailStr | None = None
    temporary_password: str | None = Field(default=None, max_length=128)
    clearance: Literal[1, 2] = 2

    # Retained only for compatibility with earlier service integrations.
    role_id: int | None = None

    @model_validator(mode="after")
    def validate_login_account(self):
        """Require complete and secure account data when account is created."""

        if not self.create_login_account:
            return self

        required_values = {
            "username": self.username,
            "login email": self.login_email,
            "temporary password": self.temporary_password,
        }

        missing = [
            name
            for name, value in required_values.items()
            if value in (None, "")
        ]

        if missing:
            raise ValueError(
                "Login account requires: "
                + ", ".join(missing)
                + "."
            )

        if (
            self.temporary_password
            and len(self.temporary_password) < 8
        ):
            raise ValueError(
                "Temporary password must contain at least 8 characters."
            )

        return self


class EmployeeMasterUpdate(BaseModel):
    """Validated editable values for one existing employee."""

    company_id: int
    employee_id: int
    expected_edit_version: int = Field(ge=1)

    employee_number: str = Field(min_length=1, max_length=80)
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    suffix: str | None = Field(default=None, max_length=30)

    work_email: EmailStr
    telephone_mobile_no: str | None = Field(
        default=None,
        max_length=50,
    )
    job_title: str | None = Field(default=None, max_length=150)
    hire_date: date | None = None
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=50)
    civil_status: str | None = Field(default=None, max_length=50)
    employment_status: Literal["employed", "resigned"]

    department_name: str | None = Field(default=None, max_length=150)
    manager_id: int | None = None
    leader_id: int | None = None
    trainings: list[TrainingItemInput] = Field(default_factory=list)

    username: str = Field(min_length=3, max_length=100)
    clearance: Literal[1, 2]
    new_temporary_password: str | None = Field(
        default=None,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_update(self):
        """Validate manager and optional password rules."""

        if (
            self.new_temporary_password
            and len(self.new_temporary_password) < 8
        ):
            raise ValueError(
                "New temporary password must contain at least 8 characters."
            )

        return self



class EmployeeDeleteRequest(BaseModel):
    """Validated permanent employee deletion request."""

    company_id: int
    employee_id: int
    # Retained as an optional legacy field for older integrations.
    # The current UI confirms deletion through the selected employee and
    # an explicit acknowledgment checkbox instead of typed re-entry.
    confirmation_employee_number: str | None = Field(
        default=None,
        max_length=80,
    )
    permanent_delete_acknowledged: bool

    @model_validator(mode="after")
    def validate_acknowledgment(self):
        """Require explicit acknowledgment for irreversible deletion."""

        if not self.permanent_delete_acknowledged:
            raise ValueError(
                "Confirm that this employee record will be "
                "permanently deleted."
            )

        return self
