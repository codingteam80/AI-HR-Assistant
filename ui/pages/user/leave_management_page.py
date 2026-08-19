"""Employee requests, manager approvals, and leave-credit status."""

from datetime import date
from decimal import Decimal

from pydantic import ValidationError
import json
import streamlit as st
from ui.components.validation_feedback import render_action_warning

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from core.leave_codes import (
    LEAVE_DURATION_OPTIONS,
    LEAVE_REASON_OPTIONS,
    duration_label,
    reason_label,
)
from database.session import SessionFactory
from schemas.leave_schema import (
    LeaveCancellationDecisionInput,
    LeaveCancellationRequestInput,
    LeaveDecisionInput,
    LeaveRequestInput,
)
from services.leave_service import LeaveService
from ui.components.browser_bridge import render_browser_bridge
from ui.components.data_table import render_admin_table
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)


_LEAVE_FORM_NONCE_KEY = "_employee_leave_form_nonce"
_APPROVAL_STATUSES = {
    "scheduled",
    "approved",
    "in_progress",
    "completed",
}


def _days(value) -> str:
    """Format leave days without unnecessary decimal zeros."""

    return (
        f"{Decimal(value):.2f}"
        .rstrip("0")
        .rstrip(".")
    )


def _status(value: str) -> str:
    """Convert a stored workflow status into a readable label."""

    labels = {
        "pending_leader_approval": "Pending Leader Approval",
        "pending_manager_approval": "Pending Manager Approval",
        "scheduled": "Approved / Scheduled",
        "approved": "Approved",
        "in_progress": "In Progress",
        "completed": "Completed",
        "rejected": "Rejected",
        "cancelled": "Cancelled",
        "partially_cancelled": "Partially Cancelled",
    }
    return labels.get(
        value,
        value.replace("_", " ").title(),
    )


def _request_duration(request) -> str:
    return duration_label(str(getattr(request, "duration_code", "") or "90503"))


def _request_reason(request) -> str:
    code = str(getattr(request, "reason_code", "") or "0")
    standard = reason_label(code)
    other = getattr(request, "reason_other", None)
    return f"{standard} · {other}" if code == "0" and other else standard


def _employee_role(employee) -> str:
    return str(getattr(employee, "job_title", "") or "Employee")


def _nonce() -> int:
    """Return the current request-form nonce."""

    value = int(
        st.session_state.get(
            _LEAVE_FORM_NONCE_KEY,
            0,
        )
    )
    st.session_state[_LEAVE_FORM_NONCE_KEY] = value
    return value


def _key(nonce: int, name: str) -> str:
    """Create one resettable request-form widget key."""

    return f"employee_leave_{nonce}_{name}"


def _render_balances(
    current_user: AuthenticatedUser,
) -> None:
    """Show credits after approved reservations and elapsed leave posting."""

    if current_user.employee_id is None:
        st.warning(
            "Your login account is not linked to an employee record."
        )
        return

    with SessionFactory() as session:
        service = LeaveService(session)
        current_leave_year = service.leave_cycle_year(current_user.company_id)
        company = service._company(current_user.company_id)
        reset_label = date(
            2024,
            int(company.leave_reset_month),
            min(int(company.leave_reset_day), 28),
        ).strftime("%B") + f" {int(company.leave_reset_day)}"
        service.reconcile_approved_leave(
            company_id=current_user.company_id
        )
        balances = service.list_employee_balances(
            current_user.company_id,
            current_user.employee_id,
        )
        table_rows = service.credit_table_rows(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
            year=current_leave_year,
            balances=balances,
        )
        employee = service.employee_repository.get_with_details(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
        )
        summary = (
            service.entitlement_summary(
                employee=employee,
                year=current_leave_year,
            )
            if employee is not None
            else None
        )

    if not balances:
        st.info("No leave credits are configured.")
        return

    columns = st.columns(
        min(4, len(table_rows))
    )

    for column, row in zip(
        columns,
        table_rows[:4],
    ):
        with column:
            st.metric(
                row.leave_type.name,
                _days(row.available_credits),
                delta=(
                    f"{_days(row.reserved_days)} reserved"
                    if Decimal(row.reserved_days) > 0
                    else None
                ),
            )

    if summary is not None:
        st.info(
            f"Completed Service: {summary['service_years']} year(s) · "
            f"{summary['basis']}\n\n"
            f"{reset_label} Annual Accrual: Vacation "
            f"{_days(summary['regular_vacation'])} days · "
            f"Sick Leave {_days(summary['sick'])} days. "
            "Unused SL/VL becomes Beginning Credit in the next leave year. "
            "SL retains up to 15 days and VL retains up to 45 days after "
            "annual-reset cash conversion. Emergency Leave is limited to 3 days "
            "per year and is deducted from Vacation Leave. Event-based "
            "credits are granted only after manager approval: Honeymoon 5 "
            "days once, Maternity 105, Paternity 7, and Bereavement 7 days "
            "per qualifying event. Vacation Leave utilization is a yearly "
            "monitoring target; it does not reduce Available Credits in "
            "advance. Only an unmet target is forfeited at year end."
        )

    render_admin_table(
        [
            {
                "Leave Type": balance.leave_type.name,
                "Beginning Credit": (
                    _days(balance.beginning_credit_days)
                    if balance.is_applicable
                    else "N/A"
                ),
                # Credit is only the current annual/event allocation. Manual
                # corrections affect Available Credits and audit history.
                "Credit": (
                    _days(balance.credit_days)
                    if balance.is_applicable
                    else "N/A"
                ),
                "Used": (
                    _days(balance.used_days)
                    if balance.is_applicable
                    else "N/A"
                ),
                "Available Credits": (
                    _days(balance.available_credits)
                    if balance.is_applicable
                    else "N/A"
                ),
                "Leave Utilization": (
                    balance.leave_utilization.display_text
                    if balance.leave_utilization is not None
                    else "N/A"
                ),
                "Converted to Cash": (
                    "N/A"
                    if not balance.is_applicable
                    else (
                        _days(balance.converted_to_cash_days)
                        if LeaveService.supports_cash_conversion(
                            balance.leave_type
                        )
                        else "—"
                    )
                ),
                "Last Updated": (
                    (
                        balance.updated_at.strftime(
                            "%Y-%m-%d %I:%M %p"
                        )
                        if balance.updated_at is not None
                        else "—"
                    )
                    if balance.is_applicable
                    else "N/A"
                ),
            }
            for balance in table_rows
        ],
        key="employee-leave-balances",
        min_width=1350,
        column_widths=(
            "200px",
            "135px",
            "110px",
            "85px",
            "145px",
            "190px",
            "155px",
            "185px",
        ),
        max_height=330,
    )

    st.caption(
        "Beginning Credit is the carried balance before the current annual "
        "accrual. Credit shows only the annual or approved event allocation "
        "for the selected year. Administrator corrections affect Available "
        "Credits and remain in audit history. Available Credits is the usable balance after usage, "
        "reservations, and cash conversion. Gender-inapplicable Maternity or "
        "Paternity rows display N/A. Only Vacation and Sick Leave may be "
        "converted to cash."
    )


def _load_request_context(
    current_user: AuthenticatedUser,
    *,
    employee_id: int | None = None,
):
    """Load detached balances, hierarchy, and searchable recipients."""

    target_employee_id = employee_id or current_user.employee_id
    with SessionFactory() as session:
        service = LeaveService(session)
        current_leave_year = service.leave_cycle_year(current_user.company_id)
        balances = service.list_employee_balances(
            current_user.company_id,
            target_employee_id,
        )
        employee = service.employee_repository.get_with_details(
            company_id=current_user.company_id,
            employee_id=target_employee_id,
        )
        table_rows = service.credit_table_rows(
            company_id=current_user.company_id,
            employee_id=target_employee_id,
            year=current_leave_year,
            balances=balances,
        )
        event_preview_credits = {
            row.leave_type.id: service.event_leave_preview_entitlement(
                company_id=current_user.company_id,
                employee_id=target_employee_id,
                leave_type=row.leave_type,
            )
            for row in table_rows
        }
        recipients = service.list_searchable_recipients(
            current_user.company_id
        )
        recipient_options = [
            {
                "id": user.id,
                "label": service.recipient_display_name(user),
                "email": user.email,
                "employee_id": (
                    user.employee.id
                    if user.employee is not None
                    else None
                ),
            }
            for user in recipients
        ]

    return (
        balances,
        employee,
        recipient_options,
        table_rows,
        event_preview_credits,
    )


def _render_submit(
    current_user: AuthenticatedUser,
    *,
    target_employee_id: int | None = None,
    on_behalf: bool = False,
) -> None:
    """Render a searchable email-style self or team leave composer."""

    if current_user.employee_id is None:
        st.warning("Your login account is not linked to an employee record.")
        return

    owner_employee_id = target_employee_id or current_user.employee_id
    settings = get_settings()
    nonce = _nonce()
    (
        balances,
        employee,
        recipient_options,
        table_rows,
        event_preview_credits,
    ) = _load_request_context(
        current_user,
        employee_id=owner_employee_id,
    )

    if employee is None:
        st.error("The selected employee record is unavailable.")
        return
    if on_behalf and current_user.employee_id not in {
        employee.leader_id,
        employee.manager_id,
    }:
        st.error("You may file only for a direct Leader or Manager report.")
        return

    manager = employee.manager
    leader = employee.leader
    manager_email = LeaveService._email_for_employee(manager)
    leader_email = LeaveService._email_for_employee(leader)
    if manager is None or not manager_email or manager.user_id is None:
        st.error(
            "A manager with an active account and work email must be assigned "
            "before leave can be filed."
        )
        return

    # Approval always follows the leave owner's hierarchy. Filing on behalf
    # creates the request only and never skips or auto-completes approval.
    current_approver = manager
    approval_stage = "Manager"
    if (
        leader is not None
        and leader.user_id is not None
        and leader_email
        and (leader.user is None or leader.user.is_active)
    ):
        current_approver = leader
        approval_stage = "Leader"

    recipient_by_id = {
        int(item["id"]): item
        for item in recipient_options
    }
    recipient_ids = list(recipient_by_id)
    if not recipient_ids:
        st.error("No active company user has a registered email address.")
        return

    default_to_user_id = current_approver.user_id
    if default_to_user_id not in recipient_by_id:
        st.error("The current approver is missing an active email account.")
        return

    employee_email = LeaveService._email_for_employee(employee)
    default_cc: list[int] = []
    if employee.user_id in recipient_by_id and employee.user_id != default_to_user_id:
        default_cc.append(employee.user_id)
    if (
        on_behalf
        and current_user.user_id in recipient_by_id
        and current_user.user_id != default_to_user_id
        and current_user.user_id not in default_cc
    ):
        default_cc.append(current_user.user_id)

    st.markdown(
        "### File Leave for Team Member"
        if on_behalf
        else "### File Leave Request"
    )
    if on_behalf:
        st.info(
            f"Leave Owner: {employee.employee_number} · {employee.full_name}\n\n"
            "Filed By: You, as the assigned Leader or Manager\n\n"
            "Any approved leave is deducted from the Leave Owner's credits, "
            "never from the filer’s credits. Filing does not count as approval."
        )
    st.caption(
        f"Approval route: {approval_stage}"
        + (" → Manager" if approval_stage == "Leader" else "")
        + ". Type a person's name in To or CC to search registered company emails."
    )

    # Searchable field labels remain "To" and "CC".
    recipient_left, recipient_right = st.columns(2)
    with recipient_left:
        to_user_id = st.selectbox(
            "To *",
            options=recipient_ids,
            index=recipient_ids.index(default_to_user_id),
            format_func=lambda value: recipient_by_id[value]["label"],
            help=(
                "Search by typing a name. The hierarchy approver still receives "
                "the approval task even when another email recipient is selected."
            ),
            key=_key(nonce, f"to_{owner_employee_id}_{int(on_behalf)}"),
        )
    with recipient_right:
        cc_user_ids = st.multiselect(
            "CC",
            options=recipient_ids,
            default=default_cc,
            format_func=lambda value: recipient_by_id[value]["label"],
            help="Type a name to add or remove copied recipients.",
            key=_key(nonce, f"cc_{owner_employee_id}_{int(on_behalf)}"),
        )

    type_options = {
        balance.leave_type_id: balance
        for balance in balances
        if balance.leave_type.is_active
        and LeaveService.is_event_leave_gender_eligible(
            employee=employee,
            leave_type_or_code=balance.leave_type,
        )
    }
    display_row_by_type = {row.leave_type.id: row for row in table_rows}
    if not type_options:
        st.info("No eligible leave type is available.")
        return

    def _format_leave_type_option(value: int) -> str:
        displayed_available = (
            display_row_by_type[value].available_credits
            if value in display_row_by_type
            else type_options[value].remaining_days
        )
        selected_leave_type = type_options[value].leave_type
        event_credit = Decimal(
            event_preview_credits.get(value, Decimal("0.00"))
        )
        selected_code = (selected_leave_type.code or "").strip().upper()
        if event_credit > Decimal("0.00"):
            suffix = (
                "one-time grant after approval"
                if selected_code == "HONEYMOON"
                else "per approved event"
            )
            return f"{selected_leave_type.name} · {_days(event_credit)} {suffix}"
        if selected_code == "HONEYMOON":
            return f"{selected_leave_type.name} · one-time benefit already requested/used"
        return f"{selected_leave_type.name} · {_days(displayed_available)} available"

    leave_type_id = st.selectbox(
        "Leave Type *",
        options=list(type_options),
        format_func=_format_leave_type_option,
        key=_key(nonce, f"type_{owner_employee_id}_{int(on_behalf)}"),
    )
    selected_balance = type_options[leave_type_id]
    selected_type = selected_balance.leave_type
    selected_display_row = display_row_by_type.get(leave_type_id)
    selected_available = Decimal(
        selected_display_row.available_credits
        if selected_display_row is not None
        else selected_balance.remaining_days
    )
    selected_event_credit = Decimal(
        event_preview_credits.get(leave_type_id, Decimal("0.00"))
    )

    available_column, rule_column = st.columns(2)
    with available_column:
        st.metric("Leave Owner Available Credits", _days(selected_available))
    with rule_column:
        st.metric(
            "Handover Plan",
            (selected_type.handover_plan_requirement or "optional").title(),
        )

    date_left, date_right = st.columns(2)
    with date_left:
        start = st.date_input(
            "Start Date *",
            value=date.today(),
            key=_key(nonce, f"start_{owner_employee_id}_{int(on_behalf)}"),
        )
    with date_right:
        end = st.date_input(
            "End Date *",
            value=date.today(),
            key=_key(nonce, f"end_{owner_employee_id}_{int(on_behalf)}"),
        )

    duration_code = st.selectbox(
        "Duration *",
        options=list(LEAVE_DURATION_OPTIONS),
        index=list(LEAVE_DURATION_OPTIONS).index("90503"),
        format_func=duration_label,
        help=(
            "AM Only and PM Only use 0.50 leave credit and are allowed for "
            "one date only. Whole Day uses the regular full-day credit."
        ),
        key=_key(nonce, f"duration_{owner_employee_id}_{int(on_behalf)}"),
    )

    with SessionFactory() as session:
        calendar_working_days = LeaveService(session).company_working_days(
            company_id=current_user.company_id,
            start_date=start,
            end_date=end,
        )
    working_days = (
        Decimal("0.50")
        if duration_code in {"90501", "90502"}
        and calendar_working_days > Decimal("0.00")
        else calendar_working_days
    )
    selected_code = (selected_type.code or "").strip().upper()
    primary_days = Decimal("0.00")
    fallback_days = Decimal("0.00")
    if selected_code == "EMERGENCY":
        vacation_balance = next(
            (
                item for item in balances
                if item.leave_type.code.upper() == "VACATION"
            ),
            None,
        )
        vacation_available = (
            max(Decimal("0.00"), Decimal(vacation_balance.remaining_days))
            if vacation_balance is not None
            else Decimal("0.00")
        )
        fallback_days = min(
            working_days,
            max(Decimal("0.00"), selected_available),
            vacation_available,
        )
        remaining_days = max(Decimal("0.00"), working_days - fallback_days)
    else:
        primary_available = max(
            Decimal("0.00"),
            selected_available + selected_event_credit,
        )
        event_limit = selected_event_credit
        primary_days = (
            min(working_days, primary_available, event_limit)
            if event_limit > Decimal("0.00")
            else min(working_days, primary_available)
        )
        remaining_days = max(Decimal("0.00"), working_days - primary_days)

    split_parts = []
    if selected_code == "EMERGENCY" and fallback_days > 0:
        split_parts.append(
            f"{_days(fallback_days)} Emergency Leave (deducted from Vacation Leave)"
        )
    elif primary_days > 0:
        split_parts.append(f"{_days(primary_days)} {selected_type.name}")
    if remaining_days > 0:
        split_parts.append(f"{_days(remaining_days)} LWOP")

    if selected_code == "EMERGENCY":
        st.caption(
            "Emergency Leave has a maximum three-day annual allowance. "
            "Approved days are deducted from the Leave Owner's Vacation Leave."
        )

    st.info(
        f"Countable Regular Workdays: {_days(working_days)} · based on the "
        "saved Attendance Schedule & OT Rules calendar; holidays and other "
        "unselected dates are excluded.\n\n"
        f"Estimated Credit / LWOP Split: "
        f"{' + '.join(split_parts) if split_parts else 'No working days'}"
    )

    if remaining_days > Decimal("0.00"):
        if primary_days + fallback_days <= Decimal("0.00"):
            st.warning(
                f"The Leave Owner has no available {selected_type.name} "
                "credits. All countable Regular Workdays in this request "
                "will be filed as Leave Without Pay (LWP). The request will "
                "still follow the normal approval process."
            )
        else:
            st.warning(
                f"Available {selected_type.name} credits do not cover the "
                f"complete request. {_days(remaining_days)} day(s) will be "
                "filed as Leave Without Pay (LWP)."
            )

    reason_columns = st.columns(2)
    with reason_columns[0]:
        reason_code = st.selectbox(
            "Reason *",
            options=list(LEAVE_REASON_OPTIONS),
            format_func=reason_label,
            key=_key(nonce, f"reason_code_{owner_employee_id}_{int(on_behalf)}"),
        )
    with reason_columns[1]:
        reason_other = st.text_area(
            "Reason for Leave: Others" + (" *" if reason_code == "0" else ""),
            height=130,
            max_chars=4000,
            disabled=reason_code != "0",
            help="Required only when 0 - OTHERS is selected.",
            key=_key(nonce, f"reason_other_{owner_employee_id}_{int(on_behalf)}"),
        )
    plan_requirement = (
        selected_type.handover_plan_requirement or "optional"
    ).lower()
    handover_plan = st.text_area(
        "Work Handover Plan / Countermeasure"
        + (" *" if plan_requirement == "required" else " (Optional)"),
        height=170,
        max_chars=10000,
        key=_key(nonce, f"plan_{owner_employee_id}_{int(on_behalf)}"),
    )
    plan_file = st.file_uploader(
        "Optional Handover Plan File",
        type=["pdf", "docx", "xlsx", "csv", "txt"],
        help=f"Maximum {settings.leave_attachment_max_mb} MB.",
        key=_key(nonce, f"plan_file_{owner_employee_id}_{int(on_behalf)}"),
    )

    submitted = st.button(
        "Submit Leave for Team Member"
        if on_behalf
        else "Send Leave Request",
        type="primary",
        width="stretch",
        key=_key(nonce, f"send_{owner_employee_id}_{int(on_behalf)}"),
    )
    if not submitted:
        return

    try:
        values = LeaveRequestInput(
            company_id=current_user.company_id,
            employee_id=owner_employee_id,
            requested_by_user_id=current_user.user_id,
            filed_by_employee_id=current_user.employee_id,
            to_user_id=to_user_id,
            cc_user_ids=cc_user_ids,
            leave_type_id=leave_type_id,
            start_date=start,
            end_date=end,
            duration_code=duration_code,
            reason_code=reason_code,
            reason_other=reason_other,
            handover_plan=handover_plan,
        )
        with st.spinner("Recording the request and sending notifications…"):
            with SessionFactory() as session:
                result = LeaveService(session).submit_leave_request(
                    values,
                    plan_filename=plan_file.name if plan_file else None,
                    plan_bytes=plan_file.getvalue() if plan_file else None,
                    plan_mime_type=plan_file.type if plan_file else None,
                )
        st.session_state[_LEAVE_FORM_NONCE_KEY] = nonce + 1
        set_operation_feedback(
            result.message,
            namespace="leave_employee",
            level="success" if result.email_sent else "warning",
        )
        st.rerun()
    except (ValidationError, ValueError) as error:
        render_action_warning(error)
    except Exception:
        st.error("The leave request could not be processed.")


def _render_team_member_submit(current_user: AuthenticatedUser) -> None:
    """Let a Leader or Manager file leave for an employed direct report."""
    if current_user.employee_id is None:
        return
    with SessionFactory() as session:
        members = LeaveService(session).list_proxy_leave_members(
            company_id=current_user.company_id,
            filer_employee_id=current_user.employee_id,
        )
    if not members:
        st.info("No employed direct Leader or Manager report is assigned to you.")
        return
    member_by_id = {member.id: member for member in members}
    selected_member_id = st.selectbox(
        "Search Team Member *",
        options=list(member_by_id),
        format_func=lambda value: (
            f"{member_by_id[value].employee_number} · "
            f"{member_by_id[value].full_name}"
        ),
        help="Type the employee name or number to search direct members.",
        key="leader_proxy_leave_member",
    )
    _render_submit(
        current_user,
        target_employee_id=selected_member_id,
        on_behalf=True,
    )


def _render_team_filed_requests(current_user: AuthenticatedUser) -> None:
    """Show proxy requests filed by the signed-in leader."""
    if current_user.employee_id is None:
        return
    with SessionFactory() as session:
        requests = LeaveService(session).list_requests_filed_for_team(
            company_id=current_user.company_id,
            leader_employee_id=current_user.employee_id,
        )
    if not requests:
        st.info("You have not filed a leave request for a team member.")
        return
    render_admin_table(
        [
            {
                "Request ID": request.public_id,
                "Leave Owner": request.employee.full_name,
                "Leave Type": request.leave_type.name,
                "Filed By": (
                    request.filed_by_employee.full_name
                    if request.filed_by_employee is not None
                    else request.employee.full_name
                ),
                "Filer Role": _employee_role(
                    request.filed_by_employee or request.employee
                ),
                "Dates": f"{request.start_date.isoformat()} to {request.end_date.isoformat()}",
                "Duration": _request_duration(request),
                "Days": _days(request.requested_days),
                "Current Approver": (
                    request.current_approver.full_name
                    if request.current_approver is not None
                    else "Completed"
                ),
                "Status": _status(request.status),
            }
            for request in requests
        ],
        key="leader-filed-team-leave-requests",
        min_width=1100,
        max_height=330,
    )


def _request_rows(requests):
    """Build employee request-history rows."""

    return [
        {
            "Request ID": request.public_id,
            "Leave Type": request.leave_type.name,
            "Filed By": (
                request.filed_by_employee.full_name
                if request.filed_by_employee is not None
                else request.employee.full_name
            ),
            "Filer Role": _employee_role(
                request.filed_by_employee or request.employee
            ),
            "Leave Dates": (
                f"{request.start_date.isoformat()} to "
                f"{request.end_date.isoformat()}"
            ),
            "Days": _days(request.requested_days),
            "Duration": _request_duration(request),
            "Credit / LWOP Split": LeaveService.allocation_breakdown(request),
            "Manager": (
                request.manager.full_name
                if request.manager
                else "—"
            ),
            "Status": _status(request.status),
            "Cancellation": LeaveService.cancellation_label(request),
            "Plan": (
                "Text + File"
                if request.handover_plan
                and request.attachment_storage_path
                else "Text"
                if request.handover_plan
                else "File"
                if request.attachment_storage_path
                else "None"
            ),
            "Reason": _request_reason(request),
        }
        for request in requests
    ]


def _render_requests(
    current_user: AuthenticatedUser,
    selected_request_id: int | None = None,
) -> None:
    """Render the employee's complete request history."""

    if current_user.employee_id is None:
        st.warning(
            "Your login account is not linked to an employee record."
        )
        return

    with SessionFactory() as session:
        service = LeaveService(session)
        service.reconcile_approved_leave(
            company_id=current_user.company_id
        )
        requests = service.list_employee_requests(
            current_user.company_id,
            current_user.employee_id,
        )

    if not requests:
        st.info(
            "You have not submitted a leave request yet."
        )
        return

    render_admin_table(
        _request_rows(requests),
        key="employee-leave-requests",
        min_width=2235,
        column_widths=(
            "125px",  # Request ID
            "160px",  # Leave Type
            "200px",  # Filed By
            "120px",  # Filer Role
            "190px",  # Leave Dates
            "90px",   # Days
            "170px",  # Duration
            "300px",  # Credit / LWOP Split
            "180px",  # Manager
            "130px",  # Status
            "170px",  # Cancellation
            "100px",  # Plan
            "300px",  # Reason
        ),
    )

    options = {
        request.id: (
            f"{request.public_id} · "
            f"{request.leave_type.name} · "
            f"{_status(request.status)}"
        )
        for request in requests
    }
    option_ids = list(options)
    if selected_request_id is not None:
        if selected_request_id not in options:
            st.error(
                "The selected leave request is not available in your "
                "request history."
            )
            return

        st.session_state["employee_request_detail"] = selected_request_id
        st.info(
            "Opened from Notifications. The related request is selected "
            "below inside the My Requests tab."
        )

    elif st.session_state.get("employee_request_detail") not in options:
        st.session_state["employee_request_detail"] = option_ids[0]

    selected_id = st.selectbox(
        "View My Request Details",
        options=option_ids,
        format_func=lambda value: options[value],
        key="employee_request_detail",
    )

    with SessionFactory() as session:
        service = LeaveService(session)
        request = service.get_request(
            current_user.company_id,
            selected_id,
        )
        plan_bytes = None

        if request and request.attachment_storage_path:
            try:
                plan_bytes = service.read_plan_file(
                    request
                )
            except FileNotFoundError:
                plan_bytes = None

    if request is None:
        return

    if Decimal(request.lwop_days or Decimal("0.00")) > Decimal("0.00"):
        paid_days = (
            Decimal(request.primary_credit_days or Decimal("0.00"))
            + Decimal(request.fallback_credit_days or Decimal("0.00"))
        )
        st.warning(
            (
                f"No available {request.leave_type.name} credits were found. "
                f"All {_days(request.lwop_days)} countable day(s) are Leave "
                "Without Pay (LWP)."
            )
            if paid_days <= Decimal("0.00")
            else (
                f"Available credits do not cover the full request. "
                f"{_days(request.lwop_days)} day(s) are Leave Without Pay (LWP)."
            )
        )

    details = [
        {
            "Field": "Status",
            "Value": _status(request.status),
        },
        {
            "Field": "Cancellation",
            "Value": LeaveService.cancellation_label(request),
        },
        {
            "Field": "Cancellation Reason",
            "Value": request.cancellation_reason or "—",
        },
        {
            "Field": "Cancellation Effective Date",
            "Value": (
                request.cancellation_effective_date.isoformat()
                if request.cancellation_effective_date is not None
                else "—"
            ),
        },
        {
            "Field": "Cancellation Decision Comment",
            "Value": request.cancellation_comment or "—",
        },
        {
            "Field": "Duration",
            "Value": _request_duration(request),
        },
        {
            "Field": "Reason for Leave",
            "Value": reason_label(str(request.reason_code or "0")),
        },
        {
            "Field": "Reason for Leave: Others",
            "Value": request.reason_other or "—",
        },
        {
            "Field": "Work Handover Plan / Countermeasure",
            "Value": request.handover_plan or "Not provided",
        },
        {
            "Field": "Credit / LWOP Split",
            "Value": LeaveService.allocation_breakdown(request),
        },
        {
            "Field": "Manager Comment",
            "Value": request.manager_comment or "—",
        },
        {
            "Field": "Posted as Used",
            "Value": (
                f"{_days(request.posted_working_days)} "
                f"of {_days(request.requested_days)} day(s)"
            ),
        },
    ]

    render_admin_table(
        details,
        key=f"employee-request-detail-{request.id}",
        min_width=850,
        column_widths=(
            "240px",
            "610px",
        ),
        compact=True,
    )

    if plan_bytes is not None:
        st.download_button(
            "Download My Handover Plan File",
            data=plan_bytes,
            file_name=(
                request.attachment_original_filename
                or "handover_plan"
            ),
            mime=(
                request.attachment_mime_type
                or "application/octet-stream"
            ),
            width="stretch",
            key=f"employee_plan_download_{request.id}",
        )

    _render_cancel_leave_action(current_user, request)


def _render_cancel_leave_action(
    current_user: AuthenticatedUser,
    request,
) -> None:
    """Offer immediate pending cancellation or approved-leave cancellation."""

    if request.cancellation_status == "requested":
        st.warning(
            "A cancellation request is waiting for the assigned Manager or HR Admin. "
            "The approved leave remains active until cancellation is approved."
        )
        return
    if request.status in {"rejected", "cancelled", "partially_cancelled", "completed"}:
        if request.status == "completed":
            st.caption(
                "Completed leave requires an HR credit correction and cannot be cancelled here."
            )
        return

    pending = request.status in {"pending_leader_approval", "pending_manager_approval"}
    st.markdown("### Cancel Leave")
    st.caption(
        "This pending request will be cancelled immediately with no credit deduction."
        if pending
        else (
            "This sends a cancellation request to the Manager or HR Admin. "
            "Future unused paid days are restored only after approval."
        )
    )
    with st.form(f"cancel-leave-{request.id}"):
        reason = st.text_area(
            "Cancellation Reason",
            max_chars=2000,
            height=90,
            key=f"cancel_reason_{request.id}",
        )
        submitted = st.form_submit_button(
            "Cancel Request Now" if pending else "Request Leave Cancellation",
            type="primary",
            width="stretch",
        )
    if not submitted:
        return
    try:
        values = LeaveCancellationRequestInput(
            company_id=current_user.company_id,
            request_id=request.id,
            requested_by_user_id=current_user.user_id,
            requested_by_employee_id=current_user.employee_id,
            reason=reason,
        )
        with st.spinner("Processing leave cancellation…"):
            with SessionFactory() as session:
                updated = LeaveService(session).request_leave_cancellation(values)
        message = (
            f"{updated.public_id} was cancelled before approval."
            if updated.cancellation_status == "cancelled"
            else f"Cancellation of {updated.public_id} was sent for approval."
        )
        set_operation_feedback(message, namespace="leave_employee")
        st.rerun()
    except (ValidationError, ValueError) as error:
        render_action_warning(error)


def _approval_rows(requests):
    """Build current leader/manager approval rows."""
    return [
        {
            "Request ID": request.public_id,
            "Leave Owner": (
                f"{request.employee.employee_number} · {request.employee.full_name}"
            ),
            "Filed By": (
                request.filed_by_employee.full_name
                if request.filed_by_employee is not None
                else request.employee.full_name
            ),
            "Filer Role": _employee_role(
                request.filed_by_employee or request.employee
            ),
            "Approval Stage": (
                "Cancellation"
                if request.cancellation_status == "requested"
                else request.approval_stage.title()
            ),
            "Leave Type": request.leave_type.name,
            "Leave Dates": (
                f"{request.start_date.isoformat()} to {request.end_date.isoformat()}"
            ),
            "Days": _days(request.requested_days),
            "Duration": _request_duration(request),
            "Credit / LWOP Split": LeaveService.allocation_breakdown(request),
            "Status": (
                "Cancellation Requested"
                if request.cancellation_status == "requested"
                else _status(request.status)
            ),
        }
        for request in requests
    ]


def _render_manager_request_detail(
    current_user: AuthenticatedUser,
    request_id: int,
) -> None:
    """Render one pending request and manager decision controls."""

    with SessionFactory() as session:
        service = LeaveService(session)
        request = service.get_request(
            current_user.company_id,
            request_id,
        )
        plan_bytes = None

        if request and request.attachment_storage_path:
            try:
                plan_bytes = service.read_plan_file(
                    request
                )
            except FileNotFoundError:
                plan_bytes = None

    if request is None:
        st.error(
            "The selected leave request is unavailable."
        )
        return

    if Decimal(request.lwop_days or Decimal("0.00")) > Decimal("0.00"):
        paid_days = (
            Decimal(request.primary_credit_days or Decimal("0.00"))
            + Decimal(request.fallback_credit_days or Decimal("0.00"))
        )
        st.warning(
            (
                f"This employee has no available {request.leave_type.name} "
                f"credits. All {_days(request.lwop_days)} countable day(s) "
                "will be Leave Without Pay (LWP) if approved."
            )
            if paid_days <= Decimal("0.00")
            else (
                f"Available credits are insufficient. {_days(request.lwop_days)} "
                "day(s) will be Leave Without Pay (LWP) if approved."
            )
        )

    st.markdown("### Request for Approval")

    is_cancellation_review = request.cancellation_status == "requested"
    stage_label = (
        "Cancellation"
        if is_cancellation_review
        else request.approval_stage.title()
    )

    render_admin_table(
        [
            {
                "Field": "Leave Owner",
                "Value": (
                    f"{request.employee.employee_number} · "
                    f"{request.employee.full_name}"
                ),
            },
            {
                "Field": "Filed By",
                "Value": (
                    request.filed_by_employee.full_name
                    if request.filed_by_employee is not None
                    else request.employee.full_name
                ),
            },
            {
                "Field": "Approval Stage",
                "Value": stage_label,
            },
            {
                "Field": "Department",
                "Value": (
                    request.employee.department.name
                    if request.employee.department
                    else "—"
                ),
            },
            {
                "Field": "Leave Type",
                "Value": request.leave_type.name,
            },
            {
                "Field": "Leave Dates",
                "Value": (
                    f"{request.start_date.isoformat()} to "
                    f"{request.end_date.isoformat()}"
                ),
            },
            {
                "Field": "Working Days",
                "Value": _days(request.requested_days),
            },
            {
                "Field": "Duration",
                "Value": _request_duration(request),
            },
            {
                "Field": "Credit / LWOP Split",
                "Value": LeaveService.allocation_breakdown(request),
            },
            {
                "Field": "Cancellation Reason",
                "Value": request.cancellation_reason or "—",
            },
            {
                "Field": "Cancellation Effective Date",
                "Value": (
                    request.cancellation_effective_date.isoformat()
                    if request.cancellation_effective_date is not None
                    else "—"
                ),
            },
            {
                "Field": "Reason for Leave",
                "Value": reason_label(str(request.reason_code or "0")),
            },
            {
                "Field": "Reason for Leave: Others",
                "Value": request.reason_other or "—",
            },
            {
                "Field": "Work Handover Plan / Countermeasure",
                "Value": request.handover_plan or "Not provided",
            },
        ],
        key=f"manager-request-detail-{request.id}",
        min_width=900,
        column_widths=(
            "250px",
            "650px",
        ),
        compact=True,
    )

    if plan_bytes is not None:
        st.download_button(
            "Download Handover Plan File",
            data=plan_bytes,
            file_name=(
                request.attachment_original_filename
                or "handover_plan"
            ),
            mime=(
                request.attachment_mime_type
                or "application/octet-stream"
            ),
            width="stretch",
            key=f"manager_plan_download_{request.id}",
        )

    if is_cancellation_review:
        cancellation_comment = st.text_area(
            "Cancellation Decision Comment (Optional)",
            height=110,
            max_chars=2000,
            key=f"cancellation_comment_{request.id}",
        )
        approve_column, reject_column = st.columns(2)
        with approve_column:
            approved_cancellation = st.button(
                "Approve Cancellation",
                type="primary",
                width="stretch",
                key=f"approve_cancel_{request.id}",
            )
        with reject_column:
            rejected_cancellation = st.button(
                "Reject Cancellation",
                width="stretch",
                key=f"reject_cancel_{request.id}",
            )
        if not approved_cancellation and not rejected_cancellation:
            return
        try:
            decision = LeaveCancellationDecisionInput(
                company_id=current_user.company_id,
                request_id=request.id,
                reviewer_employee_id=current_user.employee_id,
                reviewer_user_id=current_user.user_id,
                decision=("approve" if approved_cancellation else "reject"),
                comment=cancellation_comment,
            )
            with st.spinner("Recording the cancellation decision…"):
                with SessionFactory() as session:
                    reviewed = LeaveService(session).decide_leave_cancellation(decision)
            set_operation_feedback(
                f"Cancellation of {reviewed.public_id} was "
                f"{'approved' if approved_cancellation else 'rejected'}.",
                namespace="leave_manager",
            )
            st.rerun()
        except (ValidationError, ValueError) as error:
            render_action_warning(error)
        return

    manager_comment = st.text_area(
        f"{stage_label} Comment (Optional)",
        height=110,
        max_chars=2000,
        key=f"manager_comment_{request.id}",
    )

    approve_column, reject_column = st.columns(2)

    with approve_column:
        approved = st.button(
            (
                "Approve and Send to Manager"
                if request.status == "pending_leader_approval"
                else "Approve Leave Request"
            ),
            type="primary",
            width="stretch",
            key=f"approve_leave_{request.id}",
        )

    with reject_column:
        rejected = st.button(
            "Reject Leave Request",
            width="stretch",
            key=f"reject_leave_{request.id}",
        )

    if not approved and not rejected:
        return

    try:
        decision = LeaveDecisionInput(
            company_id=current_user.company_id,
            request_id=request.id,
            manager_employee_id=current_user.employee_id,
            manager_user_id=current_user.user_id,
            decision=(
                "approve"
                if approved
                else "reject"
            ),
            manager_comment=manager_comment,
        )

        with st.spinner(
            "Recording the approval decision…"
        ):
            with SessionFactory() as session:
                reviewed = LeaveService(
                    session
                ).decide_leave_request(decision)

        outcome = (
            "forwarded to the assigned manager"
            if approved and reviewed.status == "pending_manager_approval"
            else "approved"
            if approved
            else "rejected"
        )
        set_operation_feedback(
            f"{reviewed.public_id} was {outcome}.",
            namespace="leave_manager",
        )
        st.rerun()

    except (
        ValidationError,
        ValueError,
    ) as error:
        render_action_warning(error)


def _render_pending_approvals(
    current_user: AuthenticatedUser,
    selected_request_id: int | None = None,
) -> None:
    """Render requests waiting for this leader or manager."""

    with SessionFactory() as session:
        pending = LeaveService(
            session
        ).list_pending_manager_requests(
            company_id=current_user.company_id,
            manager_employee_id=current_user.employee_id,
        )

    if not pending:
        st.success(
            "No leave request is waiting for your approval."
        )
        return

    render_admin_table(
        _approval_rows(pending),
        key="manager-pending-leave-requests",
        min_width=1250,
    )

    options = {
        request.id: (
            f"{request.public_id} · "
            f"{request.employee.full_name} · "
            f"{request.leave_type.name}"
        )
        for request in pending
    }
    option_ids = list(options)
    selected_index = 0

    if selected_request_id is not None:
        if selected_request_id not in options:
            st.error(
                "The selected leave request is no longer pending for "
                "your approval."
            )
            return

        selected_index = option_ids.index(
            selected_request_id
        )
        st.info(
            "Opened from Notifications: request awaiting your approval."
        )

    selected_id = st.selectbox(
        "Select Request to Review",
        options=option_ids,
        index=selected_index,
        format_func=lambda value: options[value],
        key="manager_pending_selector",
    )

    _render_manager_request_detail(
        current_user,
        selected_id,
    )


def _render_reviewed_request_detail(
    current_user: AuthenticatedUser,
    request_id: int,
) -> None:
    """Show one manager-reviewed request without decision controls."""

    with SessionFactory() as session:
        request = LeaveService(
            session
        ).get_request(
            current_user.company_id,
            request_id,
        )

    if (
        request is None
        or request.manager_employee_id
        != current_user.employee_id
    ):
        st.error(
            "The selected reviewed request is unavailable."
        )
        return

    render_admin_table(
        [
            {
                "Field": "Request ID",
                "Value": request.public_id,
            },
            {
                "Field": "Employee",
                "Value": (
                    f"{request.employee.employee_number} · "
                    f"{request.employee.full_name}"
                ),
            },
            {
                "Field": "Leave Type",
                "Value": request.leave_type.name,
            },
            {
                "Field": "Leave Dates",
                "Value": (
                    f"{request.start_date.isoformat()} to "
                    f"{request.end_date.isoformat()}"
                ),
            },
            {
                "Field": "Status",
                "Value": _status(request.status),
            },
            {
                "Field": "Duration",
                "Value": _request_duration(request),
            },
            {
                "Field": "Reason for Leave",
                "Value": _request_reason(request),
            },
            {
                "Field": "Manager Comment",
                "Value": request.manager_comment or "—",
            },
        ],
        key=f"manager-reviewed-detail-{request.id}",
        min_width=900,
        column_widths=(
            "230px",
            "670px",
        ),
        compact=True,
    )


def _render_reviewed_requests(
    current_user: AuthenticatedUser,
    selected_request_id: int | None = None,
) -> None:
    """Render the current manager's reviewed request history."""

    with SessionFactory() as session:
        reviewed = LeaveService(
            session
        ).list_reviewed_manager_requests(
            company_id=current_user.company_id,
            manager_employee_id=current_user.employee_id,
        )

    if not reviewed:
        st.info(
            "You have not reviewed a leave request yet."
        )
        return

    render_admin_table(
        _approval_rows(reviewed),
        key="manager-reviewed-leave-requests",
        min_width=1250,
    )

    options = {
        request.id: (
            f"{request.public_id} · "
            f"{request.employee.full_name} · "
            f"{_status(request.status)}"
        )
        for request in reviewed
    }
    option_ids = list(options)
    selected_index = 0

    if selected_request_id is not None:
        if selected_request_id not in options:
            st.error(
                "The selected leave request is not in your reviewed "
                "request history."
            )
            return

        selected_index = option_ids.index(
            selected_request_id
        )
        st.info(
            "Opened from Notifications: reviewed leave request."
        )

    selected_id = st.selectbox(
        "View Reviewed Request Details",
        options=option_ids,
        index=selected_index,
        format_func=lambda value: options[value],
        key="manager_reviewed_selector",
    )

    _render_reviewed_request_detail(
        current_user,
        selected_id,
    )


def _assistant_leave_view() -> str | None:
    """Return a safe direct view requested by the HR Assistant."""

    value = st.query_params.get("leave_view")

    if isinstance(value, (list, tuple)):
        value = value[0] if value else None

    if value in {
        "overview",
        "file",
        "requests",
        "pending",
        "reviewed",
    }:
        return str(value)

    return None


def _notification_leave_request_id() -> int | None:
    """Return a safe leave-request ID opened from Notifications."""

    raw_value = st.query_params.get(
        "leave_request_id"
    )

    if isinstance(raw_value, (list, tuple)):
        raw_value = raw_value[0] if raw_value else None

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def _activate_employee_leave_tab(tab_label: str) -> None:
    """Select the exact employee leave tab opened from Notifications."""

    target_label_json = json.dumps(tab_label)
    script = (
        "<script>"
        "const parentDocument=window.parent.document;"
        f"const targetLabel={target_label_json};"
        "const activateTargetTab=()=>{"
        "const tabs=Array.from(parentDocument.querySelectorAll("
        "'[data-testid=\"stTabs\"] button[role=\"tab\"]'));"
        "const target=tabs.find((tab)=>tab.textContent.trim()===targetLabel);"
        "if(target&&target.getAttribute('aria-selected')!=='true'){target.click();}"
        "};"
        "activateTargetTab();"
        "window.setTimeout(activateTargetTab,80);"
        "window.setTimeout(activateTargetTab,220);"
        "</script>"
    )
    render_browser_bridge(script)


def render_employee_leave_management_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render employee, leader proxy-filing, and staged approvals."""

    st.title("Leave Management")
    st.caption(
        "File leave, monitor credits, process Leader → Manager approvals, and "
        "cancel pending or approved leave with the correct credit treatment. "
        "Assigned Leaders and Managers may file leave for direct reports; "
        "the leave owner's approval hierarchy still applies."
    )
    render_operation_feedback(namespace="leave_employee")
    render_operation_feedback(namespace="leave_manager")

    if current_user.employee_id is None:
        st.warning("Your login account is not linked to an employee record.")
        return

    with SessionFactory() as session:
        service = LeaveService(session)
        service.reconcile_approved_leave(company_id=current_user.company_id)
        approver_mode = service.is_manager(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
        )
        proxy_mode = bool(
            service.list_proxy_leave_members(
                company_id=current_user.company_id,
                filer_employee_id=current_user.employee_id,
            )
        )

    direct_view = _assistant_leave_view()
    notification_request_id = _notification_leave_request_id()
    labels = ["My Leave Overview", "File Leave Request", "My Requests"]
    if proxy_mode:
        labels.extend(["File for Team Member", "Team Filed Requests"])
    if approver_mode:
        labels.extend(["Pending Approvals", "Reviewed Requests"])

    tabs = st.tabs(
        labels,
        key="employee_leave_management_active_tab",
        on_change="rerun",
    )
    tab_by_label = dict(zip(labels, tabs))

    with tab_by_label["My Leave Overview"]:
        _render_balances(current_user)
    with tab_by_label["File Leave Request"]:
        _render_submit(current_user)
    with tab_by_label["My Requests"]:
        _render_requests(
            current_user,
            selected_request_id=(
                notification_request_id
                if direct_view == "requests"
                else None
            ),
        )
    if proxy_mode:
        with tab_by_label["File for Team Member"]:
            _render_team_member_submit(current_user)
        with tab_by_label["Team Filed Requests"]:
            _render_team_filed_requests(current_user)
    if approver_mode:
        with tab_by_label["Pending Approvals"]:
            _render_pending_approvals(
                current_user,
                selected_request_id=(
                    notification_request_id
                    if direct_view == "pending"
                    else None
                ),
            )
        with tab_by_label["Reviewed Requests"]:
            _render_reviewed_requests(
                current_user,
                selected_request_id=(
                    notification_request_id
                    if direct_view == "reviewed"
                    else None
                ),
            )

    if notification_request_id is not None:
        target_labels = {
            "requests": "My Requests",
            "pending": "Pending Approvals",
            "reviewed": "Reviewed Requests",
        }
        target_label = target_labels.get(direct_view)
        if target_label in tab_by_label:
            _activate_employee_leave_tab(target_label)
