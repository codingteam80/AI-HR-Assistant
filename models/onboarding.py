"""Company-scoped onboarding checklist, progress, and benefit records."""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class OnboardingChecklistItem(TimestampMixin, Base):
    """One reusable onboarding requirement configured by a company."""

    __tablename__ = "onboarding_checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_required: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    completion_mode: Mapped[str] = mapped_column(
        String(30), default="employee", server_default="employee", nullable=False
    )
    auto_rule: Mapped[str | None] = mapped_column(String(50))
    target_page: Mapped[str | None] = mapped_column(String(100))
    target_query_key: Mapped[str | None] = mapped_column(String(80))
    target_query_value: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", index=True, nullable=False
    )


class EmployeeOnboardingProgress(TimestampMixin, Base):
    """One employee's status for one onboarding checklist item."""

    __tablename__ = "employee_onboarding_progress"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "employee_id",
            "checklist_item_id",
            name="uq_employee_onboarding_progress_item",
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
    checklist_item_id: Mapped[int] = mapped_column(
        ForeignKey("onboarding_checklist_items.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30), default="pending", server_default="pending", nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)


class CompanyBenefit(TimestampMixin, Base):
    """One active or archived company benefit shown inside Onboarding."""

    __tablename__ = "company_benefits"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="General", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    eligibility: Mapped[str] = mapped_column(
        String(300), default="All employees", nullable=False
    )
    effective_date: Mapped[date | None] = mapped_column(Date)
    enrollment_instructions: Mapped[str] = mapped_column(
        Text, default="", nullable=False
    )
    contact_person: Mapped[str | None] = mapped_column(String(180))
    target_page: Mapped[str | None] = mapped_column(String(100))
    target_query_key: Mapped[str | None] = mapped_column(String(80))
    target_query_value: Mapped[str | None] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", index=True, nullable=False
    )
