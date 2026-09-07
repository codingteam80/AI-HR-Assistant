"""Fixed Light Mode state management.

Persistence layers:
1. Streamlit session_state keeps the fixed Light Mode during widget reruns.
2. Browser localStorage is retained only for backward compatibility.
3. The visible URL no longer carries a ``theme`` query parameter.

Streamlit is imported lazily inside runtime functions so the pure theme
normalization helpers can be unit-tested without a Streamlit runtime.
"""

from typing import Any

from core.constants import SUPPORTED_THEMES


THEME_QUERY_KEY = "theme"
DEFAULT_THEME = "light"


def normalize_theme(value: Any) -> str | None:
    """Return a supported lowercase theme or None.

    Query parameters may be a string or a one-item sequence depending on
    the Streamlit/browser environment, so both forms are supported.
    """

    if isinstance(value, (list, tuple)):
        value = value[0] if value else None

    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()

    return (
        normalized
        if normalized in SUPPORTED_THEMES
        else None
    )


def resolve_initial_theme(
    query_theme: Any,
    default_theme: Any,
) -> str:
    """Choose a supported theme; Light Mode is the only valid result."""

    return (
        normalize_theme(query_theme)
        or normalize_theme(default_theme)
        or DEFAULT_THEME
    )


def initialize_theme_state(default_theme: str) -> None:
    """Initialize the fixed Light Mode without depending on URL state."""

    import streamlit as st

    if "theme" not in st.session_state:
        st.session_state.theme = resolve_initial_theme(
            query_theme=None,
            default_theme=default_theme,
        )


def get_active_theme() -> str:
    """Return a guaranteed supported theme for rendering."""

    import streamlit as st

    return (
        normalize_theme(st.session_state.get("theme"))
        or DEFAULT_THEME
    )


def set_active_theme(theme: str) -> str:
    """Persist the supported Light Mode value for compatibility."""

    import streamlit as st

    normalized = normalize_theme(theme)

    if normalized is None:
        raise ValueError(
            f"Unsupported theme: {theme!r}. "
            f"Allowed values: {', '.join(SUPPORTED_THEMES)}."
        )

    st.session_state.theme = normalized

    # Older checkpoints persisted ``?theme=light``. It is no longer needed
    # because Light Mode is fixed; browser-side cleanup removes it without a
    # reload so navigation/query state for real portal views is untouched.
    return normalized
