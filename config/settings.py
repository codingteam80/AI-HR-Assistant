"""Central application configuration.

Purpose:
- Load values from the local `.env` file.
- Provide one consistent Settings object to the entire project.
- Keep database, company, admin, UI, and logging configuration
  outside the business logic.

Debugging note:
If a configuration value looks incorrect, check `.env` first.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.chat_assistant_settings import ChatAssistantSettingsCompatibilityMixin


class Settings(ChatAssistantSettingsCompatibilityMixin, BaseSettings):
    """Environment-driven application settings.

    Each class field can be overridden by a matching environment variable.
    Example:
        database_url -> DATABASE_URL
        initial_admin_email -> INITIAL_ADMIN_EMAIL
    """

    # Application identity and runtime behavior.
    app_name: str = "AI HR Assistant"
    app_version: str = "0.8.8.169"
    # Previous table-readability checkpoint: app_version: str = "0.8.8.164.3"
    # Previous per-tab-auth checkpoint: app_version: str = "0.8.8.164.4"
    # Immediate base checkpoint: app_version: str = "0.8.8.164"
    # Previous in-app notification checkpoint: app_version: str = "0.8.8.163"
    # Immediate base checkpoint: app_version: str = "0.8.8.161"
    # Immediate base checkpoint: app_version: str = "0.8.8.160"
    # Earlier base checkpoint: app_version: str = "0.8.8.158"
    # Earlier base checkpoint: app_version: str = "0.8.8.157"
    # Earlier base checkpoint: app_version: str = "0.8.8.156"
    # Earlier base checkpoint: app_version: str = "0.8.8.155"
    # Earlier base checkpoint: app_version: str = "0.8.8.154"
    # Earlier base checkpoint: app_version: str = "0.8.8.153"
    # Earlier base checkpoint: app_version: str = "0.8.8.152"
    # Earlier base checkpoint: app_version: str = "0.8.8.151"
    # Earlier base checkpoint: app_version: str = "0.8.8.150"
    # Earlier base checkpoint: app_version: str = "0.8.8.149"
    # Earlier base checkpoint: app_version: str = "0.8.8.148"
    # Earlier compatibility checkpoint: app_version: str = "0.8.8.147"
    # Previous compatibility marker: app_version: str = "0.8.8.70"
    # Immediate base checkpoint: 0.8.8.143
    environment: str = "development"
    debug: bool = True

    # SQLAlchemy database connection string.
    # SQLite is used for local development.
    # PostgreSQL can be used later by changing only this value.
    database_url: str = "sqlite:///./data/hr_assistant.db"

    # Shared UI and branding defaults.
    # Light Mode is fixed; no theme selector is shown.
    default_theme: str = "light"
    company_name: str = "Sample Company"
    assistant_name: str = "AI HR Assistant"

    # Signed browser authentication token.
    # The signed token is stored in tab-scoped browser sessionStorage so it
    # survives F5 refreshes without being shared across separate tabs/windows.
    # Set AUTH_COOKIE_SECRET to a long random value in production. When
    # omitted, a private local secret file is created automatically.
    auth_cookie_secret: SecretStr | None = None
    auth_cookie_secret_file: str = "data/.auth_cookie_secret"
    auth_cookie_hours: int = 12

    # Localhost uses HTTP, so secure=False is required during development.
    # Set AUTH_COOKIE_SECURE=true when the deployed app uses HTTPS.
    auth_cookie_secure: bool = False

    # Logging level used by the application logger.
    log_level: str = "INFO"

    # File-based HR policy storage.
    # Files remain private and are served only after company authorization.
    policy_upload_dir: str = "data/uploads/policies"
    policy_upload_max_mb: int = 10

    # Leave-request supporting documents.
    leave_attachment_dir: str = "data/uploads/leave_requests"
    leave_attachment_max_mb: int = 10

    # Company announcement cover images.
    announcement_upload_dir: str = "data/uploads/announcements"
    announcement_upload_max_mb: int = 5

    # Company forms, downloadable templates, and employee submissions.
    company_form_upload_dir: str = "data/uploads/company_forms"
    company_form_upload_max_mb: int = 15

    # Company-scoped sidebar logos. Uploaded files are normalized to PNG.
    company_logo_upload_dir: str = "data/uploads/company_logos"
    company_logo_upload_max_mb: int = 5

    display_timezone: str = "Asia/Manila"

    # Chat Assistant model/generation/retrieval settings live in
    # config/chat_assistant_settings.py. A compatibility mixin preserves the
    # older `settings.smart_ai_*` attributes for existing integrations.

    # Password-reset links.
    # Set this to the public Streamlit URL in production.
    password_reset_base_url: str = "http://localhost:8501"
    password_reset_token_minutes: int = 30
    password_reset_request_cooldown_seconds: int = 60

    # Email delivery:
    # - local: write reset messages to a private development outbox.
    # - smtp: send to the registered login email through SMTP.
    email_delivery_mode: str = "local"
    password_reset_outbox_dir: str = "data/dev_mail_outbox"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: str = "no-reply@example.com"
    smtp_from_name: str = "AI HR Assistant"
    smtp_use_starttls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 20

    # External notification mirroring. The Employee Master Record work_email
    # and telephone_mobile_no fields are the authoritative destinations.
    external_email_notifications_enabled: bool = False
    external_sms_notifications_enabled: bool = False

    # SMS delivery:
    # - local: write a private development SMS file.
    # - twilio: send a real SMS using Twilio Programmable Messaging.
    sms_delivery_mode: str = "local"
    external_sms_outbox_dir: str = "data/dev_sms_outbox"
    sms_default_country_code: str = "+63"
    sms_timeout_seconds: int = 12
    external_sms_max_chars: int = 320

    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None
    twilio_messaging_service_sid: str | None = None

    # Initial company values used by the seed script.
    initial_company_code: str = "DEFAULT"
    initial_company_name: str = "Default Company"

    # Initial company administrator values.
    # SecretStr hides the password when the Settings object is printed.
    initial_admin_username: str = "admin"
    initial_admin_email: str = "admin@example.com"
    initial_admin_password: SecretStr = SecretStr("ChangeMe123!")
    initial_admin_employee_number: str = "ADMIN-001"
    initial_admin_first_name: str = "System"
    initial_admin_last_name: str = "Administrator"

    # Tell Pydantic Settings how to read the environment file.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one cached Settings instance.

    Caching prevents the application from repeatedly reading `.env`.
    During debugging, restart Streamlit after changing `.env`.
    """

    return Settings()
