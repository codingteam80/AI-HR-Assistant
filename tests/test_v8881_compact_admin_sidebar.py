"""Regression checks for v8.8.81 compact admin sidebar polish."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_sidebar_removes_redundant_identity_captions() -> None:
    source = _read("ui/components/admin_sidebar.py")

    assert 'st.sidebar.caption("Administration Portal")' not in source
    assert "current_user.employee_name or current_user.username" not in source
    assert "ADMIN_NAVIGATION" in source


def test_sidebar_brand_spacing_and_button_shadow_are_scoped() -> None:
    source = _read("ui/theme/theme_loader.py")

    assert '[data-testid="stSidebarHeader"]' in source
    assert "font-size: 1.38rem" in source
    assert "text-align: center" in source
    assert "gap: 0.55rem" in source
    assert 'section[data-testid="stSidebar"] div.stButton > button' in source
    assert "0 3px 8px rgba(30, 41, 59, 0.09)" in source


def test_admin_brand_has_controlled_navigation_spacing() -> None:
    sidebar = _read("ui/components/admin_sidebar.py")
    theme = _read("ui/theme/theme_loader.py")

    assert "hr-admin-nav-spacer" in sidebar
    assert ".hr-admin-nav-spacer" in theme
    assert "height: 28px" in theme
    assert "min-height: 28px" in theme
