"""Central company-scoped audit trail for administrator operations."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class AuditEvent(TimestampMixin, Base):
    """One immutable administrator action or blocked edit conflict."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    module: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100), index=True)
    entity_label: Mapped[str | None] = mapped_column(String(350))
    result: Mapped[str] = mapped_column(
        String(40),
        default="successful",
        index=True,
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(String(700), nullable=False)
    old_values_json: Mapped[str | None] = mapped_column(Text)
    new_values_json: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)

