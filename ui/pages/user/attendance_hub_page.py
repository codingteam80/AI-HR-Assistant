"""Employee Attendance Hub with records, editing, and overtime requests."""

from authentication.current_user import AuthenticatedUser
from ui.pages.user.attendance_workspace import render_employee_attendance_workspace


def render_employee_attendance_hub_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render attendance records without duplicating Dashboard punch controls."""

    import streamlit as st

    st.title("Attendance Hub")
    st.caption(
        "Review your Attendance / DTR records, maintain permitted entries, "
        "and file or monitor overtime requests. Time In and Time Out remain "
        "available on the Dashboard."
    )
    render_employee_attendance_workspace(
        current_user,
        show_punch_controls=False,
        show_record_management=True,
    )
