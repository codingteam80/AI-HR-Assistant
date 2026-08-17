"""Reusable administrator sidebar navigation."""

import streamlit as st

from authentication.current_user import AuthenticatedUser
from authentication.session_manager import AuthSessionManager
from ui.components.theme_toggle import render_theme_toggle


ADMIN_NAVIGATION = (
    "Admin Dashboard",
    "Companies",
    "Users",
    "Employees",
    "Roles",
    "Policies",
    "Leave Settings",
    "Announcements",
    "Reports",
    "Audit Logs",
    "Integrations",
)


def render_admin_sidebar(
    assistant_name: str,
    current_user: AuthenticatedUser,
) -> None:
    """Render admin-only navigation and account controls."""

    st.sidebar.markdown(
        f"<div class='hr-brand'>🤖 {assistant_name}</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.caption("Administration Portal")
    st.sidebar.caption(
        current_user.employee_name or current_user.username
    )
    st.sidebar.divider()

    if st.session_state.current_page not in ADMIN_NAVIGATION:
        st.session_state.current_page = "Admin Dashboard"

    for page_name in ADMIN_NAVIGATION:
        button_type = (
            "primary"
            if st.session_state.current_page == page_name
            else "secondary"
        )

        if st.sidebar.button(
            page_name,
            width="stretch",
            type=button_type,
            key=f"admin_nav_{page_name}",
        ):
            st.session_state.current_page = page_name
            st.rerun()

    st.sidebar.divider()
    render_theme_toggle()

    if st.sidebar.button(
        "Employee Portal",
        width="stretch",
        key="employee_portal_button",
    ):
        st.session_state.portal_mode = "employee"
        st.session_state.current_page = "Chat Assistant"
        st.rerun()

    if st.sidebar.button(
        "Log Out",
        width="stretch",
        key="admin_logout_button",
    ):
        AuthSessionManager.logout()
        st.rerun()
