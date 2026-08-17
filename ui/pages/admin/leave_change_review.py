"""HR review controls for an approved-leave cancellation request."""

from decimal import Decimal

from pydantic import ValidationError
import streamlit as st
from ui.components.validation_feedback import render_action_warning

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from schemas.leave_schema import LeaveCancellationDecisionInput
from services.leave_service import LeaveService
from ui.components.data_table import render_admin_table
from ui.components.operation_feedback import set_operation_feedback


def _days(value) -> str:
    return f"{Decimal(value):.2f}".rstrip("0").rstrip(".")


def render_hr_change_review(
    current_user: AuthenticatedUser,
    request,
) -> None:
    """Show cancellation audit details and HR decision controls when needed."""

    if (request.cancellation_status or "none") == "none":
        return

    render_admin_table(
        [
            {
                "Field": "Cancellation State",
                "Value": LeaveService.cancellation_label(request),
            },
            {
                "Field": "Requested By",
                "Value": (
                    request.cancellation_requested_by_employee.full_name
                    if request.cancellation_requested_by_employee is not None
                    else "—"
                ),
            },
            {
                "Field": "Reason",
                "Value": request.cancellation_reason or "—",
            },
            {
                "Field": "Effective Date",
                "Value": (
                    request.cancellation_effective_date.isoformat()
                    if request.cancellation_effective_date is not None
                    else "—"
                ),
            },
            {
                "Field": "Decision Comment",
                "Value": request.cancellation_comment or "—",
            },
            {
                "Field": "Restored Paid Credits",
                "Value": _days(
                    Decimal(request.cancellation_restored_primary_days or 0)
                    + Decimal(request.cancellation_restored_fallback_days or 0)
                ),
            },
        ],
        key=f"leave-change-review-{request.id}",
        min_width=820,
        column_widths=("190px", "630px"),
        compact=True,
    )

    if request.cancellation_status != "requested":
        return

    st.markdown("### HR Cancellation Review")
    comment = st.text_area(
        "HR Cancellation Comment (Optional)",
        max_chars=2000,
        height=100,
        key=f"admin_cancel_comment_{request.id}",
    )
    confirm_column, decline_column = st.columns(2)
    with confirm_column:
        confirmed = st.button(
            "Confirm Cancellation",
            type="primary",
            width="stretch",
            key=f"admin_confirm_cancel_{request.id}",
        )
    with decline_column:
        declined = st.button(
            "Decline Cancellation",
            width="stretch",
            key=f"admin_decline_cancel_{request.id}",
        )

    if not confirmed and not declined:
        return

    try:
        values = LeaveCancellationDecisionInput(
            company_id=current_user.company_id,
            request_id=request.id,
            reviewer_user_id=current_user.user_id,
            reviewer_employee_id=current_user.employee_id,
            decision="approve" if confirmed else "reject",
            comment=comment,
        )
        with st.spinner("Recording the cancellation decision…"):
            with SessionFactory() as session:
                reviewed = LeaveService(session).decide_leave_cancellation(values)
        set_operation_feedback(
            f"Cancellation of {reviewed.public_id} was "
            f"{'approved' if confirmed else 'rejected'}.",
            namespace="leave",
        )
        st.rerun()
    except (ValidationError, ValueError) as error:
        render_action_warning(error)
