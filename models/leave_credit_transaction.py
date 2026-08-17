"""Audit history for leave credit allocations, adjustments, and reservations."""

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.employee import Employee
    from models.leave_request import LeaveRequest
    from models.leave_type import LeaveType
    from models.user import User


class LeaveCreditTransaction(TimestampMixin, Base):
    """One immutable leave-credit history entry."""

    __tablename__ = "leave_credit_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("leave_types.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    leave_balance_id: Mapped[int] = mapped_column(
        ForeignKey("leave_balances.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    leave_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("leave_requests.id", ondelete="SET NULL"),
        index=True,
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    employee: Mapped["Employee"] = relationship(foreign_keys=[employee_id])
    leave_type: Mapped["LeaveType"] = relationship(foreign_keys=[leave_type_id])
    leave_request: Mapped["LeaveRequest | None"] = relationship(
        foreign_keys=[leave_request_id]
    )
    created_by: Mapped["User | None"] = relationship(
        foreign_keys=[created_by_user_id]
    )
