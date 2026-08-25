"""Tab-scoped browser storage for the signed authentication token.

Streamlit creates a new ``st.session_state`` after a full browser refresh.
This bundled component reads the signed token from ``sessionStorage`` and
sends it back to Python before the Login page is rendered. ``sessionStorage``
preserves authentication on refresh in the same tab/window but does not
share the login with separately opened tabs/windows.

The component is bundled with the project and does not require internet or
a third-party cookie package. Legacy shared ``localStorage`` auth values are
removed by the frontend and are never used for restoration.
"""

from dataclasses import dataclass
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


AUTH_STORAGE_KEY = "ai_hr_signed_auth"
READER_COMPONENT_KEY = "ai_hr_auth_storage_reader"
WRITER_COMPONENT_KEY = "ai_hr_auth_storage_writer"
PASSWORD_CHANGE_WRITER_COMPONENT_KEY = "ai_hr_auth_storage_password_change_writer"
REMOVER_COMPONENT_KEY = "ai_hr_auth_storage_remover"

_FRONTEND_DIR = (
    Path(__file__).resolve().parent
    / "browser_auth_storage_frontend"
)

_browser_storage_component = components.declare_component(
    "ai_hr_browser_auth_storage",
    path=str(_FRONTEND_DIR),
)


@dataclass(frozen=True, slots=True)
class BrowserStorageResult:
    """One validated response from the browser-storage component."""

    ready: bool
    value: str | None = None
    error: str | None = None


def _clean_token(value) -> str | None:
    """Return one bounded non-empty signed token."""

    if not isinstance(value, str):
        return None

    cleaned = value.strip()

    if not cleaned or len(cleaned) > 4096:
        return None

    return cleaned


def _invoke_storage(
    *,
    action: str,
    token: str | None,
    component_key: str,
) -> BrowserStorageResult:
    """Run one browser-storage command and validate its response."""

    payload = _browser_storage_component(
        action=action,
        storage_key=AUTH_STORAGE_KEY,
        token=token,
        key=component_key,
        default={
            "ready": False,
            "value": None,
            "error": None,
        },
    )

    if not isinstance(payload, dict):
        return BrowserStorageResult(ready=False)

    ready = payload.get("ready") is True
    error_value = payload.get("error")
    error = (
        str(error_value).strip()
        if error_value
        else None
    )

    return BrowserStorageResult(
        ready=ready,
        value=_clean_token(payload.get("value")),
        error=error,
    )


def _stop_for_browser_result(message: str) -> None:
    """Keep public pages hidden until the browser has replied."""

    st.info(message)
    st.stop()


def read_browser_auth_token() -> str | None:
    """Read the persistent signed token before deciding to show Login."""

    result = _invoke_storage(
        action="read",
        token=None,
        component_key=READER_COMPONENT_KEY,
    )

    if not result.ready:
        _stop_for_browser_result(
            "Restoring your secure session…"
        )

    if result.error:
        st.error(
            "Browser session storage is unavailable. "
            "Please allow site storage for localhost and reload."
        )
        st.stop()

    return result.value


def write_browser_auth_token(token: str) -> bool:
    """Try to persist a token without blocking the protected portal.

    The component may need one browser round trip. Returning ``False`` keeps
    the token pending in Streamlit state while the authenticated portal is
    already allowed to render.
    """

    cleaned = _clean_token(token)

    if cleaned is None:
        raise ValueError(
            "The signed authentication token is invalid."
        )

    result = _invoke_storage(
        action="set",
        token=cleaned,
        component_key=WRITER_COMPONENT_KEY,
    )

    return bool(
        result.ready
        and result.error is None
        and result.value == cleaned
    )


def write_browser_auth_token_and_continue(token: str) -> None:
    """Compatibility helper for flows that intentionally wait for storage."""

    if not write_browser_auth_token(token):
        _stop_for_browser_result(
            "Completing sign in…"
        )

    st.rerun()


def replace_browser_auth_token_and_continue(token: str) -> None:
    """Replace the token after password change."""

    cleaned = _clean_token(token)

    if cleaned is None:
        raise ValueError(
            "The signed authentication token is invalid."
        )

    # The normal authenticated rerun may already have rendered the regular
    # writer component through ``flush_pending_browser_token`` earlier in
    # this same Streamlit run. Password replacement therefore needs its own
    # component key; reusing WRITER_COMPONENT_KEY here raises Streamlit's
    # duplicate-element-key exception after the database password update,
    # which previously showed a false failure and forced another interaction.
    result = _invoke_storage(
        action="set",
        token=cleaned,
        component_key=PASSWORD_CHANGE_WRITER_COMPONENT_KEY,
    )

    if result.error:
        st.error(
            "Browser session storage is unavailable. "
            "Please allow site storage for localhost and reload."
        )
        st.stop()

    if not result.ready or result.value != cleaned:
        _stop_for_browser_result(
            "Opening your portal…"
        )

    st.success("Password changed successfully.")
    st.rerun()


def remove_browser_auth_token(
    *,
    wait_for_completion: bool,
) -> None:
    """Remove the persistent browser token during logout/reset."""

    result = _invoke_storage(
        action="remove",
        token=None,
        component_key=REMOVER_COMPONENT_KEY,
    )

    if wait_for_completion:
        if not result.ready or result.value is not None:
            _stop_for_browser_result(
                "Signing out…"
            )
