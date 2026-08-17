"""Regression checks for v8.8.116 seamless announcement descriptions."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_employee_and_admin_description_viewports_are_borderless() -> None:
    employee = _source("ui/pages/user/announcements_page.py")
    admin = _source("ui/pages/admin/announcements_page.py")

    for source in (employee, admin):
        assert "render_announcement_description(" in source
        assert "border=False" in source
        assert "height=330" in source


def test_description_content_background_is_transparent() -> None:
    source = _source("ui/components/announcement_description.py")

    assert "background: transparent" in source
    assert "overflow-x: hidden" in source
    assert "overflow-y: visible" in source
    assert "white-space: pre-wrap" in source


def test_checkpoint_keeps_v88116_release_notes() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert (
        "v8.8.116 — Seamless Transparent Announcement Descriptions"
        in readme
    )
