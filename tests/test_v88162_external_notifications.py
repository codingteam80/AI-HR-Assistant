"""Regression tests for v8.8.162 external email/SMS notifications."""

from pydantic import SecretStr

from config.settings import Settings
from integrations.email.email_sender import OutboundEmail
from integrations.sms.sms_sender import (
    OutboundSms,
    normalize_phone_number,
)
from services.external_notification_service import (
    ExternalNotificationService,
    PendingExternalNotification,
)


class CapturingEmailSender:
    def __init__(self) -> None:
        self.messages: list[OutboundEmail] = []

    def send(self, message: OutboundEmail) -> str:
        self.messages.append(message)
        return "email-ref"


class CapturingSmsSender:
    def __init__(self) -> None:
        self.messages: list[OutboundSms] = []

    def send(self, message: OutboundSms) -> str:
        self.messages.append(message)
        return "sms-ref"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        external_email_notifications_enabled=True,
        external_sms_notifications_enabled=True,
        email_delivery_mode="smtp",
        smtp_host="smtp.example.com",
        smtp_username="hr@example.com",
        smtp_password=SecretStr("secret"),
        smtp_from_email="hr@example.com",
        sms_delivery_mode="twilio",
        sms_default_country_code="+63",
        twilio_account_sid="AC" + ("1" * 32),
        twilio_auth_token=SecretStr("token"),
        twilio_from_number="+15005550006",
    )


def _payload(event_type: str = "overtime_request_approved") -> PendingExternalNotification:
    return PendingExternalNotification(
        company_id=1,
        user_id=2,
        event_type=event_type,
        title="Overtime request approved",
        message="OTR_000001 was approved.",
        related_entity_type="overtime_request",
        related_entity_id=1,
        work_email="employee@example.com",
        mobile_number="09171234567",
    )


def test_philippine_local_number_is_normalized() -> None:
    assert normalize_phone_number(
        "0917 123 4567",
        default_country_code="+63",
    ) == "+639171234567"


def test_external_service_delivers_email_and_sms_independently() -> None:
    email = CapturingEmailSender()
    sms = CapturingSmsSender()
    service = ExternalNotificationService(
        settings=_settings(),
        email_sender=email,
        sms_sender=sms,
    )

    result = service.deliver(_payload())

    assert result.email_sent is True
    assert result.sms_sent is True
    assert email.messages[0].to_email == "employee@example.com"
    assert sms.messages[0].to_number == "+639171234567"
    assert "Overtime request approved" in email.messages[0].subject
    assert "AI HR Assistant" in sms.messages[0].body


def test_legacy_leave_email_is_not_duplicated_but_sms_still_sends() -> None:
    email = CapturingEmailSender()
    sms = CapturingSmsSender()
    service = ExternalNotificationService(
        settings=_settings(),
        email_sender=email,
        sms_sender=sms,
    )

    result = service.deliver(
        _payload("leave_request_submitted")
    )

    assert result.email_sent is False
    assert result.sms_sent is True
    assert email.messages == []
    assert len(sms.messages) == 1


def test_status_requires_real_provider_configuration() -> None:
    status = ExternalNotificationService(
        settings=_settings()
    ).get_status()

    assert status.email_enabled is True
    assert status.email_internet_ready is True
    assert status.sms_enabled is True
    assert status.sms_internet_ready is True


def test_external_delivery_failure_does_not_raise() -> None:
    class FailingSmsSender:
        def send(self, message: OutboundSms) -> str:
            raise RuntimeError("provider failed")

    service = ExternalNotificationService(
        settings=_settings(),
        email_sender=CapturingEmailSender(),
        sms_sender=FailingSmsSender(),
    )

    result = service.deliver(_payload())

    assert result.email_sent is True
    assert result.sms_sent is False
    assert result.sms_error is not None
