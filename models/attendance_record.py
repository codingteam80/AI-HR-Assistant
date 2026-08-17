"""Company-scoped daily attendance, work-location, leave, and OT record."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin
from models.employee import Employee


class AttendanceRecord(TimestampMixin, Base):
    """One employee's attendance state for one calendar date."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "employee_id",
            "attendance_date",
            name="uq_attendance_company_employee_date",
        ),
    )

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
    attendance_date: Mapped[date] = mapped_column(
        Date,
        index=True,
        nullable=False,
    )
    time_in: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    time_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # WFO/WFH are working locations. An approved Leave Management record
    # supplies the default VL/SL/EL value, which remains employee-editable.
    work_status: Mapped[str | None] = mapped_column(
        String(10),
        index=True,
    )
    status_source: Mapped[str] = mapped_column(
        String(30),
        default="manual",
        server_default="manual",
        nullable=False,
    )
    leave_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("leave_requests.id", ondelete="SET NULL"),
        index=True,
    )

    # Schedule snapshots keep historical OT stable if the company changes its
    # standard workweek later.
    scheduled_workday: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
        nullable=False,
    )
    regular_hours_target: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        default=Decimal("8.00"),
        server_default="8.00",
        nullable=False,
    )
    lunch_break_minutes: Mapped[int] = mapped_column(
        Integer,
        default=60,
        server_default="60",
        nullable=False,
    )
    total_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        default=Decimal("0.00"),
        server_default="0.00",
        nullable=False,
    )
    ot_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        default=Decimal("0.00"),
        server_default="0.00",
        nullable=False,
    )
    leave_duration_code: Mapped[str | None] = mapped_column(String(10))
    leave_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0.00", nullable=False
    )
    undertime_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0.00", nullable=False
    )

    # Latest correction metadata is kept on the record for quick review. A
    # complete immutable history is stored in attendance_corrections.
    corrected_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    corrected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    correction_reason: Mapped[str | None] = mapped_column(String(500))

    employee: Mapped[Employee] = relationship(lazy="joined")
    leave_request = relationship("LeaveRequest", lazy="joined")
    sessions = relationship(
        "AttendanceSession",
        back_populates="attendance_record",
        cascade="all, delete-orphan",
        order_by="AttendanceSession.sequence_number",
        lazy="selectin",
    )
