"""Regression checks for v8.8.164.4 per-tab authentication sessions."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_authentication_uses_session_storage_not_shared_local_storage() -> None:
    source = _read("authentication/browser_auth_storage_frontend/index.html")

    assert "window.sessionStorage.getItem(storageKey)" in source
    assert "window.sessionStorage.setItem(storageKey, token)" in source
    assert "window.sessionStorage.removeItem(storageKey)" in source
    assert "window.localStorage.getItem(storageKey)" not in source
    assert "window.localStorage.setItem(storageKey, token)" not in source


def test_legacy_shared_auth_is_removed_but_never_restored() -> None:
    source = _read("authentication/browser_auth_storage_frontend/index.html")

    assert "window.localStorage.removeItem(storageKey)" in source
    assert "legacyStorageError" in source


def test_cross_tab_storage_listener_is_not_used_for_auth() -> None:
    source = _read("authentication/browser_auth_storage_frontend/index.html")

    assert 'window.addEventListener("storage"' not in source


def test_same_tab_refresh_restore_remains_enabled() -> None:
    storage = _read("authentication/browser_auth_storage.py")
    manager = _read("authentication/session_manager.py")
    app = _read("app.py")

    assert "sessionStorage" in storage
    assert "read_browser_auth_token()" in manager
    assert "write_browser_auth_token(token)" in manager
    assert "AuthSessionManager.restore_from_browser()" in app


def test_authenticated_tab_is_migrated_to_session_storage() -> None:
    manager = _read("authentication/session_manager.py")
    block = manager.split("def flush_pending_browser_token", 1)[1].split(
        "def _clear_local_session", 1
    )[0]

    assert "current = st.session_state.get(cls.TOKEN_KEY)" in block
    assert "token = current" in block
    assert "write_browser_auth_token(token)" in block


def test_logout_only_removes_current_tab_storage() -> None:
    manager = _read("authentication/session_manager.py")
    frontend = _read("authentication/browser_auth_storage_frontend/index.html")

    assert "remove_browser_auth_token" in manager
    assert "window.sessionStorage.removeItem(storageKey)" in frontend
    assert 'window.addEventListener("storage"' not in frontend


def test_version_is_incremented_without_touching_held_branch() -> None:
    settings = _read("config/settings.py")
    env_example = _read(".env.example")

    assert 'app_version: str = "0.8.8.164.4"' in settings
    assert "APP_VERSION=0.8.8.164.4" in env_example
