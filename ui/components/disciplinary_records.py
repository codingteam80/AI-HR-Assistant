"""Administrator and employee UI for disciplinary case records."""

from datetime import date, datetime
import hashlib
import logging
from zoneinfo import ZoneInfo

import streamlit as st
from pydantic import ValidationError

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from schemas.disciplinary_record_schema import (
    DisciplinaryRecordCreateRequest,
    DisciplinaryRecordUpdateRequest,
)
from services.admin_management_service import AdminManagementService
from services.disciplinary_record_service import (
    ACKNOWLEDGMENT_STATUSES,
    CASE_STATUSES,
    DisciplinaryRecordService,
)
from services.disciplinary_record_bulk_import_service import (
    DISCIPLINARY_PREVIEW_COLUMNS,
    DisciplinaryRecordBulkImportService,
)
from services.policy_violation_service import PolicyViolationService
from ui.components.confirmation_guard import invalidate_confirmation_on_change
from ui.components.data_table import render_admin_table
from ui.components.live_search import multi_search_input
from utils.search_utils import matches_visible_row
from ui.components.operation_feedback import render_operation_feedback, set_operation_feedback
from ui.components.persistent_tabs import persistent_tabs
from ui.components.validation_feedback import render_action_warning


logger = logging.getLogger(__name__)
_DISCIPLINARY_BULK_PREVIEW_KEY = "disciplinary_bulk_preview_rows"
_DISCIPLINARY_BULK_DIGEST_KEY = "disciplinary_bulk_preview_digest"


def _today() -> date:
    return datetime.now(ZoneInfo(get_settings().display_timezone)).date()


def _optional(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _user_labels(users) -> dict[int, str]:
    return {
        user.id: (
            user.employee.full_name
            if user.employee is not None
            else user.username
        )
        for user in users
    }


def _case_rows(records, service: DisciplinaryRecordService, user_labels: dict[int, str]):
    rows: list[dict[str, object]] = []
    for item in records:
        rows.append(
            {
                "Case ID": item.public_id,
                "Employee": f"{item.employee_number} — {item.employee_name}",
                "Violation": f"{item.violation_code} — {item.violation_title}",
                "Incident Date": item.incident_date.isoformat(),
                "Incident / Case Description": item.incident_description,
                "Evidence / Remarks": item.evidence_remarks or "—",
                "Project / Team / Department": item.context_snapshot or "—",
                "Previous Offense Count": item.previous_offense_count,
                "Current Offense": item.offense_level,
                "Suggested Disciplinary Action": service.suggested_action_for_record(item),
                "Actual Action Taken": item.actual_action_taken or "—",
                "Issued By": user_labels.get(item.issued_by_user_id, "—"),
                "Reviewed / Approved By": user_labels.get(item.reviewed_approved_by_user_id, "—"),
                "Date Issued": item.date_issued.isoformat() if item.date_issued else "—",
                "Employee Acknowledgment": item.employee_acknowledgment,
                "Case Status": item.case_status,
                "Notes": item.notes or "—",
            }
        )
    return rows


def _matches(row: dict[str, object], search_terms) -> bool:
    """Match against every value rendered in the disciplinary table row."""

    return matches_visible_row(search_terms, row)


def _user_select_options(users, *, include_none: bool) -> dict[str, int | None]:
    labels = _user_labels(users)
    output: dict[str, int | None] = {"None": None} if include_none else {}
    for user in users:
        if not user.is_active:
            continue
        output[f"{labels[user.id]} · @{user.username}"] = user.id
    return output


def _index_for_value(options: dict[str, int | None], value: int | None) -> int:
    for index, candidate in enumerate(options.values()):
        if candidate == value:
            return index
    return 0


def _render_bulk_disciplinary_upload(current_user: AuthenticatedUser) -> None:
    """Render company-aware template, validation preview, and atomic import."""

    with st.expander("Bulk Add Disciplinary Cases via Excel", expanded=False):
        st.caption(
            "Download the company-aware template, enter one case per row, then "
            "validate and preview before importing. Hover Excel headers for field "
            "guidance and complete valid selections. Employee, Violation, and User "
            "reference sheets are limited to the current company."
        )
        with SessionFactory() as session:
            template_data = DisciplinaryRecordBulkImportService(session).build_template(
                company_id=current_user.company_id
            )
        st.download_button(
            "Download Disciplinary Case Excel Template",
            data=template_data,
            file_name="Disciplinary_Case_Import_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="disciplinary_bulk_template_download",
        )
        uploaded = st.file_uploader(
            "Upload Completed Disciplinary Case Template",
            type=["xlsx"],
            accept_multiple_files=False,
            key="disciplinary_bulk_upload_file",
            help="Use the downloadable .xlsx template. Maximum file size: 10 MB.",
        )
        uploaded_bytes = uploaded.getvalue() if uploaded is not None else None
        digest = hashlib.sha256(uploaded_bytes).hexdigest() if uploaded_bytes else None
        stored_digest = st.session_state.get(_DISCIPLINARY_BULK_DIGEST_KEY)
        if st.session_state.get(_DISCIPLINARY_BULK_PREVIEW_KEY) is not None and (
            digest is None or digest != stored_digest
        ):
            st.session_state.pop(_DISCIPLINARY_BULK_PREVIEW_KEY, None)
            st.session_state.pop(_DISCIPLINARY_BULK_DIGEST_KEY, None)

        if st.button(
            "Validate and Preview Disciplinary Cases",
            width="stretch",
            disabled=uploaded is None,
            key="disciplinary_bulk_validate",
        ) and uploaded is not None:
            try:
                if uploaded.size > 10 * 1024 * 1024:
                    raise ValueError("The Disciplinary Case Excel file must not exceed 10 MB.")
                with st.spinner("Validating disciplinary cases…"):
                    with SessionFactory() as session:
                        preview = DisciplinaryRecordBulkImportService(session).prepare_preview(
                            uploaded_bytes or b"",
                            filename=uploaded.name,
                            company_id=current_user.company_id,
                        )
                st.session_state[_DISCIPLINARY_BULK_PREVIEW_KEY] = preview
                st.session_state[_DISCIPLINARY_BULK_DIGEST_KEY] = digest
            except ValueError as error:
                st.session_state.pop(_DISCIPLINARY_BULK_PREVIEW_KEY, None)
                st.session_state.pop(_DISCIPLINARY_BULK_DIGEST_KEY, None)
                render_action_warning(error)

        preview_rows = st.session_state.get(_DISCIPLINARY_BULK_PREVIEW_KEY)
        if isinstance(preview_rows, list) and preview_rows:
            st.markdown("#### Disciplinary Case Import Preview")
            st.caption(
                "Invalid rows must be corrected in Excel and validated again. "
                "Previous Offense Count, Current Offense, and Suggested Action are "
                "calculated from live master data during the atomic import."
            )
            st.data_editor(
                [
                    {column: row.get(column, "") for column in DISCIPLINARY_PREVIEW_COLUMNS}
                    for row in preview_rows
                ],
                width="stretch",
                hide_index=True,
                disabled=list(DISCIPLINARY_PREVIEW_COLUMNS),
                key="disciplinary_bulk_preview_editor",
            )
            invalid_count = sum(
                str(row.get("Validation", "")) != "Ready" for row in preview_rows
            )
            if invalid_count:
                st.error(
                    f"{invalid_count} row(s) contain validation errors. "
                    "Correct the workbook and validate it again."
                )
            if st.button(
                "Import Disciplinary Cases",
                type="primary",
                width="stretch",
                disabled=invalid_count > 0,
                key="disciplinary_bulk_import_submit",
            ):
                try:
                    with st.spinner("Importing disciplinary cases…"):
                        with SessionFactory() as session:
                            created = DisciplinaryRecordBulkImportService(session).import_preview_rows(
                                preview_rows,
                                company_id=current_user.company_id,
                                actor_user_id=current_user.user_id,
                            )
                    st.session_state.pop(_DISCIPLINARY_BULK_PREVIEW_KEY, None)
                    st.session_state.pop(_DISCIPLINARY_BULK_DIGEST_KEY, None)
                    set_operation_feedback(
                        f"Successfully imported {len(created)} disciplinary case(s).",
                        namespace="disciplinary",
                    )
                    st.session_state["disciplinary_pending_tab"] = "Records"
                    st.rerun()
                except (ValidationError, ValueError, PermissionError) as error:
                    render_action_warning(error)
                except Exception:
                    logger.exception("Unexpected disciplinary case bulk import failure")
                    st.error(
                        "The disciplinary case batch could not be imported. "
                        "No case from this batch was saved."
                    )


def render_admin_disciplinary_records(current_user: AuthenticatedUser) -> None:
    """Create/update company employee disciplinary records as an administrator."""

    render_operation_feedback(namespace="disciplinary")
    with SessionFactory() as session:
        admin_service = AdminManagementService(session)
        employees = admin_service.list_employees(current_user.company_id)
        users = admin_service.list_users(current_user.company_id)
        violation_service = PolicyViolationService(session)
        violations = [
            item
            for item in violation_service.list_current(current_user.company_id)
            if item.status == "active" and item.archived_at is None
        ]
        case_service = DisciplinaryRecordService(session)
        records = case_service.list_admin_records(
            company_id=current_user.company_id,
            requester_user_id=current_user.user_id,
        )
        archived_records = case_service.list_admin_archived_records(
            company_id=current_user.company_id,
            requester_user_id=current_user.user_id,
        )
        user_labels = _user_labels(users)
        rows = _case_rows(records, case_service, user_labels)
        archived_rows = _case_rows(archived_records, case_service, user_labels)

    labels = ("Records", "Add Case", "Update Case", "Archive")
    pending = st.session_state.pop("disciplinary_pending_tab", None)
    if pending in labels:
        st.session_state["disciplinary_active_tab"] = pending
    records_tab, add_tab, update_tab, archive_tab = persistent_tabs(
        labels,
        key="disciplinary_active_tab",
    )

    with records_tab:
        st.caption(
            "Confidential company records. Suggested penalties are always derived from "
            "Policies → Violations & Disciplinary Actions."
        )
        search = multi_search_input(
            "Search Disciplinary Records",
            key="disciplinary_record_search",
            placeholder="Type any value shown in the disciplinary table, then press Enter…",
        )
        status_filter = st.selectbox(
            "Case Status",
            ["All", *CASE_STATUSES],
            key="disciplinary_case_status_filter",
        )
        filtered_indexes = [
            index
            for index, item in enumerate(records)
            if _matches(rows[index], search)
            and (status_filter == "All" or item.case_status == status_filter)
        ]
        filtered_rows = [rows[index] for index in filtered_indexes]
        st.caption(f"{len(filtered_rows)} of {len(records)} case(s) shown.")
        if filtered_rows:
            render_admin_table(
                filtered_rows,
                key="admin_employee_disciplinary_records_table",
                min_width=3400,
                compact=True,
                max_height=500,
            )
        else:
            st.info("No matching disciplinary records were found.")

    with add_tab:
        st.subheader("Add Employee Violation / Disciplinary Case")
        _render_bulk_disciplinary_upload(current_user)
        st.divider()
        st.markdown("#### Add One Case Manually")
        if not employees:
            st.info("There is no active employee available for a disciplinary case.")
        elif not violations:
            st.info(
                "Create at least one active violation under Policies → "
                "Violations & Disciplinary Actions first."
            )
        else:
            employee_options = {
                f"{employee.employee_number} — {employee.full_name}": employee.id
                for employee in employees
            }
            violation_options = {
                f"{item.violation_code} — {item.offense_title}": item.id
                for item in violations
            }
            selection_columns = st.columns(2)
            with selection_columns[0]:
                employee_label = st.selectbox(
                    "Employee",
                    list(employee_options),
                    key="disciplinary_add_employee",
                )
            with selection_columns[1]:
                violation_label = st.selectbox(
                    "Violation Code / Offense",
                    list(violation_options),
                    key="disciplinary_add_violation",
                )
            employee_id = employee_options[employee_label]
            violation_id = violation_options[violation_label]
            selected_employee = next(item for item in employees if item.id == employee_id)
            selected_violation = next(item for item in violations if item.id == violation_id)
            incident_date = st.date_input(
                "Incident Date",
                value=_today(),
                key="disciplinary_add_incident_date",
            )
            with SessionFactory() as session:
                service = DisciplinaryRecordService(session)
                previous_count = service.repository.count_previous_offenses(
                    company_id=current_user.company_id,
                    employee_id=employee_id,
                    violation_id=violation_id,
                    incident_date=incident_date,
                )
                offense_level = service.offense_level(previous_count)
                suggested_action = service.suggested_action(selected_violation, offense_level)

            info_columns = st.columns(3)
            info_columns[0].metric("Previous Offenses", previous_count)
            info_columns[1].metric("Current Offense", offense_level)
            info_columns[2].markdown(
                "**Suggested Disciplinary Action**  \n" + suggested_action
            )

            issuer_options = _user_select_options(users, include_none=True)
            reviewer_options = _user_select_options(users, include_none=True)
            default_issuer_index = _index_for_value(issuer_options, current_user.user_id)
            with st.form(f"disciplinary_add_case_{employee_id}_{violation_id}"):
                incident_description = st.text_area(
                    "Incident / Case Description",
                    height=120,
                    placeholder="Describe the incident/case facts relevant to this violation.",
                )
                evidence = st.text_area("Evidence / Remarks", height=100)
                context_snapshot = st.text_input(
                    "Project / Team / Department at Time of Incident",
                    value=(selected_employee.department.name if selected_employee.department else ""),
                )
                actual_action = st.text_area(
                    "Actual Action Taken",
                    height=90,
                    placeholder="May remain blank while the case is Draft or For Review.",
                )
                c1, c2 = st.columns(2)
                with c1:
                    issuer_label = st.selectbox(
                        "Issued By",
                        list(issuer_options),
                        index=default_issuer_index,
                    )
                with c2:
                    reviewer_label = st.selectbox(
                        "Reviewed / Approved By",
                        list(reviewer_options),
                    )
                c3, c4, c5 = st.columns(3)
                with c3:
                    status = st.selectbox("Case Status", list(CASE_STATUSES))
                with c4:
                    acknowledgment = st.selectbox(
                        "Employee Acknowledgment",
                        list(ACKNOWLEDGMENT_STATUSES),
                    )
                with c5:
                    has_issue_date = st.checkbox("Record Date Issued", value=False)
                    issue_date_value = st.date_input("Date Issued", value=_today())
                notes = st.text_area("Notes", height=90)
                submitted = st.form_submit_button(
                    "Save Disciplinary Case",
                    type="primary",
                    width="stretch",
                )
            if submitted:
                try:
                    request = DisciplinaryRecordCreateRequest(
                        company_id=current_user.company_id,
                        employee_id=employee_id,
                        violation_id=violation_id,
                        incident_date=incident_date,
                        incident_description=incident_description,
                        evidence_remarks=_optional(evidence),
                        context_snapshot=_optional(context_snapshot),
                        actual_action_taken=_optional(actual_action),
                        issued_by_user_id=issuer_options[issuer_label],
                        reviewed_approved_by_user_id=reviewer_options[reviewer_label],
                        date_issued=issue_date_value if has_issue_date else None,
                        employee_acknowledgment=acknowledgment,
                        case_status=status,
                        notes=_optional(notes),
                        created_by_user_id=current_user.user_id,
                    )
                    with SessionFactory() as session:
                        saved = DisciplinaryRecordService(session).create_record(request)
                    set_operation_feedback(
                        f"Disciplinary case {saved.public_id} was created for {saved.employee_name}.",
                        namespace="disciplinary",
                    )
                    st.session_state["disciplinary_pending_tab"] = "Records"
                    st.rerun()
                except (ValidationError, ValueError, PermissionError) as error:
                    render_action_warning(error)
                except Exception:
                    st.error("The disciplinary case could not be saved. No partial change was completed.")

    with update_tab:
        st.subheader("Update Disciplinary Case")
        if not records:
            st.info("There is no disciplinary case available to update.")
        else:
            record_options = {
                f"{item.public_id} · {item.employee_number} — {item.employee_name} · {item.violation_code}": item.id
                for item in records
            }
            selected_label = st.selectbox(
                "Select Case",
                list(record_options),
                key="disciplinary_update_selection",
            )
            selected_id = record_options[selected_label]
            selected = next(item for item in records if item.id == selected_id)
            with SessionFactory() as session:
                case_service = DisciplinaryRecordService(session)
                suggested_action = case_service.suggested_action_for_record(selected)
            st.info(
                f"{selected.violation_code} — {selected.violation_title} · "
                f"Previous Offenses: {selected.previous_offense_count} · "
                f"Current Offense: {selected.offense_level} · Suggested Action: {suggested_action}"
            )
            issuer_options = _user_select_options(users, include_none=True)
            reviewer_options = _user_select_options(users, include_none=True)
            with st.form(f"disciplinary_update_case_{selected.id}"):
                incident_date = st.date_input("Incident Date", value=selected.incident_date)
                incident_description = st.text_area(
                    "Incident / Case Description",
                    value=selected.incident_description,
                    height=120,
                )
                evidence = st.text_area(
                    "Evidence / Remarks",
                    value=selected.evidence_remarks or "",
                    height=100,
                )
                context_snapshot = st.text_input(
                    "Project / Team / Department at Time of Incident",
                    value=selected.context_snapshot or "",
                )
                actual_action = st.text_area(
                    "Actual Action Taken",
                    value=selected.actual_action_taken or "",
                    height=90,
                )
                c1, c2 = st.columns(2)
                with c1:
                    issuer_label = st.selectbox(
                        "Issued By",
                        list(issuer_options),
                        index=_index_for_value(issuer_options, selected.issued_by_user_id),
                    )
                with c2:
                    reviewer_label = st.selectbox(
                        "Reviewed / Approved By",
                        list(reviewer_options),
                        index=_index_for_value(
                            reviewer_options,
                            selected.reviewed_approved_by_user_id,
                        ),
                    )
                c3, c4, c5 = st.columns(3)
                with c3:
                    status = st.selectbox(
                        "Case Status",
                        list(CASE_STATUSES),
                        index=list(CASE_STATUSES).index(selected.case_status),
                    )
                with c4:
                    acknowledgment = st.selectbox(
                        "Employee Acknowledgment",
                        list(ACKNOWLEDGMENT_STATUSES),
                        index=list(ACKNOWLEDGMENT_STATUSES).index(selected.employee_acknowledgment),
                    )
                with c5:
                    has_issue_date = st.checkbox(
                        "Record Date Issued",
                        value=selected.date_issued is not None,
                    )
                    issue_date_value = st.date_input(
                        "Date Issued",
                        value=selected.date_issued or _today(),
                    )
                notes = st.text_area("Notes", value=selected.notes or "", height=90)
                submitted = st.form_submit_button(
                    "Save Case Changes",
                    type="primary",
                    width="stretch",
                )
            if submitted:
                try:
                    request = DisciplinaryRecordUpdateRequest(
                        company_id=current_user.company_id,
                        record_id=selected.id,
                        incident_date=incident_date,
                        incident_description=incident_description,
                        evidence_remarks=_optional(evidence),
                        context_snapshot=_optional(context_snapshot),
                        actual_action_taken=_optional(actual_action),
                        issued_by_user_id=issuer_options[issuer_label],
                        reviewed_approved_by_user_id=reviewer_options[reviewer_label],
                        date_issued=issue_date_value if has_issue_date else None,
                        employee_acknowledgment=acknowledgment,
                        case_status=status,
                        notes=_optional(notes),
                        edited_by_user_id=current_user.user_id,
                    )
                    with SessionFactory() as session:
                        saved = DisciplinaryRecordService(session).update_record(request)
                    set_operation_feedback(
                        f"Disciplinary case {saved.public_id} was updated.",
                        namespace="disciplinary",
                    )
                    st.rerun()
                except (ValidationError, ValueError, PermissionError) as error:
                    render_action_warning(error)
                except Exception:
                    st.error("The disciplinary case could not be updated. No partial change was completed.")

            with st.expander("Delete / Move Case to Archive", expanded=False):
                st.warning(
                    "This safe-delete action removes the case from active records, "
                    "Employee Portal, reports, and normal Chat Assistant results. "
                    "The case is retained in Archive and can be restored."
                )
                confirmation_key = f"disciplinary_archive_confirm_{selected.id}"
                invalidate_confirmation_on_change(
                    confirmation_key=confirmation_key,
                    dependencies={"record_id": selected.id},
                    tracker_key="__disciplinary_archive_target_confirmation",
                )
                confirmed = st.checkbox(
                    "I confirm that this disciplinary case should be moved to Archive.",
                    key=confirmation_key,
                )
                if st.button(
                    "Move Case to Archive",
                    width="stretch",
                    disabled=not confirmed,
                    key=f"disciplinary_archive_submit_{selected.id}",
                ):
                    try:
                        with SessionFactory() as session:
                            public_id = DisciplinaryRecordService(session).archive_record(
                                company_id=current_user.company_id,
                                record_id=selected.id,
                                actor_user_id=current_user.user_id,
                            )
                        st.session_state.pop("disciplinary_update_selection", None)
                        set_operation_feedback(
                            f"Disciplinary case {public_id} moved to Archive.",
                            namespace="disciplinary",
                        )
                        st.session_state["disciplinary_pending_tab"] = "Archive"
                        st.rerun()
                    except (ValueError, PermissionError) as error:
                        render_action_warning(error)

    with archive_tab:
        st.subheader(f"Archived Disciplinary Cases ({len(archived_records)})")
        st.caption(
            "Archived cases are recoverable and excluded from active employee, "
            "report, and Chat Assistant results until restored."
        )
        if not archived_records:
            st.info("No disciplinary cases are currently archived.")
        else:
            archive_display_rows = []
            for record, row in zip(archived_records, archived_rows):
                archive_display_rows.append(
                    {
                        "Case ID": row["Case ID"],
                        "Employee": row["Employee"],
                        "Violation": row["Violation"],
                        "Incident Date": row["Incident Date"],
                        "Case Status": row["Case Status"],
                        "Archived At": (
                            record.archived_at.strftime("%Y-%m-%d %H:%M")
                            if record.archived_at
                            else "—"
                        ),
                        "Archived By": user_labels.get(record.archived_by_user_id, "—"),
                    }
                )
            render_admin_table(
                archive_display_rows,
                key="admin_employee_disciplinary_archive_table",
                min_width=1450,
                compact=True,
                max_height=380,
            )
            restore_options = {
                f"{item.public_id} · {item.employee_number} — {item.employee_name} · {item.violation_code}": item.id
                for item in archived_records
            }
            restore_label = st.selectbox(
                "Select Archived Case",
                list(restore_options),
                key="disciplinary_restore_selection",
            )
            restore_id = restore_options[restore_label]
            if st.button(
                "Restore Disciplinary Case",
                type="primary",
                width="stretch",
                key=f"disciplinary_restore_submit_{restore_id}",
            ):
                try:
                    with SessionFactory() as session:
                        public_id = DisciplinaryRecordService(session).restore_record(
                            company_id=current_user.company_id,
                            record_id=restore_id,
                            actor_user_id=current_user.user_id,
                        )
                    st.session_state.pop("disciplinary_restore_selection", None)
                    set_operation_feedback(
                        f"Disciplinary case {public_id} restored from Archive.",
                        namespace="disciplinary",
                    )
                    st.session_state["disciplinary_pending_tab"] = "Records"
                    st.rerun()
                except (ValueError, PermissionError) as error:
                    render_action_warning(error)


def render_employee_disciplinary_records(current_user: AuthenticatedUser) -> None:
    """Show only the signed-in employee's own issued/closed records."""

    if not get_settings().employee_disciplinary_records_visible:
        st.info("Employee access to disciplinary records is currently disabled.")
        return
    if current_user.employee_id is None:
        st.info("Your login account is not linked to an employee master record.")
        return
    try:
        with SessionFactory() as session:
            service = DisciplinaryRecordService(session)
            records = service.list_employee_records(
                company_id=current_user.company_id,
                employee_id=current_user.employee_id,
                requester_user_id=current_user.user_id,
            )
            rows = _case_rows(records, service, {})
    except PermissionError:
        st.error("You may only view your own issued disciplinary records.")
        return

    st.caption(
        "Only your own officially issued or closed cases are shown. Draft, For Review, "
        "Cancelled, and other employees' records are never exposed here."
    )
    if not rows:
        st.info("You have no issued disciplinary records available.")
        return

    safe_rows = []
    for row in rows:
        safe_rows.append(
            {
                "Case ID": row["Case ID"],
                "Violation": row["Violation"],
                "Incident Date": row["Incident Date"],
                "Incident / Case Description": row["Incident / Case Description"],
                "Evidence / Remarks": row["Evidence / Remarks"],
                "Project / Team / Department": row["Project / Team / Department"],
                "Current Offense": row["Current Offense"],
                "Suggested Disciplinary Action": row["Suggested Disciplinary Action"],
                "Actual Action Taken": row["Actual Action Taken"],
                "Date Issued": row["Date Issued"],
                "Employee Acknowledgment": row["Employee Acknowledgment"],
                "Case Status": row["Case Status"],
                "Notes": row["Notes"],
            }
        )
    render_admin_table(
        safe_rows,
        key="employee_own_disciplinary_records_table",
        min_width=2700,
        compact=True,
        max_height=480,
    )
