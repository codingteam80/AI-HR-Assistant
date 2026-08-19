"""Administrator-facing email integration status and test delivery.

This service never returns or displays the SMTP password. It exposes only
safe configuration metadata and uses the same EmailSender adapter used by
the Forgot Password workflow.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import EmailStr, TypeAdapter

from config.settings import Settings, get_settings
from integrations.email.email_sender import (
    EmailDeliveryError,
    EmailSender,
    OutboundEmail,
    build_email_sender,
)


_EMAIL_ADAPTER = TypeAdapter(EmailStr)


@dataclass(slots=True)
class EmailIntegrationStatus:
    """Safe email-delivery configuration shown to administrators."""

    mode: str
    internet_delivery_ready: bool
    host: str | None
    port: int | None
    encryption: str
    username_configured: bool
    password_configured: bool
    from_email: str
    from_name: str
    reset_base_url: str
    message: str


@dataclass(slots=True)
class TestEmailResult:
    """Result of one administrator-requested test email."""

    recipient: str
    delivery_reference: str
    sent_at: datetime


class EmailIntegrationService:
    """Inspect and test the configured email delivery adapter."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        email_sender: EmailSender | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._email_sender = email_sender

    def get_status(self) -> EmailIntegrationStatus:
        """Return safe configuration readiness without network access."""

        mode = self.settings.email_delivery_mode.strip().lower()
        host = (self.settings.smtp_host or "").strip() or None
        username = (
            self.settings.smtp_username or ""
        ).strip()

        if self.settings.smtp_use_ssl:
            encryption = "SSL/TLS"
        elif self.settings.smtp_use_starttls:
            encryption = "STARTTLS"
        else:
            encryption = "None"

        smtp_ready = bool(
            mode == "smtp"
            and host
            and self.settings.smtp_port
            and username
            and self.settings.smtp_password is not None
            and (
                self.settings.smtp_password
                .get_secret_value()
                .strip()
            )
            and self.settings.smtp_from_email.strip()
        )

        if smtp_ready:
            message = (
                "SMTP internet email is configured. "
                "Send a test email to verify network access "
                "and provider authentication."
            )
        elif mode == "local":
            message = (
                "Local development email is active. "
                "Configure SMTP to deliver password-reset links "
                "to real inboxes."
            )
        else:
            message = (
                "SMTP mode is selected, but one or more required "
                "settings are missing."
            )

        return EmailIntegrationStatus(
            mode=mode,
            internet_delivery_ready=smtp_ready,
            host=host,
            port=(
                self.settings.smtp_port
                if host
                else None
            ),
            encryption=encryption,
            username_configured=bool(username),
            password_configured=bool(
                self.settings.smtp_password is not None
                and self.settings.smtp_password.get_secret_value().strip()
            ),
            from_email=self.settings.smtp_from_email,
            from_name=self.settings.smtp_from_name,
            reset_base_url=(
                self.settings.password_reset_base_url
            ),
            message=message,
        )

    def send_test_email(
        self,
        recipient: str,
    ) -> TestEmailResult:
        """Send a real test email through the configured SMTP adapter."""

        status = self.get_status()

        if not status.internet_delivery_ready:
            raise EmailDeliveryError(
                "SMTP internet email is not fully configured."
            )

        try:
            validated_recipient = str(
                _EMAIL_ADAPTER.validate_python(
                    recipient.strip()
                )
            )
        except Exception as error:
            raise EmailDeliveryError(
                "Enter a valid test recipient email address."
            ) from error

        sender = (
            self._email_sender
            or build_email_sender(self.settings)
        )
        sent_at = datetime.now(timezone.utc)

        reference = sender.send(
            OutboundEmail(
                to_email=validated_recipient,
                subject=(
                    "AI HR Assistant email delivery test"
                ),
                text_body=(
                    "This is a test email from AI HR Assistant.\n\n"
                    "SMTP internet delivery is working for password-reset "
                    "messages.\n\n"
                    f"Test time (UTC): {sent_at.isoformat()}\n"
                    f"Reset base URL: "
                    f"{self.settings.password_reset_base_url}\n\n"
                    "No employee password or reset token is included "
                    "in this test."
                ),
            )
        )

        return TestEmailResult(
            recipient=validated_recipient,
            delivery_reference=reference,
            sent_at=sent_at,
        )
