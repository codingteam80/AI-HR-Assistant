"""Administrator dashboard for company Attendance / DTR / OT."""

import streamlit as st
from authentication.current_user import AuthenticatedUser
from ui.pages.admin.attendance_dashboard import render_admin_attendance_dashboard


def render_admin_dashboard_page(current_user: AuthenticatedUser) -> None:
    """Display the company Attendance / DTR / OT workspace."""
    st.title('Admin Dashboard')
    st.caption('Secure administration access is active.')

    st.markdown("## Attendance / DTR / OT")
    st.caption(
        "Company-wide Login, Logout, work-location, leave, total-hours, "
        "and overtime records. Weekend columns are included."
    )
    render_admin_attendance_dashboard(
        current_user,
        show_management_tools=False,
    )
