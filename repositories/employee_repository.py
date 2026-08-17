"""Company-scoped employee master-record queries."""

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from models.employee import Employee
from repositories.base_repository import BaseRepository


class EmployeeRepository(BaseRepository[Employee]):
    """Repository for employee records and related account data."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, Employee)

    def get_by_employee_number(
        self,
        company_id: int,
        employee_number: str,
    ) -> Employee | None:
        """Find one employee using its company-scoped number."""

        return self.session.scalar(
            select(Employee).where(
                Employee.company_id == company_id,
                Employee.employee_number == employee_number,
            )
        )

    def get_by_employee_number_excluding(
        self,
        *,
        company_id: int,
        employee_number: str,
        employee_id: int,
    ) -> Employee | None:
        """Check uniqueness while editing one employee."""

        return self.session.scalar(
            select(Employee).where(
                Employee.company_id == company_id,
                Employee.employee_number == employee_number,
                Employee.id != employee_id,
            )
        )

    def get_with_details(
        self,
        *,
        company_id: int,
        employee_id: int,
    ) -> Employee | None:
        """Load one complete master record for editing."""

        statement = (
            select(Employee)
            .options(
                joinedload(Employee.department),
                joinedload(Employee.manager).joinedload(Employee.user),
                joinedload(Employee.leader).joinedload(Employee.user),
                joinedload(Employee.user),
                selectinload(Employee.trainings),
            )
            .where(
                Employee.company_id == company_id,
                Employee.id == employee_id,
            )
        )

        return self.session.scalar(statement)

    def find_by_full_name(
        self,
        company_id: int,
        first_name: str,
        last_name: str,
    ) -> list[Employee]:
        """Return all matching names because duplicate names are allowed."""

        statement = select(Employee).where(
            Employee.company_id == company_id,
            Employee.first_name == first_name,
            Employee.last_name == last_name,
        )

        return list(self.session.scalars(statement).all())

    def list_with_details(
        self,
        company_id: int,
        *,
        archived: bool | None = None,
    ) -> list[Employee]:
        """Return detailed employees, optionally filtered by archive state."""

        statement = (
            select(Employee)
            .options(
                joinedload(Employee.department),
                joinedload(Employee.manager),
                joinedload(Employee.leader),
                joinedload(Employee.user),
                selectinload(Employee.trainings),
            )
            .where(Employee.company_id == company_id)
            .order_by(
                Employee.last_name,
                Employee.first_name,
                Employee.employee_number,
            )
        )

        if archived is True:
            statement = statement.where(
                Employee.employment_status == "resigned"
            )
        elif archived is False:
            statement = statement.where(
                Employee.employment_status == "employed"
            )

        return list(
            self.session.scalars(statement).unique().all()
        )

    def list_available_managers(
        self,
        company_id: int,
    ) -> list[Employee]:
        """Return employed workers available for manager assignment."""

        statement = (
            select(Employee)
            .where(
                Employee.company_id == company_id,
                Employee.employment_status == "employed",
            )
            .order_by(
                Employee.last_name,
                Employee.first_name,
            )
        )

        return list(self.session.scalars(statement).all())


    def list_direct_reports(
        self,
        *,
        company_id: int,
        manager_employee_id: int,
    ) -> list[Employee]:
        """Return employed workers assigned to one manager."""

        statement = (
            select(Employee)
            .options(
                joinedload(Employee.department),
                joinedload(Employee.user),
            )
            .where(
                Employee.company_id == company_id,
                Employee.manager_id == manager_employee_id,
                Employee.employment_status == "employed",
            )
            .order_by(
                Employee.last_name,
                Employee.first_name,
            )
        )

        return list(
            self.session.scalars(statement).unique().all()
        )

    def list_team_members(
        self,
        *,
        company_id: int,
        leader_employee_id: int,
    ) -> list[Employee]:
        """Return employed direct members assigned to one leader."""

        statement = (
            select(Employee)
            .options(
                joinedload(Employee.department),
                joinedload(Employee.manager).joinedload(Employee.user),
                joinedload(Employee.leader).joinedload(Employee.user),
                joinedload(Employee.user),
            )
            .where(
                Employee.company_id == company_id,
                Employee.leader_id == leader_employee_id,
                Employee.employment_status == "employed",
            )
            .order_by(Employee.last_name, Employee.first_name)
        )
        return list(self.session.scalars(statement).unique().all())
