"""Persistent whole-day Shifting/OB credits created from approved OT blocks."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class ShiftingCredit(TimestampMixin, Base):
    """One auditable OB credit created from one same-cutoff OT pairing."""

    __tablename__ = "shifting_credits"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "group_key",
            name="uq_shifting_credits_company_group",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    group_key: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    cutoff_start: Mapped[date] = mapped_column(Date, nullable=False)
    cutoff_end: Mapped[date] = mapped_column(Date, nullable=False)
    earned_date: Mapped[date] = mapped_column(Date, nullable=False)
    availability_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    qualifying_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("8.00"), server_default="8.00", nullable=False
    )
    ob_credit_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("1.00"), server_default="1.00", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", index=True, nullable=False
    )
    usage_date: Mapped[date | None] = mapped_column(Date, index=True)
    usage_attendance_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendance_records.id", ondelete="SET NULL"), index=True
    )
    leave_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("leave_requests.id", ondelete="SET NULL"), index=True
    )
    restored_regular_ot_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0.00", nullable=False
    )

    employee = relationship("Employee", lazy="joined")
