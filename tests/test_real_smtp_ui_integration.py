"""Static checks for production SMTP polishing."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (
        PROJECT_ROOT / relative_path
    ).read_text(encoding="utf-8")


def test_integrations_sidebar_route_is_replaced_by_audit_trail() -> None:
    """The retired sidebar destination must open the central history."""

    layout_source = _read("ui/layouts/admin_layout.py")
    sidebar_source = _read("ui/components/admin_sidebar.py")

    assert 'page == "Audit Trail"' in layout_source
    assert "render_audit_trail_page(current_user)" in layout_source
    assert 'if st.session_state.current_page == "Integrations"' in sidebar_source
    assert 'current_page="Audit Trail"' in sidebar_source


def test_integrations_page_can_send_real_test_email() -> None:
    """The UI must expose SMTP readiness and test delivery."""

    source = _read(
        "ui/pages/admin/integrations_page.py"
    )

    assert "Internet email delivery is configured." in source
    assert '"Send Internet Test Email"' in source
    assert "service.send_test_email(" in source
    assert "SMTP password is intentionally hidden" in source


def test_public_forgot_page_hides_local_outbox_details() -> None:
    """The public reset page must remain production-like."""

    source = _read(
        "ui/pages/authentication/forgot_password_page.py"
    )

    assert "Development mode:" not in source
    assert "dev_mail_outbox" not in source
    assert "result.message" in source


def test_smtp_configuration_script_has_provider_presets() -> None:
    """The setup helper must include common and custom SMTP options."""

    source = _read(
        "scripts/configure_smtp.py"
    )

    assert "smtp.gmail.com" in source
    assert "smtp.office365.com" in source
    assert "Custom SMTP server" in source
    assert "getpass(" in source
    assert "SMTP_PASSWORD" in source
    assert "password was saved only" in source


def test_env_example_points_to_smtp_setup_script() -> None:
    """Configuration documentation must be visible in `.env.example`."""

    source = _read(".env.example")

    assert "python scripts/configure_smtp.py" in source
    assert "EMAIL_DELIVERY_MODE=local" in source
