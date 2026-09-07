"""Simplified administrator Leave Management workspace.

Main sections:
- Overview: operational summary and items requiring attention.
- Employee Leave Accounts: view and maintain one employee's credits.
- Leave Requests: monitor manager-routed requests and open full details.
- Leave Rules: configure company leave types and annual rules.

Department managers remain responsible for approvals outside this portal.
"""

from datetime import date, datetime
import calendar
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import json
import streamlit as st
from ui.components.validation_feedback import render_action_warning
from ui.components.persistent_tabs import persistent_tabs

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from core.leave_codes import duration_label, reason_label
from database.session import SessionFactory
from schemas.leave_schema import (
    CompanyLeavePolicyInput,
    LeaveCreditBalanceSetInput,
    LeaveTypeInput,
)
from services.leave_service import LeaveService
from ui.components.browser_bridge import render_browser_bridge
from ui.components.data_table import render_admin_table
from ui.components.confirmation_guard import (
    clear_confirmation_tracking,
    invalidate_confirmation_on_change,
)
from ui.components.live_search import (
    clear_multi_search,
    multi_search_input,
)
from utils.search_utils import matches_search_terms
from ui.pages.admin.leave_change_review import render_hr_change_review
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)


_LOW_CREDIT_THRESHOLD = Decimal("2.00")
_ADMIN_LEAVE_NEXT_TABS_KEY = "_admin_leave_next_tabs"
_LEAVE_RULE_SELECTED_ID_KEY = "leave_rule_selected_id"
_LEAVE_RULE_PENDING_SELECTED_ID_KEY = "_leave_rule_pending_selected_id"
_LEAVE_RULE_FORM_REVISION_PREFIX = "_leave_rule_form_revision"
_CREDIT_FORM_REVISION_PREFIX = "_leave_credit_form_revision"


def _days(value) -> str:
    """Format leave days without unnecessary decimal zeros."""

    return (
        f"{Decimal(value):.2f}"
        .rstrip("0")
        .rstrip(".")
    )


def _request_duration(request) -> str:
    return duration_label(str(getattr(request, "duration_code", "") or "90503"))


def _request_reason(request) -> str:
    code = str(getattr(request, "reason_code", "") or "0")
    standard = reason_label(code)
    other = getattr(request, "reason_other", None)
    return f"{standard} · {other}" if code == "0" and other else standard


def _state_revision(key: str) -> int:
    """Return one integer widget revision stored in session state."""

    return int(st.session_state.get(key, 0))


def _bump_state_revision(key: str) -> None:
    """Force refreshed form widgets to load committed database values."""

    st.session_state[key] = _state_revision(key) + 1


def _remember_leave_tabs(*tab_labels: str) -> None:
    """Restore the same outer and nested Leave tabs after a rerun."""

    st.session_state[_ADMIN_LEAVE_NEXT_TABS_KEY] = list(tab_labels)


def _nonnegative_editor_value(value) -> float:
    """Return a Streamlit-safe default for non-negative credit inputs.

    Legacy or test data can contain a negative remaining balance. Streamlit
    rejects a widget value below its ``min_value`` before the page renders,
    so the editor starts at zero while the original balance remains visible.
    Saving is still an explicit administrator action.
    """

    amount = Decimal(value)
    return float(max(amount, Decimal("0.00")))


def _format_datetime(value) -> str:
    """Display a stored datetime in the configured timezone."""

    if value is None:
        return "—"

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=ZoneInfo("UTC")
        )

    return value.astimezone(
        ZoneInfo(get_settings().display_timezone)
    ).strftime("%Y-%m-%d %I:%M %p")


def _current_leave_year(company_id: int | None = None) -> int:
    """Return the current company leave-cycle year."""

    today = datetime.now(
        ZoneInfo(get_settings().display_timezone)
    ).date()
    if company_id is None:
        return today.year
    with SessionFactory() as session:
        return LeaveService(session).leave_cycle_year(company_id, today)


def _today():
    """Return today's date in the configured timezone."""

    return datetime.now(
        ZoneInfo(get_settings().display_timezone)
    ).date()


def _status_label(value: str) -> str:
    """Convert a stored request status into a readable label."""

    return (
        value.replace("_", " ")
        .strip()
        .title()
    )


def _group_balances(balances) -> dict[int, list]:
    """Group annual balances by employee ID."""

    grouped: dict[int, list] = {}

    for balance in balances:
        grouped.setdefault(
            balance.employee_id,
            [],
        ).append(balance)

    return grouped


def _employee_options(
    grouped: dict[int, list],
    *,
    department_name: str = "All Departments",
) -> dict[int, str]:
    """Return employee selector labels, optionally department-filtered."""

    options: dict[int, str] = {}

    for employee_id, items in grouped.items():
        employee = items[0].employee
        employee_department = (
            employee.department.name
            if employee.department
            else "No Department"
        )

        if (
            department_name != "All Departments"
            and employee_department != department_name
        ):
            continue

        options[employee_id] = (
            f"{employee.employee_number} · "
            f"{employee.full_name} · "
            f"{employee_department}"
        )

    return options


def _account_totals(balances) -> dict[str, Decimal]:
    """Calculate one employee's leave-account totals."""

    return {
        "allocated": sum(
            (
                Decimal(item.allocated_days)
                + Decimal(item.carry_over_days)
                + Decimal(item.adjustment_days)
                for item in balances
            ),
            Decimal("0.00"),
        ),
        "used": sum(
            (
                Decimal(item.used_days)
                for item in balances
            ),
            Decimal("0.00"),
        ),
        "reserved": sum(
            (
                Decimal(item.reserved_days)
                for item in balances
            ),
            Decimal("0.00"),
        ),
        "remaining": sum(
            (
                Decimal(item.remaining_days)
                for item in balances
            ),
            Decimal("0.00"),
        ),
    }


def _low_credit_rows(
    grouped: dict[int, list],
) -> list[dict[str, str]]:
    """Return one alert row per employee with low available credits."""

    rows: list[dict[str, str]] = []

    for items in grouped.values():
        employee = items[0].employee
        low_items = [
            item
            for item in items
            if (
                Decimal(item.leave_type.annual_credits) > 0
                and Decimal(item.remaining_days)
                <= _LOW_CREDIT_THRESHOLD
            )
        ]

        if not low_items:
            continue

        rows.append(
            {
                "Employee": (
                    f"{employee.employee_number} · "
                    f"{employee.full_name}"
                ),
                "Department": (
                    employee.department.name
                    if employee.department
                    else "—"
                ),
                "Low Credits": ", ".join(
                    (
                        f"{item.leave_type.name}: "
                        f"{_days(item.remaining_days)}"
                    )
                    for item in sorted(
                        low_items,
                        key=lambda value: value.leave_type.name,
                    )
                ),
            }
        )

    return rows


def _compact_request_rows(requests) -> list[dict[str, str]]:
    """Build a concise request list with proxy-filing and hierarchy data."""

    return [
        {
            "Request ID": request.public_id or f"LRQ_{request.id:06d}",
            "Leave Owner": request.employee.full_name,
            "Filed By": (
                request.filed_by_employee.full_name
                if request.filed_by_employee is not None
                else request.employee.full_name
            ),
            "Leave Type": request.leave_type.name,
            "Leave Dates": (
                f"{request.start_date.isoformat()} to "
                f"{request.end_date.isoformat()}"
            ),
            "Duration": _request_duration(request),
            "Days": _days(request.requested_days),
            "Current Reviewer": (
                request.current_approver.full_name
                if request.current_approver is not None
                else request.manager.full_name
                if request.status.startswith("pending_") and request.manager is not None
                else "Completed"
            ),
            "Approval Stage": request.approval_stage.title(),
            "Status": _status_label(request.status),
        }
        for request in requests
    ]


def _render_overview(
    current_user: AuthenticatedUser,
    year: int,
    grouped: dict[int, list],
    requests,
) -> None:
    """Render a true dashboard without duplicating employee accounts."""

    with SessionFactory() as session:
        metrics = LeaveService(session).overview(
            current_user.company_id,
            year,
        )

    current_year = _current_leave_year(current_user.company_id)
    is_current_year = year == current_year

    metric_columns = st.columns(4)
    metric_values = [
        (
            f"Requests in {year}",
            metrics["total_requests"],
        ),
        (
            (
                "Sent This Month"
                if is_current_year
                else f"Submitted in {year}"
            ),
            (
                metrics["requests_this_month"]
                if is_current_year
                else metrics["requests_submitted_in_year"]
            ),
        ),
        (
            (
                "Employees on Leave Today"
                if is_current_year
                else f"Employees with Leave in {year}"
            ),
            (
                metrics["employees_on_leave_today"]
                if is_current_year
                else metrics["employees_with_leave"]
            ),
        ),
        (
            "Employees with Low Credits",
            metrics["employees_with_low_credits"],
        ),
    ]

    for column, (label, value) in zip(
        metric_columns,
        metric_values,
    ):
        with column:
            st.metric(label, value)

    st.info(
        "Use Overview for monitoring only. Open Employee Leave Accounts "
        "to view or adjust a specific employee's credits."
    )

    left, right = st.columns(2)

    with left:
        st.markdown(
            "### Employees on Leave Today"
            if is_current_year
            else f"### Leave Activity in {year}"
        )

        if is_current_year:
            today = _today()
            activity_requests = [
                request
                for request in requests
                if (
                    request.status in {
                        "scheduled",
                        "approved",
                        "in_progress",
                        "completed",
                    }
                    and request.start_date
                    <= today
                    <= request.end_date
                )
            ]
        else:
            activity_requests = sorted(
                requests,
                key=lambda item: (
                    item.start_date,
                    item.id,
                ),
                reverse=True,
            )[:8]

        if activity_requests:
            render_admin_table(
                _compact_request_rows(activity_requests),
                key=f"leave-overview-activity-{year}",
                min_width=920,
                compact=True,
            )
        else:
            st.info(
                "No employees are on leave today."
                if is_current_year
                else f"No leave activity is recorded for {year}."
            )

    with right:
        st.markdown("### Attention Needed")
        low_rows = _low_credit_rows(grouped)

        if low_rows:
            render_admin_table(
                low_rows,
                key=f"leave-overview-low-credit-{year}",
                min_width=680,
                column_widths=(
                    "270px",
                    "170px",
                    "240px",
                ),
                compact=True,
                max_height=170,
            )
        else:
            st.success(
                f"No employee has leave credits at or below "
                f"{_days(_LOW_CREDIT_THRESHOLD)} days for {year}."
            )

    # Former label: Recent Leave Requests. This panel now intentionally shows
    # only requests that still need an approval or cancellation decision.
    st.markdown("### Pending Leave Request")

    recent_requests = sorted(
        (
            request for request in requests
            if request.status in {
                "pending_leader_approval",
                "pending_manager_approval",
            }
            or request.cancellation_status == "requested"
        ),
        key=lambda item: (
            item.submitted_at,
            item.id,
        ),
        reverse=True,
    )[:8]

    if recent_requests:
        render_admin_table(
            _compact_request_rows(recent_requests),
            key=f"leave-overview-recent-{year}",
            min_width=1050,
            compact=True,
            max_height=205,
        )
    else:
        st.info(
            f"No pending leave request is available for {year}."
        )


def _render_employee_account_summary(
    employee,
    balances,
    year: int,
) -> None:
    """Render the reordered account metrics before selectors."""

    totals = _account_totals(balances)

    columns = st.columns(4)
    cards = [
        ("Available Credits", _days(totals["remaining"])),
        ("Used Credits", _days(totals["used"])),
        ("Reserved Credits", _days(totals["reserved"])),
        (
            "Leave Types",
            len(LeaveService.credit_table_balances(balances)),
        ),
    ]

    for column, (label, value) in zip(
        columns,
        cards,
    ):
        with column:
            st.metric(label, value)


def _render_employee_account_identity(employee, year: int) -> None:
    """Render the selected employee heading before account details."""

    st.markdown("### Employee Leave Account")
    st.caption(
        f"{employee.employee_number} · {employee.full_name} · "
        f"{employee.department.name if employee.department else 'No Department'} "
        f"· Leave Year {year}"
    )


def _render_employee_account_entitlement(employee, year: int) -> None:
    """Render hire date, service, and annual-accrual explanation."""

    with SessionFactory() as session:
        summary = LeaveService(session).entitlement_summary(
            employee=employee,
            year=year,
        )
    reset_date = summary["reset_date"]
    reset_label = reset_date.strftime("%B %d")

    hire_date = (
        employee.hire_date.isoformat()
        if employee.hire_date
        else "Not recorded"
    )
    st.info(
        f"Hire Date: {hire_date} · Completed Service: "
        f"{summary['service_years']} year(s) · {summary['basis']}\n\n"
        f"{reset_label} Annual Accrual: Vacation "
        f"{_days(summary['regular_vacation'])} days · "
        f"Sick Leave {_days(summary['sick'])} days. "
        "Unused SL/VL is shown as Beginning Credit in the next leave cycle. "
        "During annual reset processing, SL retains up to 15 days and VL "
        "retains up to 45 days; any excess is moved to Converted to Cash."
    )


def _render_credit_breakdown(
    employee_id: int,
    balances,
    year: int,
) -> None:
    """Display employee credits and the virtual EL annual allowance."""

    # The old "Current Credits" label remains retired; the visible column is
    # "Available Credits" while EL shows allowance, not additional credits.
    company_id = balances[0].company_id if balances else None
    if company_id is None:
        return

    with SessionFactory() as session:
        service = LeaveService(session)
        table_rows = service.credit_table_rows(
            company_id=company_id,
            employee_id=employee_id,
            year=year,
        )
        ob_summary = service.official_business_credit_summary(
            company_id=company_id,
            employee_id=employee_id,
            year=year,
        )

    render_admin_table(
        [
            {
                "Leave Type": item.leave_type.name,
                "Beginning Credit": (
                    _days(item.beginning_credit_days)
                    if item.is_applicable
                    else "N/A"
                ),
                # Credit is only the current annual/event allocation. Manual
                # corrections affect Available Credits and audit history.
                "Credit": (
                    _days(item.credit_days)
                    if item.is_applicable
                    else "N/A"
                ),
                "Used": (
                    _days(item.used_days)
                    if item.is_applicable
                    else "N/A"
                ),
                "Available Credits": (
                    _days(item.available_credits)
                    if item.is_applicable
                    else "N/A"
                ),
                "Leave Utilization": (
                    item.leave_utilization.display_text
                    if item.leave_utilization is not None
                    else "N/A"
                ),
                "Converted to Cash": (
                    "N/A"
                    if not item.is_applicable
                    else (
                        _days(item.converted_to_cash_days)
                        if LeaveService.supports_cash_conversion(
                            item.leave_type
                        )
                        else "—"
                    )
                ),
                "Last Updated": (
                    _format_datetime(item.updated_at)
                    if item.is_applicable
                    else "N/A"
                ),
            }
            for item in table_rows
        ],
        key=f"employee-leave-account-{employee_id}-{year}",
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
        "OB lifecycle — "
        f"Earned: {_days(ob_summary.earned_days)} · "
        f"Pending: {_days(ob_summary.pending_days)} · "
        f"Available: {_days(ob_summary.available_days)} · "
        f"Reserved: {_days(ob_summary.reserved_days)} · "
        f"Used: {_days(ob_summary.used_days)} · "
        f"Expired: {_days(ob_summary.expired_days)} · "
        f"Regular OT Restored: {_days(ob_summary.restored_regular_ot_hours)} hr(s)."
    )
    st.caption(
        "Beginning Credit is the carried balance before the current annual "
        "accrual. Credit shows only the annual or approved event allocation "
        "for the selected year. Administrator corrections affect Available "
        "Credits and remain in audit history. Available Credits is the usable balance after usage, "
        "reservations, and cash conversion. Gender-inapplicable Maternity or "
        "Paternity rows display N/A. Only Vacation and Sick Leave may be "
        "converted to cash. Vacation Leave utilization is a monitoring "
        "target and is not deducted in advance; only an unmet target is "
        "forfeited at year end. Official Business (OB) credits are earned "
        "from qualifying Shifting Credit OT blocks and become usable only "
        "after their configured availability delay."
    )


def _render_credit_balance_editor(
    current_user: AuthenticatedUser,
    employee_id: int,
    balances,
    year: int,
) -> None:
    """Set the exact remaining credits for one selected leave type."""

    balance_by_type = {
        item.leave_type.id: item
        for item in balances
        if (item.leave_type.code or "").strip().upper()
        not in {
            "EMERGENCY",
            "HONEYMOON",
            "MATERNITY",
            "PATERNITY",
            "BEREAVEMENT",
            "OB",
            "LWOP",
        }
    }
    type_options = {
        leave_type_id: (
            f"{item.leave_type.name} · "
            f"{_days(item.remaining_days)} current credits"
        )
        for leave_type_id, item in balance_by_type.items()
    }

    st.caption(
        "Emergency Leave is not editable as a separate credit. Its maximum "
        "three-day annual allowance is automatically deducted from Vacation "
        "Leave when an EL request is approved. Honeymoon, Maternity, "
        "Paternity, and Bereavement credits are also not manually editable; "
        "their fixed credits are created only after manager approval of a "
        "qualifying event request. Official Business (OB) is system-managed "
        "from approved 4+4 same-cutoff Shifting Credits."
    )

    selected_leave_type_id = st.selectbox(
        "Leave Type",
        options=list(type_options),
        format_func=lambda value: type_options[value],
        key=(
            f"leave_credit_type_"
            f"{employee_id}_{year}"
        ),
    )
    selected_balance = balance_by_type[
        selected_leave_type_id
    ]
    current_remaining = Decimal(
        selected_balance.remaining_days
    )

    st.info(
        f"Current {selected_balance.leave_type.name} credits: "
        f"{_days(current_remaining)} days. "
        "Enter the exact usable balance. The system records any difference "
        "internally so the annual and event grants remain auditable."
    )

    conversion_limits = {
        "SICK": Decimal("15.00"),
        "VACATION": Decimal("45.00"),
    }
    retained_limit = conversion_limits.get(
        (selected_balance.leave_type.code or "").strip().upper()
    )
    if retained_limit is not None:
        st.caption(
            f"Retention limit: {_days(retained_limit)} days. "
            "Any amount above this limit is automatically moved to "
            "Converted to Cash when saved."
        )

    if current_remaining < 0:
        st.warning(
            "A legacy negative leave balance was detected. "
            "The correction field starts at 0 so this page can load safely. "
            "Review the employee record, then save the correct balance."
        )

    revision_key = (
        f"{_CREDIT_FORM_REVISION_PREFIX}_"
        f"{employee_id}_{year}_{selected_leave_type_id}"
    )
    revision = _state_revision(revision_key)
    form_key = (
        f"employee-leave-credit-set-"
        f"{employee_id}-{year}-{selected_leave_type_id}-{revision}"
    )

    with st.form(form_key):
        new_remaining_days = st.number_input(
            "New Leave Credits",
            min_value=0.0,
            max_value=365.0,
            value=_nonnegative_editor_value(current_remaining),
            step=0.5,
            help=(
                "This sets the exact usable balance. Example: current 45, "
                "enter 10, result is 10—not 55. Automatic annual and event "
                "grants remain preserved in the audit history."
            ),
            key=f"{form_key}-value",
        )
        submitted = st.form_submit_button(
            "Save Leave Credits",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return

    try:
        values = LeaveCreditBalanceSetInput(
            company_id=current_user.company_id,
            employee_id=employee_id,
            leave_type_id=selected_leave_type_id,
            year=year,
            new_remaining_days=Decimal(
                str(new_remaining_days)
            ),
            reason="Manual leave credit update",
            created_by_user_id=current_user.user_id,
        )

        with st.spinner("Saving leave credits…"):
            with SessionFactory() as session:
                result = LeaveService(
                    session
                ).set_credit_balance(values)

        if result.converted_to_cash > Decimal("0.00"):
            feedback_message = (
                f"{selected_balance.leave_type.name}: "
                f"{_days(result.requested_remaining)} days entered; "
                f"{_days(result.new_remaining)} days retained and "
                f"{_days(result.converted_to_cash)} days converted to cash."
            )
        else:
            feedback_message = (
                f"{selected_balance.leave_type.name} credits changed "
                f"from {_days(result.previous_remaining)} to "
                f"{_days(result.new_remaining)} days."
            )

        set_operation_feedback(
            feedback_message,
            namespace="leave",
        )
        _bump_state_revision(revision_key)
        _remember_leave_tabs(
            "Employee Leave Accounts",
            "Set Leave Credits",
        )
        st.rerun()

    except (
        ValidationError,
        ValueError,
    ) as error:
        render_action_warning(error)



def _credit_history_entry(item) -> str:
    """Describe either an exact balance set or a signed ledger change."""

    if item.transaction_type == "manual_balance_set":
        return f"Set to {_days(item.amount_days)} days"

    amount = Decimal(item.amount_days)
    prefix = "+" if amount > 0 else ""

    return f"{prefix}{_days(amount)} days"


def _render_credit_history(
    current_user: AuthenticatedUser,
    employee_id: int,
    year: int,
) -> None:
    """Render the immutable credit history for one employee."""

    with SessionFactory() as session:
        service = LeaveService(session)
        leave_types = {
            item.id: item.name
            for item in service.list_leave_types(
                current_user.company_id
            )
        }
        transactions = service.list_credit_history(
            current_user.company_id,
            employee_id,
            year,
        )

    if not transactions:
        st.info(
            f"No credit transactions are available for {year}."
        )
        return

    render_admin_table(
        [
            {
                "Date": _format_datetime(item.created_at),
                "Leave Type": leave_types.get(
                    item.leave_type_id,
                    "—",
                ),
                "Transaction": _status_label(
                    item.transaction_type
                ),
                "Credit Entry": _credit_history_entry(
                    item
                ),
                "Details": item.note or "—",
            }
            for item in transactions
        ],
        key=f"employee-credit-history-{employee_id}-{year}",
        min_width=900,
        column_widths=(
            "190px",
            "180px",
            "170px",
            "150px",
            "360px",
        ),
        max_height=360,
    )


def _render_employee_accounts(
    current_user: AuthenticatedUser,
    year: int,
    grouped: dict[int, list],
) -> None:
    """View and maintain all credits for one selected employee."""

    if not grouped:
        st.info(
            f"No employed employee leave accounts are available for {year}."
        )
        return

    st.info(
        "One employee account contains the complete credit view, exact "
        "credit-setting form, and transaction history."
    )

    departments = sorted(
        {
            (
                items[0].employee.department.name
                if items[0].employee.department
                else "No Department"
            )
            for items in grouped.values()
        }
    )

    selected_department = st.session_state.get(
        f"leave_account_department_{year}",
        "All Departments",
    )

    options = _employee_options(
        grouped,
        department_name=selected_department,
    )

    if not options:
        st.info(
            "No employee leave account matches the selected department."
        )
        return

    selected_employee_id = st.session_state.get(
        f"leave_account_employee_{year}",
        next(iter(options)),
    )
    if selected_employee_id not in options:
        selected_employee_id = next(iter(options))

    balances = grouped[selected_employee_id]
    employee = balances[0].employee

    _render_employee_account_summary(
        employee,
        balances,
        year,
    )

    _render_employee_account_identity(employee, year)

    filter_column, employee_column = st.columns([1.1, 2.4])
    with filter_column:
        selected_department = st.selectbox(
            "Department",
            options=["All Departments", *departments],
            key=f"leave_account_department_{year}",
        )
    options = _employee_options(grouped, department_name=selected_department)
    if not options:
        st.info("No employee leave account matches the selected department.")
        return
    with employee_column:
        selected_employee_id = st.selectbox(
            "Employee",
            options=list(options),
            format_func=lambda value: options[value],
            key=f"leave_account_employee_{year}",
        )

    balances = grouped[selected_employee_id]
    employee = balances[0].employee
    _render_employee_account_entitlement(employee, year)
    _render_credit_breakdown(
        selected_employee_id,
        balances,
        year,
    )

    adjust_tab, history_tab = persistent_tabs(
        [
            "Set Leave Credits",
            "Transaction History",
        ],
        key="admin_leave_accounts_detail_tab",
    )

    with adjust_tab:
        _render_credit_balance_editor(
            current_user,
            selected_employee_id,
            balances,
            year,
        )

    with history_tab:
        _render_credit_history(
            current_user,
            selected_employee_id,
            year,
        )


def _render_leave_history(
    current_user: AuthenticatedUser,
    year: int,
    requests,
) -> None:
    """Render company-scoped leave request and immutable credit transactions."""

    search_terms = multi_search_input(
        "Search Leave History",
        placeholder="Type any value shown in the Leave History table, then press Enter…",
        key=f"leave_history_search_{year}",
    )

    rows: list[dict[str, str]] = []
    for request in requests:
        events = [(request.submitted_at, "Leave Filed", request.filed_by_employee, _status_label(request.status))]
        if request.leader_reviewed_at:
            events.append((request.leader_reviewed_at, "Leader Review", request.leader_approver, request.leader_comment or "Forwarded/Reviewed"))
        if request.reviewed_at:
            events.append((request.reviewed_at, "Manager Review", request.manager, request.manager_comment or _status_label(request.status)))
        if request.cancellation_requested_at:
            events.append((request.cancellation_requested_at, "Leave Withdrawal Requested", request.cancellation_requested_by_employee, request.cancellation_reason or "—"))
        if request.cancellation_reviewed_at:
            events.append((request.cancellation_reviewed_at, "Leave Withdrawal Reviewed", request.manager, request.cancellation_comment or LeaveService.cancellation_label(request)))
        for event_date, action, actor, details in events:
            rows.append({
                "Date": _format_datetime(event_date),
                "Employee": f"{request.employee.employee_number} · {request.employee.full_name}",
                "Request ID": request.public_id or f"LRQ_{request.id:06d}",
                "Actor": actor.full_name if actor is not None else "System",
                "Action": action,
                "Leave Type": request.leave_type.name,
                "Days": _days(request.requested_days),
                "Credit / LWP": LeaveService.allocation_breakdown(request),
                "Status / Result": details,
            })

    with SessionFactory() as session:
        transactions = LeaveService(session).list_company_credit_history(
            current_user.company_id,
            year,
        )
    for item in transactions:
        rows.append({
            "Date": _format_datetime(item.created_at),
            "Employee": f"{item.employee.employee_number} · {item.employee.full_name}",
            "Request ID": (
                item.leave_request.public_id
                if item.leave_request is not None
                else "—"
            ),
            "Actor": (
                item.created_by.employee.full_name
                if item.created_by is not None and item.created_by.employee is not None
                else item.created_by.username
                if item.created_by is not None
                else "System"
            ),
            "Action": _status_label(item.transaction_type),
            "Leave Type": item.leave_type.name,
            "Days": _credit_history_entry(item),
            "Credit / LWP": "Credit Transaction",
            "Status / Result": item.note or "—",
        })

    rows.sort(
        key=lambda row: (
            datetime.strptime(row["Date"], "%Y-%m-%d %I:%M %p")
            if row["Date"] != "—"
            else datetime.min
        ),
        reverse=True,
    )
    if search_terms:
        rows = [
            row for row in rows
            if matches_search_terms(search_terms, row.values())
        ]
    st.caption(f"{len(rows)} leave process/transaction history record(s) shown.")
    if not rows:
        st.info(f"No leave history matches the current search for {year}.")
        return
    render_admin_table(
        rows,
        key=f"leave-process-history-{year}",
        min_width=1450,
        max_height=430,
        compact=True,
    )


def _filtered_requests(
    requests,
    *,
    department: str,
    leave_type: str,
    status: str,
    employee_search,
):
    """Apply visible filters plus free-text multi-search terms."""

    output = []

    for request in requests:
        request_department = (
            request.employee.department.name
            if request.employee.department
            else "No Department"
        )
        request_status = _status_label(request.status)

        if (
            department != "All Departments"
            and request_department != department
        ):
            continue

        if (
            leave_type != "All Leave Types"
            and request.leave_type.name != leave_type
        ):
            continue

        if (
            status != "All Statuses"
            and request_status != status
        ):
            continue

        if not matches_search_terms(
            employee_search,
            (
                request.public_id,
                request.employee.employee_number,
                request.employee.full_name,
                request.filed_by_employee.full_name if request.filed_by_employee else "",
                request_department,
                request.leave_type.code,
                request.leave_type.name,
                request.start_date,
                request.end_date,
                _request_duration(request),
                request.requested_days,
                _request_reason(request),
                request.manager.full_name if request.manager else "",
                request.current_approver.full_name if request.current_approver else "",
                request.approval_stage,
                request_status,
                request.cancellation_status,
                LeaveService.allocation_breakdown(request),
                request.email_status,
            ),
        ):
            continue

        output.append(request)

    return output


def _render_request_details(
    current_user: AuthenticatedUser,
    selected_id: int,
) -> None:
    """Open one full request without exposing approval actions."""

    with SessionFactory() as session:
        service = LeaveService(session)
        request = service.get_request(
            current_user.company_id,
            selected_id,
        )
        cc_emails = (
            service.cc_emails(request)
            if request
            else []
        )
        attachment_bytes = None

        if request and request.attachment_storage_path:
            try:
                attachment_bytes = service.read_attachment(
                    request
                )
            except FileNotFoundError:
                attachment_bytes = None

    if request is None:
        st.error("The selected request is unavailable.")
        return

    if Decimal(request.lwop_days or Decimal("0.00")) > Decimal("0.00"):
        paid_days = (
            Decimal(request.primary_credit_days or Decimal("0.00"))
            + Decimal(request.fallback_credit_days or Decimal("0.00"))
        )
        st.warning(
            (
                f"No available {request.leave_type.name} credits: all "
                f"{_days(request.lwop_days)} countable day(s) are Leave "
                "Without Pay (LWP)."
            )
            if paid_days <= Decimal("0.00")
            else (
                f"Available credits are insufficient; "
                f"{_days(request.lwop_days)} day(s) are Leave Without Pay (LWP)."
            )
        )

    filed_by_employee = request.filed_by_employee
    if request.filed_on_behalf:
        filer_role = (
            filed_by_employee.job_title
            if filed_by_employee is not None and filed_by_employee.job_title
            else "Leader/Manager"
        )
        filing_source = f"{filer_role} Filed on Behalf"
    else:
        filing_source = "Employee Self-Filed"

    st.markdown("### Request Details")

    render_admin_table(
        [
            {
                "Field": "Request ID",
                "Value": (
                    request.public_id
                    or f"LRQ_{request.id:06d}"
                ),
            },
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
                    filed_by_employee.full_name
                    if filed_by_employee is not None
                    else request.employee.full_name
                ),
            },
            {
                "Field": "Filing Source",
                "Value": filing_source,
            },
            {
                "Field": "Approval Route",
                "Value": (
                    f"{request.leader_approver.full_name} → {request.manager.full_name}"
                    if request.leader_approver is not None and request.manager is not None
                    else request.manager.full_name
                    if request.manager is not None
                    else "—"
                ),
            },
            {
                "Field": "Current Reviewer",
                "Value": (
                    request.current_approver.full_name
                    if request.current_approver is not None
                    else "Completed"
                ),
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
                "Field": "To Recipients",
                "Value": (
                    "\n".join(service.to_emails(request))
                    if service.to_emails(request)
                    else "—"
                ),
            },
            {
                "Field": "CC Recipients",
                "Value": (
                    "\n".join(cc_emails)
                    if cc_emails
                    else "—"
                ),
            },
            {
                "Field": "Status",
                "Value": _status_label(request.status),
            },
            {
                "Field": "Email Delivery",
                "Value": request.email_status.title(),
            },
            {
                "Field": "Submitted",
                "Value": _format_datetime(
                    request.submitted_at
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
            {
                "Field": "Leader Comment",
                "Value": request.leader_comment or "—",
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
        ],
        key=f"leave-request-detail-{request.id}",
        min_width=820,
        column_widths=(
            "190px",
            "630px",
        ),
        compact=True,
    )

    if attachment_bytes is not None:
        st.download_button(
            "Download Handover Plan File",
            data=attachment_bytes,
            file_name=(
                request.attachment_original_filename
                or "handover_plan"
            ),
            mime=(
                request.attachment_mime_type
                or "application/octet-stream"
            ),
            width="stretch",
        )

    render_hr_change_review(current_user, request)

    st.caption(
        "Assigned leaders perform the first approval when present. The "
        "assigned manager performs the final decision. This page is view-only."
    )


def _render_requests(
    current_user: AuthenticatedUser,
    year: int,
    requests,
    selected_request_id: int | None = None,
) -> None:
    """Render filtered, view-only manager-routed leave requests."""

    st.caption(
        f"Requests shown here have leave dates that overlap Leave Year {year}."
    )

    if not requests:
        st.info(
            f"No leave requests are available for {year}."
        )
        return

    departments = sorted(
        {
            (
                request.employee.department.name
                if request.employee.department
                else "No Department"
            )
            for request in requests
        }
    )
    leave_types = sorted(
        {
            request.leave_type.name
            for request in requests
        }
    )
    statuses = sorted(
        {
            _status_label(request.status)
            for request in requests
        }
    )

    if selected_request_id is not None:
        # A notification target must not be hidden by filters left from an
        # earlier visit to the Leave Requests tab.
        st.session_state[f"leave_request_department_{year}"] = (
            "All Departments"
        )
        st.session_state[f"leave_request_type_{year}"] = (
            "All Leave Types"
        )
        st.session_state[f"leave_request_status_{year}"] = (
            "All Statuses"
        )
        clear_multi_search(
            f"leave_request_employee_search_{year}"
        )

    department_column, type_column, status_column = st.columns(3)

    with department_column:
        selected_department = st.selectbox(
            "Department",
            options=[
                "All Departments",
                *departments,
            ],
            key=f"leave_request_department_{year}",
        )

    with type_column:
        selected_leave_type = st.selectbox(
            "Leave Type",
            options=[
                "All Leave Types",
                *leave_types,
            ],
            key=f"leave_request_type_{year}",
        )

    with status_column:
        selected_status = st.selectbox(
            "Status",
            options=[
                "All Statuses",
                *statuses,
            ],
            key=f"leave_request_status_{year}",
        )

    employee_search = multi_search_input(
        "Search Leave Requests",
        placeholder="Type request, employee, department, leave type, status, or date, then press Enter…",
        key=f"leave_request_employee_search_{year}",
    )
    # Previous label kept only as migration context: "Find Employee".

    filtered = _filtered_requests(
        requests,
        department=selected_department,
        leave_type=selected_leave_type,
        status=selected_status,
        employee_search=employee_search,
    )

    st.caption(
        f"{len(filtered)} of {len(requests)} request(s) shown."
    )

    if not filtered:
        st.info(
            "No leave request matches the selected filters."
        )
        return

    render_admin_table(
        [
            {
                "Request ID": (
                    request.public_id
                    or f"LRQ_{request.id:06d}"
                ),
                "Employee": request.employee.full_name,
                "Department": (
                    request.employee.department.name
                    if request.employee.department
                    else "—"
                ),
                "Leave Type": request.leave_type.name,
                "Start Date": request.start_date.isoformat(),
                "End Date": request.end_date.isoformat(),
                "Duration": _request_duration(request),
                "Days": _days(request.requested_days),
                "Reason": _request_reason(request),
                "Manager": (
                    request.manager.full_name
                    if request.manager
                    else "—"
                ),
                "Status": _status_label(request.status),
                "Email": request.email_status.title(),
            }
            for request in filtered
        ],
        key=f"leave-request-monitoring-{year}",
        min_width=1735,
        column_widths=(
            "125px",
            "190px",
            "150px",
            "150px",
            "110px",
            "110px",
            "150px",
            "70px",
            "250px",
            "160px",
            "170px",
            "100px",
        ),
    )

    request_options = {
        request.id: (
            f"{request.public_id or f'LRQ_{request.id:06d}'} · "
            f"{request.employee.full_name} · "
            f"{request.leave_type.name}"
        )
        for request in filtered
    }
    option_ids = list(request_options)
    selector_key = f"leave_request_detail_selector_{year}"

    if selected_request_id is not None:
        if selected_request_id not in request_options:
            st.error(
                "The notification's leave request is unavailable for "
                "the selected company and leave year."
            )
            return

        st.session_state[selector_key] = selected_request_id
        st.info(
            "Opened from Notifications. The related request is selected "
            "below inside the Leave Requests tab."
        )

    selected_id = st.selectbox(
        "View Request Details",
        options=option_ids,
        format_func=lambda value: request_options[value],
        key=selector_key,
    )

    _render_request_details(
        current_user,
        selected_id,
    )


def _render_type_form(
    current_user: AuthenticatedUser,
    leave_type,
) -> None:
    """Create or update one leave type and its annual rules."""

    leave_type_key = (
        "new" if leave_type is None else str(leave_type.id)
    )
    revision_key = (
        f"{_LEAVE_RULE_FORM_REVISION_PREFIX}_{leave_type_key}"
    )
    revision = _state_revision(revision_key)
    form_key = f"leave-type-{leave_type_key}-{revision}"

    with st.form(form_key):
        code = st.text_input(
            "Code *",
            value=(
                leave_type.code
                if leave_type
                else ""
            ),
            max_chars=40,
            key=f"{form_key}-code",
        )
        name = st.text_input(
            "Leave Type Name *",
            value=(
                leave_type.name
                if leave_type
                else ""
            ),
            max_chars=120,
            key=f"{form_key}-name",
        )
        annual = st.number_input(
            "Annual Credits",
            min_value=0.0,
            max_value=365.0,
            value=(
                float(leave_type.annual_credits)
                if leave_type
                else 0.0
            ),
            step=0.5,
            key=f"{form_key}-annual",
        )
        carry = st.number_input(
            "Carry-over Limit",
            min_value=0.0,
            max_value=365.0,
            value=(
                float(leave_type.carry_over_limit)
                if leave_type
                else 0.0
            ),
            step=0.5,
            key=f"{form_key}-carry",
        )
        notice = st.number_input(
            "Minimum Notice Days",
            min_value=0,
            max_value=365,
            value=(
                int(leave_type.minimum_notice_days)
                if leave_type
                else 0
            ),
            step=1,
            key=f"{form_key}-notice",
        )
        paid = st.checkbox(
            "Paid Leave",
            value=(
                bool(leave_type.is_paid)
                if leave_type
                else True
            ),
            key=f"{form_key}-paid",
        )
        requirement_options = [
            "optional",
            "recommended",
            "required",
        ]
        current_requirement = (
            leave_type.handover_plan_requirement
            if leave_type
            else "optional"
        )
        handover_plan_requirement = st.selectbox(
            "Handover Plan Requirement",
            options=requirement_options,
            index=requirement_options.index(
                current_requirement
                if current_requirement in requirement_options
                else "optional"
            ),
            format_func=lambda value: value.title(),
            help=(
                "Required accepts either plan text or an uploaded plan file. "
                "Sick and emergency leave can remain Optional."
            ),
            key=f"{form_key}-handover",
        )
        active = st.checkbox(
            "Active",
            value=(
                bool(leave_type.is_active)
                if leave_type
                else True
            ),
            key=f"{form_key}-active",
        )
        apply_existing = st.checkbox(
            "Apply annual credits to existing current-year balances",
            value=False,
            key=f"{form_key}-apply-existing",
        )
        submitted = st.form_submit_button(
            "Save Leave Rule",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return

    try:
        values = LeaveTypeInput(
            company_id=current_user.company_id,
            code=code,
            name=name,
            annual_credits=Decimal(str(annual)),
            is_paid=paid,
            carry_over_limit=Decimal(str(carry)),
            requires_attachment=False,
            handover_plan_requirement=(
                handover_plan_requirement
            ),
            minimum_notice_days=int(notice),
            is_active=active,
            apply_annual_credits_to_existing=apply_existing,
        )

        with st.spinner("Saving leave rule…"):
            with SessionFactory() as session:
                saved_leave_type = LeaveService(
                    session
                ).save_leave_type(
                    values,
                    leave_type.id
                    if leave_type
                    else None,
                )

        set_operation_feedback(
            f"{saved_leave_type.name} was updated successfully.",
            namespace="leave",
        )
        st.session_state[
            _LEAVE_RULE_PENDING_SELECTED_ID_KEY
        ] = saved_leave_type.id
        saved_revision_key = (
            f"{_LEAVE_RULE_FORM_REVISION_PREFIX}_"
            f"{saved_leave_type.id}"
        )
        _bump_state_revision(saved_revision_key)
        _remember_leave_tabs(
            "Leave Rules",
            "Edit Leave Rule",
        )
        st.rerun()

    except (
        ValidationError,
        ValueError,
    ) as error:
        render_action_warning(error)


def _render_rules(
    current_user: AuthenticatedUser,
) -> None:
    """Render leave types, allocations, and request requirements."""

    with SessionFactory() as session:
        policy_service = LeaveService(session)
        company = policy_service._company(current_user.company_id)
        reset_month = int(company.leave_reset_month)
        reset_day = int(company.leave_reset_day)
        utilization_enabled = bool(company.leave_utilization_enabled)
        utilization_percentage = Decimal(company.leave_utilization_percentage)
        manager_retention = Decimal(company.manager_vl_retention_limit)

    reset_label = date(2024, reset_month, min(reset_day, 29 if reset_month == 2 else 28)).strftime("%B")

    with st.expander("Leave Credit Reset & Utilization Settings", expanded=True):
        st.caption(
            "Set the annual leave-cycle reset date and the Vacation Leave "
            "utilization policy. Existing history is preserved; the settings "
            "control the applicable annual cycle and future processing."
        )
        # These settings intentionally live outside st.form. A form defers
        # widget changes until submit, which would allow a stale review
        # checkbox to remain checked after the values it confirmed changed.
        # Normal widgets rerun immediately so confirmation can be invalidated.
        policy_key_prefix = f"company_leave_policy_{current_user.company_id}"
        month_key = f"{policy_key_prefix}_reset_month"
        day_key = f"{policy_key_prefix}_reset_day"
        utilization_key = f"{policy_key_prefix}_utilization_enabled"
        percentage_key = f"{policy_key_prefix}_utilization_percentage"
        retention_key = f"{policy_key_prefix}_manager_retention"
        confirmation_key = f"{policy_key_prefix}_reviewed"

        reset_columns = st.columns(2)
        with reset_columns[0]:
            selected_reset_month = st.selectbox(
                "Leave Credit Reset Month",
                range(1, 13),
                index=reset_month - 1,
                format_func=lambda value: date(2024, value, 1).strftime("%B"),
                key=month_key,
            )
        with reset_columns[1]:
            maximum_day = (
                29
                if selected_reset_month == 2
                else calendar.monthrange(2024, selected_reset_month)[1]
            )
            if day_key not in st.session_state:
                st.session_state[day_key] = min(reset_day, maximum_day)
            else:
                st.session_state[day_key] = min(
                    maximum_day,
                    max(1, int(st.session_state[day_key])),
                )
            selected_reset_day = int(
                st.number_input(
                    "Leave Credit Reset Day",
                    min_value=1,
                    max_value=maximum_day,
                    step=1,
                    key=day_key,
                )
            )

        selected_utilization_enabled = st.checkbox(
            "Enable Vacation Leave Utilization",
            value=utilization_enabled,
            key=utilization_key,
        )
        utilization_columns = st.columns(2)
        with utilization_columns[0]:
            selected_percentage = Decimal(
                str(
                    st.number_input(
                        "Required VL Utilization (%)",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(utilization_percentage),
                        step=0.5,
                        disabled=not selected_utilization_enabled,
                        help="Applied to annual Vacation Leave credit for non-manager employees.",
                        key=percentage_key,
                    )
                )
            )
        with utilization_columns[1]:
            selected_manager_retention = Decimal(
                str(
                    st.number_input(
                        "Manager Annual VL Retention",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(manager_retention),
                        step=0.5,
                        disabled=not selected_utilization_enabled,
                        help=(
                            "Managers must utilize the portion of their annual VL "
                            "credit above this retained amount. This overrides the percentage rule."
                        ),
                        key=retention_key,
                    )
                )
            )

        invalidate_confirmation_on_change(
            confirmation_key=confirmation_key,
            dependencies={
                "reset_month": selected_reset_month,
                "reset_day": selected_reset_day,
                "utilization_enabled": selected_utilization_enabled,
                "utilization_percentage": selected_percentage,
                "manager_vl_retention": selected_manager_retention,
            },
        )
        confirm_policy = st.checkbox(
            "I reviewed the reset date and utilization settings.",
            key=confirmation_key,
        )
        save_policy = st.button(
            "Save Leave Reset & Utilization Settings",
            type="primary",
            width="stretch",
            disabled=not confirm_policy,
            key=f"{policy_key_prefix}_save",
        )

        if save_policy:
            try:
                values = CompanyLeavePolicyInput(
                    company_id=current_user.company_id,
                    reset_month=selected_reset_month,
                    reset_day=selected_reset_day,
                    utilization_enabled=selected_utilization_enabled,
                    utilization_percentage=selected_percentage,
                    manager_vl_retention_limit=selected_manager_retention,
                )
                with st.spinner("Saving leave policy settings…"):
                    with SessionFactory() as session:
                        LeaveService(session).save_company_leave_policy(values)
                set_operation_feedback(
                    "Leave reset and utilization settings were saved successfully.",
                    namespace="leave",
                )
                clear_confirmation_tracking(confirmation_key)
                _remember_leave_tabs("Leave Rules")
                st.rerun()
            except (ValidationError, ValueError) as error:
                render_action_warning(error)
            except Exception:
                st.error("The leave policy settings could not be saved.")

    st.info(
        f"Annual accrual resets every {reset_label} {reset_day}. Vacation and "
        "Sick Leave follow completed tenure on the reset date: 1–5 years = "
        "15 days, 6–10 = 17, 11–15 = 20, 16–20 = 23, and 21+ = 26. "
        "A later service-bracket change applies on the next reset. Unused "
        "SL/VL becomes the next cycle's Beginning Credit, subject to the "
        "retention and cash-conversion rules."
    )

    with SessionFactory() as session:
        leave_types = LeaveService(
            session
        ).list_leave_types(
            current_user.company_id
        )

    render_admin_table(
        [
            {
                "Code": item.code,
                "Leave Type": item.name,
                "Annual Credits": _days(
                    item.annual_credits
                ),
                "Paid": (
                    "Yes" if item.is_paid else "No"
                ),
                "Carry-over Limit": _days(
                    item.carry_over_limit
                ),
                "Handover Plan": (
                    item.handover_plan_requirement
                    or "optional"
                ).title(),
                "Minimum Notice": (
                    f"{item.minimum_notice_days} day(s)"
                ),
                "Status": (
                    "Active"
                    if item.is_active
                    else "Inactive"
                ),
                "Automatic Rule": (
                    f"{reset_label} {reset_day} tenure bracket: 15 / 17 / 20 / 23 / 26 days"
                    if item.code.upper() == "VACATION"
                    else "Included in Vacation total"
                    if item.code.upper() == "EMERGENCY"
                    else f"{reset_label} {reset_day} tenure bracket: 15 / 17 / 20 / 23 / 26 days"
                    if item.code.upper() == "SICK"
                    else "Automatic excess when paid credits are insufficient"
                    if item.code.upper() == "LWOP"
                    else "Uses configured annual credits"
                ),
            }
            for item in leave_types
        ],
        key="leave-rules-table",
        min_width=1500,
        max_height=360,
    )

    add_tab, edit_tab = persistent_tabs(
        [
            "Add Leave Rule",
            "Edit Leave Rule",
        ],
        key="admin_leave_rules_editor_tab",
    )

    with add_tab:
        _render_type_form(
            current_user,
            None,
        )

    with edit_tab:
        if not leave_types:
            st.info("No leave rule is available to edit.")
            return

        options = {
            item.id: f"{item.code} · {item.name}"
            for item in leave_types
        }
        pending_selected_id = st.session_state.pop(
            _LEAVE_RULE_PENDING_SELECTED_ID_KEY,
            None,
        )
        if pending_selected_id in options:
            st.session_state[
                _LEAVE_RULE_SELECTED_ID_KEY
            ] = pending_selected_id
        elif (
            st.session_state.get(
                _LEAVE_RULE_SELECTED_ID_KEY
            ) not in options
        ):
            st.session_state[
                _LEAVE_RULE_SELECTED_ID_KEY
            ] = next(iter(options))

        selected_id = st.selectbox(
            "Select Leave Rule",
            options=list(options),
            format_func=lambda value: options[value],
            key=_LEAVE_RULE_SELECTED_ID_KEY,
        )
        selected = next(
            item
            for item in leave_types
            if item.id == selected_id
        )
        _render_type_form(
            current_user,
            selected,
        )


def _notification_leave_request_id() -> int | None:
    """Return a safe request ID opened from a notification."""

    raw_value = st.query_params.get("leave_request_id")
    if isinstance(raw_value, (list, tuple)):
        raw_value = raw_value[0] if raw_value else None

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def _activate_leave_tabs(tab_labels: list[str]) -> None:
    """Restore outer and nested Streamlit tabs after a successful update."""

    labels_json = json.dumps(tab_labels)
    script = (
        "<script>"
        "const parentDocument=window.parent.document;"
        f"const targetLabels={labels_json};"
        "const activateTargetTabs=()=>{"
        "const tabs=Array.from(parentDocument.querySelectorAll("
        "'[data-testid=\"stTabs\"] button[role=\"tab\"]'));"
        "targetLabels.forEach((targetLabel)=>{"
        "const target=tabs.find((tab)=>tab.textContent.trim()===targetLabel);"
        "if(target&&target.getAttribute('aria-selected')!=='true'){target.click();}"
        "});"
        "};"
        "activateTargetTabs();"
        "window.setTimeout(activateTargetTabs,80);"
        "window.setTimeout(activateTargetTabs,220);"
        "window.setTimeout(activateTargetTabs,450);"
        "</script>"
    )
    render_browser_bridge(script)


def _activate_leave_tab(tab_label: str) -> None:
    """Select one visible Streamlit tab after notification navigation."""

    _activate_leave_tabs([tab_label])


def _notification_request_year(
    current_user: AuthenticatedUser,
    request_id: int | None,
) -> int | None:
    """Return the target request year after company-scoped validation."""

    if request_id is None:
        return None

    with SessionFactory() as session:
        service = LeaveService(session)
        request = service.get_request(
            current_user.company_id,
            request_id,
        )
        if request is None:
            return None
        return service.leave_cycle_year(
            current_user.company_id,
            request.start_date,
        )


def render_admin_leave_management_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render the simplified company-scoped Leave Management page."""

    st.title("Leave Management")
    st.caption(
        "Monitor leave activity, maintain employee leave accounts, "
        "review manager-routed requests, and configure leave rules."
    )
    render_operation_feedback(
        namespace="leave"
    )

    notification_request_id = _notification_leave_request_id()
    notification_year = _notification_request_year(
        current_user,
        notification_request_id,
    )

    if notification_request_id is not None and notification_year is None:
        st.error(
            "The leave request linked to this notification is unavailable."
        )

    if notification_year is not None:
        st.session_state["leave_management_year"] = notification_year
    elif "leave_management_year" not in st.session_state:
        st.session_state["leave_management_year"] = _current_leave_year(
            current_user.company_id
        )

    selected_year = int(
        st.number_input(
            "Leave Year",
            min_value=2000,
            max_value=2200,
            step=1,
            key="leave_management_year",
            help=(
                "The selected year applies to Overview, Employee Leave "
                "Accounts, and Leave Requests."
            ),
        )
    )

    with SessionFactory() as session:
        service = LeaveService(session)
        balances = service.list_company_balances(
            current_user.company_id,
            selected_year,
        )
        requests = service.list_company_requests(
            current_user.company_id,
            selected_year,
        )

    grouped = _group_balances(balances)

    overview_tab, accounts_tab, requests_tab, rules_tab, history_tab = persistent_tabs(
        [
            "Overview",
            "Employee Leave Accounts",
            "Leave Requests",
            "Leave Rules",
            "History",
        ],
        key="admin_leave_management_active_tab",
    )

    with overview_tab:
        _render_overview(
            current_user,
            selected_year,
            grouped,
            requests,
        )

    with accounts_tab:
        _render_employee_accounts(
            current_user,
            selected_year,
            grouped,
        )

    with requests_tab:
        _render_requests(
            current_user,
            selected_year,
            requests,
            selected_request_id=notification_request_id,
        )

    with rules_tab:
        _render_rules(current_user)

    with history_tab:
        _render_leave_history(current_user, selected_year, requests)

    restored_tabs = st.session_state.pop(
        _ADMIN_LEAVE_NEXT_TABS_KEY,
        None,
    )

    if restored_tabs:
        _activate_leave_tabs(
            [str(label) for label in restored_tabs]
        )
    elif notification_request_id is not None:
        _activate_leave_tab("Leave Requests")
