"""Session-safe authenticated-user information."""

from dataclasses import asdict, dataclass

from models.user import User


@dataclass(slots=True)
class AuthenticatedUser:
    """Safe identity and access information stored in Streamlit state."""

    user_id: int
    company_id: int
    company_code: str
    company_name: str

    # Legacy fields remain for compatibility with older pages/integrations.
    role_id: int
    role_name: str

    # User-facing access rule: 1 = Admin, 2 = User.
    clearance: int

    username: str
    email: str
    employee_id: int | None
    employee_number: str | None
    employee_name: str | None
    must_change_password: bool

    # Employee Portal UI uses only first + last name. Keep the full legal
    # employee_name separately for official HR records, reports, forms, and
    # approval/audit workflows.
    employee_first_name: str | None = None
    employee_last_name: str | None = None

    @classmethod
    def from_model(
        cls,
        user: User,
    ) -> "AuthenticatedUser":
        """Create a detached value object from a loaded database user."""

        employee = user.employee

        return cls(
            user_id=user.id,
            company_id=user.company_id,
            company_code=user.company.code,
            company_name=user.company.name,
            role_id=user.role_id,
            role_name=user.role.name,
            clearance=int(user.clearance),
            username=user.username,
            email=user.email,
            employee_id=(
                employee.id
                if employee
                else None
            ),
            employee_number=(
                employee.employee_number
                if employee
                else None
            ),
            employee_name=(
                employee.full_name
                if employee
                else None
            ),
            must_change_password=user.must_change_password,
            employee_first_name=(
                employee.first_name
                if employee
                else None
            ),
            employee_last_name=(
                employee.last_name
                if employee
                else None
            ),
        )

    @property
    def employee_portal_display_name(self) -> str:
        """Return the compact employee-facing name for portal chrome.

        Only first and last names are shown in the Employee Portal header and
        welcome title. The full legal name remains available in employee_name
        for official HR records and workflows.
        """

        compact_parts = [
            value.strip()
            for value in (
                self.employee_first_name,
                self.employee_last_name,
            )
            if isinstance(value, str) and value.strip()
        ]

        if compact_parts:
            return " ".join(compact_parts)

        return (
            self.employee_name
            or self.username
        )

    def to_session_dict(self) -> dict[str, object]:
        """Convert the dataclass into serializable session data."""

        return asdict(self)

    @classmethod
    def from_session_dict(
        cls,
        values: dict[str, object],
    ) -> "AuthenticatedUser":
        """Restore current and older session dictionaries safely."""

        restored = dict(values)

        # Older in-memory sessions created before the compact Employee Portal
        # display-name fields remain readable until the next signed-token
        # restore refreshes them from the database.
        restored.setdefault("employee_first_name", None)
        restored.setdefault("employee_last_name", None)

        if "clearance" not in restored:
            restored["clearance"] = (
                1
                if restored.get("role_name") in {
                    "super_admin",
                    "company_admin",
                    "hr_admin",
                }
                else 2
            )

        return cls(**restored)
