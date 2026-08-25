"""Employee onboarding overview, checklist, and permanent benefits."""

from __future__ import annotations

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from ui.components.persistent_tabs import persistent_tabs

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from repositories.employee_repository import EmployeeRepository
from services.onboarding_service import OnboardingService
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)
from ui.module_view_navigation import EXACT_VIEW_QUERY_KEYS, prime_exact_module_view
from ui.navigation_state import set_navigation_state


def _open_destination(
    *,
    page: str,
    query_key: str | None,
    query_value: str | None,
) -> None:
    """Open the exact existing employee module linked by onboarding."""

    for key in {
        "announcement_id",
        "employee_id",
        "leave_request_id",
        "policy_id",
    } | EXACT_VIEW_QUERY_KEYS:
        if key in st.query_params:
            del st.query_params[key]
    params = {query_key: query_value} if query_key and query_value else {}
    prime_exact_module_view(
        portal_mode="employee",
        page=page,
        query_params=params,
    )
    set_navigation_state(portal_mode="employee", current_page=page)
    for key, value in params.items():
        st.query_params[key] = value
    st.rerun()


def _render_overview(employee, checklist) -> None:
    required = [item for item in checklist if item.is_required]
    completed = sum(item.status == "completed" for item in required)
    total = len(required)
    percentage = round((completed / total) * 100) if total else 100
    next_item = next((item for item in required if item.status != "completed"), None)

    metrics = st.columns(4)
    metrics[0].metric("Required Steps", total)
    metrics[1].metric("Completed", completed)
    metrics[2].metric("Remaining", max(0, total - completed))
    metrics[3].metric("Progress", f"{percentage}%")

    with st.container(border=True):
        st.markdown("### Employee Information")
        info_columns = st.columns(3)
        info_columns[0].markdown(
            f"**Employee Number**  \n{employee.employee_number}\n\n"
            f"**Employee Name**  \n{employee.full_name}"
        )
        info_columns[1].markdown(
            f"**Department**  \n{employee.department.name if employee.department else 'N/A'}\n\n"
            f"**Position**  \n{employee.job_title or 'N/A'}"
        )
        info_columns[2].markdown(
            f"**Hired Date**  \n{employee.hire_date.isoformat() if employee.hire_date else 'N/A'}\n\n"
            f"**Years of Service**  \n{employee.years_of_service if employee.years_of_service is not None else 'N/A'}"
        )

    with st.container(border=True):
        st.markdown("### Next Required Action")
        if next_item is None:
            st.success("All required onboarding steps are complete.")
        else:
            st.markdown(f"**{next_item.title}**")
            st.write(next_item.description or "Complete this required onboarding step.")
            st.caption(
                "Completion: "
                + (
                    "Automatically verified from the related record."
                    if next_item.completion_mode == "automatic"
                    else "Employee confirmation."
                    if next_item.completion_mode == "employee"
                    else "Administrator confirmation."
                )
            )
            if next_item.target_page and st.button(
                "Open Related Workspace",
                width="stretch",
                key=f"onboarding_overview_open_{next_item.item_id}",
            ):
                _open_destination(
                    page=next_item.target_page,
                    query_key=next_item.target_query_key,
                    query_value=next_item.target_query_value,
                )


def _render_checklist(current_user: AuthenticatedUser, checklist) -> None:
    st.subheader("Onboarding Checklist")
    st.caption(
        "Use the related workspace for each step. Automatic items follow your "
        "actual account, attendance, or assigned training record."
    )
    for item in checklist:
        with st.container(border=True, key=f"employee_onboarding_item_{item.item_id}"):
            (
                detail_column,
                status_column,
                workspace_column,
                completion_column,
            ) = st.columns(
                [4.6, 1.35, 1.9, 1.9],
                vertical_alignment="center",
            )
            with detail_column:
                st.markdown(f"**{item.title}**")
                if item.description:
                    st.caption(item.description)
                st.caption(
                    ("Required" if item.is_required else "Optional")
                    + " · "
                    + (
                        "Automatic"
                        if item.completion_mode == "automatic"
                        else "Employee confirmation"
                        if item.completion_mode == "employee"
                        else "Admin confirmation"
                    )
                )
            with status_column:
                if item.status == "completed":
                    st.success("Completed")
                elif item.status == "in_progress":
                    st.info("In Progress")
                else:
                    st.warning("Pending")

            if item.target_page:
                with workspace_column:
                    if st.button(
                        "Open Related Workspace",
                        width="stretch",
                        key=f"employee_onboarding_open_{item.item_id}",
                    ):
                        _open_destination(
                            page=item.target_page,
                            query_key=item.target_query_key,
                            query_value=item.target_query_value,
                        )
            if item.completion_mode == "employee":
                next_status = "pending" if item.status == "completed" else "completed"
                button_label = (
                    "Mark as Pending" if item.status == "completed" else "Mark as Completed"
                )
                with completion_column:
                    if st.button(
                        button_label,
                        type="primary" if next_status == "completed" else "secondary",
                        width="stretch",
                        key=f"employee_onboarding_status_{item.item_id}_{next_status}",
                    ):
                        try:
                            with SessionFactory() as session:
                                OnboardingService(session).set_progress(
                                    company_id=current_user.company_id,
                                    employee_id=int(current_user.employee_id),
                                    item_id=item.item_id,
                                    status=next_status,
                                    actor_user_id=current_user.user_id,
                                    employee_self_service=True,
                                )
                            st.session_state[
                                "employee_onboarding_pending_active_tab"
                            ] = "Checklist"
                            set_operation_feedback(
                                "Onboarding checklist status saved.",
                                namespace="employee_onboarding",
                            )
                            st.rerun()
                        except ValueError as error:
                            render_action_warning(error)
            elif item.completion_mode == "automatic" and item.status != "completed":
                with completion_column:
                    st.caption("Completes automatically from the related record.")
            elif item.completion_mode == "admin" and item.status != "completed":
                with completion_column:
                    st.caption("Awaiting administrator confirmation.")


def _render_benefits(benefits) -> None:
    st.subheader("Employee Benefits")
    st.caption(
        "Company benefits remain available here after onboarding is completed."
    )
    if not benefits:
        st.info("No active company benefits have been published yet.")
        return
    for benefit in benefits:
        with st.container(border=True, key=f"employee_benefit_{benefit.id}"):
            st.markdown(f"### {benefit.name}")
            st.caption(
                f"{benefit.category} · Eligibility: {benefit.eligibility}"
                + (
                    f" · Effective {benefit.effective_date.isoformat()}"
                    if benefit.effective_date
                    else ""
                )
            )
            if benefit.description:
                st.write(benefit.description)
            if benefit.enrollment_instructions:
                st.markdown("**Enrollment / Claim Instructions**")
                st.write(benefit.enrollment_instructions)
            if benefit.contact_person:
                st.markdown(f"**Contact:** {benefit.contact_person}")
            if benefit.target_page and st.button(
                "Open Related Workspace",
                width="stretch",
                key=f"employee_benefit_open_{benefit.id}",
            ):
                _open_destination(
                    page=benefit.target_page,
                    query_key=benefit.target_query_key,
                    query_value=benefit.target_query_value,
                )


def render_employee_onboarding_page(current_user: AuthenticatedUser) -> None:
    """Render the consolidated employee onboarding and benefits workspace."""

    st.title("Onboarding")
    st.caption(
        "Track your onboarding progress, complete assigned steps, and review "
        "the company benefits available to you."
    )
    render_operation_feedback(namespace="employee_onboarding")
    if current_user.employee_id is None:
        st.error(
            "Your login account is not linked to an employee record. "
            "Contact your administrator."
        )
        return
    with SessionFactory() as session:
        employee = EmployeeRepository(session).get_with_details(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
        )
        if employee is None:
            st.error("Your employee record is unavailable for this company.")
            return
        service = OnboardingService(session)
        checklist = service.sync_employee(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
        )
        benefits = service.list_benefits(current_user.company_id, active_only=True)

    pending_tab = st.session_state.pop(
        "employee_onboarding_pending_active_tab", None
    )
    if pending_tab in {"Overview", "Checklist", "Benefits"}:
        st.session_state["employee_onboarding_active_tab"] = pending_tab

    overview_tab, checklist_tab, benefits_tab = persistent_tabs(
        ["Overview", "Checklist", "Benefits"],
        key="employee_onboarding_active_tab",
    )
    with overview_tab:
        _render_overview(employee, checklist)
    with checklist_tab:
        _render_checklist(current_user, checklist)
    with benefits_tab:
        _render_benefits(benefits)
