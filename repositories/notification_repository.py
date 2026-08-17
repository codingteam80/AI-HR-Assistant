"""Queries for the authenticated notification bell."""

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from models.notification import Notification
from repositories.base_repository import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    """Company/user-scoped notification persistence."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, Notification)

    def unread_count(self, *, company_id: int, user_id: int) -> int:
        return int(
            self.session.scalar(
                select(func.count(Notification.id)).where(
                    Notification.company_id == company_id,
                    Notification.user_id == user_id,
                    Notification.is_read.is_(False),
                )
            )
            or 0
        )

    def exists_for_entity_event(
        self,
        *,
        company_id: int,
        user_id: int,
        event_type: str,
        related_entity_type: str,
        related_entity_id: int,
    ) -> bool:
        """Return whether one idempotent entity notification exists."""

        count = self.session.scalar(
            select(func.count(Notification.id)).where(
                Notification.company_id == company_id,
                Notification.user_id == user_id,
                Notification.event_type == event_type,
                Notification.related_entity_type == related_entity_type,
                Notification.related_entity_id == related_entity_id,
            )
        )
        return bool(count)

    def list_recent(self, *, company_id: int, user_id: int, limit: int = 10) -> list[Notification]:
        statement = (
            select(Notification)
            .where(
                Notification.company_id == company_id,
                Notification.user_id == user_id,
            )
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def unread_announcement_count(
        self,
        *,
        company_id: int,
        user_id: int,
        announcement_ids: list[int],
    ) -> int:
        """Count unread publication notifications for visible announcements."""

        if not announcement_ids:
            return 0
        return int(
            self.session.scalar(
                select(func.count(Notification.id)).where(
                    Notification.company_id == company_id,
                    Notification.user_id == user_id,
                    Notification.is_read.is_(False),
                    Notification.event_type == "announcement_published",
                    Notification.related_entity_type == "announcement",
                    Notification.related_entity_id.in_(announcement_ids),
                )
            )
            or 0
        )

    def mark_announcements_read(
        self,
        *,
        company_id: int,
        user_id: int,
        announcement_ids: list[int],
    ) -> int:
        """Mark visible company-announcement notifications as viewed."""

        if not announcement_ids:
            return 0
        result = self.session.execute(
            update(Notification)
            .where(
                Notification.company_id == company_id,
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.event_type == "announcement_published",
                Notification.related_entity_type == "announcement",
                Notification.related_entity_id.in_(announcement_ids),
            )
            .values(
                is_read=True,
                read_at=datetime.now(timezone.utc),
            )
        )
        self.session.commit()
        return int(result.rowcount or 0)

    def mark_read(
        self,
        *,
        company_id: int,
        user_id: int,
        notification_id: int,
    ) -> int:
        """Mark one authorized notification as read."""

        result = self.session.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.company_id == company_id,
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(
                is_read=True,
                read_at=datetime.now(timezone.utc),
            )
        )
        self.session.commit()

        return int(result.rowcount or 0)

    def mark_all_read(self, *, company_id: int, user_id: int) -> int:
        result = self.session.execute(
            update(Notification)
            .where(
                Notification.company_id == company_id,
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=datetime.now(timezone.utc))
        )
        self.session.commit()
        return int(result.rowcount or 0)
