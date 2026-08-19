"""Persistent browser-storage authentication regression tests."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_refresh_uses_bundled_local_storage_component() -> None:
    source = _read("authentication/browser_auth_storage.py")

    assert "components.declare_component" in source
    assert "browser_auth_storage_frontend" in source
    assert 'action="read"' in source
    assert 'action="set"' in source
    assert 'action="remove"' in source
    assert "streamlit_cookies_controller" not in source


def test_frontend_reads_and_writes_tab_scoped_storage_offline() -> None:
    source = _read(
        "authentication/browser_auth_storage_frontend/index.html"
    )

    assert "window.sessionStorage.getItem" in source
    assert "window.sessionStorage.setItem" in source
    assert "window.sessionStorage.removeItem" in source
    # Legacy shared auth is cleanup-only and must never be restored.
    assert "window.localStorage.getItem" not in source
    assert "window.localStorage.setItem" not in source
    assert "window.localStorage.removeItem" in source
    assert "streamlit:componentReady" in source
    assert "streamlit:setComponentValue" in source
    assert "https://" not in source


def test_app_waits_for_browser_storage_before_login() -> None:
    source = _read("authentication/session_manager.py")
    block = source.split(
        "def restore_from_browser",
        1,
    )[1].split(
        "def restore_from_cookie",
        1,
    )[0]

    assert "read_browser_auth_token()" in block
    assert "SignedCookieAuthService" in block
    assert "remove_browser_auth_token" in block

    app = _read("app.py")
    assert "AuthSessionManager.restore_from_browser()" in app


def test_login_logout_and_password_change_use_same_storage() -> None:
    source = _read("authentication/session_manager.py")

    assert "write_browser_auth_token" in source
    assert "flush_pending_browser_token" in source
    assert "replace_browser_auth_token_and_continue" in source
    assert "remove_browser_auth_token" in source


def test_no_third_party_cookie_dependency_remains() -> None:
    requirements = _read("requirements.txt")

    assert "streamlit-cookies-controller" not in requirements


def test_signed_token_validation_and_persistent_secret_remain() -> None:
    source = _read(
        "authentication/signed_cookie_auth_service.py"
    )

    assert "URLSafeTimedSerializer" in source
    assert "resolve_auth_cookie_secret" in source
    assert "auth_cookie_secret_file" in source
