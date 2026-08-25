"""Employee attendance controls and hierarchy-scoped monthly DTR."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from pydantic import ValidationError

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from schemas.attendance_schema import (
    AttendancePunchInput,
    AttendanceSessionInput,
    AttendanceSelfEditInput,
    AttendanceStatusInput,
)
from schemas.overtime_schema import (
    OT_TYPE_OPTIONS,
    OvertimeRequestInput,
    OvertimeReviewInput,
)
from services.attendance_service import AttendanceService
from services.overtime_service import OvertimeService
from ui.components.attendance_editor_utils import attendance_editor_clock
from ui.components.attendance_table import render_attendance_matrix
from ui.components.browser_bridge import render_browser_bridge
from ui.components.data_table import render_admin_table
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)


STATUS_OPTIONS = ("WFO", "WFH", "VL", "SL", "EL")
WORK_LOCATION_OPTIONS = ("WFO", "WFH")
_EDITOR_SCROLL_STATE_KEY = "_employee_attendance_scroll_to_editor"


def _local_overtime_time(value: datetime | None, timezone_value: ZoneInfo) -> str:
    """Format a persisted OT timestamp without assuming SQLite kept tzinfo."""

    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(timezone_value).strftime("%I:%M %p")


def _render_team_overtime_approvals(current_user: AuthenticatedUser) -> None:
    """Allow an assigned leader or manager to review direct-member OT."""

    with SessionFactory() as session:
        pending = OvertimeService(session).list_pending(
            company_id=current_user.company_id,
            reviewer_employee_id=current_user.employee_id,
            clearance=2,
        )
    if not pending:
        return
    st.divider()
    st.markdown("**Team Overtime Requests for Approval**")
    st.caption(
        "Only requests assigned to you through the employee hierarchy are shown."
    )
    render_admin_table(
        [
            {
                "Request ID": item.public_id,
                "Employee": item.employee.full_name,
                "Date": item.date_rendered.isoformat(),
                "Submitted Hours": f"{Decimal(item.estimated_hours):.2f}",
                "DTR Hours": f"{Decimal(item.dtr_estimated_hours):.2f}",
                "DTR Review": "Mismatch" if item.has_dtr_mismatch else "Matched",
            }
            for item in pending
        ],
        key="employee-team-overtime-pending",
        min_width=850,
        compact=True,
        max_height=260,
    )
    request_map = {
        f"{item.public_id} · {item.employee.full_name} · {item.date_rendered}": item
        for item in pending
    }
    selected_label = st.selectbox(
        "Review Team Overtime Request",
        list(request_map),
        key="employee_team_overtime_review",
    )
    selected = request_map[selected_label]
    st.write(f"**Purpose:** {selected.ot_purpose}")
    comment = st.text_area(
        "Approver Comment",
        key=f"employee_team_ot_comment_{selected.id}",
    )
    actions = st.columns(2)
    approve = actions[0].button(
        "Approve Overtime",
        type="primary",
        width="stretch",
        key=f"employee_team_ot_approve_{selected.id}",
    )
    reject = actions[1].button(
        "Reject Overtime",
        width="stretch",
        key=f"employee_team_ot_reject_{selected.id}",
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
                namespace="attendance",
            )
            st.rerun()
        except (ValidationError, ValueError) as error:
            render_action_warning(error)
        except Exception:
            st.error("The overtime request could not be reviewed.")


def _render_overtime_request(
    current_user: AuthenticatedUser,
    *,
    today: date,
    local_timezone: ZoneInfo,
) -> None:
    """Render combined employee OT filing and personal request history."""

    with st.expander("Overtime Request"):
        st.caption(
            "The filing form is prefilled from your DTR but remains editable. "
            "Editing an OT request does not change the original attendance record."
        )
        st.markdown("**File Overtime Request**")
        with st.container(border=True):
            employee_columns = st.columns(2)
            employee_columns[0].text_input(
                "Employee ID",
                value=current_user.employee_number or "",
                disabled=True,
                key="overtime_employee_number",
            )
            employee_columns[1].text_input(
                "Employee Name",
                value=current_user.employee_name or "",
                disabled=True,
                key="overtime_employee_name",
            )

            rendered_date = st.date_input(
                "Date Rendered",
                value=today,
                min_value=date(2020, 1, 1),
                max_value=date(2100, 12, 31),
                key="employee_overtime_date_rendered",
                help="Automatically starts with today's date and may be changed.",
            )
            with SessionFactory() as session:
                overtime_service = OvertimeService(session)
                reference = overtime_service.dtr_reference(
                    company_id=current_user.company_id,
                    employee_id=current_user.employee_id,
                    date_rendered=rendered_date,
                )
                overtime_rules = overtime_service.rule_snapshot(
                    current_user.company_id
                )
                shifting_eligible, employee_position = (
                    overtime_service.shifting_eligibility(
                        company_id=current_user.company_id,
                        employee_id=current_user.employee_id,
                    )
                )

            st.markdown("**DTR Reference — read-only**")
            reference_columns = st.columns(4)
            reference_columns[0].text_input(
                "DTR Time In",
                value=(
                    reference.time_in.strftime("%I:%M %p")
                    if reference and reference.time_in
                    else "No record"
                ),
                disabled=True,
                key=f"overtime_dtr_in_{rendered_date}",
            )
            reference_columns[1].text_input(
                "DTR Time Out",
                value=(
                    reference.time_out.strftime("%I:%M %p")
                    if reference and reference.time_out
                    else "No record"
                ),
                disabled=True,
                key=f"overtime_dtr_out_{rendered_date}",
            )
            reference_columns[2].text_input(
                "Detected OT",
                value=(
                    (
                        f"{reference.ot_start:%I:%M %p}–"
                        f"{reference.ot_end:%I:%M %p}"
                    )
                    if reference and reference.ot_start and reference.ot_end
                    else "None"
                ),
                disabled=True,
                key=f"overtime_dtr_range_{rendered_date}",
            )
            reference_columns[3].text_input(
                "Detected Hours",
                value=(
                    f"{reference.estimated_hours:.2f}"
                    if reference is not None
                    else "0.00"
                ),
                disabled=True,
                key=f"overtime_dtr_hours_{rendered_date}",
            )

            default_start = (
                reference.ot_start.time().replace(second=0, microsecond=0)
                if reference and reference.ot_start
                else time(17, 0)
            )
            default_end = (
                reference.ot_end.time().replace(second=0, microsecond=0)
                if reference and reference.ot_end
                else time(18, 0)
            )
            time_columns = st.columns(2)
            with time_columns[0]:
                ot_start_time = st.time_input(
                    "OT Start Time",
                    value=default_start,
                    step=900,
                    key=f"employee_ot_start_{rendered_date}",
                )
            with time_columns[1]:
                ot_end_time = st.time_input(
                    "OT End Time",
                    value=default_end,
                    step=900,
                    key=f"employee_ot_end_{rendered_date}",
                )

            start_datetime = datetime.combine(
                rendered_date, ot_start_time, tzinfo=local_timezone
            )
            end_datetime = datetime.combine(
                rendered_date, ot_end_time, tzinfo=local_timezone
            )
            if end_datetime <= start_datetime:
                end_datetime += timedelta(days=1)
            calculated_hours = Decimal(
                str((end_datetime - start_datetime).total_seconds() / 3600)
            ).quantize(Decimal("0.01"))
            # The initial times come from DTR, so this starts with the same
            # detected hours. Changing either time automatically refreshes the
            # suggested value, while the number input itself remains editable.
            default_hours = calculated_hours

            details_columns = st.columns(2)
            with details_columns[0]:
                estimated_hours = st.number_input(
                    "Estimated Hours",
                    min_value=0.25,
                    max_value=24.0,
                    value=float(default_hours),
                    step=0.25,
                    key=(
                        f"employee_ot_hours_{rendered_date}_"
                        f"{ot_start_time}_{ot_end_time}"
                    ),
                    help="Prefilled from DTR and may be edited.",
                )
            with details_columns[1]:
                ot_type = st.selectbox(
                    "OT Type",
                    OT_TYPE_OPTIONS,
                    key=f"employee_ot_type_{rendered_date}",
                )

            ot_purpose = st.text_area(
                "OT Purpose",
                height=90,
                key=f"employee_ot_purpose_{rendered_date}",
            )
            travel_columns = st.columns(2)
            with travel_columns[0]:
                include_fare = st.checkbox(
                    "Include Travel Fare",
                    key=f"employee_ot_include_fare_{rendered_date}",
                )
                travel_fare = (
                    st.number_input(
                        "Travel Fare",
                        min_value=0.0,
                        max_value=1_000_000.0,
                        value=0.0,
                        step=1.0,
                        key=f"employee_ot_fare_{rendered_date}",
                    )
                    if include_fare
                    else None
                )
            with travel_columns[1]:
                travel_route = st.text_input(
                    "Travel Route",
                    disabled=not include_fare,
                    key=f"employee_ot_route_{rendered_date}",
                    help="Required when Travel Fare has a value.",
                )
            dinner_break = st.selectbox(
                "Dinner Break",
                ("No", "Yes"),
                key=f"employee_ot_dinner_{rendered_date}",
            )
            payable_preview = OvertimeService.payable_hours_before_shifting(
                Decimal(str(estimated_hours)),
                dinner_break_flag=dinner_break == "Yes",
                dinner_break_deduction_hours=(
                    overtime_rules.dinner_break_deduction_hours
                ),
            )
            st.caption(
                f"Payable OT before Shifting Credit pairing: "
                f"{payable_preview:.2f} hour(s). "
                + (
                    f"Dinner Break deducts "
                    f"{overtime_rules.dinner_break_deduction_hours:.2f} hour(s). "
                    if dinner_break == "Yes"
                    else ""
                )
                + (
                    "This position is eligible for Shifting Credits."
                    if shifting_eligible and overtime_rules.shifting_credits_enabled
                    else (
                        f"Position {employee_position or '—'} is excluded from "
                        "Shifting Credits."
                        if overtime_rules.shifting_credits_enabled
                        else "Shifting Credits are currently disabled."
                    )
                )
            )
            st.text_input(
                "Status",
                value="Pending Approval",
                disabled=True,
                key=f"employee_ot_status_{rendered_date}",
            )
            submit_overtime = st.button(
                "Submit Overtime Request",
                type="primary",
                width="stretch",
                disabled=(
                    reference is None
                    or reference.time_out is None
                    or reference.estimated_hours <= 0
                ),
                key=f"submit_employee_overtime_{rendered_date}",
            )
            if reference is None:
                st.info("No DTR record is available for the selected date.")
            elif reference.time_out is None:
                st.info("Complete your DTR Time Out before filing overtime.")
            elif reference.estimated_hours <= 0:
                st.info("The selected DTR date has no detected overtime.")

        if submit_overtime:
            try:
                request = OvertimeRequestInput(
                    company_id=current_user.company_id,
                    employee_id=current_user.employee_id,
                    requested_by_user_id=current_user.user_id,
                    date_rendered=rendered_date,
                    ot_time_start=start_datetime,
                    ot_time_end=end_datetime,
                    estimated_hours=Decimal(str(estimated_hours)),
                    ot_type=ot_type,
                    ot_purpose=ot_purpose,
                    travel_fare=(
                        Decimal(str(travel_fare)) if travel_fare is not None else None
                    ),
                    travel_route=travel_route,
                    dinner_break_flag=dinner_break == "Yes",
                )
                with SessionFactory() as session:
                    submitted = OvertimeService(session).submit(request)
                set_operation_feedback(
                    f"Overtime request {submitted.public_id} was submitted.",
                    namespace="attendance",
                )
                st.rerun()
            except (ValidationError, ValueError) as error:
                render_action_warning(error)
            except Exception:
                st.error("The overtime request could not be submitted.")

        st.markdown("**My Overtime Requests**")
        with SessionFactory() as session:
            own_requests = OvertimeService(session).list_own(
                company_id=current_user.company_id,
                employee_id=current_user.employee_id,
            )
        if not own_requests:
            st.info("You have no overtime requests yet.")
            _render_team_overtime_approvals(current_user)
            return
        render_admin_table(
            [
                {
                    "Request ID": item.public_id,
                    "Date": item.date_rendered.isoformat(),
                    "OT Time": (
                        f"{_local_overtime_time(item.ot_time_start, local_timezone)}–"
                        f"{_local_overtime_time(item.ot_time_end, local_timezone)}"
                    ),
                    "Gross Hours": f"{Decimal(item.estimated_hours):.2f}",
                    "Payable OT": f"{Decimal(item.payable_hours):.2f}",
                    "Shifting Credit": f"{Decimal(item.shifting_credit_hours):.2f}",
                    "Additional VL": f"{Decimal(item.additional_vl_days):.2f}",
                    "OT Type": item.ot_type,
                    "Status": item.status.replace("_", " ").title(),
                    "DTR Review": "Mismatch" if item.has_dtr_mismatch else "Matched",
                }
                for item in own_requests
            ],
            key="employee-overtime-requests",
            min_width=1050,
            compact=True,
            max_height=310,
        )
        request_map = {
            f"{item.public_id} · {item.date_rendered} · "
            f"{item.status.replace('_', ' ').title()}": item
            for item in own_requests
        }
        selected_label = st.selectbox(
            "View Overtime Request",
            list(request_map),
            key="employee_overtime_request_details",
        )
        selected_request = request_map[selected_label]
        with st.container(border=True):
            st.markdown(f"**{selected_request.public_id} · {selected_request.ot_type}**")
            st.write(selected_request.ot_purpose)
            st.caption(
                "Original DTR detected: "
                f"{_local_overtime_time(selected_request.dtr_ot_start, local_timezone)}–"
                f"{_local_overtime_time(selected_request.dtr_ot_end, local_timezone)} · "
                f"{Decimal(selected_request.dtr_estimated_hours):.2f} hour(s)"
            )
            st.caption(
                "Submitted OT: "
                f"{_local_overtime_time(selected_request.ot_time_start, local_timezone)}–"
                f"{_local_overtime_time(selected_request.ot_time_end, local_timezone)} · "
                f"{Decimal(selected_request.estimated_hours):.2f} hour(s)"
            )
            st.caption(
                f"Payable OT: {Decimal(selected_request.payable_hours):.2f} hour(s) · "
                f"Shifting Credit: {Decimal(selected_request.shifting_credit_hours):.2f} hour(s) · "
                f"Additional VL: {Decimal(selected_request.additional_vl_days):.2f} day(s)"
            )
            st.caption(
                f"Travel Fare: {selected_request.travel_fare or '—'} · "
                f"Route: {selected_request.travel_route or '—'} · "
                f"Dinner Break: {'Yes' if selected_request.dinner_break_flag else 'No'}"
            )
            if selected_request.reviewer_comment:
                st.caption(f"Reviewer comment: {selected_request.reviewer_comment}")
            if selected_request.status == "pending_approval" and st.button(
                "Cancel Pending Request",
                width="stretch",
                key=f"cancel_employee_overtime_{selected_request.id}",
            ):
                try:
                    with SessionFactory() as session:
                        OvertimeService(session).cancel_own(
                            company_id=current_user.company_id,
                            request_id=selected_request.id,
                            employee_id=current_user.employee_id,
                            user_id=current_user.user_id,
                        )
                    set_operation_feedback(
                        f"{selected_request.public_id} was cancelled.",
                        namespace="attendance",
                    )
                    st.rerun()
                except ValueError as error:
                    render_action_warning(error)
        _render_team_overtime_approvals(current_user)


def _restore_editor_position() -> None:
    """Return the browser to the attendance editor after a save rerun."""

    if not st.session_state.pop(_EDITOR_SCROLL_STATE_KEY, False):
        return

    render_browser_bridge(
        """
        <script>
        const restoreAttendanceEditor = () => {
            const target = parent.document.getElementById(
                "employee-attendance-editor-anchor"
            );
            if (target) {
                target.scrollIntoView({behavior: "auto", block: "start"});
            }
        };
        window.setTimeout(restoreAttendanceEditor, 80);
        window.setTimeout(restoreAttendanceEditor, 260);
        window.setTimeout(restoreAttendanceEditor, 600);
        </script>
        """
    )


def render_employee_attendance_workspace(
    current_user: AuthenticatedUser,
    *,
    show_punch_controls: bool = True,
    show_record_management: bool = True,
) -> None:
    """Render reusable employee punch, DTR, editor, and overtime sections."""

    st.markdown("## Attendance / DTR")
    st.caption(
        (
            "Use Time In and Time Out to record today's attendance. "
            "The selected work status is saved automatically at Time In. "
            if show_punch_controls
            else "Review your attendance table and manage your permitted records. "
        )
        + "Approved leave requests automatically create the default VL, SL, "
        "or EL status, which remains editable in the attendance editor."
    )

    if current_user.employee_id is None:
        st.info("Link this account to an employee record to use attendance.")
        return

    local_timezone = ZoneInfo(get_settings().display_timezone)
    local_now = datetime.now(local_timezone)
    today = local_now.date()
    selected_year = int(
        st.session_state.get("employee_dtr_year", today.year)
    )
    selected_month = int(
        st.session_state.get("employee_dtr_month", today.month)
    )
    if not 1 <= selected_month <= 12:
        selected_month = today.month
    if not 2020 <= selected_year <= 2100:
        selected_year = today.year

    with SessionFactory() as session:
        service = AttendanceService(session)
        daily = service.get_daily(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
            attendance_date=today,
        )
        matrix = service.monthly_matrix(
            company_id=current_user.company_id,
            year=selected_year,
            month=selected_month,
            user_id=current_user.user_id,
            employee_id=current_user.employee_id,
            clearance=current_user.clearance,
        )
        summary = service.employee_month_summary(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
            matrix=matrix,
            today=today,
        )
        # The requested monthly metrics remain specific to the signed-in
        # employee even when a leader or manager can view team rows below.
        metric_columns = st.columns(4)
        metric_columns[0].metric("Leave Count", summary.leave_count)
        metric_columns[1].metric(
            "Overtime Hours (Day)",
            f"{summary.overtime_hours_day:.2f}",
        )
        metric_columns[2].metric(
            "Total Overtime Hours (Whole Month)",
            f"{summary.total_overtime_hours:.2f}",
        )
        metric_columns[3].metric(
            "Work Rate",
            f"{summary.work_rate:.2f}%",
        )

        render_operation_feedback(namespace="attendance")

    punch_clicked = False
    punch_action = ""
    status = "WFO"
    if show_punch_controls:
        default_status = (
            daily.work_status
            if daily and daily.work_status in WORK_LOCATION_OPTIONS
            else "WFO"
        )
        status = st.selectbox(
            "Today's Work Status",
            WORK_LOCATION_OPTIONS,
            index=WORK_LOCATION_OPTIONS.index(default_status),
            help=(
                "WFO = Work From Office, WFH = Work From Home. Approved leave "
                "is supplied automatically by Leave Management."
            ),
            key="attendance_today_status",
        )
        daily_sessions = list(daily.sessions) if daily is not None else []
        has_legacy_punch = bool(daily is not None and daily.time_in is not None)
        has_any_punch = bool(daily_sessions) or has_legacy_punch
        has_open_session = any(
            item.actual_time_out is None for item in daily_sessions
        ) or bool(
            has_legacy_punch
            and not daily_sessions
            and daily.time_out is None
        )
        has_completed_session = has_any_punch and not has_open_session
        punch_action = "time_out" if has_any_punch else "time_in"
        punch_label = "Time Out" if has_any_punch else "Time In"
        punch_clicked = st.button(
            punch_label,
            type="primary" if punch_action == "time_in" else "secondary",
            width="stretch",
            disabled=has_completed_session,
            key="employee_attendance_punch",
        )

    if punch_clicked:
        try:
            common = {
                "company_id": current_user.company_id,
                "employee_id": current_user.employee_id,
                "user_id": current_user.user_id,
                "attendance_date": today,
                "work_status": status,
            }
            with SessionFactory() as session:
                service = AttendanceService(session)
                if punch_action == "time_in":
                    record = service.clock_in(AttendancePunchInput(**common))
                    local_time = service.to_local(record.time_in)
                    message = (
                        f"Time In recorded at {local_time:%H:%M}."
                        if local_time is not None
                        else "Time In recorded."
                    )
                else:
                    record = service.clock_out(AttendancePunchInput(**common))
                    local_time = service.to_local(record.time_out)
                    logout_prefix = (
                        f"Time Out recorded at {local_time:%H:%M}. "
                        if local_time is not None
                        else "Time Out recorded. "
                    )
                    message = (
                        f"{logout_prefix}Total: {record.total_hours}h · "
                        f"OT: {record.ot_hours}h."
                    )
            set_operation_feedback(message, namespace="attendance")
            st.rerun()
        except (ValidationError, ValueError) as error:
            render_action_warning(error)
        except Exception:
            st.error("The attendance record could not be updated.")

    filter_columns = st.columns(2)
    with filter_columns[0]:
        year_options = list(range(2100, 2019, -1))
        year = st.selectbox(
            "Year",
            year_options,
            index=year_options.index(selected_year),
            key="employee_dtr_year",
        )
    with filter_columns[1]:
        month = st.selectbox(
            "Month",
            range(1, 13),
            index=selected_month - 1,
            format_func=lambda value: date(2000, value, 1).strftime("%B"),
            key="employee_dtr_month",
        )

    with SessionFactory() as session:
        table_service = AttendanceService(session)
        render_attendance_matrix(
            matrix,
            service=table_service,
            key="employee-monthly-attendance",
        )

    if not show_record_management:
        return

    st.markdown(
        '<div id="employee-attendance-editor-anchor"></div>',
        unsafe_allow_html=True,
    )
    _restore_editor_position()

    with st.expander("Edit Attendance Record", expanded=True):
        st.caption(
            "Select a date to update your own Time In, Time Out, and Work "
            "Status. Every change is recorded in the admin audit history."
        )
        edit_date = st.date_input(
            "Attendance Date",
            value=today,
            min_value=date(2020, 1, 1),
            max_value=date(2100, 12, 31),
            key="employee_attendance_edit_date",
        )

        with SessionFactory() as session:
            edit_service = AttendanceService(session)
            edit_record = edit_service.get_daily(
                company_id=current_user.company_id,
                employee_id=current_user.employee_id,
                attendance_date=edit_date,
            )
            existing_sessions = list(edit_record.sessions) if edit_record else []
            local_sessions = [
                {
                    "status": item.work_status,
                    "time_in": edit_service.to_local(item.actual_time_in),
                    "time_out": edit_service.to_local(item.actual_time_out),
                }
                for item in existing_sessions
            ]

        edit_record_marker = (
            f"{edit_date}_{edit_record.id}_{edit_record.updated_at}_"
            f"{edit_record.time_in}_{edit_record.time_out}_"
            f"{edit_record.work_status}_{len(local_sessions)}"
            if edit_record is not None
            else f"{edit_date}_new"
        )
        st.markdown("**Work Status Only**")
        st.caption(
            "Correct the selected date's Work Status without changing Time In, "
            "Time Out, work sessions, or completion state."
        )
        status_only_columns = st.columns([2, 1])
        with status_only_columns[0]:
            status_only_value = st.selectbox(
                "Work Status",
                STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(
                    edit_record.work_status
                    if edit_record is not None
                    and edit_record.work_status in STATUS_OPTIONS
                    else "WFO"
                ),
                key=f"attendance_status_only_{edit_record_marker}",
            )
        with status_only_columns[1]:
            st.write("")
            st.write("")
            save_status_only = st.button(
                "Save Work Status Only",
                width="stretch",
                key=f"save_attendance_status_only_{edit_record_marker}",
            )
        st.divider()
        leave_note = ""
        if edit_record is not None and edit_record.leave_duration_code:
            leave_note = (
                f"Approved leave: {edit_record.leave_duration_code} · "
                f"{edit_record.leave_hours} paid leave hour(s). "
            )
        st.caption(
            leave_note
            + "Add WFO/WFH sessions for actual work. Mixed locations become "
            "Hybrid automatically. Times use 15-minute increments; payroll "
            "keeps the rounded value while audit history keeps the actual punch."
        )
        default_session_count = len(local_sessions)
        if edit_record is None:
            default_session_count = 1
        session_count = int(
            st.number_input(
                "Work Sessions",
                min_value=0,
                max_value=8,
                value=default_session_count,
                step=1,
                key=f"attendance_edit_session_count_{edit_record_marker}",
            )
        )
        edited_session_values: list[dict[str, object]] = []
        for index in range(session_count):
            existing = local_sessions[index] if index < len(local_sessions) else None
            st.markdown(f"**Session {index + 1}**")
            session_columns = st.columns([1, 1, 1, .6])
            with session_columns[0]:
                session_status = st.selectbox(
                    "Location",
                    WORK_LOCATION_OPTIONS,
                    index=WORK_LOCATION_OPTIONS.index(
                        existing["status"] if existing else "WFO"
                    ),
                    key=f"attendance_edit_session_status_{edit_record_marker}_{index}",
                )
            with session_columns[1]:
                # Legacy or incomplete sessions may not yet have a usable
                # timestamp. Keep the editor renderable without turning the
                # fallback clock value into a saved punch automatically.
                default_in = (
                    existing["time_in"]
                    if existing and existing["time_in"] is not None
                    else local_now
                )
                session_time_in = st.time_input(
                    "Time In",
                    value=attendance_editor_clock(default_in, fallback=local_now),
                    step=900,
                    key=f"attendance_edit_session_in_{edit_record_marker}_{index}",
                )
            with session_columns[2]:
                # An active session correctly has no Time Out yet. Display a
                # safe local-time fallback while ``Completed`` remains false,
                # so the missing punch stays None unless the employee elects
                # to complete the session.
                default_out = (
                    existing["time_out"]
                    if existing and existing["time_out"] is not None
                    else local_now
                )
                session_time_out = st.time_input(
                    "Time Out",
                    value=attendance_editor_clock(default_out, fallback=local_now),
                    step=900,
                    key=f"attendance_edit_session_out_{edit_record_marker}_{index}",
                )
            with session_columns[3]:
                has_session_out = st.checkbox(
                    "Completed",
                    value=bool(existing and existing["time_out"]),
                    key=f"attendance_edit_session_complete_{edit_record_marker}_{index}",
                )
            edited_session_values.append(
                {
                    "work_status": session_status,
                    "time_in": session_time_in,
                    "time_out": session_time_out if has_session_out else None,
                }
            )

        save_time_changes = st.button(
            "Save Attendance Changes",
            width="stretch",
            key="save_employee_attendance_changes",
        )

    if save_status_only:
        try:
            request = AttendanceStatusInput(
                company_id=current_user.company_id,
                employee_id=current_user.employee_id,
                user_id=current_user.user_id,
                attendance_date=edit_date,
                work_status=status_only_value,
            )
            with SessionFactory() as session:
                AttendanceService(session).edit_own_work_status(request)
            set_operation_feedback(
                f"Work Status for {edit_date:%Y/%m/%d} was updated without changing attendance times.",
                namespace="attendance",
            )
            st.session_state[_EDITOR_SCROLL_STATE_KEY] = True
            st.rerun()
        except (ValidationError, ValueError) as error:
            render_action_warning(error)
        except Exception:
            st.error("The Work Status could not be saved.")

    if save_time_changes:
        try:
            sessions = [
                AttendanceSessionInput(
                    work_status=str(item["work_status"]),
                    time_in=datetime.combine(
                        edit_date,
                        item["time_in"],
                        tzinfo=local_timezone,
                    ),
                    time_out=(
                        datetime.combine(
                            edit_date,
                            item["time_out"],
                            tzinfo=local_timezone,
                        )
                        if item["time_out"] is not None
                        else None
                    ),
                )
                for item in edited_session_values
            ]
            request = AttendanceSelfEditInput(
                company_id=current_user.company_id,
                employee_id=current_user.employee_id,
                user_id=current_user.user_id,
                attendance_date=edit_date,
                work_status=(
                    edit_record.work_status
                    if edit_record is not None and edit_record.work_status in STATUS_OPTIONS
                    else "WFO"
                ),
                sessions=sessions,
            )
            with SessionFactory() as session:
                updated = AttendanceService(session).edit_own_daily_attendance(
                    request
                )
            message = f"Attendance for {edit_date:%Y/%m/%d} was updated."
            set_operation_feedback(message, namespace="attendance")
            st.session_state[_EDITOR_SCROLL_STATE_KEY] = True
            st.rerun()
        except (ValidationError, ValueError) as error:
            render_action_warning(error)
        except Exception:
            st.error("The attendance changes could not be saved.")

    _render_overtime_request(
        current_user,
        today=today,
        local_timezone=local_timezone,
    )
