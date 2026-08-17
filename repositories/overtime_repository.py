"""Company- and employee-scoped overtime request queries."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.overtime_request import OvertimeRequest
from repositories.base_repository import BaseRepository


class OvertimeRequestRepository(BaseRepository[OvertimeRequest]):
    """Persistent OT request access with explicit tenant filters."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, OvertimeRequest)

    def list_employee(self, *, company_id: int, employee_id: int) -> list[OvertimeRequest]:
        statement = (
            select(OvertimeRequest)
            .where(
                OvertimeRequest.company_id == company_id,
                OvertimeRequest.employee_id == employee_id,
            )
            .order_by(
                OvertimeRequest.date_rendered.desc(),
                OvertimeRequest.id.desc(),
            )
        )
        return list(self.session.scalars(statement).unique().all())

    def list_pending_for_approver(
        self,
        *,
        company_id: int,
        employee_id: int | None,
        include_all: bool,
    ) -> list[OvertimeRequest]:
        statement = select(OvertimeRequest).where(
            OvertimeRequest.company_id == company_id,
            OvertimeRequest.status == "pending_approval",
        )
        if not include_all:
            if employee_id is None:
                return []
            statement = statement.where(
                OvertimeRequest.current_approver_employee_id == employee_id
            )
        statement = statement.order_by(
            OvertimeRequest.submitted_at,
            OvertimeRequest.id,
        )
        return list(self.session.scalars(statement).unique().all())

    def list_company_range(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
        employee_ids: list[int] | None = None,
    ) -> list[OvertimeRequest]:
        statement = select(OvertimeRequest).where(
            OvertimeRequest.company_id == company_id,
            OvertimeRequest.date_rendered >= start_date,
            OvertimeRequest.date_rendered <= end_date,
        )
        if employee_ids is not None:
            if not employee_ids:
                return []
            statement = statement.where(OvertimeRequest.employee_id.in_(employee_ids))
        statement = statement.order_by(
            OvertimeRequest.date_rendered,
            OvertimeRequest.id,
        )
        return list(self.session.scalars(statement).unique().all())
