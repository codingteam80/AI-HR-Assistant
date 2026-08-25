"""Employee Company Form/Documents browser, download, and submission page."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from ui.components.persistent_tabs import persistent_tabs

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from services.company_form_service import (
    ALLOWED_SUBMISSION_EXTENSIONS,
    CompanyFormService,
)
from ui.components.company_form_download import (
    prepare_editable_company_form_download,
)
from ui.components.data_table import render_selectable_admin_table
from ui.components.file_preview import render_file_preview_dialog
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)


EMPLOYEE_FORM_TABS = ["View", "Download", "Fill / Submit", "My Documents"]
NEXT_TAB_KEY = "employee_company_forms_next_tab"
PREVIEW_STATE_KEY = "employee_company_forms_preview_target"
VIEW_TABLE_VERSION_KEY = "employee_company_forms_view_table_version"
SUBMISSION_TABLE_VERSION_KEY = "employee_company_forms_submission_table_version"
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


def _selected_tab() -> str:
    """Consume one post-submit tab target."""

    target = st.session_state.pop(NEXT_TAB_KEY, "View")
    return target if target in EMPLOYEE_FORM_TABS else "View"


def _form_rows(forms) -> list[dict[str, object]]:
    """Build employee-facing form rows."""

    return [
        {
            "Form ID": item.public_id,
            "Title": item.title,
            "Action": (
                "Download and submit"
                if item.allow_employee_submission
                else "Download only"
            ),
            "Last Updated": _format_datetime(item.updated_at),
        }
        for item in forms
    ]


def _submission_rows(submissions) -> list[dict[str, object]]:
    """Build the authenticated employee's own submission history."""

    return [
        {
            "Submission ID": item.public_id,
            "Form": item.form.title,
            "File": item.original_filename,
            "Status": STATUS_LABELS.get(item.status, item.status.title()),
            "Admin Note": item.admin_note or "—",
            "Submitted": _format_datetime(item.created_at),
        }
        for item in submissions
    ]


def _queue_preview(
    *,
    kind: str,
    record_id: int,
    table_version_key: str,
) -> None:
    """Remember one employee-authorized file for the modal preview."""

    st.session_state[PREVIEW_STATE_KEY] = {
        "kind": kind,
        "record_id": int(record_id),
        "table_version_key": table_version_key,
    }


def _render_pending_preview(current_user: AuthenticatedUser) -> None:
    """Open the queued template or employee-owned submission in a modal."""

    target = st.session_state.get(PREVIEW_STATE_KEY)
    if not isinstance(target, dict):
        return

    try:
        with SessionFactory() as session:
            service = CompanyFormService(session)
            if target.get("kind") == "submission":
                if current_user.employee_id is None:
                    raise ValueError(
                        "Your login account is not linked to an employee profile."
                    )
                download = service.get_submission_download(
                    company_id=current_user.company_id,
                    submission_id=int(target["record_id"]),
                    employee_id=int(current_user.employee_id),
                )
            else:
                download = service.get_form_download(
                    company_id=current_user.company_id,
                    form_id=int(target["record_id"]),
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


def _render_view(
    current_user: AuthenticatedUser,
    forms,
) -> None:
    """Show available company forms in a fixed-height scroll box."""

    with st.container(height=540, border=True):
        st.subheader("Available Company Forms")
        st.caption(
            "Only active forms uploaded by your company are shown. Use the "
            "Download tab to obtain an editable template."
        )
        if not forms:
            st.info("No company forms are currently available.")
            return

        st.caption("Click a form row to open its file preview.")
        table_version = int(
            st.session_state.get(VIEW_TABLE_VERSION_KEY, 0)
        )
        selected_index = render_selectable_admin_table(
            _form_rows(forms),
            key=f"employee_company_forms_view_{table_version}",
            height=420,
        )
        if selected_index is not None:
            _queue_preview(
                kind="form",
                record_id=forms[selected_index].id,
                table_version_key=VIEW_TABLE_VERSION_KEY,
            )


def _render_download(
    current_user: AuthenticatedUser,
    forms,
) -> None:
    """Download one authorized active company form."""

    with st.container(height=480, border=True):
        st.subheader("Download Form")
        if not forms:
            st.info("No company forms are currently available for download.")
            return

        label_map = {
            f"{item.public_id} · {item.title} · {item.original_filename}": item.id
            for item in forms
        }
        selected_label = st.selectbox(
            "Company Form",
            options=list(label_map),
            key="employee_company_form_download_select",
        )
        selected = next(
            item for item in forms if item.id == label_map[selected_label]
        )

        st.markdown(
            f"**Submission:** "
            + (
                "A completed copy may be submitted in the Fill / Submit tab."
                if selected.allow_employee_submission
                else "This document is download-only."
            )
        )
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
            "View Form",
            width="stretch",
            key=f"employee_preview_company_form_{selected.id}",
        ):
            _queue_preview(
                kind="form",
                record_id=selected.id,
                table_version_key="employee_download_preview_version",
            )
        download_column.download_button(
            "Download Form",
            data=download.data,
            file_name=download.filename,
            mime=download.mime_type,
            type="primary",
            width="stretch",
            key=f"employee_download_company_form_{selected.id}",
        )


def _render_fill_submit(
    current_user: AuthenticatedUser,
    forms,
) -> None:
    """Upload one completed company form for administrator review."""

    settings = get_settings()
    with st.container(height=720, border=False):
        st.subheader("Fill / Submit Completed Form")
        eligible_forms = [
            item for item in forms if item.allow_employee_submission
        ]

        if current_user.employee_id is None:
            st.error(
                "Your login account is not linked to an employee profile. "
                "Contact an administrator before submitting a form."
            )
        elif not eligible_forms:
            st.info("No company forms currently accept employee submissions.")
        else:
            label_map = {
                f"{item.public_id} · {item.title}": item.id
                for item in eligible_forms
            }
            with st.form(
                "employee_company_form_submit",
                clear_on_submit=True,
            ):
                selected_label = st.selectbox(
                    "Form Being Submitted",
                    options=list(label_map),
                )
                completed_file = st.file_uploader(
                    "Completed Form File",
                    type=sorted(
                        ext.lstrip(".")
                        for ext in ALLOWED_SUBMISSION_EXTENSIONS
                    ),
                    accept_multiple_files=False,
                    help=(
                        "Fill the downloaded template, save the completed "
                        "copy, then upload it here."
                    ),
                )
                notes = st.text_area(
                    "Submission Note",
                    height=95,
                    placeholder="Optional message for the administrator...",
                )
                submit = st.form_submit_button(
                    "Submit Filled Form",
                    type="primary",
                    width="stretch",
                )

            if submit:
                if completed_file is None:
                    st.error("Select the completed form file.")
                else:
                    try:
                        with SessionFactory() as session:
                            CompanyFormService(session).submit_completed_form(
                                company_id=current_user.company_id,
                                form_id=label_map[selected_label],
                                employee_id=int(current_user.employee_id),
                                submitted_by_user_id=current_user.user_id,
                                notes=notes,
                                filename=completed_file.name,
                                file_bytes=completed_file.getvalue(),
                                maximum_size_bytes=(
                                    settings.company_form_upload_max_mb
                                    * 1024
                                    * 1024
                                ),
                            )
                        set_operation_feedback(
                            "Your completed form was submitted and administrators were notified.",
                            namespace="employee_company_forms",
                        )
                        st.session_state[NEXT_TAB_KEY] = "My Documents"
                        st.rerun()
                    except ValueError as error:
                        render_action_warning(error)


def _render_my_documents(
    current_user: AuthenticatedUser,
    submissions,
) -> None:
    """Display only the signed-in employee's submitted form copies."""

    with st.container(height=620, border=False):
        st.subheader("My Submitted Forms")
        st.caption(
            "Review the forms you submitted to administrators, including "
            "their current status and any administrator note."
        )
        if not submissions:
            st.info("You have not submitted a completed company form yet.")
            return

        st.caption("Click a submission row to preview your filled file.")
        table_version = int(
            st.session_state.get(SUBMISSION_TABLE_VERSION_KEY, 0)
        )
        selected_index = render_selectable_admin_table(
            _submission_rows(submissions),
            key=f"employee_company_form_submissions_{table_version}",
            height=260,
        )

        label_map = {
            f"{item.public_id} · {item.form.title}": item.id
            for item in submissions
        }
        if selected_index is not None:
            clicked_submission = submissions[selected_index]
            clicked_label = (
                f"{clicked_submission.public_id} · "
                f"{clicked_submission.form.title}"
            )
            st.session_state[
                "employee_company_form_submission_select"
            ] = clicked_label
            _queue_preview(
                kind="submission",
                record_id=clicked_submission.id,
                table_version_key=SUBMISSION_TABLE_VERSION_KEY,
            )

        selected_label = st.selectbox(
            "My Submission",
            options=list(label_map),
            key="employee_company_form_submission_select",
        )
        selected_id = label_map[selected_label]
        with SessionFactory() as session:
            download = CompanyFormService(session).get_submission_download(
                company_id=current_user.company_id,
                submission_id=selected_id,
                employee_id=int(current_user.employee_id),
            )
        preview_column, download_column = st.columns(2)
        if preview_column.button(
            "View My Submitted Copy",
            width="stretch",
            key=f"employee_preview_submission_{selected_id}",
        ):
            _queue_preview(
                kind="submission",
                record_id=selected_id,
                table_version_key=SUBMISSION_TABLE_VERSION_KEY,
            )
        download_column.download_button(
            "Download My Submitted Copy",
            data=download.data,
            file_name=download.filename,
            mime=download.mime_type,
            width="stretch",
            key=f"employee_download_submission_{selected_id}",
        )


def render_employee_company_forms_documents_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render the employee company-form workspace."""

    st.title("Company Form/Documents")
    st.caption(
        "View and download company forms, then submit completed copies "
        "directly to administrators when the form allows it."
    )
    render_operation_feedback(namespace="employee_company_forms")

    with SessionFactory() as session:
        service = CompanyFormService(session)
        forms = service.list_active_forms(current_user.company_id)
        submissions = (
            service.list_employee_submissions(
                company_id=current_user.company_id,
                employee_id=current_user.employee_id,
            )
            if current_user.employee_id is not None
            else []
        )

    requested_tab = _selected_tab()
    if (
        "employee_company_forms_active_tab" not in st.session_state
        or requested_tab != "View"
    ):
        # Session State is the sole initial-value source for this keyed tab.
        # Supplying both ``default`` and a stored value emits a Streamlit
        # warning and is intentionally avoided.
        st.session_state["employee_company_forms_active_tab"] = requested_tab
    tabs = persistent_tabs(
        EMPLOYEE_FORM_TABS,
        key="employee_company_forms_active_tab",
    )
    with tabs[0]:
        _render_view(current_user, forms)
    with tabs[1]:
        _render_download(current_user, forms)
    with tabs[2]:
        _render_fill_submit(current_user, forms)
    with tabs[3]:
        _render_my_documents(current_user, submissions)

    _render_pending_preview(current_user)
