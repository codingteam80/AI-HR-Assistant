"""Generic in-app notifications shared by every HR module."""

from sqlalchemy.orm import Session

from models.notification import Notification
from repositories.notification_repository import NotificationRepository
from services.external_notification_service import queue_external_notification


class NotificationService:
    """Create, read, and mark company/user-scoped notifications.

    ``event_type`` is intentionally generic. Leave, policies, training,
    employee/account, security, integration, and future HR modules use the
    same notification center.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = NotificationRepository(session)

    def create(self, *, company_id: int, user_id: int, event_type: str, title: str, message: str, related_entity_type: str | None = None, related_entity_id: int | None = None) -> Notification:
        notification = Notification(
            company_id=company_id,
            user_id=user_id,
            event_type=event_type,
            title=title.strip(),
            message=message.strip(),
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            is_read=False,
        )
        self.session.add(notification)

        # External channels mirror the same event only after the surrounding
        # HR transaction commits successfully. Missing/invalid external
        # delivery never blocks the authoritative in-app notification.
        queue_external_notification(
            self.session,
            company_id=company_id,
            user_id=user_id,
            event_type=event_type,
            title=title,
            message=message,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        return notification

    def unread_count(self, *, company_id: int, user_id: int) -> int:
        return self.repository.unread_count(company_id=company_id, user_id=user_id)

    def exists_for_entity_event(
        self,
        *,
        company_id: int,
        user_id: int,
        event_type: str,
        related_entity_type: str,
        related_entity_id: int,
    ) -> bool:
        """Check an entity event before creating a reminder again."""

        return self.repository.exists_for_entity_event(
            company_id=company_id,
            user_id=user_id,
            event_type=event_type,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )

    def list_recent(self, *, company_id: int, user_id: int, limit: int = 10):
        return self.repository.list_recent(company_id=company_id, user_id=user_id, limit=limit)

    def unread_announcement_count(
        self,
        *,
        company_id: int,
        user_id: int,
        announcement_ids: list[int],
    ) -> int:
        return self.repository.unread_announcement_count(
            company_id=company_id,
            user_id=user_id,
            announcement_ids=announcement_ids,
        )

    def mark_announcements_read(
        self,
        *,
        company_id: int,
        user_id: int,
        announcement_ids: list[int],
    ) -> int:
        """Mark announcements presented in the employee workspace read."""

        return self.repository.mark_announcements_read(
            company_id=company_id,
            user_id=user_id,
            announcement_ids=announcement_ids,
        )

    def mark_read(
        self,
        *,
        company_id: int,
        user_id: int,
        notification_id: int,
    ) -> int:
        """Mark one notification as read after it is opened."""

        return self.repository.mark_read(
            company_id=company_id,
            user_id=user_id,
            notification_id=notification_id,
        )

    def mark_all_read(self, *, company_id: int, user_id: int) -> int:
        return self.repository.mark_all_read(company_id=company_id, user_id=user_id)
