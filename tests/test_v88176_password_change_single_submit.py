"""v8.8.176 password-change single-submit regression checks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_password_change_uses_a_dedicated_browser_writer_key():
    source = _read("authentication/browser_auth_storage.py")
    assert 'PASSWORD_CHANGE_WRITER_COMPONENT_KEY = "ai_hr_auth_storage_password_change_writer"' in source
    block = source.split("def replace_browser_auth_token_and_continue", 1)[1]
    assert "component_key=PASSWORD_CHANGE_WRITER_COMPONENT_KEY" in block
    assert "component_key=WRITER_COMPONENT_KEY" not in block


def test_regular_session_persistence_keeps_the_original_writer_key():
    source = _read("authentication/browser_auth_storage.py")
    block = source.split("def write_browser_auth_token", 1)[1].split(
        "def write_browser_auth_token_and_continue", 1
    )[0]
    assert "component_key=WRITER_COMPONENT_KEY" in block


def test_password_change_backend_and_transition_order_remain_intact():
    page = _read("ui/pages/authentication/change_password_page.py")
    assert ").change_password(" in page
    assert ").issue_token(updated_user)" in page
    assert "AuthSessionManager.complete_password_change(" in page
    assert page.index(").change_password(") < page.index(").issue_token(updated_user)")
    assert page.index(").issue_token(updated_user)") < page.index("AuthSessionManager.complete_password_change(")


def test_version_is_v88176():
    assert "APP_VERSION=0.8.8.176" in _read(".env")
    assert "APP_VERSION=0.8.8.176" in _read(".env.example")
    assert 'app_version: str = "0.8.8.176"' in _read("config/settings.py")
