"""Employee dashboard full-width announcement regression tests."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_removes_redundant_quick_access() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/user/dashboard_page.py"
    ).read_text(encoding="utf-8")

    assert "Quick Access" not in source
    assert "_render_quick_access" not in source
    assert "_open_employee_page" not in source
    assert "quick_access_area" not in source
    assert "announcement_area" not in source


def test_announcements_use_a_separate_full_width_workspace() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/user/announcements_page.py"
    ).read_text(encoding="utf-8")

    assert "Company Announcements" in source
    assert "Search Announcements" in source
    assert "render_announcement_card" in source


def test_notification_deep_link_is_preserved() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/user/announcements_page.py"
    ).read_text(encoding="utf-8")

    assert "def _target_announcement_id(" in source
    assert '"announcement_id"' in source
    assert "Opened from Notifications" in source
