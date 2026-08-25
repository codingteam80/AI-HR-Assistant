"""v8.8.188 original-layout + fixed upper-banner regression checks."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _block(source: str, selector: str) -> str:
    start = source.index(selector)
    brace = source.index("{{", start)
    end = source.index("}}", brace)
    return source[start:end + 2]


def test_version_is_v88188() -> None:
    assert 'app_version: str = "0.8.8.188"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.188" in _source(".env")
    assert "APP_VERSION=0.8.8.188" in _source(".env.example")


def test_topbar_markup_and_columns_are_unchanged() -> None:
    source = _source("ui/components/topbar.py")
    assert 'with st.container(key="hr_global_topbar_shell"):' in source
    assert "[9.1, 0.9]" in source
    assert 'class="hr-topbar"' in source
    assert 'class="hr-topbar-company"' in source
    assert 'class="hr-muted hr-topbar-account"' in source
    assert 'class="hr-topbar-flow-spacer"' in source


def test_banner_is_fixed_but_uses_original_top_offset() -> None:
    theme = _source("ui/theme/theme_loader.py")
    block = _block(theme, ".st-key-hr_global_topbar_shell,")
    assert "position: fixed !important;" in block
    assert "top: 3rem !important;" in block
    assert "z-index: 9000 !important;" in block
    assert "--hr-topbar-sidebar-width: 285px;" in block
    assert "--hr-topbar-inline-gutter:" in block
    assert "calc(50vw - 892.5px + 2rem)" in block
    assert "padding: 4px var(--hr-topbar-inline-gutter) 8px !important;" in block


def test_nested_keyed_shell_is_not_double_fixed() -> None:
    theme = _source("ui/theme/theme_loader.py")
    marker = '''div[data-testid="stElementContainer"]:has(.st-key-hr_global_topbar_shell)\n    .st-key-hr_global_topbar_shell,'''
    block = _block(theme, marker)
    assert "position: relative !important;" in block
    assert "inset: auto !important;" in block
    assert "padding: 0 !important;" in block
    assert "background: transparent !important;" in block


def test_original_card_visual_rules_are_preserved() -> None:
    theme = _source("ui/theme/theme_loader.py")
    block = _block(theme, "    .hr-topbar {{")
    expected = [
        "display: flex;",
        "align-items: center;",
        "justify-content: space-between;",
        "gap: 18px;",
        "margin-bottom: 20px;",
        "padding: 14px 18px;",
        "background: var(--hr-surface);",
        "border: 1px solid var(--hr-border);",
        "border-radius: 18px;",
        "box-shadow: var(--hr-shadow);",
    ]
    for rule in expected:
        assert rule in block


def test_v88187_full_width_reconstruction_is_removed() -> None:
    theme = _source("ui/theme/theme_loader.py")
    topbar_region = theme[
        theme.index("ORIGINAL-LAYOUT FIXED PORTAL UPPER BANNER"):
        theme.index('div[class*="_profile_photo_compact"]')
    ]
    assert "top: 0.6rem !important;" not in topbar_region
    assert "padding-left: 2rem !important;" not in topbar_region
    assert "padding-right: 2rem !important;" not in topbar_region
    assert "max-width: 1500px !important;" not in topbar_region
    assert "padding: 0.35rem 0 0.45rem !important;" not in topbar_region


def test_sidebar_responsive_offsets_match_existing_layout() -> None:
    theme = _source("ui/theme/theme_loader.py")
    assert "--hr-topbar-sidebar-width: 285px;" in theme
    media = theme[theme.index("@media (max-width: 900px)") :]
    assert "--hr-topbar-sidebar-width: 250px;" in media
    assert "margin-left: 285px !important;" in theme
    assert "margin-left: 250px !important;" in theme


def test_notification_dropdown_remains_above_banner() -> None:
    theme = _source("ui/theme/theme_loader.py")
    wide = theme[theme.index("WIDE CLICKABLE NOTIFICATIONS") :]
    assert "z-index: 10030 !important;" in wide
    assert "position: fixed !important;" in wide
    # Responsive rules may move the panel from 128px to 118px, but they must
    # not lower its stacking order beneath the fixed banner (z-index 9000).
    assert "z-index: 9000 !important;" in theme


def test_horizontal_tabs_are_not_fixed_or_sticky_by_banner_patch() -> None:
    theme = _source("ui/theme/theme_loader.py")
    topbar_region = theme[
        theme.index("ORIGINAL-LAYOUT FIXED PORTAL UPPER BANNER"):
        theme.index('div[class*="_profile_photo_compact"]')
    ]
    assert 'data-testid="stTabs"' not in topbar_region
