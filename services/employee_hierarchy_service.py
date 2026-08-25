"""Company-scoped employee Manager/Leader hierarchy resolution.

The HR project does not store a separate supervisory-role flag.  An employee
is a Manager and/or Leader only when other employed employees reference that
employee through the existing ``manager_id`` and/or ``leader_id`` fields.
This service keeps that rule in one place so portal pages and Chat Assistant
answers cannot drift into job-title-based guesses.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from models.employee import Employee
from repositories.employee_repository import EmployeeRepository


@dataclass(frozen=True)
class EmployeeHierarchySnapshot:
    """One employee's current, company-scoped assignment relationships."""

    employee: Employee
    manager_reports: tuple[Employee, ...]
    leader_members: tuple[Employee, ...]

    @property
    def is_manager(self) -> bool:
        """Return whether employed employees currently reference this Manager."""

        return bool(self.manager_reports)

    @property
    def is_leader(self) -> bool:
        """Return whether employed employees currently reference this Leader."""

        return bool(self.leader_members)

    @property
    def role_label(self) -> str:
        """Describe the derived supervisory assignment without using job title."""

        if self.is_manager and self.is_leader:
            return "Manager and Leader"
        if self.is_manager:
            return "Manager"
        if self.is_leader:
            return "Leader"
        return "No supervisory assignment"

    @property
    def manager(self) -> Employee | None:
        """Return the employee selected in this employee's Manager field."""

        return self.employee.manager

    @property
    def leader(self) -> Employee | None:
        """Return the employee selected in this employee's Leader field."""

        return self.employee.leader


class EmployeeHierarchyService:
    """Resolve live hierarchy assignments from Employee Master relationships."""

    def __init__(self, session: Session) -> None:
        self.employee_repository = EmployeeRepository(session)

    def snapshot(
        self,
        *,
        company_id: int,
        employee_id: int,
    ) -> EmployeeHierarchySnapshot | None:
        """Return one hierarchy snapshot without crossing company boundaries."""

        employee = self.employee_repository.get_with_details(
            company_id=company_id,
            employee_id=employee_id,
        )
        if employee is None:
            return None

        manager_reports = self.employee_repository.list_direct_reports(
            company_id=company_id,
            manager_employee_id=employee.id,
        )
        leader_members = self.employee_repository.list_team_members(
            company_id=company_id,
            leader_employee_id=employee.id,
        )
        return EmployeeHierarchySnapshot(
            employee=employee,
            manager_reports=tuple(manager_reports),
            leader_members=tuple(leader_members),
        )
