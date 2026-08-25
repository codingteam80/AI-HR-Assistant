"""v8.8.187 real-browser upper-banner pinning regression checks."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_version_markers() -> None:
    assert 'app_version: str = "0.8.8.187"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.187" in _source(".env")
    assert "APP_VERSION=0.8.8.187" in _source(".env.example")


def test_shared_topbar_is_viewport_pinned_not_scroll_parent_sticky() -> None:
    theme = _source("ui/theme/theme_loader.py")
    start = theme.index(".st-key-hr_global_topbar_shell {{")
    block = theme[start : theme.index("}}", start) + 2]
    assert "position: fixed !important;" in block
    assert "position: sticky" not in block
    assert "top: 0.6rem !important;" in block
    assert "left: 285px !important;" in block
    assert "right: 0 !important;" in block
    assert "z-index: 9000 !important;" in block
    assert "overflow: visible !important;" in block


def test_fixed_banner_stays_aligned_with_main_content() -> None:
    theme = _source("ui/theme/theme_loader.py")
    assert 'max-width: 1500px !important;' in theme
    assert 'padding-left: 2rem !important;' in theme
    assert 'padding-right: 2rem !important;' in theme
    responsive = theme[theme.index("@media (max-width: 900px) {{") :]
    assert ".st-key-hr_global_topbar_shell {{" in responsive
    assert "left: 250px !important;" in responsive


def test_flow_spacer_prevents_page_content_overlap() -> None:
    topbar = _source("ui/components/topbar.py")
    theme = _source("ui/theme/theme_loader.py")
    assert 'class="hr-topbar-flow-spacer"' in topbar
    assert ".hr-topbar-flow-spacer {{" in theme
    assert "height: 5.75rem !important;" in theme
    assert "visibility: hidden !important;" in theme
    assert "pointer-events: none !important;" in theme


def test_notification_dropdown_remains_above_pinned_banner() -> None:
    theme = _source("ui/theme/theme_loader.py")
    assert "z-index: 9000 !important;" in theme
    assert "z-index: 10020 !important;" in theme
    assert "z-index: 10030 !important;" in theme
    assert "const buttonRect = button.getBoundingClientRect();" in theme
    assert "setImportant(panel, 'position', 'fixed');" in theme


def test_sidebar_and_horizontal_tabs_are_not_changed_to_fixed_by_banner_patch() -> None:
    theme = _source("ui/theme/theme_loader.py")
    sidebar_start = theme.index('section[data-testid="stSidebar"] {{')
    sidebar = theme[sidebar_start : theme.index("}}", sidebar_start) + 2]
    assert "position: fixed !important;" in sidebar
    assert "z-index: 999 !important;" in sidebar

    # The targeted patch must not add a generic fixed-position rule to tabs.
    assert '[data-testid="stTabs"] {{\n        position: fixed' not in theme
    assert '[data-testid="stTabs"] {\n        position: fixed' not in theme


def test_admin_and_employee_still_use_the_same_shared_topbar() -> None:
    admin = _source("ui/layouts/admin_layout.py")
    employee = _source("ui/layouts/user_layout.py")
    assert "render_topbar(" in admin
    assert 'section_name="Administration Portal"' in admin
    assert "render_topbar(" in employee
    assert "display_name_override=(" in employee
