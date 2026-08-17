"""Administration attendance schedule, matrix, corrections, and reports."""

import calendar
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from pydantic import ValidationError
from sqlalchemy import select

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from models.department import Department
from modules.reports.attendance_report import (
    build_attendance_excel,
    build_attendance_pdf,
)
from schemas.attendance_schema import (
    AttendanceCorrectionInput,
    AttendanceSessionInput,
    CompanyAttendanceCalendarInput,
)
from schemas.overtime_schema import OvertimeReviewInput
from services.attendance_service import AttendanceService
from ui.components.attendance_editor_utils import attendance_editor_clock
from services.attendance_service import AttendanceMatrix
from services.overtime_service import OvertimeService
from ui.components.attendance_table import render_attendance_matrix
from ui.components.data_table import render_admin_table
from ui.components.live_search import live_search_input
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)


STATUS_OPTIONS = ("WFO", "WFH", "VL", "SL", "EL")
CALENDAR_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _render_overtime_approvals(current_user: AuthenticatedUser) -> None:
    """Review pending DTR-grounded OT requests before attendance correction."""

    with st.expander("Overtime Requests & Validation"):
        with SessionFactory() as session:
            pending = OvertimeService(session).list_pending(
                company_id=current_user.company_id,
                reviewer_employee_id=current_user.employee_id,
                clearance=current_user.clearance,
            )
        if not pending:
            st.info("No overtime requests are waiting for your approval.")
            return
        render_admin_table(
            [
                {
                    "Request ID": item.public_id,
                    "Employee": item.employee.full_name,
                    "Date": item.date_rendered.isoformat(),
                    "Submitted Hours": f"{Decimal(item.estimated_hours):.2f}",
                    "DTR Hours": f"{Decimal(item.dtr_estimated_hours):.2f}",
                    "OT Type": item.ot_type,
                    "DTR Review": "Mismatch" if item.has_dtr_mismatch else "Matched",
                }
                for item in pending
            ],
            key="admin-overtime-pending",
            min_width=1050,
            compact=True,
            max_height=310,
        )
        request_map = {
            f"{item.public_id} · {item.employee.full_name} · {item.date_rendered}": item
            for item in pending
        }
        selected_label = st.selectbox(
            "Review Overtime Request",
            list(request_map),
            key="admin_overtime_review_request",
        )
        selected = request_map[selected_label]
        with st.container(border=True):
            details = st.columns(2)
            details[0].markdown(
                f"**DTR reference**  \n"
                f"Detected OT: {selected.dtr_estimated_hours} hour(s)"
            )
            details[1].markdown(
                f"**Employee request**  \n"
                f"Submitted OT: {selected.estimated_hours} hour(s)"
            )
            st.write(f"**Purpose:** {selected.ot_purpose}")
            st.caption(
                f"Travel Fare: {selected.travel_fare or '—'} · "
                f"Route: {selected.travel_route or '—'} · "
                f"Dinner Break: {'Yes' if selected.dinner_break_flag else 'No'}"
            )
            comment = st.text_area(
                "Reviewer Comment",
                key=f"admin_ot_comment_{selected.id}",
            )
            actions = st.columns(2)
            approve = actions[0].button(
                "Approve Overtime",
                type="primary",
                width="stretch",
                key=f"approve_ot_{selected.id}",
            )
            reject = actions[1].button(
                "Reject Overtime",
                width="stretch",
                key=f"reject_ot_{selected.id}",
            )
        if approve or reject:
            try:
                with SessionFactory() as session:
                    reviewed = OvertimeService(session).review(
                        OvertimeReviewInput(
                            company_id=current_user.company_id,
                            overtime_request_id=selected.id,
                            reviewed_by_user_id=current_user.user_id,
                            reviewer_employee_id=current_user.employee_id,
                            clearance=current_user.clearance,
                            decision="approved" if approve else "rejected",
                            comment=comment,
                        )
                    )
                set_operation_feedback(
                    f"{reviewed.public_id} was {reviewed.status}.",
                    namespace="admin_attendance",
                )
                st.rerun()
            except (ValidationError, ValueError) as error:
                render_action_warning(error)
            except Exception:
                st.error("The overtime request could not be reviewed.")


def _month_filters() -> tuple[int, int]:
    today = date.today()
    columns = st.columns(2)
    with columns[0]:
        month = st.selectbox(
            "Month", range(1, 13), index=today.month - 1,
            format_func=lambda value: date(2000, value, 1).strftime("%B"),
            key="admin_dtr_month",
        )
    with columns[1]:
        year = st.number_input(
            "Year", 2020, 2100, today.year, step=1, key="admin_dtr_year"
        )
    return int(year), int(month)


def _render_attendance_settings(
    current_user: AuthenticatedUser,
    *,
    year: int,
    month: int,
) -> None:
    """Render compact monthly workday selection and OT rule settings."""

    with SessionFactory() as session:
        service = AttendanceService(session)
        company = service.get_company(current_user.company_id)
        regular_hours = float(company.attendance_regular_hours)
        lunch_minutes = int(company.attendance_lunch_minutes)
        workdays = service.monthly_workday_map(
            company_id=current_user.company_id,
            year=year,
            month=month,
        )

    with st.expander("Attendance Schedule & OT Rules"):
        st.caption(
            "Configure paid hours, the unpaid lunch allowance, and the exact "
            "regular workdays for the selected DTR month. Unselected dates "
            "are rest days, where every paid hour is OT."
        )
        value_columns = st.columns(2)
        with value_columns[0]:
            new_regular_hours = st.number_input(
                "Regular Paid Hours per Day",
                min_value=1.0,
                max_value=24.0,
                value=regular_hours,
                step=0.5,
                key=f"attendance_regular_hours_{current_user.company_id}",
            )
        with value_columns[1]:
            new_lunch_minutes = st.number_input(
                "Unpaid Lunch Break (minutes)",
                min_value=0,
                max_value=240,
                value=lunch_minutes,
                step=15,
                key=f"attendance_lunch_minutes_{current_user.company_id}",
            )

        required_span = Decimal(str(new_regular_hours)) + (
            Decimal(int(new_lunch_minutes)) / Decimal("60")
        )
        st.caption(
            "Attendance span before OT: "
            f"{required_span:.2f} hours = {float(new_regular_hours):.2f} "
            f"paid hours + {int(new_lunch_minutes)}-minute unpaid lunch."
        )

        month_label = date(year, month, 1).strftime("%B %Y")
        st.markdown(f"**Regular Workdays — {month_label}**")
        st.caption(
            "Weekdays are selected by default for a new month. Select or "
            "deselect any date for holidays and catch-up workdays."
        )

        header_columns = st.columns(7, gap="small")
        for column, day_name in zip(header_columns, CALENDAR_DAY_NAMES):
            with column:
                st.caption(day_name)

        selected_dates: list[date] = []
        month_calendar = calendar.Calendar(firstweekday=0)
        for week in month_calendar.monthdatescalendar(year, month):
            week_columns = st.columns(7, gap="small")
            for column, work_date in zip(week_columns, week):
                with column:
                    if work_date.month != month:
                        st.markdown("&nbsp;", unsafe_allow_html=True)
                        continue
                    selected = st.checkbox(
                        str(work_date.day),
                        value=workdays[work_date],
                        key=(
                            "attendance_calendar_"
                            f"{current_user.company_id}_{work_date.isoformat()}"
                        ),
                    )
                    if selected:
                        selected_dates.append(work_date)

        if st.button(
            "Save Attendance Schedule",
            type="primary",
            width="stretch",
            key=(
                "save_attendance_schedule_"
                f"{current_user.company_id}_{year}_{month}"
            ),
        ):
            try:
                request = CompanyAttendanceCalendarInput(
                    company_id=current_user.company_id,
                    year=year,
                    month=month,
                    regular_hours=new_regular_hours,
                    lunch_break_minutes=new_lunch_minutes,
                    work_dates=selected_dates,
                )
                with SessionFactory() as session:
                    AttendanceService(session).save_attendance_calendar(request)
                set_operation_feedback(
                    f"Attendance schedule for {month_label} was updated.",
                    namespace="admin_attendance",
                )
                st.rerun()
            except (ValidationError, ValueError) as error:
                render_action_warning(error)
            except Exception:
                st.error("The attendance schedule could not be updated.")


def _render_correction(
    current_user: AuthenticatedUser,
    employees,
) -> None:
    with st.expander("Admin Attendance Correction"):
        if not employees:
            st.info("No employee records are available.")
            return
        employee_map = {employee.full_name: employee.id for employee in employees}
        employee_name = st.selectbox("Employee", list(employee_map), key="dtr_fix_employee")
        correction_date = st.date_input("Date", value=date.today(), key="dtr_fix_date")
        status = st.selectbox("Correct Status", STATUS_OPTIONS, key="dtr_fix_status")
        with SessionFactory() as session:
            service = AttendanceService(session)
            existing_record = service.get_daily(
                company_id=current_user.company_id,
                employee_id=employee_map[employee_name],
                attendance_date=correction_date,
            )
            existing_sessions = [
                {
                    "status": item.work_status,
                    "time_in": service.to_local(item.actual_time_in),
                    "time_out": service.to_local(item.actual_time_out),
                }
                for item in (existing_record.sessions if existing_record else [])
            ]
        marker = (
            f"{employee_map[employee_name]}_{correction_date}_"
            f"{existing_record.updated_at if existing_record else 'new'}"
        )
        st.caption(
            "Use zero sessions for a leave-only/status-only correction. "
            "WFO/WFH sessions may be added for split or hybrid work; session "
            "times use 15-minute increments and may not overlap."
        )
        session_count = int(
            st.number_input(
                "Work Sessions",
                min_value=0,
                max_value=8,
                value=len(existing_sessions),
                step=1,
                key=f"dtr_fix_session_count_{marker}",
            )
        )
        correction_session_values: list[dict[str, object]] = []
        for index in range(session_count):
            existing = existing_sessions[index] if index < len(existing_sessions) else None
            st.markdown(f"**Session {index + 1}**")
            columns = st.columns([1, 1, 1, .6])
            with columns[0]:
                location = st.selectbox(
                    "Location",
                    ("WFO", "WFH"),
                    index=("WFO", "WFH").index(
                        existing["status"] if existing else "WFO"
                    ),
                    key=f"dtr_fix_location_{marker}_{index}",
                )
            with columns[1]:
                local_in = (
                    existing["time_in"]
                    if existing and existing["time_in"] is not None
                    else datetime.combine(correction_date, time(9, 0))
                )
                session_in = st.time_input(
                    "Time In",
                    value=attendance_editor_clock(
                        local_in,
                        fallback=datetime.combine(correction_date, time(9, 0)),
                    ),
                    step=900,
                    key=f"dtr_fix_in_{marker}_{index}",
                )
            with columns[2]:
                # Open attendance sessions have no Time Out. Use the visual
                # fallback only; the unchecked ``Completed`` control below
                # continues to submit None until the correction is completed.
                local_out = (
                    existing["time_out"]
                    if existing and existing["time_out"] is not None
                    else datetime.combine(correction_date, time(18, 0))
                )
                session_out = st.time_input(
                    "Time Out",
                    value=attendance_editor_clock(
                        local_out,
                        fallback=datetime.combine(correction_date, time(18, 0)),
                    ),
                    step=900,
                    key=f"dtr_fix_out_{marker}_{index}",
                )
            with columns[3]:
                completed = st.checkbox(
                    "Completed",
                    value=bool(existing and existing["time_out"]),
                    key=f"dtr_fix_complete_{marker}_{index}",
                )
            correction_session_values.append(
                {
                    "work_status": location,
                    "time_in": session_in,
                    "time_out": session_out if completed else None,
                }
            )
        reason = st.text_input("Correction Reason", max_chars=500, key="dtr_fix_reason")
        if st.button("Save Attendance Correction", type="primary", width="stretch"):
            try:
                timezone = ZoneInfo(get_settings().display_timezone)
                sessions = [
                    AttendanceSessionInput(
                        work_status=str(item["work_status"]),
                        time_in=datetime.combine(
                            correction_date,
                            item["time_in"],
                            tzinfo=timezone,
                        ),
                        time_out=(
                            datetime.combine(
                                correction_date,
                                item["time_out"],
                                tzinfo=timezone,
                            )
                            if item["time_out"] is not None
                            else None
                        ),
                    )
                    for item in correction_session_values
                ]
                request = AttendanceCorrectionInput(
                    company_id=current_user.company_id,
                    employee_id=employee_map[employee_name],
                    attendance_date=correction_date,
                    corrected_by_user_id=current_user.user_id,
                    work_status=status,
                    sessions=sessions,
                    reason=reason,
                )
                with SessionFactory() as session:
                    AttendanceService(session).correct_attendance(request)
                set_operation_feedback(
                    "Attendance correction saved with an audit record.",
                    namespace="admin_attendance",
                )
                st.rerun()
            except (ValidationError, ValueError) as error:
                render_action_warning(error)
            except Exception:
                st.error("The attendance correction could not be saved.")


def _render_correction_history(
    current_user: AuthenticatedUser,
) -> None:
    """Show immutable employee and administrator attendance edits."""

    with st.expander("Attendance Edit History"):
        st.caption(
            "Employee self-service changes and administrator corrections are "
            "recorded here with their previous and updated values."
        )
        with SessionFactory() as session:
            history = AttendanceService(session).list_correction_history(
                company_id=current_user.company_id,
            )

        if not history:
            st.info("No attendance edits have been recorded yet.")
            return

        employee_options = [
            "All Employees",
            *sorted({entry.employee_name for entry in history}),
        ]
        selected_employee = st.selectbox(
            "History Employee",
            employee_options,
            key="attendance_history_employee",
        )
        if selected_employee != "All Employees":
            history = [
                entry
                for entry in history
                if entry.employee_name == selected_employee
            ]

        rows = [
            {
                "Employee": entry.employee_name,
                "Attendance Date": entry.attendance_date.strftime("%Y/%m/%d"),
                "Edited By": entry.edited_by,
                "Changed At": entry.changed_at,
                "Change Type": entry.change_type,
                "Previous Time In": entry.previous_time_in,
                "New Time In": entry.new_time_in,
                "Previous Time Out": entry.previous_time_out,
                "New Time Out": entry.new_time_out,
                "Previous Status": entry.previous_status,
                "New Status": entry.new_status,
                "Reason": entry.reason,
            }
            for entry in history
        ]
        render_admin_table(
            rows,
            key="attendance-edit-history",
            min_width=1900,
            compact=True,
        )


def _render_reports(current_user: AuthenticatedUser, employees) -> None:
    st.subheader("Attendance Reports")
    today = date.today()
    range_value = st.date_input(
        "Report Period",
        value=(today.replace(day=1), today),
        key="attendance_report_period",
    )
    if not isinstance(range_value, (tuple, list)) or len(range_value) != 2:
        st.info("Select a start and end date.")
        return
    start_date, end_date = range_value
    employee_ids = {employee.id for employee in employees}
    options = ["All Employees"] + [employee.full_name for employee in employees]
    filter_columns = st.columns(3)
    with filter_columns[0]:
        selected = st.selectbox("Employee", options, key="attendance_report_employee")
    with SessionFactory() as session:
        departments = list(
            session.scalars(
                select(Department).where(Department.company_id == current_user.company_id)
                .order_by(Department.name)
            ).all()
        )
    department_options = ["All Departments"] + [item.name for item in departments]
    with filter_columns[1]:
        selected_department = st.selectbox(
            "Department", department_options, key="attendance_report_department"
        )
    with filter_columns[2]:
        selected_status = st.selectbox(
            "Status", ["All Statuses", *STATUS_OPTIONS],
            key="attendance_report_status",
        )
    selected_ids = None
    if selected != "All Employees":
        selected_ids = [
            employee.id for employee in employees if employee.full_name == selected
        ]
    if selected_department != "All Departments":
        department_id = next(
            item.id for item in departments if item.name == selected_department
        )
        department_employee_ids = {
            employee.id for employee in employees
            if employee.department_id == department_id
        }
        selected_ids = list(
            department_employee_ids
            if selected_ids is None
            else set(selected_ids) & department_employee_ids
        )
    if selected_ids is None:
        selected_ids = list(employee_ids)
    with SessionFactory() as session:
        service = AttendanceService(session)
        records = service.list_report_records(
            company_id=current_user.company_id,
            start_date=start_date,
            end_date=end_date,
            employee_ids=selected_ids,
        )
        if selected_status != "All Statuses":
            records = [
                record for record in records
                if record.work_status == selected_status
            ]
        report_metrics = st.columns(3)
        report_metrics[0].metric("Records", len(records))
        report_metrics[1].metric(
            "Total Hours", f"{sum(float(row.total_hours) for row in records):.2f}"
        )
        report_metrics[2].metric(
            "OT Hours", f"{sum(float(row.ot_hours) for row in records):.2f}"
        )
        rows = []
        for record in records:
            session_parts = []
            for item in record.sessions:
                local_in = service.to_local(item.rounded_time_in)
                local_out = service.to_local(item.rounded_time_out)
                local_in_text = (
                    f"{local_in:%H:%M}" if local_in is not None else "—"
                )
                local_out_text = (
                    f"{local_out:%H:%M}" if local_out is not None else "OPEN"
                )
                session_parts.append(
                    f"{item.work_status} {local_in_text}-{local_out_text}"
                )
            session_text = " / ".join(session_parts)
            rows.append({
                "Employee Name": record.employee.full_name,
                "Date": record.attendance_date.strftime("%Y/%m/%d"),
                "Sessions": session_text or "—",
                "Status": record.work_status or "—",
                "Total Hours": record.total_hours,
                "Leave Hours": record.leave_hours,
                "Undertime Hours": record.undertime_hours,
                "OT Hours": record.ot_hours,
            })
        if rows:
            render_admin_table(rows, key="attendance-report", min_width=900, compact=True)
        else:
            st.info("No attendance records match this report period.")
        timezone_name = get_settings().display_timezone
        excel = build_attendance_excel(records, timezone_name=timezone_name)
        pdf = build_attendance_pdf(
            records, timezone_name=timezone_name,
            start_date=start_date, end_date=end_date,
        )
    buttons = st.columns(2)
    with buttons[0]:
        st.download_button(
            "Download Excel", excel,
            file_name=f"attendance_{start_date}_{end_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
    with buttons[1]:
        st.download_button(
            "Download PDF", pdf,
            file_name=f"attendance_{start_date}_{end_date}.pdf",
            mime="application/pdf", width="stretch",
        )


def render_admin_attendance_dashboard(
    current_user: AuthenticatedUser,
    *,
    show_management_tools: bool = True,
) -> None:
    """Render reusable company-wide DTR with optional management tools."""

    render_operation_feedback(namespace="admin_attendance")
    year, month = _month_filters()
    with SessionFactory() as session:
        service = AttendanceService(session)
        matrix = service.monthly_matrix(
            company_id=current_user.company_id,
            year=year, month=month,
            user_id=current_user.user_id,
            employee_id=current_user.employee_id,
            clearance=current_user.clearance,
        )
        total_employee_count = len(matrix.employees)

        def searchable_employee(employee) -> str:
            records = [
                record
                for (employee_id, _), record in matrix.records.items()
                if employee_id == employee.id
            ]
            values = [
                employee.employee_number,
                employee.full_name,
                employee.work_email,
                employee.telephone_mobile_no,
                employee.job_title,
                employee.employment_status,
                employee.department.name if employee.department else "",
                employee.manager.full_name if employee.manager else "",
                employee.leader.full_name if employee.leader else "",
                employee.user.username if employee.user else "",
                *(value for record in records for value in (
                    record.attendance_date,
                    record.work_status,
                    record.time_in,
                    record.time_out,
                    record.total_hours,
                    record.leave_hours,
                    record.undertime_hours,
                    record.ot_hours,
                )),
            ]
            return " ".join(str(value).casefold() for value in values if value not in (None, ""))

        search = live_search_input(
            "Search Employee / Attendance / DTR / OT",
            placeholder="Search any employee or attendance column…",
            key="admin_dtr_employee_search",
            suggestions=(
                value
                for employee in matrix.employees
                for value in (
                    employee.employee_number,
                    employee.full_name,
                    employee.employment_status,
                    employee.department.name if employee.department else None,
                    employee.job_title,
                )
                if value
            ),
        ).strip().casefold()
        if search:
            visible = [
                employee for employee in matrix.employees
                if search in searchable_employee(employee)
            ]
            visible_ids = {employee.id for employee in visible}
            matrix = AttendanceMatrix(
                employees=visible,
                dates=matrix.dates,
                records={
                    key: value for key, value in matrix.records.items()
                    if key[0] in visible_ids
                },
                scheduled_workdays=matrix.scheduled_workdays,
            )
        st.caption(
            f"{len(matrix.employees)} of {total_employee_count} "
            "employee(s) shown. The table displays seven rows before "
            "vertical scrolling."
        )
        total_hours = sum(float(row.total_hours) for row in matrix.records.values())
        ot_hours = sum(float(row.ot_hours) for row in matrix.records.values())
        metrics = st.columns(3)
        metrics[0].metric("Employees", len(matrix.employees))
        metrics[1].metric("Total Hours", f"{total_hours:.2f}")
        metrics[2].metric("OT Hours", f"{ot_hours:.2f}")
        render_attendance_matrix(matrix, service=service, key="admin-monthly-dtr")
        employees = list(matrix.employees)
    if show_management_tools:
        _render_attendance_settings(
            current_user,
            year=year,
            month=month,
        )
        _render_overtime_approvals(current_user)
        _render_correction(current_user, employees)
        _render_correction_history(current_user)
