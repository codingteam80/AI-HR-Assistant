"""Employee-filed overtime details reconciled with a daily DTR record."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class OvertimeRequest(TimestampMixin, Base):
    """One employee OT filing with its original DTR snapshot and approval."""

    __tablename__ = "overtime_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attendance_record_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_records.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    filed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    current_approver_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )

    date_rendered: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    # Read-only snapshot of the DTR values detected when the request was filed.
    dtr_time_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dtr_time_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dtr_ot_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dtr_ot_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dtr_estimated_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0", nullable=False
    )

    # Employee-submitted values may be edited without changing the source DTR.
    ot_time_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ot_time_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estimated_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    ot_type: Mapped[str] = mapped_column(String(80), nullable=False)
    ot_purpose: Mapped[str] = mapped_column(Text, nullable=False)
    travel_fare: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    travel_route: Mapped[str | None] = mapped_column(String(500))
    dinner_break_flag: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    has_dtr_mismatch: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30), default="pending_approval", server_default="pending_approval",
        index=True, nullable=False,
    )
    reviewer_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    employee = relationship("Employee", foreign_keys=[employee_id], lazy="joined")
    current_approver = relationship(
        "Employee", foreign_keys=[current_approver_employee_id], lazy="joined"
    )
    attendance_record = relationship("AttendanceRecord", lazy="joined")
