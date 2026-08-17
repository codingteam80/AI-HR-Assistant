"""Reusable employee sidebar navigation."""

import streamlit as st

from authentication.access_control import AccessControl
from authentication.current_user import AuthenticatedUser
from authentication.session_manager import AuthSessionManager
from core.constants import USER_NAVIGATION
from ui.components.theme_toggle import render_theme_toggle


def render_sidebar(
    assistant_name: str,
    current_user: AuthenticatedUser,
) -> None:
    """Render employee navigation and account controls."""

    st.sidebar.markdown(
        f"<div class='hr-brand'>🤖 {assistant_name}</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.caption(
        current_user.employee_name or current_user.username
    )
    st.sidebar.caption(
        f"{current_user.role_name} · {current_user.company_code}"
    )
    st.sidebar.divider()

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
            st.session_state.current_page = page_name
            st.rerun()

    st.sidebar.divider()
    render_theme_toggle()

    # Admin users can move between employee and admin portals.
    if AccessControl.is_admin(current_user):
        if st.sidebar.button(
            "Admin Portal",
            width="stretch",
            key="admin_portal_button",
        ):
            st.session_state.portal_mode = "admin"
            st.session_state.current_page = "Admin Dashboard"
            st.rerun()

    if st.sidebar.button(
        "Log Out",
        width="stretch",
        key="logout_button",
    ):
        AuthSessionManager.logout()
        st.rerun()

    st.sidebar.markdown(
        """
        <div class="hr-card" style="margin-top: 18px;">
            <div class="hr-card-title">Need Human Support?</div>
            <div class="hr-card-text">
                Contact HR when the assistant cannot resolve your concern.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
