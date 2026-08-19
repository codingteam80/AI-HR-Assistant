"""Static wiring checks for external notification integration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_global_notification_service_queues_external_delivery() -> None:
    source = (ROOT / "services/notification_service.py").read_text(encoding="utf-8")
    assert "queue_external_notification" in source


def test_external_delivery_is_after_commit_and_rollback_safe() -> None:
    source = (ROOT / "services/external_notification_service.py").read_text(encoding="utf-8")
    assert '"after_commit"' in source
    assert '"after_rollback"' in source
    assert "employee.telephone_mobile_no" in source
    assert "employee.work_email" in source


def test_admin_integrations_has_sms_status_and_test() -> None:
    source = (ROOT / "ui/pages/admin/integrations_page.py").read_text(encoding="utf-8")
    assert 'st.subheader("External HR Notifications")' in source
    assert '"Send Internet Test SMS"' in source
    assert "ExternalNotificationService" in source


def test_environment_example_documents_external_channels() -> None:
    source = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "EXTERNAL_EMAIL_NOTIFICATIONS_ENABLED=false" in source
    assert "EXTERNAL_SMS_NOTIFICATIONS_ENABLED=false" in source
    assert "SMS_DELIVERY_MODE=local" in source
    assert "TWILIO_ACCOUNT_SID=" in source


def test_external_notifications_are_reachable_from_admin_navigation() -> None:
    sidebar = (ROOT / "ui/components/admin_sidebar.py").read_text(encoding="utf-8")
    layout = (ROOT / "ui/layouts/admin_layout.py").read_text(encoding="utf-8")
    assert '"External Notifications"' in sidebar
    assert 'page == "External Notifications"' in layout
    assert "render_integrations_page(current_user)" in layout
