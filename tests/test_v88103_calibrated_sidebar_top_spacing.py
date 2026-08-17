"""Regression checks for v8.8.103 calibrated sidebar top spacing."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _sidebar_user_content_block(theme: str) -> str:
    return theme.split(
        '[data-testid="stSidebarUserContent"] {{',
        1,
    )[1].split("}}", 1)[0]


def test_sidebar_uses_browser_verified_top_padding() -> None:
    theme = _read("ui/theme/theme_loader.py")
    block = _sidebar_user_content_block(theme)

    assert "padding-top: 2.00rem !important" in block
    assert "padding-bottom: 0.75rem !important" in block


def test_auto_balancing_and_short_window_support_remain() -> None:
    theme = _read("ui/theme/theme_loader.py")

    assert "min-height: 100dvh !important" in theme
    assert "margin-top: auto !important" in theme
    assert "margin-bottom: auto !important" in theme
    assert "overflow-y: auto !important" in theme


def test_v88103_version_and_release_notes() -> None:
    settings = _read("config/settings.py")
    readme = _read("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.103 — Calibrated Sidebar Top Spacing" in readme
