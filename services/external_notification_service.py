"""External email/SMS mirroring for committed in-app notifications.

The in-app notification remains the authoritative record. This module queues
external delivery while the HR transaction is open and sends only after a
successful database commit. A failed email or SMS is logged but never rolls
back an already successful HR action.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from integrations.email.email_sender import (
    EmailDeliveryError,
    EmailSender,
    OutboundEmail,
    build_email_sender,
)
from integrations.sms.sms_sender import (
    OutboundSms,
    SmsDeliveryError,
    SmsSender,
    build_sms_sender,
    normalize_phone_number,
)
from models.employee import Employee


logger = logging.getLogger(__name__)
_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_PENDING_KEY = "pending_external_hr_notifications"
_LISTENER_MARKER = "_ai_hr_external_notification_listener_installed"

# These leave events already send one rich email with To/CC/attachments from
# LeaveService. Mirroring those events again would create duplicate email.
# SMS remains enabled for them because there is no legacy SMS delivery.
_LEGACY_LEAVE_EMAIL_EVENTS = {
    "leave_request_submitted",
    "leave_request_forwarded_to_manager",
    "leave_request_approved",
    "leave_request_rejected",
}


@dataclass(frozen=True, slots=True)
class PendingExternalNotification:
    company_id: int
    user_id: int
    event_type: str
    title: str
    message: str
    related_entity_type: str | None
    related_entity_id: int | None
    work_email: str | None
    mobile_number: str | None


@dataclass(frozen=True, slots=True)
class ExternalNotificationStatus:
    email_enabled: bool
    email_mode: str
    email_internet_ready: bool
    sms_enabled: bool
    sms_mode: str
    sms_internet_ready: bool
    sms_sender_configured: bool
    default_country_code: str


@dataclass(frozen=True, slots=True)
class ExternalDeliveryResult:
    email_sent: bool = False
    sms_sent: bool = False
    email_reference: str | None = None
    sms_reference: str | None = None
    email_error: str | None = None
    sms_error: str | None = None


class ExternalNotificationService:
    """Deliver one already-committed notification outside the portal."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        email_sender: EmailSender | None = None,
        sms_sender: SmsSender | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._email_sender = email_sender
        self._sms_sender = sms_sender

    def get_status(self) -> ExternalNotificationStatus:
        mode = self.settings.email_delivery_mode.strip().lower()
        smtp_password = (
            self.settings.smtp_password.get_secret_value().strip()
            if self.settings.smtp_password is not None
            else ""
        )
        email_ready = bool(
            self.settings.external_email_notifications_enabled
            and mode == "smtp"
            and (self.settings.smtp_host or "").strip()
            and (self.settings.smtp_username or "").strip()
            and smtp_password
            and self.settings.smtp_from_email.strip()
        )

        sms_mode = self.settings.sms_delivery_mode.strip().lower()
        twilio_token = (
            self.settings.twilio_auth_token.get_secret_value().strip()
            if self.settings.twilio_auth_token is not None
            else ""
        )
        sms_sender_configured = bool(
            (self.settings.twilio_from_number or "").strip()
            or (self.settings.twilio_messaging_service_sid or "").strip()
        )
        sms_ready = bool(
            self.settings.external_sms_notifications_enabled
            and sms_mode == "twilio"
            and (self.settings.twilio_account_sid or "").strip()
            and twilio_token
            and sms_sender_configured
        )

        return ExternalNotificationStatus(
            email_enabled=(
                self.settings.external_email_notifications_enabled
            ),
            email_mode=mode,
            email_internet_ready=email_ready,
            sms_enabled=(
                self.settings.external_sms_notifications_enabled
            ),
            sms_mode=sms_mode,
            sms_internet_ready=sms_ready,
            sms_sender_configured=sms_sender_configured,
            default_country_code=(
                self.settings.sms_default_country_code
            ),
        )

    def deliver(
        self,
        payload: PendingExternalNotification,
    ) -> ExternalDeliveryResult:
        """Attempt enabled channels independently and never raise outward."""

        email_sent = False
        sms_sent = False
        email_reference: str | None = None
        sms_reference: str | None = None
        email_error: str | None = None
        sms_error: str | None = None

        if (
            self.settings.external_email_notifications_enabled
            and payload.event_type not in _LEGACY_LEAVE_EMAIL_EVENTS
            and payload.work_email
        ):
            try:
                recipient = str(
                    _EMAIL_ADAPTER.validate_python(
                        payload.work_email.strip()
                    )
                )
                sender = (
                    self._email_sender
                    or build_email_sender(self.settings)
                )
                email_reference = sender.send(
                    OutboundEmail(
                        to_email=recipient,
                        subject=(
                            f"AI HR Assistant · {payload.title}"
                        ),
                        text_body=(
                            f"{payload.message}\n\n"
                            "Open AI HR Assistant to review the full "
                            "record and available actions."
                        ),
                    )
                )
                email_sent = True
            except Exception as error:
                email_error = _safe_delivery_error(error)
                logger.warning(
                    "External HR email notification failed for "
                    "company=%s user=%s event=%s: %s",
                    payload.company_id,
                    payload.user_id,
                    payload.event_type,
                    email_error,
                )

        if (
            self.settings.external_sms_notifications_enabled
            and payload.mobile_number
        ):
            try:
                normalized = normalize_phone_number(
                    payload.mobile_number,
                    default_country_code=(
                        self.settings.sms_default_country_code
                    ),
                )
                sender = (
                    self._sms_sender
                    or build_sms_sender(self.settings)
                )
                sms_reference = sender.send(
                    OutboundSms(
                        to_number=normalized,
                        body=_sms_body(
                            title=payload.title,
                            message=payload.message,
                            maximum=(
                                self.settings.external_sms_max_chars
                            ),
                        ),
                    )
                )
                sms_sent = True
            except Exception as error:
                sms_error = _safe_delivery_error(error)
                logger.warning(
                    "External HR SMS notification failed for "
                    "company=%s user=%s event=%s: %s",
                    payload.company_id,
                    payload.user_id,
                    payload.event_type,
                    sms_error,
                )

        return ExternalDeliveryResult(
            email_sent=email_sent,
            sms_sent=sms_sent,
            email_reference=email_reference,
            sms_reference=sms_reference,
            email_error=email_error,
            sms_error=sms_error,
        )

    def send_test_sms(self, recipient: str) -> str:
        """Send a real provider test SMS from Admin Integrations."""

        status = self.get_status()
        if not status.sms_internet_ready:
            raise SmsDeliveryError(
                "Internet SMS is not fully configured or enabled."
            )
        normalized = normalize_phone_number(
            recipient,
            default_country_code=(
                self.settings.sms_default_country_code
            ),
        )
        sender = self._sms_sender or build_sms_sender(self.settings)
        return sender.send(
            OutboundSms(
                to_number=normalized,
                body=(
                    "AI HR Assistant test: external SMS notification "
                    "delivery is working."
                ),
            )
        )


def _safe_delivery_error(error: Exception) -> str:
    if isinstance(error, (EmailDeliveryError, SmsDeliveryError)):
        return str(error)[:500]
    return (
        f"{type(error).__name__}: external delivery failed."
    )[:500]


def _sms_body(*, title: str, message: str, maximum: int) -> str:
    text = " ".join(
        f"AI HR Assistant: {title}. {message}".split()
    )
    max_chars = max(80, int(maximum or 320))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _install_session_listeners() -> None:
    """Install one process-wide after-commit/rollback notification hook."""

    if getattr(Session, _LISTENER_MARKER, False):
        return

    @event.listens_for(Session, "after_commit")
    def _send_after_commit(session: Session) -> None:
        payloads = list(
            session.info.pop(_PENDING_KEY, [])
        )
        if not payloads:
            return

        service = ExternalNotificationService()
        for payload in payloads:
            try:
                service.deliver(payload)
            except Exception:
                logger.exception(
                    "Unexpected external notification dispatch failure."
                )

    @event.listens_for(Session, "after_rollback")
    def _discard_after_rollback(session: Session) -> None:
        session.info.pop(_PENDING_KEY, None)

    setattr(Session, _LISTENER_MARKER, True)


def queue_external_notification(
    session: Session,
    *,
    company_id: int,
    user_id: int,
    event_type: str,
    title: str,
    message: str,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
) -> bool:
    """Queue one recipient using Employee Master Record contact details."""

    settings = get_settings()
    if not (
        settings.external_email_notifications_enabled
        or settings.external_sms_notifications_enabled
    ):
        return False

    employee = session.scalar(
        select(Employee).where(
            Employee.company_id == company_id,
            Employee.user_id == user_id,
            Employee.employment_status == "employed",
        ).limit(1)
    )
    if employee is None:
        return False

    work_email = (
        employee.work_email.strip()
        if employee.work_email and employee.work_email.strip()
        else None
    )
    mobile_number = (
        employee.telephone_mobile_no.strip()
        if (
            employee.telephone_mobile_no
            and employee.telephone_mobile_no.strip()
        )
        else None
    )
    if not work_email and not mobile_number:
        return False

    payload = PendingExternalNotification(
        company_id=company_id,
        user_id=user_id,
        event_type=event_type.strip(),
        title=title.strip(),
        message=message.strip(),
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        work_email=work_email,
        mobile_number=mobile_number,
    )

    pending: list[PendingExternalNotification] = (
        session.info.setdefault(_PENDING_KEY, [])
    )
    dedupe_key = (
        payload.company_id,
        payload.user_id,
        payload.event_type,
        payload.title,
        payload.message,
        payload.related_entity_type,
        payload.related_entity_id,
    )
    if any(
        (
            item.company_id,
            item.user_id,
            item.event_type,
            item.title,
            item.message,
            item.related_entity_type,
            item.related_entity_id,
        )
        == dedupe_key
        for item in pending
    ):
        return False

    pending.append(payload)
    _install_session_listeners()
    return True
