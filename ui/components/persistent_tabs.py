"""Session-backed tab-style navigation for rerun-safe admin workspaces."""

from collections.abc import Mapping

import streamlit as st


def render_persistent_tabs(
    options: Mapping[str, str],
    *,
    key: str,
    default: str,
    label: str = "Workspace",
) -> str:
    """Render one persistent tab selector and return its stable option key."""

    option_keys = tuple(options)
    if not option_keys:
        raise ValueError("Persistent tabs require at least one option.")
    if default not in options:
        raise ValueError("The default persistent tab must be a valid option.")

    if st.session_state.get(key) not in options:
        st.session_state[key] = default

    selected = st.segmented_control(
        label,
        options=option_keys,
        format_func=lambda option: options[option],
        selection_mode="single",
        key=key,
        label_visibility="collapsed",
        width="content",
    )
    return selected if selected in options else default
