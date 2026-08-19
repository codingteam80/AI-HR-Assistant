"""Employee-profile business logic."""

from sqlalchemy.orm import Session

from repositories.employee_repository import EmployeeRepository
from schemas.user_schema import EmployeeCreate


class EmployeeService:
    """Create employees while enforcing the correct unique identifier."""

    def __init__(self, session: Session) -> None:
        self.repository = EmployeeRepository(session)

    def create_employee(self, values: EmployeeCreate):
        """Create an employee.

        Employee number and normalized full name are checked without case or
        spacing differences so a second master record is not created by a
        capitalization-only change.
        """

        existing = self.repository.get_by_employee_number(
            values.company_id,
            values.employee_number,
        )

        if existing is not None:
            raise ValueError(
                f"Employee number '{values.employee_number}' "
                "already exists inside this company."
            )

        name_matches = self.repository.find_normalized_name_matches(
            company_id=values.company_id,
            first_name=values.first_name,
            middle_name=values.middle_name,
            last_name=values.last_name,
            suffix=values.suffix,
        )
        if name_matches:
            match = name_matches[0]
            raise ValueError(
                "Possible duplicate employee record: "
                f"{match.employee_number} — {match.full_name}. Open Edit "
                "Employee and review the existing record instead of creating "
                "another capitalization or spacing variant."
            )

        payload = values.model_dump()

        # Convert validated EmailStr into a normal string for SQLAlchemy.
        if payload.get("work_email") is not None:
            payload["work_email"] = str(payload["work_email"])

        return self.repository.create(payload)
