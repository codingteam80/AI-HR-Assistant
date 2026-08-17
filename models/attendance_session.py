"""One WFO/WFH work session belonging to a daily attendance record."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class AttendanceSession(TimestampMixin, Base):
    """Preserve actual punches and payroll-rounded quarter-hour values."""

    __tablename__ = "attendance_sessions"
    __table_args__ = (
        UniqueConstraint(
            "attendance_record_id",
            "sequence_number",
            name="uq_attendance_session_record_sequence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attendance_record_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_records.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    work_status: Mapped[str] = mapped_column(String(10), nullable=False)
    actual_time_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_time_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rounded_time_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rounded_time_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(
        String(30), default="employee_punch", server_default="employee_punch", nullable=False
    )
    corrected_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    correction_reason: Mapped[str | None] = mapped_column(String(500))

    attendance_record = relationship("AttendanceRecord", back_populates="sessions")
