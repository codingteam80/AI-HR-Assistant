"""Reusable employee sidebar navigation."""

import streamlit as st

from authentication.access_control import AccessControl
from authentication.current_user import AuthenticatedUser
from authentication.session_manager import AuthSessionManager
from ui.components.company_logo import render_company_sidebar_logo
from core.constants import USER_NAVIGATION
from ui.navigation_state import set_sidebar_navigation_state


def render_sidebar(
    assistant_name: str,
    current_user: AuthenticatedUser,
) -> None:
    """Render employee navigation and account controls."""

    render_company_sidebar_logo(current_user)

    st.sidebar.markdown(
        (
            f"<div class='hr-brand'>🤖 {assistant_name}</div>"
            "<div class='hr-employee-nav-spacer' aria-hidden='true'></div>"
        ),
        unsafe_allow_html=True,
    )

    for page_name in USER_NAVIGATION:
        button_type = (
            "primary"
            if st.session_state.current_page == page_name
            else "secondary"
        )

        if st.sidebar.button(
            page_name,
            width="stretch",
            type=button_type,
            key=f"nav_{page_name}",
        ):
            set_sidebar_navigation_state(
                portal_mode="employee",
                current_page=page_name,
            )
            st.rerun()

    st.sidebar.divider()

    # Admin users can move between employee and admin portals.
    if AccessControl.is_admin(current_user):
        if st.sidebar.button(
            "Admin Portal",
            width="stretch",
            key="admin_portal_button",
        ):
            set_sidebar_navigation_state(
                portal_mode="admin",
                current_page="Admin Dashboard",
            )
            st.rerun()

    if st.sidebar.button(
        "Log Out",
        width="stretch",
        key="logout_button",
    ):
        AuthSessionManager.logout()
