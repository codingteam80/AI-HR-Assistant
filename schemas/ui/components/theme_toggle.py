import streamlit as st


def render_theme_toggle() -> None:
    current = st.session_state.get('theme', 'light')
    label = '🌙 Dark Mode' if current == 'light' else '☀️ Light Mode'
    if st.button(label, width="stretch", key='theme_toggle'):
        st.session_state.theme = 'dark' if current == 'light' else 'light'
        st.rerun()
