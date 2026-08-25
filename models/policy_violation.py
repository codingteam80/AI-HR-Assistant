"""Company-scoped violation and disciplinary-action master records."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class PolicyViolation(TimestampMixin, Base):
    """One company-defined violation/offense and its disciplinary matrix."""

    __tablename__ = "policy_violations"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "violation_code",
            name="uq_policy_violations_company_code",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str | None] = mapped_column(
        String(30), unique=True, index=True, nullable=True,
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    last_edited_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    violation_code: Mapped[str] = mapped_column(
        String(40), index=True, nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(100), index=True, nullable=False,
    )
    offense_title: Mapped[str] = mapped_column(
        String(200), index=True, nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False,
    )

    first_offense_action: Mapped[str] = mapped_column(Text, nullable=False)
    second_offense_action: Mapped[str] = mapped_column(Text, nullable=False)
    third_offense_action: Mapped[str] = mapped_column(Text, nullable=False)
    final_action: Mapped[str] = mapped_column(Text, nullable=False)

    related_policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_policies.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    effective_date: Mapped[date | None] = mapped_column(
        Date, index=True, nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), index=True, default="active", nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True,
    )
    archived_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
