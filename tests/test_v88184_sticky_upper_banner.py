"""v8.8.184 sticky portal upper-banner regression checks."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_version_markers() -> None:
    assert 'app_version: str = "0.8.8.184"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.184" in _source(".env")
    assert "APP_VERSION=0.8.8.184" in _source(".env.example")


def test_shared_topbar_is_wrapped_in_one_stable_keyed_container() -> None:
    source = _source("ui/components/topbar.py")
    assert 'with st.container(key="hr_global_topbar_shell"):' in source
    assert 'content, bell = st.columns(' in source
    assert 'class="hr-topbar-company"' in source
    assert 'class="hr-muted hr-topbar-account"' in source
    assert "_render_notification_bell(current_user)" in source


def test_admin_and_employee_portals_still_use_shared_topbar() -> None:
    admin = _source("ui/layouts/admin_layout.py")
    employee = _source("ui/layouts/user_layout.py")
    assert "render_topbar(" in admin
    assert 'section_name="Administration Portal"' in admin
    assert "render_topbar(" in employee
    assert "display_name_override=(" in employee


def test_topbar_shell_is_sticky_not_hard_fixed() -> None:
    theme = _source("ui/theme/theme_loader.py")
    outer_selector = 'div[data-testid="stElementContainer"]:has(.st-key-hr_global_topbar_shell)'
    start = theme.index(outer_selector)
    block = theme[start : theme.index("}}", start) + 2]
    assert "position: sticky !important;" in block
    assert "position: fixed" not in block
    assert "top: 3rem !important;" in block
    assert "z-index: 9000 !important;" in block
    assert "background: var(--hr-bg) !important;" in block
    assert "border-bottom: 1px solid var(--hr-border) !important;" in block

    inner_start = theme.index(".st-key-hr_global_topbar_shell {{")
    inner = theme[inner_start : theme.index("}}", inner_start) + 2]
    assert "position: relative !important;" in inner
    assert "position: sticky" not in inner


def test_banner_keeps_card_compact_and_prevents_text_overflow() -> None:
    theme = _source("ui/theme/theme_loader.py")
    assert ".st-key-hr_global_topbar_shell .hr-topbar {{" in theme
    assert "margin-bottom: 0 !important;" in theme
    assert ".hr-topbar-company {{" in theme
    assert ".hr-topbar-account {{" in theme
    assert "text-overflow: ellipsis;" in theme
    assert "white-space: nowrap;" in theme


def test_banner_has_responsive_small_width_behavior() -> None:
    theme = _source("ui/theme/theme_loader.py")
    assert "@media (max-width: 1100px) {{" in theme
    assert "@media (max-width: 760px) {{" in theme
    small = theme[theme.index("@media (max-width: 760px) {{") :]
    small = small[: small.index("    .hr-profile-photo-large {{")]
    assert ".hr-topbar-account {{" in small
    assert "display: none;" in small
    assert "width: 34px;" in small
    assert "height: 34px;" in small


def test_notification_dropdown_tracks_the_sticky_bell_position() -> None:
    theme = _source("ui/theme/theme_loader.py")
    assert "const positionNotificationDropdown = () =>" in theme
    assert "const buttonRect = button.getBoundingClientRect();" in theme
    assert "buttonRect.bottom + 8" in theme
    assert "setImportant(panel, 'position', 'fixed');" in theme
    assert "setImportant(panel, 'top', `${top}px`);" in theme
    assert "z-index: 10030 !important;" in theme


def test_sidebar_layout_is_not_made_sticky_by_banner_change() -> None:
    theme = _source("ui/theme/theme_loader.py")
    sidebar = theme[theme.index('section[data-testid="stSidebar"] {{') :]
    sidebar = sidebar[: sidebar.index("}}") + 2]
    assert "position: fixed !important;" in sidebar
    assert "z-index: 999 !important;" in sidebar
