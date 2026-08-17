"""Administrator workspace for company forms and employee submissions."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st
from ui.components.validation_feedback import render_action_warning

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from services.company_form_service import (
    ALLOWED_FORM_EXTENSIONS,
    CompanyFormService,
)
from ui.components.data_table import render_selectable_admin_table
from ui.components.company_form_download import (
    prepare_editable_company_form_download,
)
from ui.components.file_preview import render_file_preview_dialog
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)


NEXT_TAB_KEY = "company_forms_next_tab"
PREVIEW_STATE_KEY = "company_forms_preview_target"
OVERVIEW_TABLE_VERSION_KEY = "company_forms_overview_table_version"
SUBMISSION_TABLE_VERSION_KEY = "company_forms_submission_table_version"
MANAGE_TABLE_VERSION_KEY = "company_forms_manage_table_version"
BIN_TABLE_VERSION_KEY = "company_forms_bin_table_version"
TAB_LABELS = ["Overview", "Upload Form", "Manage Form", "Bin"]
STATUS_LABELS = {
    "submitted": "Submitted",
    "reviewed": "Reviewed",
    "approved": "Approved",
    "returned": "Returned",
}


def _format_datetime(value: datetime | None) -> str:
    """Format a stored timestamp in the configured display timezone."""

    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(
        ZoneInfo(get_settings().display_timezone)
    ).strftime("%Y-%m-%d %I:%M %p")


def _remember_tab(label: str) -> None:
    """Keep the selected Company Form/Documents tab after a rerun."""

    st.session_state[NEXT_TAB_KEY] = label


def _selected_tab() -> str:
    """Consume one valid post-action tab target."""

    target = st.session_state.pop(NEXT_TAB_KEY, "Overview")
    return target if target in TAB_LABELS else "Overview"


def _form_rows(forms) -> list[dict[str, object]]:
    """Build the active/Bin table rows."""

    return [
        {
            "Form ID": item.public_id,
            "Title": item.title,
            "File": item.original_filename,
            "Employee Submission": (
                "Allowed" if item.allow_employee_submission else "Download only"
            ),
            "Last Updated": _format_datetime(item.updated_at),
        }
        for item in forms
    ]


def _submission_rows(submissions) -> list[dict[str, object]]:
    """Build administrator submission inbox rows."""

    return [
        {
            "Submission ID": item.public_id,
            "Employee": item.employee.full_name,
            "Employee No.": item.employee.employee_number,
            "Form": item.form.title,
            "File": item.original_filename,
            "Status": STATUS_LABELS.get(item.status, item.status.title()),
            "Submitted": _format_datetime(item.created_at),
        }
        for item in submissions
    ]


def _queue_preview(
    *,
    kind: str,
    record_id: int,
    table_version_key: str,
    active_only: bool = True,
) -> None:
    """Remember one authorized file target for the modal preview."""

    st.session_state[PREVIEW_STATE_KEY] = {
        "kind": kind,
        "record_id": int(record_id),
        "active_only": bool(active_only),
        "table_version_key": table_version_key,
    }


def _render_pending_preview(current_user: AuthenticatedUser) -> None:
    """Open the queued template/submission in one secure file modal."""

    target = st.session_state.get(PREVIEW_STATE_KEY)
    if not isinstance(target, dict):
        return

    try:
        with SessionFactory() as session:
            service = CompanyFormService(session)
            if target.get("kind") == "submission":
                download = service.get_submission_download(
                    company_id=current_user.company_id,
                    submission_id=int(target["record_id"]),
                )
            else:
                download = service.get_form_download(
                    company_id=current_user.company_id,
                    form_id=int(target["record_id"]),
                    active_only=bool(target.get("active_only", True)),
                )
    except (ValueError, FileNotFoundError) as error:
        st.session_state[PREVIEW_STATE_KEY] = None
        render_action_warning(error)
        return

    render_file_preview_dialog(
        filename=download.filename,
        mime_type=download.mime_type,
        data=download.data,
        preview_state_key=PREVIEW_STATE_KEY,
        table_version_key=str(target["table_version_key"]),
    )


def _render_submission_review(
    current_user: AuthenticatedUser,
    submissions,
) -> None:
    """Allow an administrator to open, download, and review one submission."""

    if not submissions:
        st.info("No employee form submissions have been received yet.")
        return

    label_map = {
        (
            f"{item.public_id} · {item.employee.full_name} · "
            f"{item.form.title}"
        ): item.id
        for item in submissions
    }
    selected_label = st.selectbox(
        "Employee Submission",
        options=list(label_map),
        key="admin_company_form_submission_select",
    )
    selected_id = label_map[selected_label]
    selected = next(item for item in submissions if item.id == selected_id)

    detail_columns = st.columns(3)
    detail_columns[0].metric("Status", STATUS_LABELS.get(selected.status, selected.status.title()))
    detail_columns[1].metric("Employee", selected.employee.full_name)
    detail_columns[2].metric("Submitted", _format_datetime(selected.created_at))

    st.caption(
        f"Form: {selected.form.title} · File: {selected.original_filename}"
    )
    if selected.notes:
        st.markdown(f"**Employee note:** {selected.notes}")

    with SessionFactory() as session:
        download = CompanyFormService(session).get_submission_download(
            company_id=current_user.company_id,
            submission_id=selected.id,
        )

    preview_column, download_column = st.columns(2)
    if preview_column.button(
        "View Filled Form",
        width="stretch",
        key=f"admin_preview_submission_{selected.id}",
    ):
        _queue_preview(
            kind="submission",
            record_id=selected.id,
            table_version_key="admin_submission_preview_version",
        )

    download_column.download_button(
        "Download Filled Form",
        data=download.data,
        file_name=download.filename,
        mime=download.mime_type,
        width="stretch",
        key=f"admin_download_submission_{selected.id}",
    )

    with st.form(
        f"admin_submission_review_{selected.id}",
        clear_on_submit=False,
    ):
        status = st.selectbox(
            "Review Status",
            options=list(STATUS_LABELS),
            format_func=lambda value: STATUS_LABELS[value],
            index=list(STATUS_LABELS).index(selected.status),
        )
        admin_note = st.text_area(
            "Admin Note",
            value=selected.admin_note,
            height=110,
            placeholder="Optional message shown to the employee...",
        )
        submitted = st.form_submit_button(
            "Save Review",
            type="primary",
            width="stretch",
        )

    if submitted:
        try:
            with SessionFactory() as session:
                CompanyFormService(session).update_submission_status(
                    company_id=current_user.company_id,
                    submission_id=selected.id,
                    reviewed_by_user_id=current_user.user_id,
                    status=status,
                    admin_note=admin_note,
                )
            set_operation_feedback(
                "Employee form review was saved and the employee was notified.",
                namespace="company_forms",
            )
            _remember_tab("Overview")
            st.rerun()
        except ValueError as error:
            render_action_warning(error)


def _render_overview(
    current_user: AuthenticatedUser,
    overview,
    active_forms,
    submissions,
) -> None:
    """Render metrics, active form summary, and the submission inbox."""

    metrics = st.columns(4)
    metrics[0].metric("Active Forms", overview.active_forms)
    metrics[1].metric("All Submissions", overview.total_submissions)
    metrics[2].metric("Awaiting Review", overview.pending_submissions)
    metrics[3].metric("In Bin", overview.bin_forms)

    if active_forms:
        st.caption("Click anywhere on a form row to open its file preview.")
        table_version = int(
            st.session_state.get(OVERVIEW_TABLE_VERSION_KEY, 0)
        )
        selected_index = render_selectable_admin_table(
            _form_rows(active_forms),
            key=f"company_forms_overview_active_{table_version}",
            height=245,
        )
        if selected_index is not None:
            _queue_preview(
                kind="form",
                record_id=active_forms[selected_index].id,
                table_version_key=OVERVIEW_TABLE_VERSION_KEY,
            )
    else:
        st.info("No active company forms are available.")

    st.divider()
    st.subheader("Employee Filled Forms")
    with st.container(height=560, border=False):
        if submissions:
            st.caption(
                "Click anywhere on a submission row to preview the filled file."
            )
            table_version = int(
                st.session_state.get(SUBMISSION_TABLE_VERSION_KEY, 0)
            )
            selected_index = render_selectable_admin_table(
                _submission_rows(submissions),
                key=f"company_forms_overview_submissions_{table_version}",
                height=245,
            )
            if selected_index is not None:
                selected_submission = submissions[selected_index]
                selected_label = (
                    f"{selected_submission.public_id} · "
                    f"{selected_submission.employee.full_name} · "
                    f"{selected_submission.form.title}"
                )
                st.session_state[
                    "admin_company_form_submission_select"
                ] = selected_label
                _queue_preview(
                    kind="submission",
                    record_id=selected_submission.id,
                    table_version_key=SUBMISSION_TABLE_VERSION_KEY,
                )
            st.divider()
        _render_submission_review(current_user, submissions)


def _render_upload(current_user: AuthenticatedUser) -> None:
    """Upload one downloadable company form template."""

    settings = get_settings()
    with st.container(height=620, border=False):
        st.subheader("Upload Company Form")
        st.caption(
            "Upload PDF, Word, Excel, CSV, or TXT templates. Files remain "
            "private and company-scoped."
        )

        with st.form("company_form_upload", clear_on_submit=True):
            title = st.text_input(
                "Form Title",
                placeholder="Example: Employee Information Update Form",
            )
            allow_submission = st.checkbox(
                "Allow employees to submit a completed copy",
                value=True,
            )
            uploaded = st.file_uploader(
                "Form File",
                type=sorted(ext.lstrip(".") for ext in ALLOWED_FORM_EXTENSIONS),
                accept_multiple_files=False,
            )
            submit = st.form_submit_button(
                "Upload Form",
                type="primary",
                width="stretch",
            )

        if submit:
            if uploaded is None:
                st.error("Select a form file to upload.")
                return
            try:
                with SessionFactory() as session:
                    CompanyFormService(session).upload_form(
                        company_id=current_user.company_id,
                        uploaded_by_user_id=current_user.user_id,
                        title=title,
                        # Category/description are intentionally hidden in
                        # this simplified UI. Keep stable backend defaults so
                        # existing schemas and future enhancements remain safe.
                        category="General",
                        description="",
                        allow_employee_submission=allow_submission,
                        filename=uploaded.name,
                        file_bytes=uploaded.getvalue(),
                        maximum_size_bytes=settings.company_form_upload_max_mb
                        * 1024
                        * 1024,
                    )
                set_operation_feedback(
                    "Company form was uploaded and employees were notified.",
                    namespace="company_forms",
                )
                _remember_tab("Upload Form")
                st.rerun()
            except ValueError as error:
                render_action_warning(error)


def _render_manage(
    current_user: AuthenticatedUser,
    active_forms,
) -> None:
    """Edit metadata, download templates, or move forms to Bin."""

    with st.container(height=660, border=False):
        st.subheader("Manage Active Forms")
        if not active_forms:
            st.info("No active forms are available to manage.")
            return

        st.caption(
            "Click anywhere on a form row to preview and select it for editing."
        )
        table_version = int(
            st.session_state.get(MANAGE_TABLE_VERSION_KEY, 0)
        )
        selected_index = render_selectable_admin_table(
            _form_rows(active_forms),
            key=f"company_forms_manage_{table_version}",
            height=230,
        )

        label_map = {
            f"{item.public_id} · {item.title}": item.id
            for item in active_forms
        }
        if selected_index is not None:
            clicked_form = active_forms[selected_index]
            clicked_label = f"{clicked_form.public_id} · {clicked_form.title}"
            st.session_state["manage_company_form_select"] = clicked_label
            _queue_preview(
                kind="form",
                record_id=clicked_form.id,
                table_version_key=MANAGE_TABLE_VERSION_KEY,
            )

        selected_label = st.selectbox(
            "Select Form",
            options=list(label_map),
            key="manage_company_form_select",
        )
        selected_id = label_map[selected_label]
        selected = next(item for item in active_forms if item.id == selected_id)

        try:
            with SessionFactory() as session:
                original_download = CompanyFormService(
                    session
                ).get_form_download(
                    company_id=current_user.company_id,
                    form_id=selected.id,
                )
            download = prepare_editable_company_form_download(
                filename=original_download.filename,
                mime_type=original_download.mime_type,
                data=original_download.data,
            )
        except (ValueError, FileNotFoundError) as error:
            render_action_warning(error)
            return

        if original_download.filename.lower().endswith(".pdf"):
            st.caption(
                "The stored PDF remains unchanged. Download Form provides an "
                "editable Word (.docx) copy."
            )
        preview_column, download_column = st.columns(2)
        if preview_column.button(
            "View Original Form",
            width="stretch",
            key=f"admin_preview_form_{selected.id}",
        ):
            _queue_preview(
                kind="form",
                record_id=selected.id,
                table_version_key=MANAGE_TABLE_VERSION_KEY,
            )
        download_column.download_button(
            "Download Form",
            data=download.data,
            file_name=download.filename,
            mime=download.mime_type,
            width="stretch",
            key=f"admin_download_form_{selected.id}",
        )

        with st.form(f"manage_company_form_{selected.id}"):
            title = st.text_input("Form Title", value=selected.title)
            allow_submission = st.checkbox(
                "Allow employees to submit a completed copy",
                value=selected.allow_employee_submission,
            )
            save = st.form_submit_button(
                "Save Form Details",
                type="primary",
                width="stretch",
            )

        if save:
            try:
                with SessionFactory() as session:
                    CompanyFormService(session).update_form_metadata(
                        company_id=current_user.company_id,
                        form_id=selected.id,
                        title=title,
                        # The old metadata is intentionally preserved while
                        # Category and Description are hidden from this UI.
                        category=selected.category,
                        description=selected.description,
                        allow_employee_submission=allow_submission,
                    )
                set_operation_feedback(
                    "Company form details were updated.",
                    namespace="company_forms",
                )
                _remember_tab("Manage Form")
                st.rerun()
            except ValueError as error:
                render_action_warning(error)

        if st.button(
            "Move Form to Bin",
            width="stretch",
            key=f"move_company_form_bin_{selected.id}",
        ):
            with SessionFactory() as session:
                CompanyFormService(session).move_to_bin(
                    company_id=current_user.company_id,
                    form_id=selected.id,
                    user_id=current_user.user_id,
                )
            set_operation_feedback(
                "Company form was moved to Bin.",
                namespace="company_forms",
            )
            _remember_tab("Manage Form")
            st.rerun()


def _render_bin(current_user: AuthenticatedUser, bin_forms) -> None:
    """Restore or permanently delete forms retained in Bin."""

    with st.container(height=580, border=True):
        st.subheader("Form Bin")
        st.caption(
            "Forms in Bin are hidden from employees. Existing submission "
            "records remain available until permanent deletion."
        )
        if not bin_forms:
            st.info("The Company Form/Documents Bin is empty.")
            return

        st.caption(
            "Click anywhere on a Bin row to preview and select the stored form."
        )
        table_version = int(
            st.session_state.get(BIN_TABLE_VERSION_KEY, 0)
        )
        selected_index = render_selectable_admin_table(
            _form_rows(bin_forms),
            key=f"company_forms_bin_{table_version}",
            height=260,
        )
        label_map = {
            f"{item.public_id} · {item.title}": item.id
            for item in bin_forms
        }
        if selected_index is not None:
            clicked_form = bin_forms[selected_index]
            clicked_label = f"{clicked_form.public_id} · {clicked_form.title}"
            st.session_state["company_form_bin_select"] = clicked_label
            _queue_preview(
                kind="form",
                record_id=clicked_form.id,
                table_version_key=BIN_TABLE_VERSION_KEY,
                active_only=False,
            )

        selected_label = st.selectbox(
            "Bin Form",
            options=list(label_map),
            key="company_form_bin_select",
        )
        selected_id = label_map[selected_label]
        action_columns = st.columns(2)

        if action_columns[0].button(
            "Restore Form",
            type="primary",
            width="stretch",
        ):
            with SessionFactory() as session:
                CompanyFormService(session).restore_from_bin(
                    company_id=current_user.company_id,
                    form_id=selected_id,
                )
            set_operation_feedback(
                "Company form was restored.",
                namespace="company_forms",
            )
            _remember_tab("Bin")
            st.rerun()

        confirm_delete = action_columns[1].checkbox(
            "Confirm permanent deletion",
            key=f"confirm_company_form_delete_{selected_id}",
        )
        if st.button(
            "Permanently Delete Form",
            disabled=not confirm_delete,
            width="stretch",
            key=f"permanent_company_form_delete_{selected_id}",
        ):
            with SessionFactory() as session:
                CompanyFormService(session).permanently_delete(
                    company_id=current_user.company_id,
                    form_id=selected_id,
                )
            set_operation_feedback(
                "Company form and attached employee submissions were permanently deleted.",
                namespace="company_forms",
            )
            _remember_tab("Bin")
            st.rerun()


def render_company_forms_documents_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render the complete administrator Company Form/Documents module."""

    st.title("Company Form/Documents")
    st.caption(
        "Upload company templates, manage employee access, and review filled "
        "forms submitted through the Employee Portal."
    )
    render_operation_feedback(namespace="company_forms")

    with SessionFactory() as session:
        service = CompanyFormService(session)
        overview = service.overview(current_user.company_id)
        active_forms = service.list_active_forms(current_user.company_id)
        bin_forms = service.list_bin_forms(current_user.company_id)
        submissions = service.list_admin_submissions(current_user.company_id)

    requested_tab = _selected_tab()
    if (
        "company_forms_active_tab" not in st.session_state
        or requested_tab != "Overview"
    ):
        # Prime the widget before creation, then omit ``default`` below. This
        # preserves the requested tab without Streamlit's duplicate
        # default/session-state warning.
        st.session_state["company_forms_active_tab"] = requested_tab
    tabs = st.tabs(
        TAB_LABELS,
        key="company_forms_active_tab",
        on_change="rerun",
    )

    with tabs[0]:
        _render_overview(current_user, overview, active_forms, submissions)
    with tabs[1]:
        _render_upload(current_user)
    with tabs[2]:
        _render_manage(current_user, active_forms)
    with tabs[3]:
        _render_bin(current_user, bin_forms)

    _render_pending_preview(current_user)
