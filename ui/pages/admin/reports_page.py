"""Administrator combined DTR, overtime, and leave reporting workspace."""

from __future__ import annotations

from datetime import date

import streamlit as st
from sqlalchemy import select

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from models.department import Department
from modules.reports.combined_hr_report import build_combined_hr_excel
from modules.reports.leave_conversion_report import (
    build_leave_conversion_excel,
    build_leave_conversion_rows,
)
from repositories.employee_repository import EmployeeRepository
from repositories.leave_repository import (
    LeaveBalanceRepository,
    LeaveRequestRepository,
)
from services.leave_service import LeaveService
from services.attendance_service import AttendanceService
from services.overtime_service import OvertimeService
from ui.components.live_search import live_search_input


def _selected_employee_ids(
    *,
    employees,
    employee_id: int | None,
    department_name: str,
) -> list[int]:
    selected = list(employees)
    if employee_id is not None:
        selected = [item for item in selected if item.id == employee_id]
    if department_name != "All Departments":
        selected = [
            item
            for item in selected
            if item.department is not None
            and item.department.name == department_name
        ]
    return [item.id for item in selected]


def _render_combined_hr_report(current_user: AuthenticatedUser) -> None:
    """Generate one company-scoped workbook with three operational sheets."""

    st.markdown("## Combined DTR / OT / Leave Report")
    st.caption(
        "Generate one Excel workbook containing DTR Logs, Overtime File, and Leave "
        "File for the same selected reporting period and employee scope."
    )

    today = date.today()
    range_value = st.date_input(
        "Report Period",
        value=(today.replace(day=1), today),
        key="combined_hr_report_period",
    )
    if not isinstance(range_value, (tuple, list)) or len(range_value) != 2:
        st.info("Select both the report start date and end date.")
        return
    start_date, end_date = range_value
    if end_date < start_date:
        st.error("The report end date cannot be earlier than the start date.")
        return
    if (end_date - start_date).days > 366:
        st.error("Select a report period of 366 days or less.")
        return

    with SessionFactory() as session:
        attendance_service = AttendanceService(session)
        employees = attendance_service.visible_employees(
            company_id=current_user.company_id,
            user_id=current_user.user_id,
            employee_id=current_user.employee_id,
            clearance=current_user.clearance,
        )
        departments = list(
            session.scalars(
                select(Department)
                .where(Department.company_id == current_user.company_id)
                .order_by(Department.name)
            ).all()
        )

        filters = st.columns(2)
        employee_options = {
            "All Employees": None,
            **{
                f"{item.employee_number} · {item.full_name}": item.id
                for item in employees
            },
        }
        with filters[0]:
            selected_employee_label = st.selectbox(
                "Employee",
                list(employee_options),
                key="combined_hr_report_employee",
            )
        with filters[1]:
            selected_department = st.selectbox(
                "Department",
                ["All Departments", *[item.name for item in departments]],
                key="combined_hr_report_department",
            )

        selected_ids = _selected_employee_ids(
            employees=employees,
            employee_id=employee_options[selected_employee_label],
            department_name=selected_department,
        )
        selected_id_set = set(selected_ids)
        selected_employees = [
            item for item in employees if item.id in selected_id_set
        ]
        attendance_records = attendance_service.list_report_records(
            company_id=current_user.company_id,
            start_date=start_date,
            end_date=end_date,
            employee_ids=selected_ids,
        )
        scheduled_workdays = attendance_service.workday_map(
            company_id=current_user.company_id,
            start_date=start_date,
            end_date=end_date,
        )
        leave_requests = [
            request
            for request in LeaveRequestRepository(session).list_company(
                current_user.company_id
            )
            if request.employee_id in selected_id_set
            and request.end_date >= start_date
            and request.start_date <= end_date
        ]
        overtime_requests = OvertimeService(session).list_company_range(
            company_id=current_user.company_id,
            start_date=start_date,
            end_date=end_date,
            employee_ids=selected_ids,
        )
        timezone_name = get_settings().display_timezone
        workbook_bytes = build_combined_hr_excel(
            employees=selected_employees,
            attendance_records=attendance_records,
            leave_requests=leave_requests,
            overtime_requests=overtime_requests,
            start_date=start_date,
            end_date=end_date,
            scheduled_workdays=scheduled_workdays,
            timezone_name=timezone_name,
        )

    approved_leave_statuses = {
        "scheduled",
        "approved",
        "in_progress",
        "completed",
        "partially_cancelled",
    }
    overtime_count = sum(
        1 for item in attendance_records if float(item.ot_hours) > 0
    )
    approved_leave_count = sum(
        1 for item in leave_requests if item.status in approved_leave_statuses
    )
    metrics = st.columns(3)
    metrics[0].metric("Employees", len(selected_employees))
    metrics[1].metric("OT Records", overtime_count)
    metrics[2].metric("Approved Leave Records", approved_leave_count)

    with st.container(border=True):
        st.markdown("**Combined workbook contents**")
        st.markdown(
            "- `DTR Logs` — two rows per employee: Start Time and End Time\n"
            "- `Overtime File` — one row per attendance record with computed OT\n"
            "- `Leave File` — approved VL, SL, EL, and other configured leave types"
        )
        st.caption(
            "Approved employee OT requests supply the OT time, type, purpose, "
            "travel, dinner-break, and CC approval fields. If only DTR data "
            "exists, the export fills only Employee ID, Employee Name, Date "
            "Rendered, and Estimated Hours; all unsupported fields remain blank."
        )

    st.download_button(
        "Download Combined Excel Report",
        data=workbook_bytes,
        file_name=(
            f"combined_hr_report_{start_date.isoformat()}_to_"
            f"{end_date.isoformat()}.xlsx"
        ),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
        disabled=not selected_employees,
    )


def _render_leave_conversion_report(
    current_user: AuthenticatedUser,
) -> None:
    """Render and export the annual SL/VL cash-conversion summary."""

    st.markdown("## Leave Conversion to Cash Report")
    st.caption(
        "Review prior-year carried balances, current Vacation Leave credit, "
        "and the converted Vacation/Sick Leave days for the selected leave year."
    )
    today = date.today()
    leave_year = int(
        st.number_input(
            "Leave Year",
            min_value=2020,
            max_value=2100,
            value=today.year,
            step=1,
            key="leave_conversion_report_year",
        )
    )

    with SessionFactory() as session:
        # Idempotent annual processing ensures the report reads the same
        # persisted ledger used by Leave Management.
        leave_service = LeaveService(session)
        leave_service.ensure_current_year_balances(
            current_user.company_id,
            leave_year,
        )
        session.commit()
        employees = EmployeeRepository(session).list_with_details(
            current_user.company_id,
            archived=False,
        )
        balances = LeaveBalanceRepository(session).list_company_year(
            current_user.company_id,
            leave_year,
        )
        rows = build_leave_conversion_rows(
            employees=employees,
            balances=balances,
            leave_year=leave_year,
        )

    search = live_search_input(
        "Search Leave Conversion",
        placeholder="Search any report column…",
        key="leave_conversion_report_search",
        suggestions=(
            value
            for row in rows
            for value in row.values()
            if value not in (None, "")
        ),
    ).strip().casefold()
    if search:
        rows = [
            row
            for row in rows
            if search in " ".join(
                str(value).casefold() for value in row.values()
            )
        ]

    total_conversion = sum(
        (row["Total Conversion"] for row in rows),
        start=0,
    )
    metrics = st.columns(2)
    metrics[0].metric("Employees", len(rows))
    metrics[1].metric("Total Conversion (Days)", f"{total_conversion:.2f}")

    if rows:
        from ui.components.data_table import render_admin_table

        render_admin_table(
            rows,
            key="leave-conversion-to-cash-report",
            min_width=2200,
            compact=True,
            max_height=430,
        )
    else:
        st.info("No employee records match the selected report filters.")

    workbook_bytes = build_leave_conversion_excel(rows)
    st.download_button(
        "Download Leave Conversion to Cash Report",
        data=workbook_bytes,
        file_name=f"leave_conversion_to_cash_{leave_year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
        disabled=not rows,
    )


def render_admin_reports_page(current_user: AuthenticatedUser) -> None:
    """Render stateful report workspaces without duplicating sidebar pages."""

    st.title("Reports")
    combined_tab, conversion_tab = st.tabs(
        ("Combined HR Report", "Leave Conversion to Cash"),
        key="admin_reports_active_tab",
        on_change="rerun",
    )
    if combined_tab.open:
        with combined_tab:
            _render_combined_hr_report(current_user)
    elif conversion_tab.open:
        with conversion_tab:
            _render_leave_conversion_report(current_user)
