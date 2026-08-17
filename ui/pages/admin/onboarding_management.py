"""Admin onboarding progress, checklist setup, and benefit management."""

from __future__ import annotations

from datetime import date

import streamlit as st
from ui.components.validation_feedback import render_action_warning

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from services.onboarding_service import OnboardingService
from ui.components.data_table import render_admin_table
from ui.components.live_search import live_search_input
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)
from ui.onboarding_destinations import (
    ONBOARDING_DESTINATIONS,
    destination_label,
)


STATUS_LABELS = {
    "Pending": "pending",
    "In Progress": "in_progress",
    "Completed": "completed",
}
MODE_LABELS = {
    "Employee confirmation": "employee",
    "Admin confirmation": "admin",
    "Automatic from related record": "automatic",
}
AUTO_RULE_LABELS = {
    "Password changed": "password_changed",
    "First Time In recorded": "first_time_in",
    "All assigned training completed": "training_complete",
}


def _stay_on_onboarding(subtab: str) -> None:
    # These values are consumed before the keyed st.tabs widgets are created
    # on the next rerun. Streamlit does not allow mutating a widget's own
    # session-state key after that widget has already been instantiated.
    st.session_state["employees_pending_active_tab"] = "Onboarding Management"
    st.session_state["admin_onboarding_management_pending_active_tab"] = subtab


def _destination_fields(selected_label: str) -> dict[str, str | None]:
    page, query_key, query_value = ONBOARDING_DESTINATIONS[selected_label]
    return {
        "target_page": page,
        "target_query_key": query_key,
        "target_query_value": query_value,
    }


def _render_employee_progress(
    current_user: AuthenticatedUser,
    progress_rows: list[dict[str, object]],
) -> None:
    st.subheader("Employee Progress")
    st.caption(
        "Monitor each employee's required onboarding steps. Automatic items "
        "follow the linked account, attendance, or training record."
    )
    search = live_search_input(
        "Search Onboarding Progress",
        key="admin_onboarding_progress_search",
        placeholder="Search any employee-progress column…",
        suggestions=(
            value
            for row in progress_rows
            for value in row.values()
            if value is not None
        ),
    ).strip().casefold()
    filtered = [
        row
        for row in progress_rows
        if not search
        or search
        in " ".join(str(value or "") for value in row.values()).casefold()
    ]
    st.caption(f"Showing {len(filtered)} of {len(progress_rows)} employee record(s).")
    if filtered:
        render_admin_table(
            [
                {
                    "Employee Number": row["employee_number"],
                    "Employee": row["employee_name"],
                    "Department": row["department"],
                    "Position": row["position"],
                    "Hired Date": (
                        row["hire_date"].isoformat() if row["hire_date"] else "N/A"
                    ),
                    "Completed": f"{row['completed']} of {row['total']}",
                    "Progress": f"{row['percentage']}%",
                    "Status": row["status"],
                }
                for row in filtered
            ],
            key="admin-onboarding-progress",
            min_width=1180,
            column_widths=("140px", "210px", "170px", "180px", "130px", "130px", "110px", "130px"),
            max_height=360,
        )
    else:
        st.info("No employee onboarding progress matches the current search.")
        return

    employee_options = {
        f"{row['employee_number']} — {row['employee_name']}": int(row["employee_id"])
        for row in filtered
    }
    selected_employee_label = st.selectbox(
        "View Employee Checklist",
        options=list(employee_options),
        key="admin_onboarding_progress_employee",
    )
    employee_id = employee_options[selected_employee_label]
    with SessionFactory() as session:
        checklist = OnboardingService(session).sync_employee(
            company_id=current_user.company_id,
            employee_id=employee_id,
        )
    render_admin_table(
        [
            {
                "Checklist Item": item.title,
                "Required": "Yes" if item.is_required else "No",
                "Completion": item.completion_mode.title(),
                "Status": item.status.replace("_", " ").title(),
                "Completed": (
                    item.completed_at.strftime("%Y-%m-%d %I:%M %p")
                    if item.completed_at
                    else "—"
                ),
                "Note": item.note or "—",
            }
            for item in checklist
        ],
        key=f"admin-onboarding-employee-{employee_id}",
        min_width=1040,
        column_widths=("280px", "100px", "140px", "130px", "180px", "210px"),
        max_height=330,
    )

    editable = [item for item in checklist if item.completion_mode != "automatic"]
    if not editable:
        return
    with st.expander("Update Employee Onboarding Status", expanded=False):
        item_options = {item.title: item for item in editable}
        selected_item_label = st.selectbox(
            "Checklist Item",
            options=list(item_options),
            key=f"admin_onboarding_item_{employee_id}",
        )
        selected_item = item_options[selected_item_label]
        current_status_label = next(
            label for label, value in STATUS_LABELS.items() if value == selected_item.status
        )
        status_label = st.selectbox(
            "Status",
            options=list(STATUS_LABELS),
            index=list(STATUS_LABELS).index(current_status_label),
            key=f"admin_onboarding_status_{employee_id}_{selected_item.item_id}",
        )
        note = st.text_area(
            "Note",
            value=selected_item.note,
            height=100,
            key=f"admin_onboarding_note_{employee_id}_{selected_item.item_id}",
        )
        if st.button(
            "Save Onboarding Status",
            type="primary",
            width="stretch",
            key=f"admin_onboarding_save_{employee_id}_{selected_item.item_id}",
        ):
            try:
                with SessionFactory() as session:
                    OnboardingService(session).set_progress(
                        company_id=current_user.company_id,
                        employee_id=employee_id,
                        item_id=selected_item.item_id,
                        status=STATUS_LABELS[status_label],
                        actor_user_id=current_user.user_id,
                        note=note,
                    )
                _stay_on_onboarding("Employee Progress")
                set_operation_feedback(
                    "Employee onboarding status saved.",
                    namespace="onboarding",
                )
                st.rerun()
            except ValueError as error:
                render_action_warning(error)


def _checklist_form_values(prefix: str, item=None) -> dict[str, object] | None:
    title = st.text_input(
        "Checklist Title *",
        value=item.title if item else "",
        key=f"{prefix}_title",
    )
    description = st.text_area(
        "Description",
        value=item.description if item else "",
        height=100,
        key=f"{prefix}_description",
    )
    order_col, required_col = st.columns(2)
    with order_col:
        sort_order = st.number_input(
            "Display Order",
            min_value=0,
            value=int(item.sort_order if item else 10),
            step=10,
            key=f"{prefix}_order",
        )
    with required_col:
        is_required = st.checkbox(
            "Required",
            value=bool(item.is_required) if item else True,
            key=f"{prefix}_required",
        )
    current_mode = item.completion_mode if item else "employee"
    mode_label = next(label for label, value in MODE_LABELS.items() if value == current_mode)
    selected_mode_label = st.selectbox(
        "Completion Method",
        options=list(MODE_LABELS),
        index=list(MODE_LABELS).index(mode_label),
        key=f"{prefix}_mode",
    )
    mode = MODE_LABELS[selected_mode_label]
    auto_rule = None
    if mode == "automatic":
        current_rule = item.auto_rule if item and item.auto_rule else "password_changed"
        rule_label = next(label for label, value in AUTO_RULE_LABELS.items() if value == current_rule)
        selected_rule_label = st.selectbox(
            "Automatic Rule",
            options=list(AUTO_RULE_LABELS),
            index=list(AUTO_RULE_LABELS).index(rule_label),
            key=f"{prefix}_rule",
        )
        auto_rule = AUTO_RULE_LABELS[selected_rule_label]
    current_destination = destination_label(
        item.target_page if item else None,
        item.target_query_key if item else None,
        item.target_query_value if item else None,
    )
    destination = st.selectbox(
        "Related Workspace",
        options=list(ONBOARDING_DESTINATIONS),
        index=list(ONBOARDING_DESTINATIONS).index(current_destination),
        key=f"{prefix}_destination",
    )
    return {
        "title": title,
        "description": description,
        "sort_order": sort_order,
        "is_required": is_required,
        # Archiving and restoration are confirmation-protected actions below;
        # Add/Edit never changes the lifecycle state implicitly.
        "is_active": True,
        "completion_mode": mode,
        "auto_rule": auto_rule,
        **_destination_fields(destination),
    }


def _render_checklist_setup(current_user: AuthenticatedUser, items) -> None:
    st.subheader("Checklist Setup")
    st.caption(
        "Configure onboarding requirements and link each item to the original "
        "portal workspace. Documents and policies remain managed in their own modules."
    )
    active_items = [item for item in items if item.is_active]
    archived_items = [item for item in items if not item.is_active]
    if active_items:
        render_admin_table(
            [
            {
                "Order": item.sort_order,
                "Checklist Item": item.title,
                "Required": "Yes" if item.is_required else "No",
                "Completion": item.completion_mode.title(),
                "Related Workspace": item.target_page or "—",
                "Status": "Active" if item.is_active else "Inactive",
            }
                for item in active_items
            ],
            key="admin-onboarding-checklist-setup",
            min_width=1020,
            column_widths=("90px", "300px", "100px", "150px", "220px", "120px"),
            max_height=360,
        )
    else:
        st.info("No active onboarding checklist items. Add a new item or restore one from Archive.")
    with st.expander("Add Checklist Item", expanded=False):
        values = _checklist_form_values("onboarding_create_item")
        if st.button(
            "Add Checklist Item",
            type="primary",
            width="stretch",
            key="onboarding_create_item_submit",
        ):
            try:
                with SessionFactory() as session:
                    OnboardingService(session).create_checklist_item(
                        company_id=current_user.company_id,
                        values=values,
                    )
                _stay_on_onboarding("Checklist Setup")
                set_operation_feedback(
                    "Onboarding checklist item added.", namespace="onboarding"
                )
                st.rerun()
            except ValueError as error:
                render_action_warning(error)
    if active_items:
        with st.expander("Edit Checklist Item", expanded=False):
            item_options = {
                f"{item.sort_order} — {item.title}": item for item in active_items
            }
            selected_label = st.selectbox(
                "Select Checklist Item",
                options=list(item_options),
                key="onboarding_edit_item_selection",
            )
            item = item_options[selected_label]
            values = _checklist_form_values(f"onboarding_edit_item_{item.id}", item)
            if st.button(
                "Save Checklist Changes",
                type="primary",
                width="stretch",
                key=f"onboarding_edit_item_submit_{item.id}",
            ):
                try:
                    with SessionFactory() as session:
                        OnboardingService(session).update_checklist_item(
                            company_id=current_user.company_id,
                            item_id=item.id,
                            values=values,
                        )
                    _stay_on_onboarding("Checklist Setup")
                    set_operation_feedback(
                        "Onboarding checklist changes saved.", namespace="onboarding"
                    )
                    st.rerun()
                except ValueError as error:
                    render_action_warning(error)

        with st.expander("Delete / Move Checklist Item to Archive", expanded=False):
            archive_options = {
                f"{item.sort_order} — {item.title}": item.id for item in active_items
            }
            archive_label = st.selectbox(
                "Select Checklist Item",
                options=list(archive_options),
                key="onboarding_archive_item_selection",
            )
            archive_item_id = archive_options[archive_label]
            st.warning(
                "This safe-delete action moves the checklist item to Archive. "
                "Its employee progress history stays in the database and returns "
                "when the item is restored."
            )
            archive_confirmed = st.checkbox(
                "I confirm that this checklist item should be moved to Archive.",
                key=f"onboarding_archive_item_confirm_{archive_item_id}",
            )
            if st.button(
                "Move Checklist Item to Archive",
                width="stretch",
                disabled=not archive_confirmed,
                key=f"onboarding_archive_item_submit_{archive_item_id}",
            ):
                try:
                    with SessionFactory() as session:
                        title = OnboardingService(session).archive_checklist_item(
                            company_id=current_user.company_id,
                            item_id=archive_item_id,
                        )
                    st.session_state.pop("onboarding_archive_item_selection", None)
                    _stay_on_onboarding("Checklist Setup")
                    set_operation_feedback(
                        f"Checklist item moved to Archive: {title}",
                        namespace="onboarding",
                    )
                    st.rerun()
                except ValueError as error:
                    render_action_warning(error)

    with st.expander(
        f"Archived Checklist Items ({len(archived_items)})",
        expanded=False,
    ):
        if not archived_items:
            st.info("No archived onboarding checklist items.")
        else:
            render_admin_table(
                [
                    {
                        "Order": item.sort_order,
                        "Checklist Item": item.title,
                        "Completion": item.completion_mode.title(),
                        "Related Workspace": item.target_page or "—",
                    }
                    for item in archived_items
                ],
                key="admin-onboarding-checklist-archive",
                min_width=760,
                column_widths=("90px", "300px", "150px", "220px"),
                max_height=300,
            )
            restore_options = {
                f"{item.sort_order} — {item.title}": item.id for item in archived_items
            }
            restore_label = st.selectbox(
                "Select Archived Checklist Item",
                options=list(restore_options),
                key="onboarding_restore_item_selection",
            )
            restore_item_id = restore_options[restore_label]
            if st.button(
                "Restore Checklist Item",
                type="primary",
                width="stretch",
                key=f"onboarding_restore_item_submit_{restore_item_id}",
            ):
                try:
                    with SessionFactory() as session:
                        title = OnboardingService(session).restore_checklist_item(
                            company_id=current_user.company_id,
                            item_id=restore_item_id,
                        )
                    st.session_state.pop("onboarding_restore_item_selection", None)
                    _stay_on_onboarding("Checklist Setup")
                    set_operation_feedback(
                        f"Checklist item restored: {title}",
                        namespace="onboarding",
                    )
                    st.rerun()
                except ValueError as error:
                    render_action_warning(error)


def _benefit_form_values(prefix: str, benefit=None) -> dict[str, object]:
    name_col, category_col = st.columns([2, 1])
    with name_col:
        name = st.text_input(
            "Benefit Name *", value=benefit.name if benefit else "", key=f"{prefix}_name"
        )
    with category_col:
        category = st.text_input(
            "Category", value=benefit.category if benefit else "General", key=f"{prefix}_category"
        )
    description = st.text_area(
        "Description",
        value=benefit.description if benefit else "",
        height=130,
        key=f"{prefix}_description",
    )
    eligibility = st.text_input(
        "Eligibility",
        value=benefit.eligibility if benefit else "All employees",
        key=f"{prefix}_eligibility",
    )
    instructions = st.text_area(
        "Enrollment / Claim Instructions",
        value=benefit.enrollment_instructions if benefit else "",
        height=110,
        key=f"{prefix}_instructions",
    )
    contact_col, order_col = st.columns([2, 1])
    with contact_col:
        contact = st.text_input(
            "Contact Person / Team",
            value=benefit.contact_person if benefit and benefit.contact_person else "",
            key=f"{prefix}_contact",
        )
    with order_col:
        sort_order = st.number_input(
            "Display Order",
            min_value=0,
            value=int(benefit.sort_order if benefit else 10),
            step=10,
            key=f"{prefix}_order",
        )
    current_effective = benefit.effective_date if benefit else None
    set_effective = st.checkbox(
        "Set Effective Date",
        value=current_effective is not None,
        key=f"{prefix}_set_effective",
    )
    effective_date = None
    if set_effective:
        effective_date = st.date_input(
            "Effective Date",
            value=current_effective or date.today(),
            key=f"{prefix}_effective_date",
        )
    current_destination = destination_label(
        benefit.target_page if benefit else None,
        benefit.target_query_key if benefit else None,
        benefit.target_query_value if benefit else None,
    )
    destination = st.selectbox(
        "Related Workspace",
        options=list(ONBOARDING_DESTINATIONS),
        index=list(ONBOARDING_DESTINATIONS).index(current_destination),
        key=f"{prefix}_destination",
    )
    return {
        "name": name,
        "category": category,
        "description": description,
        "eligibility": eligibility,
        "effective_date": effective_date,
        "enrollment_instructions": instructions,
        "contact_person": contact,
        "sort_order": sort_order,
        # Benefits move between Active and Archive only through the explicit
        # confirmation-protected lifecycle controls.
        "is_active": True,
        **_destination_fields(destination),
    }


def _render_benefits_management(current_user: AuthenticatedUser, benefits) -> None:
    st.subheader("Benefits Management")
    st.caption(
        "Maintain the company benefits shown permanently in Employee Onboarding."
    )
    active_benefits = [benefit for benefit in benefits if benefit.is_active]
    archived_benefits = [benefit for benefit in benefits if not benefit.is_active]
    if active_benefits:
        render_admin_table(
            [
                {
                    "Order": benefit.sort_order,
                    "Benefit": benefit.name,
                    "Category": benefit.category,
                    "Eligibility": benefit.eligibility,
                    "Effective Date": (
                        benefit.effective_date.isoformat() if benefit.effective_date else "—"
                    ),
                    "Status": "Active" if benefit.is_active else "Inactive",
                }
                for benefit in active_benefits
            ],
            key="admin-onboarding-benefits",
            min_width=1000,
            column_widths=("90px", "260px", "150px", "260px", "140px", "110px"),
            max_height=330,
        )
    else:
        st.info("No active company benefits. Add a benefit or restore one from Archive.")
    with st.expander("Add Benefit", expanded=False):
        values = _benefit_form_values("onboarding_create_benefit")
        if st.button(
            "Add Benefit",
            type="primary",
            width="stretch",
            key="onboarding_create_benefit_submit",
        ):
            try:
                with SessionFactory() as session:
                    OnboardingService(session).create_benefit(
                        company_id=current_user.company_id,
                        values=values,
                    )
                _stay_on_onboarding("Benefits Management")
                set_operation_feedback("Company benefit added.", namespace="onboarding")
                st.rerun()
            except ValueError as error:
                render_action_warning(error)
    with st.expander("Edit Benefit", expanded=False):
        if not active_benefits:
            st.info("No active benefit is available to edit.")
        else:
            benefit_options = {
                f"{benefit.name} (ID {benefit.id})": benefit
                for benefit in active_benefits
            }
            selected_label = st.selectbox(
                "Select Benefit",
                options=list(benefit_options),
                key="onboarding_edit_benefit_selection",
            )
            benefit = benefit_options[selected_label]
            values = _benefit_form_values(
                f"onboarding_edit_benefit_{benefit.id}", benefit
            )
            if st.button(
                "Save Benefit Changes",
                type="primary",
                width="stretch",
                key=f"onboarding_edit_benefit_submit_{benefit.id}",
            ):
                try:
                    with SessionFactory() as session:
                        OnboardingService(session).update_benefit(
                            company_id=current_user.company_id,
                            benefit_id=benefit.id,
                            values=values,
                        )
                    _stay_on_onboarding("Benefits Management")
                    set_operation_feedback(
                        "Company benefit changes saved.", namespace="onboarding"
                    )
                    st.rerun()
                except ValueError as error:
                    render_action_warning(error)

    with st.expander("Delete / Move Benefit to Archive", expanded=False):
        if not active_benefits:
            st.info("No active benefit is available to move to Archive.")
        else:
            archive_options = {
                f"{benefit.name} (ID {benefit.id})": benefit.id
                for benefit in active_benefits
            }
            archive_label = st.selectbox(
                "Select Benefit",
                options=list(archive_options),
                key="onboarding_archive_benefit_selection",
            )
            archive_benefit_id = archive_options[archive_label]
            st.warning(
                "This safe-delete action removes the benefit from the Employee "
                "Portal and moves it to Archive. The company benefit record is retained."
            )
            archive_confirmed = st.checkbox(
                "I confirm that this benefit should be moved to Archive.",
                key=f"onboarding_archive_benefit_confirm_{archive_benefit_id}",
            )
            if st.button(
                "Move Benefit to Archive",
                width="stretch",
                disabled=not archive_confirmed,
                key=f"onboarding_archive_benefit_submit_{archive_benefit_id}",
            ):
                try:
                    with SessionFactory() as session:
                        name = OnboardingService(session).archive_benefit(
                            company_id=current_user.company_id,
                            benefit_id=archive_benefit_id,
                        )
                    st.session_state.pop("onboarding_archive_benefit_selection", None)
                    _stay_on_onboarding("Benefits Management")
                    set_operation_feedback(
                        f"Benefit moved to Archive: {name}",
                        namespace="onboarding",
                    )
                    st.rerun()
                except ValueError as error:
                    render_action_warning(error)

    with st.expander(
        f"Archived Benefits ({len(archived_benefits)})",
        expanded=False,
    ):
        if not archived_benefits:
            st.info("No archived company benefits.")
        else:
            render_admin_table(
                [
                    {
                        "Benefit": benefit.name,
                        "Category": benefit.category,
                        "Eligibility": benefit.eligibility,
                        "Effective Date": (
                            benefit.effective_date.isoformat()
                            if benefit.effective_date
                            else "—"
                        ),
                    }
                    for benefit in archived_benefits
                ],
                key="admin-onboarding-benefits-archive",
                min_width=840,
                column_widths=("260px", "160px", "280px", "140px"),
                max_height=300,
            )
            restore_options = {
                f"{benefit.name} (ID {benefit.id})": benefit.id
                for benefit in archived_benefits
            }
            restore_label = st.selectbox(
                "Select Archived Benefit",
                options=list(restore_options),
                key="onboarding_restore_benefit_selection",
            )
            restore_benefit_id = restore_options[restore_label]
            if st.button(
                "Restore Benefit",
                type="primary",
                width="stretch",
                key=f"onboarding_restore_benefit_submit_{restore_benefit_id}",
            ):
                try:
                    with SessionFactory() as session:
                        name = OnboardingService(session).restore_benefit(
                            company_id=current_user.company_id,
                            benefit_id=restore_benefit_id,
                        )
                    st.session_state.pop("onboarding_restore_benefit_selection", None)
                    _stay_on_onboarding("Benefits Management")
                    set_operation_feedback(
                        f"Benefit restored: {name}",
                        namespace="onboarding",
                    )
                    st.rerun()
                except ValueError as error:
                    render_action_warning(error)


def render_onboarding_management(current_user: AuthenticatedUser) -> None:
    """Render the Employees sub-workspace for onboarding administration."""

    render_operation_feedback(namespace="onboarding")
    with SessionFactory() as session:
        service = OnboardingService(session)
        progress_rows = service.company_progress_rows(current_user.company_id)
        items = service.list_items(current_user.company_id)
        benefits = service.list_benefits(current_user.company_id)

    pending_subtab = st.session_state.pop(
        "admin_onboarding_management_pending_active_tab", None
    )
    if pending_subtab in {
        "Employee Progress",
        "Checklist Setup",
        "Benefits Management",
    }:
        st.session_state["admin_onboarding_management_active_tab"] = pending_subtab

    progress_tab, checklist_tab, benefits_tab = st.tabs(
        ["Employee Progress", "Checklist Setup", "Benefits Management"],
        key="admin_onboarding_management_active_tab",
        on_change="rerun",
    )
    with progress_tab:
        _render_employee_progress(current_user, progress_rows)
    with checklist_tab:
        _render_checklist_setup(current_user, items)
    with benefits_tab:
        _render_benefits_management(current_user, benefits)
