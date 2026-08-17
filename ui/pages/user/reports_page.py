"""Employee-scoped DTR, overtime, and leave report workspace."""

from __future__ import annotations

from datetime import date

import streamlit as st

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from modules.reports.combined_hr_report import build_combined_hr_excel
from repositories.employee_repository import EmployeeRepository
from repositories.leave_repository import LeaveRequestRepository
from services.attendance_service import AttendanceService
from services.overtime_service import OvertimeService


MAX_REPORT_PERIOD_DAYS = 366
APPROVED_LEAVE_STATUSES = {
    "scheduled",
    "approved",
    "in_progress",
    "completed",
    "partially_cancelled",
}


def _validated_report_period(
    range_value: object,
) -> tuple[date, date] | None:
    """Validate one complete, chronological, bounded report period."""

    if not isinstance(range_value, (tuple, list)) or len(range_value) != 2:
        st.info("Select both the report start date and end date.")
        return None

    start_date, end_date = range_value
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        st.error("Select a valid report start date and end date.")
        return None
    if end_date < start_date:
        st.error("The report end date cannot be earlier than the start date.")
        return None
    if (end_date - start_date).days > MAX_REPORT_PERIOD_DAYS:
        st.error("Select a report period of 366 days or less.")
        return None
    return start_date, end_date


def render_employee_reports_page(
    current_user: AuthenticatedUser,
) -> None:
    """Generate a three-sheet workbook containing only the signed-in employee."""

    st.title("My Reports")
    st.caption(
        "Generate your own DTR Logs, Overtime File, and Leave File in one Excel "
        "workbook. Reports never include another employee's records."
    )

    if current_user.employee_id is None:
        st.error(
            "Your login account is not linked to an employee record. "
            "Contact your administrator before generating a report."
        )
        return

    today = date.today()
    range_value = st.date_input(
        "Report Period",
        value=(today.replace(day=1), today),
        key="employee_personal_report_period",
    )
    report_period = _validated_report_period(range_value)
    if report_period is None:
        return
    start_date, end_date = report_period

    with SessionFactory() as session:
        employee = EmployeeRepository(session).get_with_details(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
        )
        if employee is None:
            st.error(
                "Your employee record is unavailable for this company. "
                "Contact your administrator."
            )
            return

        employee_ids = [employee.id]
        attendance_service = AttendanceService(session)
        attendance_records = attendance_service.list_report_records(
            company_id=current_user.company_id,
            start_date=start_date,
            end_date=end_date,
            employee_ids=employee_ids,
        )
        scheduled_workdays = attendance_service.workday_map(
            company_id=current_user.company_id,
            start_date=start_date,
            end_date=end_date,
        )
        leave_requests = [
            request
            for request in LeaveRequestRepository(session).list_employee(
                current_user.company_id,
                employee.id,
            )
            if request.end_date >= start_date
            and request.start_date <= end_date
        ]
        overtime_requests = OvertimeService(session).list_company_range(
            company_id=current_user.company_id,
            start_date=start_date,
            end_date=end_date,
            employee_ids=employee_ids,
        )
        workbook_bytes = build_combined_hr_excel(
            employees=[employee],
            attendance_records=attendance_records,
            leave_requests=leave_requests,
            overtime_requests=overtime_requests,
            start_date=start_date,
            end_date=end_date,
            scheduled_workdays=scheduled_workdays,
            timezone_name=get_settings().display_timezone,
        )

    approved_leave_count = sum(
        1
        for request in leave_requests
        if request.status in APPROVED_LEAVE_STATUSES
    )
    approved_ot_count = sum(
        1
        for request in overtime_requests
        if request.status == "approved"
    )
    metrics = st.columns(3)
    metrics[0].metric("DTR Records", len(attendance_records))
    metrics[1].metric("Approved OT Requests", approved_ot_count)
    metrics[2].metric("Approved Leave Requests", approved_leave_count)

    with st.container(border=True):
        st.markdown("**Personal workbook contents**")
        st.markdown(
            "- `DTR Logs` — your Start Time and End Time rows\n"
            "- `Overtime File` — your DTR-detected and approved overtime details\n"
            "- `Leave File` — your approved VL, SL, EL, and other leave records"
        )
        st.caption(
            "The workbook uses the same payroll-compatible formats as the "
            "administrator report, restricted to your linked employee ID."
        )

    st.download_button(
        "Download My DTR / OT / Leave Report",
        data=workbook_bytes,
        file_name=(
            f"employee_{employee.employee_number}_hr_report_"
            f"{start_date.isoformat()}_to_{end_date.isoformat()}.xlsx"
        ),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
    )
