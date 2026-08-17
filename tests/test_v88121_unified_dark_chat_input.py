"""Unified dark Chat Assistant field and send-button regression checks."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_keyed_chat_input_outer_wrappers_are_transparent() -> None:
    theme = _source("ui/theme/theme_loader.py")

    assert 'div[class*="st-key-admin_hr_assistant_chat_input__"]' in theme
    assert 'div[class*="st-key-hr_assistant_chat_input__"]' in theme
    assert "background-color: transparent !important;" in theme
    assert "padding: 0 !important;" in theme


def test_entire_native_chat_input_is_one_dark_rounded_field() -> None:
    theme = _source("ui/theme/theme_loader.py")

    assert '[data-testid="stChatInput"] > div' in theme
    assert '[data-testid="stChatInput"] div[data-baseweb="base-input"]' in theme
    assert "background-color: #252630 !important;" in theme
    assert "border-radius: 10px !important;" in theme
    assert "overflow: hidden !important;" in theme


def test_v88121_black_send_box_is_preserved() -> None:
    theme = _source("ui/theme/theme_loader.py")

    assert '[data-testid="stChatInput"] button {' in theme
    assert '[data-testid="stChatInput"] button:disabled' in theme
    assert "background-color: #101116 !important;" in theme
    assert "color: #FFFFFF !important;" in theme


def test_v88121_release_remains_preserved_after_later_checkpoints() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.121 — Unified Dark Chat Input" in readme
