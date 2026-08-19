"""In-app configuration for external email and SMS notifications.

Administrators can configure the company sender from the protected Admin
Portal. Settings are persisted to the project's private `.env` file so the
existing provider adapters remain the single delivery implementation.

Recipient destinations are never configured here. Employee Master Record
`work_email` and `telephone_mobile_no` remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from dotenv import set_key
from pydantic import EmailStr, TypeAdapter

from config.settings import Settings, get_settings
from integrations.sms.sms_sender import normalize_phone_number


_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_PATH = _PROJECT_ROOT / ".env"


class NotificationConfigurationError(ValueError):
    """Raised for safe administrator-facing configuration validation."""


@dataclass(frozen=True, slots=True)
class EmailProviderProfile:
    """Detected sender-email profile used to preconfigure SMTP."""

    key: str
    display_name: str
    host: str | None
    port: int | None
    use_starttls: bool
    use_ssl: bool
    automatic: bool
    credential_label: str
    guidance: str


@dataclass(frozen=True, slots=True)
class SavedNotificationConfiguration:
    """Safe summary after one in-app configuration save."""

    email_provider: str | None = None
    email_enabled: bool | None = None
    sms_enabled: bool | None = None


_COMMON_EMAIL_PROVIDERS: dict[str, EmailProviderProfile] = {
    "gmail.com": EmailProviderProfile(
        key="google",
        display_name="Google / Gmail",
        host="smtp.gmail.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="App Password / SMTP Credential",
        guidance=(
            "Google accounts commonly require an App Password when the "
            "account is eligible for App Passwords. Google Workspace may "
            "use an administrator-approved SMTP configuration instead."
        ),
    ),
    "googlemail.com": EmailProviderProfile(
        key="google",
        display_name="Google / Gmail",
        host="smtp.gmail.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="App Password / SMTP Credential",
        guidance=(
            "Google accounts commonly require an App Password when the "
            "account is eligible for App Passwords. Google Workspace may "
            "use an administrator-approved SMTP configuration instead."
        ),
    ),
    "outlook.com": EmailProviderProfile(
        key="microsoft",
        display_name="Microsoft Outlook",
        host="smtp-mail.outlook.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="SMTP Credential",
        guidance=(
            "Microsoft may require Modern Authentication for some accounts. "
            "If basic SMTP authentication is not allowed, use the custom "
            "company SMTP server approved by your Microsoft 365 admin."
        ),
    ),
    "hotmail.com": EmailProviderProfile(
        key="microsoft",
        display_name="Microsoft Outlook",
        host="smtp-mail.outlook.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="SMTP Credential",
        guidance=(
            "Microsoft may require Modern Authentication for some accounts. "
            "If basic SMTP authentication is not allowed, use the custom "
            "company SMTP server approved by your Microsoft 365 admin."
        ),
    ),
    "live.com": EmailProviderProfile(
        key="microsoft",
        display_name="Microsoft Outlook",
        host="smtp-mail.outlook.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="SMTP Credential",
        guidance=(
            "Microsoft may require Modern Authentication for some accounts. "
            "If basic SMTP authentication is not allowed, use the custom "
            "company SMTP server approved by your Microsoft 365 admin."
        ),
    ),
    "msn.com": EmailProviderProfile(
        key="microsoft",
        display_name="Microsoft Outlook",
        host="smtp-mail.outlook.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="SMTP Credential",
        guidance=(
            "Microsoft may require Modern Authentication for some accounts. "
            "If basic SMTP authentication is not allowed, use the custom "
            "company SMTP server approved by your Microsoft 365 admin."
        ),
    ),
    "yahoo.com": EmailProviderProfile(
        key="yahoo",
        display_name="Yahoo Mail",
        host="smtp.mail.yahoo.com",
        port=465,
        use_starttls=False,
        use_ssl=True,
        automatic=True,
        credential_label="App Password / SMTP Credential",
        guidance=(
            "Yahoo may require an app password for third-party SMTP clients."
        ),
    ),
    "ymail.com": EmailProviderProfile(
        key="yahoo",
        display_name="Yahoo Mail",
        host="smtp.mail.yahoo.com",
        port=465,
        use_starttls=False,
        use_ssl=True,
        automatic=True,
        credential_label="App Password / SMTP Credential",
        guidance=(
            "Yahoo may require an app password for third-party SMTP clients."
        ),
    ),
    "rocketmail.com": EmailProviderProfile(
        key="yahoo",
        display_name="Yahoo Mail",
        host="smtp.mail.yahoo.com",
        port=465,
        use_starttls=False,
        use_ssl=True,
        automatic=True,
        credential_label="App Password / SMTP Credential",
        guidance=(
            "Yahoo may require an app password for third-party SMTP clients."
        ),
    ),
    "icloud.com": EmailProviderProfile(
        key="apple",
        display_name="Apple iCloud Mail",
        host="smtp.mail.me.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="App-Specific Password / SMTP Credential",
        guidance=(
            "iCloud Mail commonly uses an app-specific password for SMTP."
        ),
    ),
    "me.com": EmailProviderProfile(
        key="apple",
        display_name="Apple iCloud Mail",
        host="smtp.mail.me.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="App-Specific Password / SMTP Credential",
        guidance=(
            "iCloud Mail commonly uses an app-specific password for SMTP."
        ),
    ),
    "mac.com": EmailProviderProfile(
        key="apple",
        display_name="Apple iCloud Mail",
        host="smtp.mail.me.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="App-Specific Password / SMTP Credential",
        guidance=(
            "iCloud Mail commonly uses an app-specific password for SMTP."
        ),
    ),
    "aol.com": EmailProviderProfile(
        key="aol",
        display_name="AOL Mail",
        host="smtp.aol.com",
        port=465,
        use_starttls=False,
        use_ssl=True,
        automatic=True,
        credential_label="App Password / SMTP Credential",
        guidance=(
            "AOL may require an app password for third-party SMTP clients."
        ),
    ),
    "zoho.com": EmailProviderProfile(
        key="zoho",
        display_name="Zoho Mail",
        host="smtp.zoho.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="SMTP Credential",
        guidance=(
            "Zoho organization policies determine whether an app-specific "
            "password or normal SMTP credential is accepted."
        ),
    ),
    "gmx.com": EmailProviderProfile(
        key="gmx",
        display_name="GMX Mail",
        host="mail.gmx.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="SMTP Credential",
        guidance="Use the SMTP credential allowed by the GMX account.",
    ),
    "mail.com": EmailProviderProfile(
        key="mailcom",
        display_name="mail.com",
        host="smtp.mail.com",
        port=587,
        use_starttls=True,
        use_ssl=False,
        automatic=True,
        credential_label="SMTP Credential",
        guidance="Use the SMTP credential allowed by the mail.com account.",
    ),
}


def detect_email_provider(sender_email: str) -> EmailProviderProfile:
    """Detect common public providers from the sender address.

    A custom/company domain intentionally returns a manual profile instead of
    guessing. A domain alone cannot reliably reveal whether the company uses
    Google Workspace, Microsoft 365, an on-premise server, or another relay.
    """

    try:
        validated = str(
            _EMAIL_ADAPTER.validate_python((sender_email or "").strip())
        )
    except Exception as error:
        raise NotificationConfigurationError(
            "Enter a valid sender email address."
        ) from error

    domain = validated.rsplit("@", 1)[1].lower()
    profile = _COMMON_EMAIL_PROVIDERS.get(domain)
    if profile is not None:
        return profile

    return EmailProviderProfile(
        key="custom",
        display_name="Custom / Company Email",
        host=None,
        port=None,
        use_starttls=True,
        use_ssl=False,
        automatic=False,
        credential_label="SMTP Password / Credential",
        guidance=(
            "This email uses a custom domain. The domain does not uniquely "
            "identify its outgoing mail server, so enter the company SMTP "
            "server once in Advanced SMTP Settings."
        ),
    )


def _validate_host(value: str) -> str:
    host = (value or "").strip()
    if not host or len(host) > 255:
        raise NotificationConfigurationError(
            "Enter the outgoing SMTP server for the company email."
        )
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", host):
        raise NotificationConfigurationError(
            "The SMTP server contains unsupported characters."
        )
    return host


def _ensure_env() -> None:
    if not _ENV_PATH.exists():
        _ENV_PATH.touch(encoding="utf-8")


def _set_env_values(values: dict[str, str]) -> None:
    """Persist private settings without exposing secret values in the UI."""

    _ensure_env()
    for key, value in values.items():
        set_key(
            str(_ENV_PATH),
            key,
            str(value),
            quote_mode="always",
        )

    # Settings is lru-cached across Streamlit reruns. Clearing here makes the
    # saved values effective immediately on the next service construction.
    get_settings.cache_clear()


class NotificationConfigurationService:
    """Save protected external notification settings from the Admin Portal."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def detect_sender(self, sender_email: str) -> EmailProviderProfile:
        return detect_email_provider(sender_email)

    def save_email(
        self,
        *,
        sender_email: str,
        sender_name: str,
        credential: str,
        enabled: bool,
        custom_host: str | None = None,
        custom_port: int | None = None,
        custom_encryption: str = "STARTTLS",
    ) -> SavedNotificationConfiguration:
        try:
            validated_email = str(
                _EMAIL_ADAPTER.validate_python(sender_email.strip())
            )
        except Exception as error:
            raise NotificationConfigurationError(
                "Enter a valid sender email address."
            ) from error

        profile = detect_email_provider(validated_email)
        safe_name = (sender_name or "AI HR Assistant").strip()[:120]
        existing_password = (
            self.settings.smtp_password.get_secret_value()
            if self.settings.smtp_password is not None
            else ""
        )
        password_to_store = credential if credential else existing_password

        if profile.automatic:
            host = str(profile.host)
            port = int(profile.port or 587)
            use_starttls = profile.use_starttls
            use_ssl = profile.use_ssl
        else:
            host = _validate_host(custom_host or "")
            port = int(custom_port or 0)
            if port < 1 or port > 65535:
                raise NotificationConfigurationError(
                    "SMTP port must be between 1 and 65535."
                )
            encryption = (custom_encryption or "STARTTLS").strip().upper()
            if encryption not in {"STARTTLS", "SSL/TLS", "NONE"}:
                raise NotificationConfigurationError(
                    "Choose STARTTLS, SSL/TLS, or None for SMTP encryption."
                )
            use_starttls = encryption == "STARTTLS"
            use_ssl = encryption == "SSL/TLS"

        if enabled and not password_to_store.strip():
            raise NotificationConfigurationError(
                "Enter the sender email credential before activating email notifications."
            )

        values = {
            "EMAIL_DELIVERY_MODE": (
                "smtp"
                if password_to_store.strip()
                else self.settings.email_delivery_mode
            ),
            "SMTP_HOST": host,
            "SMTP_PORT": str(port),
            "SMTP_USERNAME": validated_email,
            "SMTP_FROM_EMAIL": validated_email,
            "SMTP_FROM_NAME": safe_name,
            "SMTP_USE_STARTTLS": str(use_starttls).lower(),
            "SMTP_USE_SSL": str(use_ssl).lower(),
            "EXTERNAL_EMAIL_NOTIFICATIONS_ENABLED": str(bool(enabled)).lower(),
        }
        if credential:
            values["SMTP_PASSWORD"] = credential

        _set_env_values(values)
        return SavedNotificationConfiguration(
            email_provider=profile.display_name,
            email_enabled=bool(enabled),
        )

    def save_sms(
        self,
        *,
        enabled: bool,
        account_sid: str,
        auth_token: str,
        from_number: str,
        messaging_service_sid: str,
        default_country_code: str,
    ) -> SavedNotificationConfiguration:
        existing_token = (
            self.settings.twilio_auth_token.get_secret_value()
            if self.settings.twilio_auth_token is not None
            else ""
        )
        token_to_store = auth_token if auth_token else existing_token
        sid = (account_sid or "").strip()
        sender_number = (from_number or "").strip()
        messaging_sid = (messaging_service_sid or "").strip()
        country_code = (default_country_code or "+63").strip()

        # Reuse the same number validator used for employee recipients, but
        # accept a country-code-only value such as +63 for local normalization.
        if not re.fullmatch(r"\+[1-9]\d{0,3}", country_code):
            raise NotificationConfigurationError(
                "Default country code must look like +63, +1, or +44."
            )

        if sender_number:
            try:
                sender_number = normalize_phone_number(
                    sender_number,
                    default_country_code=country_code,
                )
            except Exception as error:
                raise NotificationConfigurationError(
                    "Enter a valid SMS sender number or leave it blank when using a Messaging Service SID."
                ) from error

        if enabled:
            if not sid or not token_to_store:
                raise NotificationConfigurationError(
                    "Enter the company SMS gateway Account SID and Auth Token before activating SMS notifications."
                )
            if not sender_number and not messaging_sid:
                raise NotificationConfigurationError(
                    "Enter an SMS sender number or Messaging Service SID before activating SMS notifications."
                )

        values = {
            "SMS_DELIVERY_MODE": "twilio",
            "SMS_DEFAULT_COUNTRY_CODE": country_code,
            "TWILIO_ACCOUNT_SID": sid,
            "TWILIO_FROM_NUMBER": sender_number,
            "TWILIO_MESSAGING_SERVICE_SID": messaging_sid,
            "EXTERNAL_SMS_NOTIFICATIONS_ENABLED": str(bool(enabled)).lower(),
        }
        if auth_token:
            values["TWILIO_AUTH_TOKEN"] = auth_token

        _set_env_values(values)
        return SavedNotificationConfiguration(
            sms_enabled=bool(enabled),
        )


def reload_notification_settings() -> Settings:
    """Return settings freshly read from `.env` after an in-app save."""

    get_settings.cache_clear()
    return get_settings()
