"""Administrator Attendance Hub workspace."""

import streamlit as st

from authentication.current_user import AuthenticatedUser
from ui.pages.admin.attendance_dashboard import render_admin_attendance_dashboard


def render_admin_attendance_hub_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render company attendance records and all administration tools."""

    st.title("Attendance Hub")
    st.caption(
        "Review company-wide Attendance / DTR / OT records, configure workday "
        "rules, validate overtime, correct attendance, and inspect edit history."
    )
    st.markdown("## Attendance / DTR / OT")
    render_admin_attendance_dashboard(
        current_user,
        show_management_tools=True,
    )
