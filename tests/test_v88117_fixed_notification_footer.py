"""Regression checks for v8.8.117 fixed notification actions."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_notification_list_scrolls_separately_from_action_footer() -> None:
    source = _source("ui/components/topbar.py")
    dropdown = source.split("def _render_notification_dropdown(", 1)[1].split(
        "def _render_notification_bell(", 1
    )[0]

    scroll_area = dropdown.index('key="notification_scroll_area"')
    notification_items = dropdown.index("for item in recent:", scroll_area)
    footer = dropdown.index('key="notification_action_footer"')
    mark_all = dropdown.index('"Mark All as Read"', footer)
    close = dropdown.index('"Close"', footer)

    assert scroll_area < notification_items < footer < mark_all < close
    assert "height=notification_list_height" in dropdown
    assert "border=False" in dropdown


def test_fixed_footer_keeps_existing_button_actions() -> None:
    source = _source("ui/components/topbar.py")

    assert "mark_all_read(" in source
    assert 'key="notification_dropdown_mark_all_read"' in source
    assert 'key="notification_dropdown_close"' in source
    assert "_NOTIFICATION_PANEL_KEY" in source
    assert "_open_notification(" in source


def test_notification_theme_scrolls_only_the_list() -> None:
    source = _source("ui/theme/theme_loader.py")

    scroll_style = source.split(
        ".st-key-notification_scroll_area {{", 1
    )[1].split("}}", 1)[0]
    footer_style = source.split(
        ".st-key-notification_action_footer {{", 1
    )[1].split("}}", 1)[0]

    assert "overflow-y: auto !important" in scroll_style
    assert "overflow-x: hidden !important" in scroll_style
    assert "position: relative !important" in footer_style
    assert "background: #FFFFFF !important" in footer_style


def test_checkpoint_keeps_v88117_release_notes() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.117 — Fixed Notification Action Footer" in readme
