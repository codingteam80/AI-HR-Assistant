"""Regression checks for v8.8.101 restored active-announcement count."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_announcement_workspace_keeps_unread_count() -> None:
    source = _read("ui/pages/user/announcements_page.py")

    assert "announcement-unread-count" in source
    assert "dashboard_announcement_category" not in source
    assert "dashboard_announcement_search" not in source


def test_count_appears_before_empty_and_content_sections() -> None:
    source = _read("ui/pages/user/announcements_page.py")

    count_position = source.index("_announcement_title(unread_count)")
    empty_position = source.index("if not announcements:")
    content_position = source.index("for announcement in filtered:")

    assert count_position < empty_position < content_position


def test_v88101_version_and_release_notes() -> None:
    settings = _read("config/settings.py")
    readme = _read("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.101 — Restored Active Announcement Count" in readme
