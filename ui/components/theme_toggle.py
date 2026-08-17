"""Reusable persistent light/dark mode control."""

import streamlit as st

from ui.theme.theme_state import (
    get_active_theme,
    set_active_theme,
)


def render_theme_toggle() -> None:
    """Render the theme button and save the selected browser state."""

    current_theme = get_active_theme()
    next_theme = (
        "dark" if current_theme == "light" else "light"
    )
    button_label = (
        "🌙 Dark Mode"
        if current_theme == "light"
        else "☀️ Light Mode"
    )

    if st.button(
        button_label,
        width="stretch",
        key="theme_toggle",
    ):
        set_active_theme(next_theme)
        st.rerun()
