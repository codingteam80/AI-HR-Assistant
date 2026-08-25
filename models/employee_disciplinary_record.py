"""Confidential company-scoped employee disciplinary case records."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class EmployeeDisciplinaryRecord(TimestampMixin, Base):
    """One employee case linked to the official PolicyViolation master row."""

    __tablename__ = "employee_disciplinary_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True, nullable=True
    )
    violation_id: Mapped[int | None] = mapped_column(
        ForeignKey("policy_violations.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    last_edited_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # Historical identity snapshots remain readable even if an employee or
    # master rule is later archived. Penalties are intentionally NOT copied;
    # suggested action is always derived from the linked master violation.
    employee_number: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    employee_name: Mapped[str] = mapped_column(String(350), nullable=False)
    violation_code: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    violation_title: Mapped[str] = mapped_column(String(200), nullable=False)

    incident_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    incident_description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_snapshot: Mapped[str | None] = mapped_column(String(300), nullable=True)

    previous_offense_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    offense_level: Mapped[str] = mapped_column(String(30), nullable=False)

    actual_action_taken: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    reviewed_approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    date_issued: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    employee_acknowledgment: Mapped[str] = mapped_column(
        String(30), default="Pending", nullable=False
    )
    case_status: Mapped[str] = mapped_column(
        String(30), default="Draft", index=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Safe-delete lifecycle. Archived cases remain recoverable for HR/Audit
    # purposes but are excluded from active admin, employee, reports, and chat
    # queries until restored.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    archived_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
