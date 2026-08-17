"""Regression checks for v8.8.102 balanced sidebar vertical spacing."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _sidebar_user_content_block(theme: str) -> str:
    return theme.split(
        '[data-testid="stSidebarUserContent"] {{',
        1,
    )[1].split("}}", 1)[0]


def _sidebar_vertical_block(theme: str) -> str:
    return theme.split(
        '[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {{',
        1,
    )[1].split("}}", 1)[0]


def test_sidebar_content_uses_full_viewport_with_equal_safety_padding() -> None:
    theme = _read("ui/theme/theme_loader.py")
    block = _sidebar_user_content_block(theme)

    assert "min-height: 100vh !important" in block
    assert "min-height: 100dvh !important" in block
    assert "padding-top:" in block
    assert "padding-bottom: 0.75rem !important" in block
    assert "display: flex !important" in block
    assert "flex-direction: column !important" in block


def test_sidebar_inner_block_balances_remaining_vertical_space() -> None:
    theme = _read("ui/theme/theme_loader.py")
    block = _sidebar_vertical_block(theme)

    assert "margin-top: auto !important" in block
    assert "margin-bottom: auto !important" in block
    assert "width: 100% !important" in block


def test_balancing_is_shared_by_admin_and_employee_sidebars() -> None:
    theme = _read("ui/theme/theme_loader.py")
    admin = _read("ui/components/admin_sidebar.py")
    employee = _read("ui/components/sidebar.py")

    assert '[data-testid="stSidebarUserContent"]' in theme
    assert "render_company_sidebar_logo(current_user)" in admin
    assert "render_company_sidebar_logo(current_user)" in employee
    assert "hr-admin-nav-spacer" in admin
    assert "hr-employee-nav-spacer" in employee


def test_v88102_version_and_release_notes() -> None:
    settings = _read("config/settings.py")
    readme = _read("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.102 — Balanced Sidebar Vertical Spacing" in readme
