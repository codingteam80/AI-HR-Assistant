"""v8.7.5 combined UI workflow regression checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_notification_count_is_visible_without_hover() -> None:
    topbar = (
        ROOT / "ui/components/topbar.py"
    ).read_text(encoding="utf-8")
    theme = (
        ROOT / "ui/theme/theme_loader.py"
    ).read_text(encoding="utf-8")

    assert 'label = f"🔔 {unread}"' in topbar
    assert 'type="primary"' in topbar
    assert '@st.dialog("Notifications")' not in topbar
    assert 'key="notification_dropdown_panel"' in topbar
    assert "background: var(--hr-primary) !important;" in theme


def test_announcements_use_a_separate_full_width_workspace() -> None:
    source = (
        ROOT / "ui/pages/user/announcements_page.py"
    ).read_text(encoding="utf-8")

    assert "Company Announcements" in source
    assert "render_announcement_card" in source
    assert "Search Announcements" in source


def test_delete_never_calls_repository_hard_delete() -> None:
    admin_page = (
        ROOT
        / "ui/pages/admin/announcements_page.py"
    ).read_text(encoding="utf-8")
    service = (
        ROOT
        / "services/announcement_service.py"
    ).read_text(encoding="utf-8")

    assert "move_to_archive(" in admin_page
    assert "session.delete(" not in service
    assert 'status = "archived"' in service
