"""Company-scoped leave-management database queries."""

from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_credit_transaction import LeaveCreditTransaction
from models.leave_request import LeaveRequest
from models.leave_type import LeaveType
from models.user import User
from repositories.base_repository import BaseRepository


class LeaveTypeRepository(BaseRepository[LeaveType]):
    """Queries for leave type settings."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, LeaveType)

    def list_company(self, company_id: int, *, active_only: bool = False) -> list[LeaveType]:
        statement = select(LeaveType).where(LeaveType.company_id == company_id)
        if active_only:
            statement = statement.where(LeaveType.is_active.is_(True))
        statement = statement.order_by(LeaveType.name)
        return list(self.session.scalars(statement).all())

    def get_by_code(self, company_id: int, code: str) -> LeaveType | None:
        return self.session.scalar(
            select(LeaveType).where(
                LeaveType.company_id == company_id,
                func.lower(LeaveType.code) == code.strip().lower(),
            )
        )

    def get_by_name(self, company_id: int, name: str) -> LeaveType | None:
        return self.session.scalar(
            select(LeaveType).where(
                LeaveType.company_id == company_id,
                func.lower(LeaveType.name) == name.strip().lower(),
            )
        )


class LeaveBalanceRepository(BaseRepository[LeaveBalance]):
    """Queries for employee leave balances."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, LeaveBalance)

    def get_balance(self, *, company_id: int, employee_id: int, leave_type_id: int, year: int) -> LeaveBalance | None:
        return self.session.scalar(
            select(LeaveBalance)
            .options(
                joinedload(
                    LeaveBalance.employee
                ).joinedload(
                    Employee.department
                ),
                joinedload(
                    LeaveBalance.employee
                ).joinedload(
                    Employee.manager
                ).joinedload(
                    Employee.user
                ),
                joinedload(
                    LeaveBalance.employee
                ).joinedload(
                    Employee.user
                ),
                joinedload(
                    LeaveBalance.leave_type
                ),
            )
            .where(
                LeaveBalance.company_id == company_id,
                LeaveBalance.employee_id == employee_id,
                LeaveBalance.leave_type_id == leave_type_id,
                LeaveBalance.year == year,
            )
        )

    def list_company_year(self, company_id: int, year: int) -> list[LeaveBalance]:
        statement = (
            select(LeaveBalance)
            .options(
                joinedload(
                    LeaveBalance.employee
                ).joinedload(
                    Employee.department
                ),
                joinedload(
                    LeaveBalance.employee
                ).joinedload(
                    Employee.manager
                ).joinedload(
                    Employee.user
                ),
                joinedload(
                    LeaveBalance.employee
                ).joinedload(
                    Employee.user
                ),
                joinedload(
                    LeaveBalance.leave_type
                ),
            )
            .join(Employee, Employee.id == LeaveBalance.employee_id)
            .where(LeaveBalance.company_id == company_id, LeaveBalance.year == year)
            .order_by(Employee.last_name, Employee.first_name, LeaveBalance.leave_type_id)
        )
        return list(self.session.scalars(statement).unique().all())

    def list_employee_year(self, company_id: int, employee_id: int, year: int) -> list[LeaveBalance]:
        statement = (
            select(LeaveBalance)
            .options(
                joinedload(
                    LeaveBalance.employee
                ).joinedload(
                    Employee.department
                ),
                joinedload(
                    LeaveBalance.employee
                ).joinedload(
                    Employee.manager
                ).joinedload(
                    Employee.user
                ),
                joinedload(
                    LeaveBalance.employee
                ).joinedload(
                    Employee.user
                ),
                joinedload(
                    LeaveBalance.leave_type
                ),
            )
            .where(
                LeaveBalance.company_id == company_id,
                LeaveBalance.employee_id == employee_id,
                LeaveBalance.year == year,
            )
            .order_by(LeaveBalance.leave_type_id)
        )
        return list(self.session.scalars(statement).unique().all())


class LeaveRequestRepository(BaseRepository[LeaveRequest]):
    """Queries for leave request monitoring, ownership, and staged approval."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, LeaveRequest)

    # Centralized eager-load guard for detached UI use: Employee.department.
    @staticmethod
    def _detail_options():
        return (
            joinedload(LeaveRequest.employee).joinedload(Employee.department),
            joinedload(LeaveRequest.employee).joinedload(Employee.user),
            joinedload(LeaveRequest.filed_by_employee).joinedload(Employee.user),
            joinedload(LeaveRequest.manager).joinedload(Employee.user),
            joinedload(LeaveRequest.leader_approver).joinedload(Employee.user),
            joinedload(LeaveRequest.current_approver).joinedload(Employee.user),
            joinedload(LeaveRequest.cancellation_requested_by_employee).joinedload(Employee.user),
            joinedload(LeaveRequest.leave_type),
            joinedload(LeaveRequest.fallback_leave_type),
        )

    def list_company(
        self,
        company_id: int,
        year: int | None = None,
        *,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> list[LeaveRequest]:
        statement = select(LeaveRequest).options(*self._detail_options()).where(
            LeaveRequest.company_id == company_id
        )
        if period_start is not None and period_end is not None:
            statement = statement.where(
                LeaveRequest.end_date >= period_start,
                LeaveRequest.start_date <= period_end,
            )
        elif year is not None:
            year_start = date(int(year), 1, 1)
            year_end = date(int(year), 12, 31)
            statement = statement.where(
                LeaveRequest.end_date >= year_start,
                LeaveRequest.start_date <= year_end,
            )
        statement = statement.order_by(LeaveRequest.submitted_at.desc(), LeaveRequest.id.desc())
        return list(self.session.scalars(statement).unique().all())

    def list_employee(self, company_id: int, employee_id: int) -> list[LeaveRequest]:
        statement = (
            select(LeaveRequest)
            .options(*self._detail_options())
            .where(
                LeaveRequest.company_id == company_id,
                LeaveRequest.employee_id == employee_id,
            )
            .order_by(LeaveRequest.submitted_at.desc(), LeaveRequest.id.desc())
        )
        return list(self.session.scalars(statement).unique().all())

    def list_filed_by_employee(self, *, company_id: int, filed_by_employee_id: int) -> list[LeaveRequest]:
        statement = (
            select(LeaveRequest)
            .options(*self._detail_options())
            .where(
                LeaveRequest.company_id == company_id,
                LeaveRequest.filed_by_employee_id == filed_by_employee_id,
                LeaveRequest.filed_on_behalf.is_(True),
            )
            .order_by(LeaveRequest.submitted_at.desc(), LeaveRequest.id.desc())
        )
        return list(self.session.scalars(statement).unique().all())

    def get_with_details(self, company_id: int, request_id: int) -> LeaveRequest | None:
        return self.session.scalar(
            select(LeaveRequest)
            .options(*self._detail_options())
            .where(LeaveRequest.company_id == company_id, LeaveRequest.id == request_id)
        )

    def list_overlapping(
        self,
        *,
        company_id: int,
        employee_id: int,
        start_date: date,
        end_date: date,
    ) -> list[LeaveRequest]:
        """Return date-intersecting requests except rejected/full-cancelled rows."""

        statement = (
            select(LeaveRequest)
            .options(*self._detail_options())
            .where(
                LeaveRequest.company_id == company_id,
                LeaveRequest.employee_id == employee_id,
                LeaveRequest.start_date <= end_date,
                LeaveRequest.end_date >= start_date,
                LeaveRequest.status.notin_(("rejected", "cancelled")),
            )
            .order_by(LeaveRequest.start_date, LeaveRequest.id)
        )
        return list(self.session.scalars(statement).unique().all())

    def list_pending_for_manager(self, *, company_id: int, manager_employee_id: int) -> list[LeaveRequest]:
        """Return requests awaiting this employee at either approval stage."""
        statement = (
            select(LeaveRequest)
            .options(*self._detail_options())
            .where(
                LeaveRequest.company_id == company_id,
                or_(
                    and_(
                        LeaveRequest.status.in_(("pending_leader_approval", "pending_manager_approval")),
                        or_(
                            LeaveRequest.current_approver_employee_id == manager_employee_id,
                            and_(
                                LeaveRequest.current_approver_employee_id.is_(None),
                                LeaveRequest.manager_employee_id == manager_employee_id,
                            ),
                        ),
                    ),
                    and_(
                        LeaveRequest.cancellation_status == "requested",
                        LeaveRequest.manager_employee_id == manager_employee_id,
                    ),
                ),
            )
            .order_by(LeaveRequest.submitted_at.asc(), LeaveRequest.id.asc())
        )
        return list(self.session.scalars(statement).unique().all())

    def list_reviewed_for_manager(self, *, company_id: int, manager_employee_id: int) -> list[LeaveRequest]:
        """Return final manager reviews plus requests forwarded by this leader."""
        statement = (
            select(LeaveRequest)
            .options(*self._detail_options())
            .where(
                LeaveRequest.company_id == company_id,
                or_(
                    and_(
                        LeaveRequest.manager_employee_id == manager_employee_id,
                        LeaveRequest.reviewed_at.is_not(None),
                        LeaveRequest.cancellation_status != "requested",
                        LeaveRequest.status.in_((
                            "scheduled", "approved", "in_progress", "completed",
                            "rejected", "cancelled", "partially_cancelled"
                        )),
                    ),
                    and_(
                        LeaveRequest.leader_employee_id == manager_employee_id,
                        LeaveRequest.leader_reviewed_at.is_not(None),
                    ),
                ),
            )
            .order_by(LeaveRequest.updated_at.desc(), LeaveRequest.id.desc())
        )
        return list(self.session.scalars(statement).unique().all())

    def list_reconcilable(self, *, company_id: int, through_date: date) -> list[LeaveRequest]:
        statement = (
            select(LeaveRequest)
            .options(*self._detail_options())
            .where(
                LeaveRequest.company_id == company_id,
                LeaveRequest.status.in_(("scheduled", "approved", "in_progress")),
                LeaveRequest.start_date <= through_date,
            )
            .order_by(LeaveRequest.start_date, LeaveRequest.id)
        )
        return list(self.session.scalars(statement).unique().all())

class LeaveCreditTransactionRepository(BaseRepository[LeaveCreditTransaction]):
    """Queries for immutable leave-credit history."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, LeaveCreditTransaction)

    def list_employee_year(self, company_id: int, employee_id: int, year: int) -> list[LeaveCreditTransaction]:
        statement = (
            select(LeaveCreditTransaction)
            .join(LeaveBalance, LeaveBalance.id == LeaveCreditTransaction.leave_balance_id)
            .where(
                LeaveCreditTransaction.company_id == company_id,
                LeaveCreditTransaction.employee_id == employee_id,
                LeaveBalance.year == year,
            )
            .order_by(LeaveCreditTransaction.created_at.desc(), LeaveCreditTransaction.id.desc())
        )
        return list(self.session.scalars(statement).all())

    def list_company_year(
        self,
        company_id: int,
        year: int,
    ) -> list[LeaveCreditTransaction]:
        """Return every company credit transaction with display relations."""

        statement = (
            select(LeaveCreditTransaction)
            .options(
                joinedload(LeaveCreditTransaction.employee),
                joinedload(LeaveCreditTransaction.leave_type),
                joinedload(LeaveCreditTransaction.leave_request),
                joinedload(LeaveCreditTransaction.created_by).joinedload(User.employee),
            )
            .join(LeaveBalance, LeaveBalance.id == LeaveCreditTransaction.leave_balance_id)
            .where(
                LeaveCreditTransaction.company_id == company_id,
                LeaveBalance.year == year,
            )
            .order_by(
                LeaveCreditTransaction.created_at.desc(),
                LeaveCreditTransaction.id.desc(),
            )
        )
        return list(self.session.scalars(statement).unique().all())
