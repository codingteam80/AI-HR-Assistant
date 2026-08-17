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


class Settings(BaseSettings):
    """Environment-driven application settings.

    Each class field can be overridden by a matching environment variable.
    Example:
        database_url -> DATABASE_URL
        initial_admin_email -> INITIAL_ADMIN_EMAIL
    """

    # Application identity and runtime behavior.
    app_name: str = "AI HR Assistant"
    app_version: str = "0.8.8.158"
    # Immediate base checkpoint: app_version: str = "0.8.8.157"
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
    # The signed token is stored in browser localStorage so it survives F5
    # refreshes without depending on asynchronous third-party cookie APIs.
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

    # Shared local Smart AI configuration for both the Admin and Employee
    # Chat Assistant pages. The deterministic HR services remain authoritative;
    # Ollama is used only to synthesize grounded answers from approved portal
    # context. Both normal and complex questions use the same lightweight model
    # so an installation needs to download only one Ollama model.
    smart_ai_enabled: bool = True
    smart_ai_ollama_base_url: str = "http://localhost:11434"
    smart_ai_ollama_model: str = "qwen2.5:3b"
    smart_ai_quality_ollama_model: str = "qwen2.5:3b"
    smart_ai_ollama_timeout_seconds: int = 120

    # Retrieval remains dependency-safe: BM25 always works, while Chroma,
    # embeddings, and reranking activate only when their optional packages are
    # installed locally.
    smart_ai_chunk_size: int = 256
    smart_ai_chunk_overlap: int = 40
    smart_ai_bm25_top_k: int = 8
    smart_ai_vector_top_k: int = 8
    smart_ai_final_top_k: int = 5
    smart_ai_chroma_dir: str = "data/smart_ai/chroma"
    smart_ai_chroma_collection: str = "hr_portal_knowledge"
    smart_ai_embedding_model: str = "intfloat/multilingual-e5-small"
    smart_ai_reranker_enabled: bool = False
    smart_ai_reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

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
