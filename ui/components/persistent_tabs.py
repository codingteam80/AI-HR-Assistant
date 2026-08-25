"""Refresh-safe native Streamlit tabs.

Streamlit Session State is tied to the WebSocket connection and is reset by a
full browser refresh. These helpers mirror only the active tab index into a
small URL query parameter, then restore the keyed ``st.tabs`` state before the
widget is created on the new session.

The URL value is only a navigation index. It is not trusted for authorization
or data access, and all normal portal permission checks still run.
"""

from __future__ import annotations

from collections.abc import Sequence
import re

import streamlit as st


_QUERY_PREFIX = "tab_"
_REGISTRY_KEY = "_persistent_tab_state_keys"


def _query_key(state_key: str) -> str:
    """Return a compact, stable query-parameter key for one tab widget."""

    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", str(state_key)).strip("_")
    return (_QUERY_PREFIX + cleaned)[:120]


def _single_query_value(value: object) -> str | None:
    """Normalize one Streamlit query parameter value."""

    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _query_index(query_key: str, labels: Sequence[str]) -> int | None:
    """Read one bounded tab index from the current URL."""

    raw = _single_query_value(st.query_params.get(query_key))
    if raw is None:
        return None
    try:
        index = int(raw)
    except (TypeError, ValueError):
        return None
    return index if 0 <= index < len(labels) else None


def _active_index(state_key: str, labels: Sequence[str]) -> int | None:
    """Return the current keyed-tab index from Session State."""

    current = st.session_state.get(state_key)
    try:
        return list(labels).index(current)
    except ValueError:
        return None


def _write_query_index(query_key: str, index: int) -> None:
    """Write a tab index only when the URL does not already contain it."""

    desired = str(index)
    current = _single_query_value(st.query_params.get(query_key))
    if current != desired:
        st.query_params[query_key] = desired


def _persist_tab_change(
    state_key: str,
    query_key: str,
    labels: tuple[str, ...],
) -> None:
    """Mirror a native tab change into the refresh-safe URL state."""

    index = _active_index(state_key, labels)
    if index is not None:
        _write_query_index(query_key, index)


def clear_persistent_tab_navigation() -> None:
    """Forget saved native-tab positions for an intentional page change.

    Full browser refresh must preserve the active tab, so normal renders leave
    the URL/session values untouched. Sidebar navigation is different: the
    destination module should open at its first/default horizontal tab. This
    helper clears both the refresh-safe ``tab_*`` URL values and the keyed tab
    Session State values that were registered during this browser session.
    """

    registered = st.session_state.get(_REGISTRY_KEY, ())
    if isinstance(registered, (list, tuple, set)):
        for state_key in tuple(registered):
            st.session_state.pop(str(state_key), None)

    st.session_state[_REGISTRY_KEY] = []

    for query_key in list(st.query_params.keys()):
        if str(query_key).startswith(_QUERY_PREFIX):
            del st.query_params[query_key]


def _register_tab_state_key(state_key: str) -> None:
    """Remember one keyed native-tab state for sidebar-reset cleanup."""

    registered = st.session_state.get(_REGISTRY_KEY, [])
    if not isinstance(registered, list):
        registered = list(registered) if isinstance(registered, (tuple, set)) else []
    if state_key not in registered:
        registered.append(state_key)
    st.session_state[_REGISTRY_KEY] = registered


def persistent_tabs(
    labels: Sequence[str],
    *,
    key: str,
    default: str | None = None,
    width: str | int = "stretch",
    height: str | int = "content",
):
    """Render ``st.tabs`` whose active tab survives a hard browser refresh.

    Precedence on a new Streamlit session:
    1. an already-primed Session State value (quick actions / post-save target),
    2. the tab index stored in the current URL,
    3. the caller's explicit ``default`` label,
    4. the first tab.

    The selected label is still stored in ``st.session_state[key]`` exactly as
    with keyed native tabs, so existing application code remains compatible.
    """

    normalized = tuple(str(label) for label in labels)
    if not normalized:
        raise ValueError("persistent_tabs requires at least one tab label.")

    _register_tab_state_key(key)
    query_key = _query_key(key)

    current = st.session_state.get(key)
    if current not in normalized:
        restored_index = _query_index(query_key, normalized)
        if restored_index is not None:
            st.session_state[key] = normalized[restored_index]
        elif default in normalized:
            st.session_state[key] = default
        else:
            st.session_state[key] = normalized[0]

    # Keep programmatic tab changes (quick actions, post-save redirects, dynamic
    # labels) refresh-safe as well. Session State is the sole initial-value
    # source, so no ``default=`` conflict is created on the keyed widget.
    active_index = _active_index(key, normalized)
    if active_index is not None:
        _write_query_index(query_key, active_index)

    return st.tabs(
        normalized,
        key=key,
        on_change=_persist_tab_change,
        args=(key, query_key, normalized),
        width=width,
        height=height,
    )
