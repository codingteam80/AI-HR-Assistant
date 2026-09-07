"""Administrator workspace for company violation and disciplinary rules."""

from __future__ import annotations

from datetime import date
import hashlib
import logging

import streamlit as st
from pydantic import ValidationError

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from schemas.policy_violation_schema import (
    PolicyViolationCreateRequest,
    PolicyViolationUpdateRequest,
)
from services.policy_service import PolicyService
from services.policy_violation_service import (
    PolicyViolationService,
    VIOLATION_SEVERITIES,
)
from services.policy_violation_bulk_import_service import (
    PolicyViolationBulkImportService,
    VIOLATION_PREVIEW_COLUMNS,
)
from ui.components.confirmation_guard import invalidate_confirmation_on_change
from ui.components.data_table import render_admin_table
from ui.components.live_search import multi_search_input
from ui.components.operation_feedback import render_operation_feedback, set_operation_feedback
from ui.components.persistent_tabs import persistent_tabs
from ui.components.validation_feedback import render_action_warning
from utils.search_utils import matches_visible_row


_VIOLATION_ADD_NONCE_KEY = "_policy_violation_add_nonce"
_VIOLATION_BULK_PREVIEW_KEY = "policy_violation_bulk_preview"
_VIOLATION_BULK_FILENAME_KEY = "policy_violation_bulk_filename"
_VIOLATION_BULK_DIGEST_KEY = "policy_violation_bulk_digest"


logger = logging.getLogger(__name__)


def _add_nonce() -> int:
    try:
        return max(0, int(st.session_state.get(_VIOLATION_ADD_NONCE_KEY, 0)))
    except (TypeError, ValueError):
        return 0


def _policy_options(current_user: AuthenticatedUser):
    with SessionFactory() as session:
        service = PolicyService(session)
        active = service.list_for_admin(current_user.company_id)
        all_versions = service.list_all_versions(current_user.company_id)
    labels = {
        0: "None / Not linked",
        **{
            policy.id: (
                f"{PolicyService.public_id_for(policy)} · "
                f"{policy.title} · v{policy.version}"
            )
            for policy in active
        },
    }
    all_labels = {
        policy.id: f"{policy.title} · v{policy.version}"
        for policy in all_versions
    }
    return labels, all_labels


def _table_rows(items, *, company_id: int, policy_labels: dict[int, str]):
    rows = []
    for item in items:
        rows.append(
            {
                "Code": item.violation_code,
                "Category": item.category,
                "Violation / Offense": item.offense_title,
                "Severity": item.severity,
                "Description": item.description,
                "1st Offense": item.first_offense_action,
                "2nd Offense": item.second_offense_action,
                "3rd Offense": item.third_offense_action,
                "Final / Maximum": item.final_action,
                "Related Policy": (
                    policy_labels.get(item.related_policy_id, "Unavailable policy")
                    if item.related_policy_id
                    else "—"
                ),
                "Effective Date": (
                    item.effective_date.isoformat() if item.effective_date else "Immediate"
                ),
                "Status": item.status.title(),
                "Notes": item.notes or "—",
            }
        )
    return rows


def _current_list(
    current_user: AuthenticatedUser,
    items,
    policy_labels: dict[int, str],
) -> None:
    st.subheader("Violation Master List")
    st.caption(
        "Company-defined violations and disciplinary actions. Archived rules are "
        "kept separately and are not visible to employees."
    )

    categories = sorted({item.category for item in items})
    search = multi_search_input(
        "Search Violations",
        placeholder="Type any value shown in the violations table, then press Enter…",
        key="admin_policy_violation_search"
    )
    cols = st.columns(3)
    with cols[0]:
        category = st.selectbox(
            "Category",
            ["All Categories", *categories],
            key="admin_policy_violation_category_filter",
        )
    with cols[1]:
        severity = st.selectbox(
            "Severity",
            ["All Severities", *VIOLATION_SEVERITIES],
            key="admin_policy_violation_severity_filter",
        )
    with cols[2]:
        status = st.selectbox(
            "Status",
            ["All Statuses", "Active", "Inactive"],
            key="admin_policy_violation_status_filter",
        )

    candidate_items = [
        item for item in items
        if (category == "All Categories" or item.category == category)
        and (severity == "All Severities" or item.severity == severity)
        and (status == "All Statuses" or item.status == status.casefold())
    ]
    candidate_rows = _table_rows(
        candidate_items,
        company_id=current_user.company_id,
        policy_labels=policy_labels,
    )
    filtered_pairs = [
        (item, row)
        for item, row in zip(candidate_items, candidate_rows, strict=True)
        if matches_visible_row(search, row)
    ]
    filtered = [item for item, _ in filtered_pairs]
    filtered_rows = [row for _, row in filtered_pairs]

    st.caption(f"{len(filtered)} of {len(items)} current violation rule(s) shown.")
    if not filtered:
        st.info("No matching violation rules were found.")
        return

    render_admin_table(
        filtered_rows,
        key="policy-violation-current-list",
        min_width=1800,
        max_height=430,
        compact=True,
    )




def _render_bulk_violation_upload(current_user: AuthenticatedUser) -> None:
    """Render template download, validation preview, and atomic bulk import."""

    with st.expander("Bulk Add Violations via Excel", expanded=False):
        st.caption(
            "Download the company-aware template, enter one violation per row, "
            "then validate and preview before importing. Hover Excel column "
            "headers to see field guidance and complete valid selections; closed "
            "choices also have dropdowns. Existing and duplicate Violation Codes "
            "are blocked before any batch is saved."
        )
        with SessionFactory() as session:
            template_data = PolicyViolationBulkImportService(session).build_template(
                company_id=current_user.company_id,
            )
        st.download_button(
            "Download Violation Excel Template",
            data=template_data,
            file_name="Violation_Import_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="content",
            key="policy_violation_bulk_template_download",
        )

        uploaded_file = st.file_uploader(
            "Upload Completed Violation Template",
            type=["xlsx"],
            accept_multiple_files=False,
            key="policy_violation_bulk_upload_file",
            help="Only the downloadable .xlsx Violation template is accepted. Maximum file size: 10 MB.",
        )
        uploaded_bytes = uploaded_file.getvalue() if uploaded_file is not None else None
        uploaded_digest = (
            hashlib.sha256(uploaded_bytes).hexdigest()
            if uploaded_bytes is not None
            else None
        )
        stored_digest = st.session_state.get(_VIOLATION_BULK_DIGEST_KEY)
        if st.session_state.get(_VIOLATION_BULK_PREVIEW_KEY) is not None and (
            uploaded_digest is None or uploaded_digest != stored_digest
        ):
            # Never allow an old validated preview to be imported after the
            # uploader contents were removed or replaced.
            st.session_state.pop(_VIOLATION_BULK_PREVIEW_KEY, None)
            st.session_state.pop(_VIOLATION_BULK_FILENAME_KEY, None)
            st.session_state.pop(_VIOLATION_BULK_DIGEST_KEY, None)

        validate_clicked = st.button(
            "Validate and Preview Violations",
            width="stretch",
            disabled=uploaded_file is None,
            key="policy_violation_bulk_validate",
        )
        if validate_clicked and uploaded_file is not None:
            try:
                if uploaded_file.size > 10 * 1024 * 1024:
                    raise ValueError("The Violation Excel file must not exceed 10 MB.")
                with st.spinner("Validating violation master records…"):
                    with SessionFactory() as session:
                        preview = PolicyViolationBulkImportService(session).prepare_preview(
                            uploaded_bytes or b"",
                            filename=uploaded_file.name,
                            company_id=current_user.company_id,
                        )
                st.session_state[_VIOLATION_BULK_PREVIEW_KEY] = preview
                st.session_state[_VIOLATION_BULK_FILENAME_KEY] = uploaded_file.name
                st.session_state[_VIOLATION_BULK_DIGEST_KEY] = uploaded_digest
            except ValueError as error:
                st.session_state.pop(_VIOLATION_BULK_PREVIEW_KEY, None)
                st.session_state.pop(_VIOLATION_BULK_FILENAME_KEY, None)
                st.session_state.pop(_VIOLATION_BULK_DIGEST_KEY, None)
                render_action_warning(error)

        preview_rows = st.session_state.get(_VIOLATION_BULK_PREVIEW_KEY)
        if isinstance(preview_rows, list) and preview_rows:
            st.markdown("#### Violation Import Preview")
            st.caption(
                "Review every row. Invalid rows must be corrected in Excel and "
                "validated again. Import is atomic, so a failed batch saves nothing."
            )
            display_rows = [
                {column: row.get(column, "") for column in VIOLATION_PREVIEW_COLUMNS}
                for row in preview_rows
            ]
            st.data_editor(
                display_rows,
                width="stretch",
                hide_index=True,
                disabled=list(VIOLATION_PREVIEW_COLUMNS),
                key="policy_violation_bulk_preview_editor",
            )
            invalid_count = sum(
                str(row.get("Validation", "")) != "Ready"
                for row in preview_rows
            )
            if invalid_count:
                st.error(
                    f"{invalid_count} row(s) contain validation errors. "
                    "Correct the Excel file and validate it again."
                )

            import_clicked = st.button(
                "Import Violations",
                type="primary",
                width="stretch",
                disabled=invalid_count > 0,
                key="policy_violation_bulk_import_submit",
            )
            if import_clicked:
                try:
                    with st.spinner("Importing violation master records…"):
                        with SessionFactory() as session:
                            created = PolicyViolationBulkImportService(session).import_preview_rows(
                                preview_rows,
                                company_id=current_user.company_id,
                                actor_user_id=current_user.user_id,
                            )
                    st.session_state.pop(_VIOLATION_BULK_PREVIEW_KEY, None)
                    st.session_state.pop(_VIOLATION_BULK_FILENAME_KEY, None)
                    st.session_state.pop(_VIOLATION_BULK_DIGEST_KEY, None)
                    set_operation_feedback(
                        f"Successfully imported {len(created)} violation rule(s).",
                        namespace="policy_violation",
                    )
                    st.rerun()
                except (ValidationError, ValueError) as error:
                    render_action_warning(error)
                except Exception:
                    logger.exception("Unexpected policy violation bulk import failure")
                    st.error(
                        "The violation batch could not be imported. No violation "
                        "from this batch was saved."
                    )

def _add_form(
    current_user: AuthenticatedUser,
    policy_options: dict[int, str],
) -> None:
    st.subheader("Add Violation")
    st.caption(
        "Create reusable company violation/offense definitions. Employee case "
        "records are intentionally separate from this master list."
    )
    _render_bulk_violation_upload(current_user)
    st.divider()
    st.markdown("#### Add One Violation Manually")
    nonce = _add_nonce()
    prefix = f"policy_violation_add_{nonce}"
    ids = list(policy_options.keys())

    with st.form(f"{prefix}_form"):
        row = st.columns(2)
        with row[0]:
            code = st.text_input("Violation Code", placeholder="ATT-001", key=f"{prefix}_code")
        with row[1]:
            category = st.text_input("Category", placeholder="Attendance", key=f"{prefix}_category")

        row = st.columns([2, 1])
        with row[0]:
            offense_title = st.text_input(
                "Violation / Offense",
                placeholder="Habitual Tardiness",
                key=f"{prefix}_title",
            )
        with row[1]:
            severity = st.selectbox(
                "Severity",
                VIOLATION_SEVERITIES,
                key=f"{prefix}_severity",
            )

        description = st.text_area(
            "Description",
            height=110,
            key=f"{prefix}_description",
        )

        row = st.columns(2)
        with row[0]:
            first_action = st.text_area("1st Offense", height=90, key=f"{prefix}_first")
            third_action = st.text_area("3rd Offense", height=90, key=f"{prefix}_third")
        with row[1]:
            second_action = st.text_area("2nd Offense", height=90, key=f"{prefix}_second")
            final_action = st.text_area(
                "Final / Maximum Action",
                height=90,
                key=f"{prefix}_final",
            )

        row = st.columns([2, 1, 1])
        with row[0]:
            related_policy_id = st.selectbox(
                "Related Policy",
                ids,
                format_func=lambda value: policy_options[value],
                key=f"{prefix}_policy",
            )
        with row[1]:
            effective_date = st.date_input(
                "Effective Date",
                value=date.today(),
                key=f"{prefix}_effective",
            )
        with row[2]:
            status_label = st.selectbox(
                "Status",
                ["Active", "Inactive"],
                key=f"{prefix}_status",
            )

        notes = st.text_area(
            "Notes",
            height=90,
            key=f"{prefix}_notes",
        )
        submitted = st.form_submit_button(
            "Save Violation",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return
    try:
        request = PolicyViolationCreateRequest(
            company_id=current_user.company_id,
            created_by_user_id=current_user.user_id,
            violation_code=code,
            category=category,
            offense_title=offense_title,
            description=description,
            severity=severity,
            first_offense_action=first_action,
            second_offense_action=second_action,
            third_offense_action=third_action,
            final_action=final_action,
            related_policy_id=(related_policy_id or None),
            effective_date=effective_date,
            status=status_label.casefold(),
            notes=notes or None,
        )
        with SessionFactory() as session:
            created = PolicyViolationService(session).create_violation(request)
        st.session_state[_VIOLATION_ADD_NONCE_KEY] = nonce + 1
        set_operation_feedback(
            f"Saved {created.violation_code} · {created.offense_title}.",
            namespace="policy_violation",
        )
        st.rerun()
    except (ValidationError, ValueError) as error:
        render_action_warning(error)


def _edit_form(
    current_user: AuthenticatedUser,
    items,
    policy_options: dict[int, str],
) -> None:
    st.subheader("Edit Violation")
    if not items:
        st.info("Add a violation before editing the master list.")
        return

    labels = {
        f"{item.violation_code} · {item.offense_title}": item.id
        for item in items
    }
    selected_label = st.selectbox(
        "Select Violation",
        list(labels),
        key="policy_violation_edit_selector",
    )
    selected_id = labels[selected_label]
    item = next(item for item in items if item.id == selected_id)
    prefix = f"policy_violation_edit_{item.id}"
    ids = list(policy_options.keys())
    policy_index = ids.index(item.related_policy_id) if item.related_policy_id in ids else 0

    with st.form(f"{prefix}_form"):
        row = st.columns(2)
        with row[0]:
            code = st.text_input("Violation Code", value=item.violation_code, key=f"{prefix}_code")
        with row[1]:
            category = st.text_input("Category", value=item.category, key=f"{prefix}_category")

        row = st.columns([2, 1])
        with row[0]:
            offense_title = st.text_input(
                "Violation / Offense", value=item.offense_title, key=f"{prefix}_title"
            )
        with row[1]:
            severity = st.selectbox(
                "Severity",
                VIOLATION_SEVERITIES,
                index=VIOLATION_SEVERITIES.index(item.severity),
                key=f"{prefix}_severity",
            )

        description = st.text_area(
            "Description", value=item.description, height=110, key=f"{prefix}_description"
        )
        row = st.columns(2)
        with row[0]:
            first_action = st.text_area(
                "1st Offense", value=item.first_offense_action, height=90, key=f"{prefix}_first"
            )
            third_action = st.text_area(
                "3rd Offense", value=item.third_offense_action, height=90, key=f"{prefix}_third"
            )
        with row[1]:
            second_action = st.text_area(
                "2nd Offense", value=item.second_offense_action, height=90, key=f"{prefix}_second"
            )
            final_action = st.text_area(
                "Final / Maximum Action", value=item.final_action, height=90, key=f"{prefix}_final"
            )

        row = st.columns([2, 1, 1])
        with row[0]:
            related_policy_id = st.selectbox(
                "Related Policy",
                ids,
                index=policy_index,
                format_func=lambda value: policy_options[value],
                key=f"{prefix}_policy",
            )
        with row[1]:
            effective_date = st.date_input(
                "Effective Date",
                value=item.effective_date or date.today(),
                key=f"{prefix}_effective",
            )
        with row[2]:
            status_options = ["Active", "Inactive"]
            status_label = st.selectbox(
                "Status",
                status_options,
                index=status_options.index(item.status.title()),
                key=f"{prefix}_status",
            )

        notes = st.text_area(
            "Notes", value=item.notes or "", height=90, key=f"{prefix}_notes"
        )
        submitted = st.form_submit_button(
            "Save Changes",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return
    try:
        request = PolicyViolationUpdateRequest(
            company_id=current_user.company_id,
            violation_id=item.id,
            edited_by_user_id=current_user.user_id,
            violation_code=code,
            category=category,
            offense_title=offense_title,
            description=description,
            severity=severity,
            first_offense_action=first_action,
            second_offense_action=second_action,
            third_offense_action=third_action,
            final_action=final_action,
            related_policy_id=(related_policy_id or None),
            effective_date=effective_date,
            status=status_label.casefold(),
            notes=notes or None,
        )
        with SessionFactory() as session:
            updated = PolicyViolationService(session).update_violation(request)
        set_operation_feedback(
            f"Updated {updated.violation_code} · {updated.offense_title}.",
            namespace="policy_violation",
        )
        st.rerun()
    except (ValidationError, ValueError) as error:
        render_action_warning(error)


def _archive_workspace(
    current_user: AuthenticatedUser,
    current_items,
    archived_items,
    policy_labels: dict[int, str],
) -> None:
    st.subheader("Violation Archive")
    st.caption(
        "Archive removes a violation rule from the employee directory without "
        "deleting its history. Restore makes the same rule available again based "
        "on its Status and Effective Date."
    )

    if current_items:
        options = {
            f"{item.violation_code} · {item.offense_title}": item.id
            for item in current_items
        }
        selected_label = st.selectbox(
            "Select Current Violation",
            list(options),
            key="policy_violation_archive_selector",
        )
        selected_id = options[selected_label]
        selected = next(item for item in current_items if item.id == selected_id)
        confirmation_key = "policy_violation_archive_confirm"
        invalidate_confirmation_on_change(
            confirmation_key=confirmation_key,
            dependencies={
                "violation_id": selected.id,
                "violation_code": selected.violation_code,
            },
        )
        confirmed = st.checkbox(
            f"I confirm that {selected.violation_code} will be archived.",
            key=confirmation_key,
        )
        if st.button(
            "Archive Selected Violation",
            type="primary",
            width="stretch",
            disabled=not confirmed,
            key="policy_violation_archive_button",
        ):
            try:
                with SessionFactory() as session:
                    archived = PolicyViolationService(session).archive_violation(
                        company_id=current_user.company_id,
                        violation_id=selected.id,
                        archived_by_user_id=current_user.user_id,
                    )
                set_operation_feedback(
                    f"Archived {archived.violation_code} · {archived.offense_title}.",
                    namespace="policy_violation",
                )
                st.rerun()
            except ValueError as error:
                render_action_warning(error)
    else:
        st.info("No current violation rules are available to archive.")

    st.divider()
    st.markdown(f"**Archived Rules ({len(archived_items)})**")
    if not archived_items:
        st.info("The violation archive is empty.")
        return

    render_admin_table(
        _table_rows(
            archived_items,
            company_id=current_user.company_id,
            policy_labels=policy_labels,
        ),
        key="policy-violation-archive-list",
        min_width=1600,
        max_height=320,
        compact=True,
    )
    restore_options = {
        f"{item.violation_code} · {item.offense_title}": item.id
        for item in archived_items
    }
    restore_label = st.selectbox(
        "Select Archived Violation",
        list(restore_options),
        key="policy_violation_restore_selector",
    )
    if st.button(
        "Restore Selected Violation",
        type="primary",
        width="stretch",
        key="policy_violation_restore_button",
    ):
        try:
            with SessionFactory() as session:
                restored = PolicyViolationService(session).restore_violation(
                    company_id=current_user.company_id,
                    violation_id=restore_options[restore_label],
                    restored_by_user_id=current_user.user_id,
                )
            set_operation_feedback(
                f"Restored {restored.violation_code} · {restored.offense_title}.",
                namespace="policy_violation",
            )
            st.rerun()
        except ValueError as error:
            render_action_warning(error)


def render_admin_policy_violations(
    current_user: AuthenticatedUser,
) -> None:
    """Render the violation master-list workspace inside Admin → Policies."""

    render_operation_feedback(namespace="policy_violation")
    with SessionFactory() as session:
        service = PolicyViolationService(session)
        current_items = service.list_current(current_user.company_id)
        archived_items = service.list_archived(current_user.company_id)
    policy_options, policy_labels = _policy_options(current_user)

    tabs = persistent_tabs(
        ["Current Violations", "Add Violation", "Edit Violation", "Archive"],
        key="admin_policy_violations_active_tab",
    )
    with tabs[0]:
        _current_list(current_user, current_items, policy_labels)
    with tabs[1]:
        _add_form(current_user, policy_options)
    with tabs[2]:
        _edit_form(current_user, current_items, policy_options)
    with tabs[3]:
        _archive_workspace(
            current_user,
            current_items,
            archived_items,
            policy_labels,
        )
