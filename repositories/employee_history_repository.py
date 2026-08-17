"""Company-scoped Employee workspace history queries."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.employee_history import EmployeeHistory
from repositories.base_repository import BaseRepository


class EmployeeHistoryRepository(BaseRepository[EmployeeHistory]):
    """Store and list immutable employee audit entries."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, EmployeeHistory)

    def list_for_company(self, company_id: int) -> list[EmployeeHistory]:
        statement = (
            select(EmployeeHistory)
            .where(EmployeeHistory.company_id == company_id)
            .order_by(EmployeeHistory.created_at.desc(), EmployeeHistory.id.desc())
        )
        return list(self.session.scalars(statement).all())
