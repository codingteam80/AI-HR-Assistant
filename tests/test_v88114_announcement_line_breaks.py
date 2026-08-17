"""Regression checks for v8.8.114 preserved announcement line breaks."""

from pathlib import Path

from ui.components.announcement_description import (
    build_announcement_description_html,
)


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_description_html_preserves_newlines_and_wraps_long_text() -> None:
    html = build_announcement_description_html(
        "First line\nSecond line\nAContinuousLongValue"
    )

    assert "First line\nSecond line\nAContinuousLongValue" in html
    assert "white-space: pre-wrap" in html
    assert "overflow-wrap: anywhere" in html
    assert "word-break: break-word" in html


def test_description_html_escapes_unsafe_markup() -> None:
    html = build_announcement_description_html(
        '<script>alert("unsafe")</script>\nSafe line'
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Safe line" in html


def test_admin_and_employee_use_shared_preserved_text_renderer() -> None:
    admin = _source("ui/pages/admin/announcements_page.py")
    employee = _source("ui/pages/user/announcements_page.py")

    for source in (admin, employee):
        assert "render_announcement_description(" in source
        assert 'st.markdown("**Description**")' not in source
        assert "height=330" in source


def test_checkpoint_keeps_v88114_release_notes() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.114 — Preserved Announcement Line Breaks" in readme
