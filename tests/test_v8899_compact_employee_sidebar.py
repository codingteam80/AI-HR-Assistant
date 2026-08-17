"""Regression checks for v8.8.99 compact Employee Portal sidebar polish."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_employee_sidebar_removes_redundant_identity_captions() -> None:
    source = _read("ui/components/sidebar.py")

    assert "st.sidebar.caption" not in source
    assert "current_user.employee_name or current_user.username" not in source
    assert "access_label" not in source
    assert "current_user.company_code" not in source


def test_employee_sidebar_matches_admin_brand_spacing() -> None:
    employee_sidebar = _read("ui/components/sidebar.py")
    admin_sidebar = _read("ui/components/admin_sidebar.py")
    theme = _read("ui/theme/theme_loader.py")

    assert "hr-employee-nav-spacer" in employee_sidebar
    assert "hr-admin-nav-spacer" in admin_sidebar
    assert ".hr-admin-nav-spacer," in theme
    assert ".hr-employee-nav-spacer" in theme
    assert "height: 28px" in theme
    assert "min-height: 28px" in theme


def test_employee_navigation_and_account_actions_are_preserved() -> None:
    source = _read("ui/components/sidebar.py")

    assert "for page_name in USER_NAVIGATION" in source
    assert '"Admin Portal"' in source
    assert '"Log Out"' in source


def test_v8899_version_and_release_notes() -> None:
    settings = _read("config/settings.py")
    readme = _read("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.99 — Compact Employee Sidebar Polish" in readme
