"""Regression coverage for in-app external notification configuration."""

from pathlib import Path

from pydantic import SecretStr

from config.settings import Settings
import services.notification_configuration_service as config_module
from services.notification_configuration_service import (
    NotificationConfigurationError,
    NotificationConfigurationService,
    detect_email_provider,
)


ROOT = Path(__file__).resolve().parents[1]


def _settings(**overrides) -> Settings:
    values = {
        "email_delivery_mode": "local",
        "smtp_port": 587,
        "smtp_from_email": "no-reply@example.com",
        "smtp_from_name": "AI HR Assistant",
        "external_email_notifications_enabled": False,
        "external_sms_notifications_enabled": False,
        "sms_delivery_mode": "local",
        "sms_default_country_code": "+63",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_common_sender_domains_are_detected_without_provider_selection() -> None:
    gmail = detect_email_provider("hr@gmail.com")
    outlook = detect_email_provider("hr@outlook.com")
    yahoo = detect_email_provider("hr@yahoo.com")

    assert gmail.display_name == "Google / Gmail"
    assert gmail.host == "smtp.gmail.com"
    assert gmail.port == 587
    assert gmail.use_starttls is True

    assert outlook.display_name == "Microsoft Outlook"
    assert outlook.host == "smtp-mail.outlook.com"
    assert outlook.port == 587

    assert yahoo.display_name == "Yahoo Mail"
    assert yahoo.host == "smtp.mail.yahoo.com"
    assert yahoo.port == 465
    assert yahoo.use_ssl is True


def test_custom_company_domain_uses_advanced_smtp_fallback() -> None:
    profile = detect_email_provider("hr@company-example.com")

    assert profile.display_name == "Custom / Company Email"
    assert profile.automatic is False
    assert profile.host is None


def test_gmail_save_persists_detected_smtp_and_activation(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("APP_NAME=AI HR Assistant\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "_ENV_PATH", env_path)

    service = NotificationConfigurationService(
        settings=_settings()
    )
    result = service.save_email(
        sender_email="companyhr@gmail.com",
        sender_name="Company HR",
        credential="app-password",
        enabled=True,
    )

    saved = Settings(_env_file=env_path)
    assert result.email_provider == "Google / Gmail"
    assert saved.smtp_host == "smtp.gmail.com"
    assert saved.smtp_port == 587
    assert saved.smtp_username == "companyhr@gmail.com"
    assert saved.smtp_from_email == "companyhr@gmail.com"
    assert saved.smtp_use_starttls is True
    assert saved.smtp_use_ssl is False
    assert saved.external_email_notifications_enabled is True
    assert saved.smtp_password is not None
    assert saved.smtp_password.get_secret_value() == "app-password"


def test_custom_email_requires_explicit_server(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("APP_NAME=AI HR Assistant\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "_ENV_PATH", env_path)

    service = NotificationConfigurationService(settings=_settings())

    try:
        service.save_email(
            sender_email="hr@company-example.com",
            sender_name="Company HR",
            credential="secret",
            enabled=False,
        )
    except NotificationConfigurationError as error:
        assert "SMTP server" in str(error)
    else:
        raise AssertionError("Custom domain was saved without SMTP server.")


def test_sms_gateway_is_saved_once_without_employee_network_selection(
    tmp_path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("APP_NAME=AI HR Assistant\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "_ENV_PATH", env_path)

    service = NotificationConfigurationService(settings=_settings())
    service.save_sms(
        enabled=True,
        account_sid="AC" + ("1" * 32),
        auth_token="token",
        from_number="+15005550006",
        messaging_service_sid="",
        default_country_code="+63",
    )

    saved = Settings(_env_file=env_path)
    assert saved.sms_delivery_mode == "twilio"
    assert saved.sms_default_country_code == "+63"
    assert saved.external_sms_notifications_enabled is True
    assert saved.twilio_auth_token is not None
    assert saved.twilio_auth_token.get_secret_value() == "token"


def test_existing_secret_can_be_kept_when_reactivating_email(
    tmp_path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("APP_NAME=AI HR Assistant\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "_ENV_PATH", env_path)

    service = NotificationConfigurationService(
        settings=_settings(
            email_delivery_mode="smtp",
            smtp_password=SecretStr("existing-secret"),
        )
    )
    service.save_email(
        sender_email="hr@gmail.com",
        sender_name="Company HR",
        credential="",
        enabled=True,
    )

    saved = Settings(_env_file=env_path)
    assert saved.email_delivery_mode == "smtp"
    assert saved.external_email_notifications_enabled is True
    # Blank credential keeps the already-loaded secret in memory and does not
    # overwrite the private .env value with an empty password.
    assert "SMTP_PASSWORD" not in env_path.read_text(encoding="utf-8")


def test_admin_ui_uses_in_app_setup_and_no_email_provider_dropdown() -> None:
    source = (ROOT / "ui/pages/admin/integrations_page.py").read_text(
        encoding="utf-8"
    )

    assert '"Company Sender Email"' in source
    assert '"Activate Email Notifications"' in source
    assert '"Save Email Settings"' in source
    assert '"Activate SMS Notifications"' in source
    assert '"Save SMS Settings"' in source
    assert "Provider detected automatically" in source
    assert "Employee Master Record · Work Email" in source
    assert "Employee Master Record · Telephone / Mobile No." in source
    assert "Select Email Provider" not in source
    assert "Select Mobile Network" not in source


def test_root_readme_is_execution_guide_without_release_history() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Run" not in readme  # old release-log opening removed
    assert "## 7. Run the Application" in readme
    assert "Foundation v1.1 update" not in readme
    assert "v8.8" not in readme
    assert not list(ROOT.glob("RELEASE_*.md"))


def test_app_version_is_incremented() -> None:
    settings_source = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    assert 'app_version: str = "0.8.8.163"' in settings_source
