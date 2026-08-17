"""Immutable company-scoped history for Employee workspace operations."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class EmployeeHistory(TimestampMixin, Base):
    """One employee create, import, edit, archive, or restore event."""

    __tablename__ = "employee_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"),
        index=True,
    )
    employee_number: Mapped[str] = mapped_column(
        String(80),
        index=True,
        nullable=False,
    )
    employee_name: Mapped[str] = mapped_column(String(350), nullable=False)
    performed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    action_type: Mapped[str] = mapped_column(
        String(80),
        index=True,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(40),
        default="manual",
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    old_values_json: Mapped[str | None] = mapped_column(Text)
    new_values_json: Mapped[str | None] = mapped_column(Text)
    upload_batch_id: Mapped[str | None] = mapped_column(String(50), index=True)
    upload_filename: Mapped[str | None] = mapped_column(String(255))
