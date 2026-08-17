"""Immutable correction history for attendance records."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class AttendanceCorrection(TimestampMixin, Base):
    """One auditable before/after snapshot from admin or self-service edit."""

    __tablename__ = "attendance_corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    attendance_record_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_records.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    corrected_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    previous_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    new_values_json: Mapped[str] = mapped_column(Text, nullable=False)
