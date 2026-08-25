"""v8.8.189 fixed-banner top-cover and border cleanup regression checks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _block(source: str, selector: str) -> str:
    start = source.index(selector)
    brace = source.index("{{", start)
    end = source.index("}}", brace)
    return source[start:end + 2]


def test_version_is_v88189() -> None:
    assert 'app_version: str = "0.8.8.189"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.189" in _source(".env")
    assert "APP_VERSION=0.8.8.189" in _source(".env.example")


def test_fixed_host_covers_viewport_top_and_moves_card_slightly_up() -> None:
    theme = _source("ui/theme/theme_loader.py")
    block = _block(theme, ".st-key-hr_global_topbar_shell,")
    assert "position: fixed !important;" in block
    assert "top: 0 !important;" in block
    assert "padding: 2.5rem var(--hr-topbar-inline-gutter) 8px !important;" in block
    assert "top: 3rem !important;" not in block
    assert "background: var(--hr-bg) !important;" in block


def test_fixed_host_bottom_border_is_removed() -> None:
    theme = _source("ui/theme/theme_loader.py")
    block = _block(theme, ".st-key-hr_global_topbar_shell,")
    assert "border: 0 !important;" in block
    assert "border-bottom: 0 !important;" in block
    assert "border-bottom: 1px solid var(--hr-border) !important;" not in block


def test_original_banner_card_visuals_and_columns_remain_unchanged() -> None:
    topbar = _source("ui/components/topbar.py")
    theme = _source("ui/theme/theme_loader.py")
    card = _block(theme, "    .hr-topbar {{")
    assert "[9.1, 0.9]" in topbar
    for rule in (
        "gap: 18px;",
        "padding: 14px 18px;",
        "background: var(--hr-surface);",
        "border: 1px solid var(--hr-border);",
        "border-radius: 18px;",
        "box-shadow: var(--hr-shadow);",
    ):
        assert rule in card


def test_notification_and_sidebar_safety_are_preserved() -> None:
    theme = _source("ui/theme/theme_loader.py")
    assert "--hr-topbar-sidebar-width: 285px;" in theme
    assert "--hr-topbar-sidebar-width: 250px;" in theme
    wide = theme[theme.index("WIDE CLICKABLE NOTIFICATIONS") :]
    assert "z-index: 10030 !important;" in wide
    assert "top: 128px !important;" in wide


def test_horizontal_tabs_are_not_changed_by_banner_patch() -> None:
    theme = _source("ui/theme/theme_loader.py")
    region = theme[
        theme.index("ORIGINAL-LAYOUT FIXED PORTAL UPPER BANNER"):
        theme.index('div[class*="_profile_photo_compact"]')
    ]
    assert 'data-testid="stTabs"' not in region
