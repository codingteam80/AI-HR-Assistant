"""Regression checks for v8.8.104 removed human-support sidebar card."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_employee_sidebar_removes_human_support_card() -> None:
    source = _read("ui/components/sidebar.py")

    assert "Need Human Support?" not in source
    assert "Contact HR when the assistant cannot resolve your concern." not in source
    assert 'class="hr-card"' not in source


def test_employee_navigation_and_hr_contacts_remain_available() -> None:
    sidebar = _read("ui/components/sidebar.py")
    constants = _read("core/constants.py")

    assert "for page_name in USER_NAVIGATION" in sidebar
    assert '"HR Contacts"' in constants
    assert '"Admin Portal"' in sidebar
    assert '"Log Out"' in sidebar


def test_calibrated_spacing_is_not_reverted() -> None:
    theme = _read("ui/theme/theme_loader.py")

    assert "padding-top: 2.00rem !important" in theme
    assert "padding-bottom: 0.75rem !important" in theme


def test_v88104_version_and_release_notes() -> None:
    settings = _read("config/settings.py")
    readme = _read("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.104 — Removed Human Support Sidebar Card" in readme
