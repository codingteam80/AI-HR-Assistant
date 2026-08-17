"""Employee landing dashboard and attendance workspace."""

import streamlit as st

from authentication.current_user import AuthenticatedUser
from ui.pages.user.attendance_workspace import (
    render_employee_attendance_workspace,
)
from ui.pages.user.announcements_page import (
    _target_announcement_id,
    load_employee_announcement_state,
    render_employee_announcements_page,
)


_DASHBOARD_TAB_STATE_KEY = "employee_dashboard_active_tab"
_ANNOUNCEMENT_TARGET_STATE_KEY = "_employee_announcement_target_opened"


def _render_dashboard_tabs(unread_count: int):
    """Render stateful native tabs matching the Leave Management layout."""

    target_id = _target_announcement_id()
    opened_target_id = st.session_state.get(
        _ANNOUNCEMENT_TARGET_STATE_KEY
    )
    if target_id is not None and target_id != opened_target_id:
        st.session_state[_DASHBOARD_TAB_STATE_KEY] = "Announcements"
        st.session_state[_ANNOUNCEMENT_TARGET_STATE_KEY] = target_id

    current = st.session_state.get(
        _DASHBOARD_TAB_STATE_KEY,
        "Dashboard",
    )
    options = ("Dashboard", "Announcements")
    if current not in options:
        st.session_state[_DASHBOARD_TAB_STATE_KEY] = "Dashboard"

    shake_css = (
        "animation: employeeAnnouncementTabShake .65s ease-in-out 3;"
        if unread_count > 0
        else ""
    )
    st.markdown(
        f"""
        <style>
        @keyframes employeeAnnouncementTabShake {{
            0%, 100% {{ transform: translateX(0); }}
            25% {{ transform: translateX(-2px); }}
            75% {{ transform: translateX(2px); }}
        }}
        .st-key-employee_dashboard_active_tab
        [data-baseweb="tab-list"] [role="tab"]:nth-child(2)::after {{
            content: " ({unread_count})";
        }}
        .st-key-employee_dashboard_active_tab
        [data-baseweb="tab-list"] [role="tab"]:nth-child(2) {{
            {shake_css}
        }}
        @media (prefers-reduced-motion: reduce) {{
            .st-key-employee_dashboard_active_tab
            [data-baseweb="tab-list"] [role="tab"]:nth-child(2) {{
                animation: none !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    return st.tabs(
        options,
        key=_DASHBOARD_TAB_STATE_KEY,
        on_change="rerun",
    )


def render_employee_dashboard_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render the employee summary and Attendance / DTR workspace."""

    display_name = (
        current_user.employee_name
        or current_user.username
    )

    st.title(f"Welcome, {display_name}")

    announcement_state = load_employee_announcement_state(current_user)
    dashboard_tab, announcements_tab = _render_dashboard_tabs(
        announcement_state[2]
    )

    if dashboard_tab.open:
        with dashboard_tab:
            render_employee_attendance_workspace(
                current_user,
                show_punch_controls=True,
                show_record_management=False,
            )
    elif announcements_tab.open:
        with announcements_tab:
            render_employee_announcements_page(
                current_user,
                announcement_state=announcement_state,
                show_heading=False,
            )
