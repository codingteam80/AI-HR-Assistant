"""Regression checks for v8.8.100 simplified Employee Dashboard."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_employee_announcements_workspace_keeps_count() -> None:
    source = _read("ui/pages/user/announcements_page.py")

    assert "ANNOUNCEMENT_CATEGORIES" in source
    assert "dashboard_announcement_category" not in source
    assert "dashboard_announcement_search" not in source
    assert "announcement-unread-count" in source


def test_employee_workspace_keeps_announcement_content_and_deep_links() -> None:
    source = _read("ui/pages/user/announcements_page.py")

    assert "Company Announcements" in source
    assert "def _target_announcement_id(" in source
    assert '"Opened from Notifications"' in source
    assert "render_announcement_card(" in source


def test_empty_announcement_message_remains_clear() -> None:
    source = _read("ui/pages/user/announcements_page.py")

    assert "There is no active company announcement at this time." in source
    assert "There is no active company announcement at this time." in source


def test_v88100_version_release_notes_and_dtr_plan() -> None:
    settings = _read("config/settings.py")
    readme = _read("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.100 — Simplified Employee Announcements Dashboard" in readme
    assert "Planned Attendance / DTR Module" in readme
    assert "weekend-overtime policy remains pending confirmation" in readme
