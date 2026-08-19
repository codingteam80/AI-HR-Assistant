"""Company-scoped central audit-event queries."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.audit_event import AuditEvent
from repositories.base_repository import BaseRepository


class AuditEventRepository(BaseRepository[AuditEvent]):
    """Store and retrieve immutable central audit events."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, AuditEvent)

    def list_for_company(self, company_id: int) -> list[AuditEvent]:
        statement = (
            select(AuditEvent)
            .where(AuditEvent.company_id == company_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        )
        return list(self.session.scalars(statement).all())

