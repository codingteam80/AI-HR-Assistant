"""Administrator policy library, integrated upload preview, and Bin."""

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import html

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from ui.components.persistent_tabs import persistent_tabs
from pydantic import ValidationError

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from modules.documents.policy_file_parser import ALLOWED_POLICY_EXTENSIONS
from schemas.policy_schema import (
    PolicyMetadataUpdate,
    PolicyPermanentDeleteRequest,
    PolicyUploadRequest,
)
from services.policy_service import PolicyAdminView, PolicyService
from ui.pages.admin.policy_violations import render_admin_policy_violations
from ui.components.data_table import render_admin_table
from ui.components.confirmation_guard import invalidate_confirmation_on_change
from ui.components.live_search import multi_search_input
from utils.search_utils import matches_search_terms, matches_visible_row
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)


POLICY_CONTENT_VIEWER_HEIGHT = 460
POLICY_CONTENT_EDITOR_HEIGHT = 520
POLICY_SECTION_RESULTS_HEIGHT = 430
POLICY_VERSION_HISTORY_HEIGHT = 340
POLICY_LIBRARY_TABLE_HEIGHT = 390

_POLICY_LIBRARY_PREVIEW_STATE_KEY = "_policy_library_preview_policy_id"

_POLICY_UPLOAD_NONCE_STATE_KEY = "_policy_upload_nonce"
_POLICY_UPLOAD_WIDGET_PREFIX = "policy_upload_"
_POLICY_UPLOAD_RESULT_STATE_KEY = "_policy_upload_batch_result"
_AUTO_VERSION_LINK_LABEL = "Auto-detect from filename"


def _get_policy_upload_nonce() -> int:
    """Return the current upload-widget generation number."""

    raw_value = st.session_state.get(
        _POLICY_UPLOAD_NONCE_STATE_KEY,
        0,
    )

    try:
        nonce = max(0, int(raw_value))
    except (TypeError, ValueError):
        nonce = 0

    st.session_state[
        _POLICY_UPLOAD_NONCE_STATE_KEY
    ] = nonce

    return nonce


def _policy_upload_widget_key(
    nonce: int,
    name: str,
) -> str:
    """Build one upload widget key for the current generation."""

    normalized_name = (
        name.strip()
        .replace(" ", "_")
        .replace("-", "_")
    )

    return (
        f"{_POLICY_UPLOAD_WIDGET_PREFIX}"
        f"{nonce}_{normalized_name}"
    )


def _cleanup_old_policy_upload_state(
    active_nonce: int,
) -> None:
    """Remove upload-widget state from earlier completed uploads.

    Cleanup runs before the current generation's widgets are created.
    This avoids modifying an already-instantiated Streamlit widget.
    """

    active_prefix = (
        f"{_POLICY_UPLOAD_WIDGET_PREFIX}"
        f"{active_nonce}_"
    )

    stale_keys = [
        key
        for key in list(st.session_state.keys())
        if (
            isinstance(key, str)
            and key.startswith(
                _POLICY_UPLOAD_WIDGET_PREFIX
            )
            and not key.startswith(active_prefix)
        )
    ]

    for key in stale_keys:
        st.session_state.pop(key, None)


def _advance_policy_upload_state(
    current_nonce: int,
) -> None:
    """Switch the next rerun to a fresh upload-widget generation."""

    st.session_state[
        _POLICY_UPLOAD_NONCE_STATE_KEY
    ] = current_nonce + 1


_POLICY_VERSION_NONCE_PREFIX = "_policy_version_upload_nonce_"
_POLICY_VERSION_WIDGET_PREFIX = "policy_version_upload_"


def _get_policy_version_nonce(policy_id: int) -> int:
    """Return the current inline new-version uploader generation."""

    state_key = (
        f"{_POLICY_VERSION_NONCE_PREFIX}"
        f"{policy_id}"
    )
    raw_value = st.session_state.get(state_key, 0)

    try:
        nonce = max(0, int(raw_value))
    except (TypeError, ValueError):
        nonce = 0

    st.session_state[state_key] = nonce
    return nonce


def _policy_version_widget_key(
    policy_id: int,
    nonce: int,
    name: str,
) -> str:
    """Build a unique key for one managed-policy version uploader."""

    normalized_name = (
        name.strip()
        .replace(" ", "_")
        .replace("-", "_")
    )

    return (
        f"{_POLICY_VERSION_WIDGET_PREFIX}"
        f"{policy_id}_{nonce}_{normalized_name}"
    )


def _cleanup_policy_version_state(
    policy_id: int,
    active_nonce: int,
) -> None:
    """Remove stale widget state for this policy's old upload runs."""

    policy_prefix = (
        f"{_POLICY_VERSION_WIDGET_PREFIX}"
        f"{policy_id}_"
    )
    active_prefix = (
        f"{policy_prefix}"
        f"{active_nonce}_"
    )

    stale_keys = [
        key
        for key in list(st.session_state.keys())
        if (
            isinstance(key, str)
            and key.startswith(policy_prefix)
            and not key.startswith(active_prefix)
        )
    ]

    for key in stale_keys:
        st.session_state.pop(key, None)


def _advance_policy_version_state(
    policy_id: int,
    current_nonce: int,
) -> None:
    """Reset the inline new-version uploader after success."""

    st.session_state[
        f"{_POLICY_VERSION_NONCE_PREFIX}"
        f"{policy_id}"
    ] = current_nonce + 1


def _unique_preview_headings(
    sections,
) -> list[str]:
    """Return every unique heading in its original source order."""

    headings: list[str] = []
    seen: set[str] = set()

    for section in sections:
        heading = " ".join(
            str(section.heading or "").split()
        ).strip()

        if not heading:
            continue

        normalized = heading.casefold()

        if normalized in seen:
            continue

        seen.add(normalized)
        headings.append(heading)

    return headings


def _render_detected_headings(
    sections,
) -> None:
    """Render every detected heading inside a bounded scroll box.

    The complete heading list remains available, but a large policy no
    longer stretches the whole page vertically.
    """

    headings = _unique_preview_headings(sections)

    if not headings:
        return

    items = "".join(
        (
            "<li>"
            f"{html.escape(heading)}"
            "</li>"
        )
        for heading in headings
    )

    st.markdown(
        (
            "<div class='hr-policy-headings-preview'>"
            "<div class='hr-policy-headings-title'>"
            f"Detected headings ({len(headings)})"
            "</div>"
            "<div class='hr-policy-headings-scroll'>"
            f"<ol>{items}</ol>"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Scroll inside the headings box to review the complete list."
    )


def _format_section_preview(
    sections,
) -> str:
    """Return all sections with a separator before each heading."""

    blocks: list[str] = []

    for index, section in enumerate(
        sections,
        start=1,
    ):
        heading = " ".join(
            str(
                section.heading
                or "Policy Details"
            ).split()
        ).strip()
        body = str(section.text or "").strip()
        page_label = (
            f" · Page {section.page_number}"
            if getattr(
                section,
                "page_number",
                None,
            )
            else ""
        )

        blocks.append(
            (
                f"{'─' * 56}\n"
                f"{index}. {heading}{page_label}\n"
                f"{body}"
            ).strip()
        )

    if blocks:
        blocks.append("─" * 56)

    return "\n".join(blocks)


def _policy_text_to_html(value: str) -> str:
    """Escape source text and preserve every line explicitly."""

    return (
        html.escape(value)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


def _render_full_section_preview(
    sections,
) -> None:
    """Render all extracted sections inside a bounded scroll viewer.

    Every heading and line remains available. The fixed-height viewer keeps
    large files from making the Policies page excessively long.
    """

    if not sections:
        st.info("No extracted policy content is available.")
        return

    section_cards: list[str] = []

    for index, section in enumerate(
        sections,
        start=1,
    ):
        heading = " ".join(
            str(
                section.heading
                or "Policy Details"
            ).split()
        ).strip()
        body = str(section.text or "").strip()
        page_label = (
            f" · Page {section.page_number}"
            if getattr(
                section,
                "page_number",
                None,
            )
            else ""
        )

        safe_heading = html.escape(
            f"{index}. {heading}{page_label}"
        )
        safe_body = _policy_text_to_html(body)

        section_cards.append(
            (
                "<section class='hr-policy-preview-section'>"
                "<div class='hr-policy-preview-heading'>"
                f"{safe_heading}"
                "</div>"
                "<div class='hr-policy-preview-content'>"
                f"{safe_body}"
                "</div>"
                "</section>"
            )
        )

    st.markdown("**Extracted Text Preview**")
    st.caption(
        "Scroll inside the preview box to review all extracted text."
    )
    st.markdown(
        (
            "<div class='hr-policy-section-preview'>"
            f"{''.join(section_cards)}"
            "<div class='hr-policy-preview-final-line'></div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )



def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "—"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_datetime(value) -> str:
    return PolicyService.format_datetime(
        value,
        get_settings().display_timezone,
    )


def _policy_id(policy) -> str:
    return PolicyService.public_id_for(policy)


def _filename_title(policy, document) -> str:
    if document is None:
        return policy.title
    return f"{document.original_filename}\n{policy.title}"


def _extracted_text_filename(view: PolicyAdminView) -> str:
    source_name = view.document.original_filename if view.document else view.policy.title
    return f"{Path(source_name).stem.strip() or 'policy'}_extracted_text.txt"


def _policy_rows(policies, document_map, *, include_bin_date: bool = False):
    rows = []
    for policy in policies:
        document = document_map.get(policy.id)
        row = {
            "Policy ID": _policy_id(policy),
            "Filename / Title": _filename_title(policy, document),
            "Category": policy.category,
            "Version": policy.version,
            "File Size": _format_size(document.size_bytes if document else None),
            "Date Uploaded": _format_datetime(policy.created_at),
        }
        if include_bin_date:
            row["Moved to Bin"] = _format_datetime(policy.trashed_at)
        rows.append(row)
    return rows


def _render_policy_table(
    policies,
    document_map,
    *,
    key: str,
    include_bin_date: bool = False,
    max_height: int | None = POLICY_LIBRARY_TABLE_HEIGHT,
) -> None:
    """Render a bounded policy list with visible table scrollbars."""

    rows = _policy_rows(
        policies,
        document_map,
        include_bin_date=include_bin_date,
    )
    search_terms = multi_search_input(
        "Search Policies",
        placeholder="Type any value shown in the policy table, then press Enter…",
        key=f"{key}_multi_search",
    )
    rows = [row for row in rows if matches_visible_row(search_terms, row)]

    if not rows:
        st.info(
            "No policy versions are available in this section."
        )
        return

    widths = (
        "115px",
        "330px",
        "190px",
        "100px",
        "120px",
        "190px",
    )

    if include_bin_date:
        widths = (*widths, "190px")

    render_admin_table(
        rows,
        key=key,
        min_width=(
            1180
            if not include_bin_date
            else 1340
        ),
        column_widths=widths,
        max_height=max_height,
    )


def _render_overview(view: PolicyAdminView) -> None:
    policy, document = view.policy, view.document
    metrics = st.columns(4)
    metrics[0].metric("Policy ID", _policy_id(policy))
    metrics[1].metric("Version", policy.version)
    metrics[2].metric("Category", policy.category)
    metrics[3].metric("Sections", len(view.sections))

    rows = [
        {"Field": "Filename / Title", "Value": _filename_title(policy, document)},
        {"Field": "Date uploaded", "Value": _format_datetime(policy.created_at)},
        {"Field": "Library location", "Value": "Bin" if policy.status == "trashed" else "Policies"},
        {"Field": "Source type", "Value": "Uploaded file" if document else "Legacy manual entry"},
    ]
    render_admin_table(
        rows,
        key=f"policy-overview-{policy.id}",
        min_width=680,
        column_widths=("190px", "490px"),
        compact=True,
    )

    if document:
        render_admin_table(
            [
                {"Field": "Original filename", "Value": document.original_filename},
                {"Field": "File type", "Value": f"{document.file_extension.upper()} · {document.mime_type}"},
                {"Field": "File size", "Value": _format_size(document.size_bytes)},
                {"Field": "Page count", "Value": document.page_count or "Not available"},
                {"Field": "SHA-256", "Value": document.sha256},
            ],
            key=f"policy-file-{policy.id}",
            min_width=680,
            column_widths=("190px", "490px"),
            compact=True,
        )


def _render_extracted_content(view: PolicyAdminView) -> None:
    """Show complete extracted text in a fixed-height scroll viewer."""

    text = view.extracted_text or ""
    st.caption(
        f"{len(text):,} extracted characters · "
        "scroll inside the box to review the complete content"
    )
    st.text_area(
        "Extracted Policy Content",
        value=text,
        height=POLICY_CONTENT_VIEWER_HEIGHT,
        disabled=True,
        key=f"policy_content_{view.policy.id}",
    )
    st.download_button(
        "Download Complete Extracted Text",
        data=text.encode("utf-8"),
        file_name=_extracted_text_filename(view),
        mime="text/plain",
        width="stretch",
        key=f"download_extracted_{view.policy.id}",
    )


def _render_sections(view: PolicyAdminView) -> None:
    """Render searchable policy sections in a bounded scroll box."""

    section_search = multi_search_input(
        "Find in Sections",
        placeholder="Type a heading or extracted-text term, then press Enter…",
        key=f"section_search_{view.policy.id}",
    )
    matches = [
        section
        for section in view.sections
        if matches_search_terms(
            section_search,
            (section.sequence_number, section.heading, section.text, section.page_number or ""),
        )
    ]
    st.caption(
        f"Showing {len(matches)} of {len(view.sections)} sections · "
        "scroll inside the results box when more sections are available"
    )

    if not matches:
        st.info("No searchable sections match the current search.")
        return

    with st.container(
        key=(
            f"policy_section_results_"
            f"{view.policy.id}"
        ),
        height=POLICY_SECTION_RESULTS_HEIGHT,
        border=True,
    ):
        for section in matches:
            page = (
                f" · Page {section.page_number}"
                if section.page_number
                else ""
            )
            with st.expander(
                f"{section.sequence_number}. "
                f"{section.heading}{page}"
            ):
                st.write(section.text)


def _render_original_file(current_user: AuthenticatedUser, view: PolicyAdminView) -> None:
    if view.document is None:
        st.info("No original uploaded file exists for this legacy record.")
        return
    try:
        with SessionFactory() as session:
            download = PolicyService(session).get_policy_download(
                company_id=current_user.company_id,
                policy_id=view.policy.id,
                published_only=False,
            )
        st.download_button(
            "Download Original Policy File",
            data=download.data,
            file_name=download.filename,
            mime=download.mime_type,
            width="stretch",
            key=f"download_original_{view.policy.id}",
        )
    except (ValueError, FileNotFoundError) as error:
        render_action_warning(error)


def _version_rows(current_user: AuthenticatedUser, title: str):
    with SessionFactory() as session:
        service = PolicyService(session)
        versions = service.repository.list_by_title(
            company_id=current_user.company_id,
            title=title,
        )
        documents = service.get_document_map(
            company_id=current_user.company_id,
            policies=versions,
        )
    rows = []
    for policy in versions:
        doc = documents.get(policy.id)
        rows.append({
            "Policy ID": _policy_id(policy),
            "Version": policy.version,
            "Filename": doc.original_filename if doc else "Legacy manual entry",
            "Date Uploaded": _format_datetime(policy.created_at),
            "Location": "Bin" if policy.status == "trashed" else "Policies",
        })
    return rows


def _render_version_history(current_user: AuthenticatedUser, view: PolicyAdminView) -> None:
    """Render complete version history in a fixed-height table."""

    rows = _version_rows(current_user, view.policy.title)
    search_terms = multi_search_input(
        "Search Version History",
        placeholder="Type any value shown in the version table, then press Enter…",
        key=f"policy_version_history_search_{view.policy.id}",
    )
    rows = [row for row in rows if matches_visible_row(search_terms, row)]
    st.caption(
        f"{len(rows)} matching version(s) · scroll inside the table when the "
        "history exceeds the fixed view"
    )
    render_admin_table(
        rows,
        key=f"version-history-{view.policy.id}",
        min_width=900,
        column_widths=("120px", "100px", "300px", "190px", "110px"),
        max_height=POLICY_VERSION_HISTORY_HEIGHT,
    )


def _render_move_to_bin(current_user: AuthenticatedUser, view: PolicyAdminView) -> None:
    public_id = _policy_id(view.policy)
    st.warning(
        "This keeps the file and all extracted content in the Bin. "
        "Employees and Policy Q&A will no longer see this version."
    )
    st.info(
        f"Selected target: {public_id} · {view.policy.title} "
        f"v{view.policy.version}"
    )
    move_confirmation_key = f"confirm_move_policy_bin_{view.policy.id}"
    invalidate_confirmation_on_change(
        confirmation_key=move_confirmation_key,
        dependencies={"policy_id": view.policy.id},
        tracker_key="__policy_move_to_bin_target_confirmation",
    )
    with st.form(f"move_policy_bin_{view.policy.id}"):
        acknowledged = st.checkbox(
            "I confirm that the selected policy version above should "
            "be moved to the Bin.",
            key=move_confirmation_key,
        )
        submitted = st.form_submit_button(
            "Move Policy Version to Bin",
            width="stretch",
        )
    if submitted:
        if not acknowledged:
            st.error(
                "Select the confirmation checkbox before moving the "
                "policy to the Bin."
            )
            return

        try:
            with st.spinner("Moving policy version to Bin…"):
                with SessionFactory() as session:
                    moved = PolicyService(session).move_to_bin(
                        company_id=current_user.company_id,
                        policy_id=view.policy.id,
                        user_id=current_user.user_id,
                        confirmation_public_id=public_id,
                    )
            set_operation_feedback(
                f"Moved {_policy_id(moved)} · {moved.title} v{moved.version} to Bin.",
                namespace="policy",
            )
            st.rerun()
        except ValueError as error:
            render_action_warning(error)


def _render_policy_upload_result() -> None:
    """Show one batch result after the uploader is safely remounted."""

    result = st.session_state.pop(
        _POLICY_UPLOAD_RESULT_STATE_KEY,
        None,
    )
    if not isinstance(result, dict):
        return

    successes = list(result.get("successes") or [])
    failures = list(result.get("failures") or [])

    if successes:
        st.success(
            f"{len(successes)} policy file(s) uploaded and published "
            "successfully."
        )
        st.caption(" · ".join(str(item) for item in successes))

    if failures:
        lines = []
        for failure in failures:
            if isinstance(failure, dict):
                filename = str(failure.get("filename") or "Policy file")
                message = str(
                    failure.get("message")
                    or "The file could not be processed."
                )
                lines.append(f"- **{filename}** — {message}")
        if lines:
            st.warning(
                f"{len(lines)} policy file(s) were not uploaded.\n\n"
                + "\n".join(lines)
            )


def _policy_upload_validation_message(error: ValidationError) -> str:
    """Return a short validation message suitable for one batch row."""

    errors = error.errors()
    if not errors:
        return "The policy metadata is invalid."
    return str(errors[0].get("msg") or "The policy metadata is invalid.")


def _render_upload(current_user: AuthenticatedUser, all_versions) -> None:
    """Render single- or multi-file policy upload without batch-wide failure."""

    settings = get_settings()

    upload_nonce = _get_policy_upload_nonce()
    _cleanup_old_policy_upload_state(upload_nonce)
    st.subheader("Upload Policy File")
    st.caption(
        "Select one or multiple policy documents. Each file becomes its own "
        "published policy/version, with independent title, category, version "
        "history, extraction, and Policy Q&A content."
    )
    _render_policy_upload_result()

    uploaded_files = st.file_uploader(
        "Policy File(s) *",
        type=[ext.lstrip(".") for ext in sorted(ALLOWED_POLICY_EXTENSIONS)],
        accept_multiple_files=True,
        help=(
            f"Maximum size: {settings.policy_upload_max_mb} MB per file. "
            "Supported files are processed independently, so one invalid "
            "document does not cancel the rest of the batch. Scanned "
            "image-only PDFs are not supported yet."
        ),
        key=_policy_upload_widget_key(
            upload_nonce,
            "file",
        ),
    )
    if not uploaded_files:
        st.info(
            "Choose one or more files to generate titles, category suggestions, "
            "version history, and document previews."
        )
        return

    uploaded_files = list(uploaded_files)
    st.caption(
        f"{len(uploaded_files)} file(s) selected · "
        f"{settings.policy_upload_max_mb} MB maximum per file"
    )

    unique_titles = sorted({p.title for p in all_versions})
    prepared: list[dict] = []
    preview_failures: list[dict] = []
    seen_document_hashes: set[str] = set()

    for file_index, uploaded in enumerate(uploaded_files, start=1):
        file_bytes = uploaded.getvalue()
        selection_fingerprint = hashlib.sha256(file_bytes).hexdigest()[:12]

        with st.container(border=True):
            st.markdown(f"**{file_index}. {uploaded.name}**")

            link_options = [
                _AUTO_VERSION_LINK_LABEL,
                *unique_titles,
            ]
            link_choice = st.selectbox(
                "Version linking",
                options=link_options,
                key=_policy_upload_widget_key(
                    upload_nonce,
                    f"version_linking_{selection_fingerprint}_{file_index}",
                ),
                help=(
                    "Keep Auto-detect when the filename identifies the policy. "
                    "Choose an existing policy only when this file is a new "
                    "version with a different filename."
                ),
            )
            selected_title = (
                None
                if link_choice == _AUTO_VERSION_LINK_LABEL
                else link_choice
            )

            try:
                with SessionFactory() as session:
                    preview = PolicyService(session).preview_policy_upload(
                        company_id=current_user.company_id,
                        filename=uploaded.name,
                        file_bytes=file_bytes,
                        maximum_size_bytes=(
                            settings.policy_upload_max_mb * 1024 * 1024
                        ),
                        mime_type=uploaded.type,
                        selected_existing_title=selected_title,
                    )
            except ValueError as error:
                message = str(error)
                st.error(message)
                preview_failures.append(
                    {
                        "filename": uploaded.name,
                        "message": message,
                    }
                )
                continue

            if preview.parsed.sha256 in seen_document_hashes:
                message = "The same file was selected more than once in this batch."
                st.error(message)
                preview_failures.append(
                    {
                        "filename": uploaded.name,
                        "message": message,
                    }
                )
                continue
            seen_document_hashes.add(preview.parsed.sha256)

            fingerprint = hashlib.sha256(
                (preview.parsed.sha256 + preview.display_title).encode("utf-8")
            ).hexdigest()[:12]
            category_key = _policy_upload_widget_key(
                upload_nonce,
                f"category_{fingerprint}",
            )
            version_key = _policy_upload_widget_key(
                upload_nonce,
                f"version_{fingerprint}",
            )
            if category_key not in st.session_state:
                st.session_state[category_key] = preview.suggested_category
            if version_key not in st.session_state:
                st.session_state[version_key] = (
                    "1.0" if not preview.previous_versions else ""
                )

            columns = st.columns([1.35, 1.0, 0.7, 0.9], gap="small")
            with columns[0]:
                st.text_input(
                    "Policy Filename / Title",
                    value=preview.display_title,
                    disabled=True,
                    key=_policy_upload_widget_key(
                        upload_nonce,
                        f"title_{fingerprint}",
                    ),
                )
            with columns[1]:
                category = st.text_input(
                    "Category *",
                    key=category_key,
                    max_chars=100,
                    help=(
                        "Used for filtering and organizing Policy Q&A. "
                        "The suggestion is editable."
                    ),
                )
            with columns[2]:
                version = st.text_input(
                    "Version *",
                    key=version_key,
                    max_chars=30,
                    placeholder="Example: 1.1",
                    help="Manual input. Previous versions are shown below.",
                )
            with columns[3]:
                st.text_input(
                    "Date Uploaded",
                    value=_format_datetime(datetime.now(timezone.utc)),
                    disabled=True,
                    key=_policy_upload_widget_key(
                        upload_nonce,
                        f"date_{fingerprint}",
                    ),
                    help=(
                        "The final date and time are recorded automatically "
                        "when this file is uploaded."
                    ),
                )

            if preview.previous_versions:
                st.markdown("**Previous versions**")
                render_admin_table(
                    [
                        {
                            "Policy ID": item.public_id,
                            "Version": item.version,
                            "Date Uploaded": _format_datetime(item.uploaded_at),
                            "Location": "Bin" if item.in_bin else "Policies",
                        }
                        for item in preview.previous_versions
                    ],
                    key=(
                        f"upload-history-{upload_nonce}-"
                        f"{fingerprint}-{file_index}"
                    ),
                    min_width=700,
                    column_widths=("130px", "120px", "260px", "130px"),
                    compact=True,
                    max_height=POLICY_VERSION_HISTORY_HEIGHT,
                )
            else:
                st.caption("No previous version was detected for this title.")

            with st.expander(
                f"Document Preview — {file_index}. {uploaded.name}",
                expanded=(len(uploaded_files) == 1),
            ):
                st.caption(
                    f"{len(preview.parsed.sections)} searchable sections · "
                    f"{_format_size(preview.parsed.size_bytes)} · "
                    f"{preview.parsed.original_filename}"
                )
                _render_detected_headings(preview.parsed.sections)
                _render_full_section_preview(preview.parsed.sections)

            prepared.append(
                {
                    "uploaded": uploaded,
                    "file_bytes": file_bytes,
                    "preview": preview,
                    "category": category,
                    "version": version,
                }
            )

    if preview_failures:
        st.warning(
            f"{len(preview_failures)} selected file(s) cannot be prepared. "
            "Ready files can still be uploaded independently."
        )

    if not prepared:
        return

    submit_label = (
        "Upload and Process Policy"
        if len(uploaded_files) == 1
        else f"Upload and Process {len(prepared)} Policy Files"
    )
    submitted = st.button(
        submit_label,
        type="primary",
        width="stretch",
        key=_policy_upload_widget_key(
            upload_nonce,
            "submit",
        ),
    )
    if not submitted:
        return

    successes: list[str] = []
    failures: list[dict] = list(preview_failures)

    with st.spinner(
        f"Uploading, extracting, and publishing {len(prepared)} policy file(s)…"
    ):
        for item in prepared:
            uploaded = item["uploaded"]
            preview = item["preview"]

            try:
                request = PolicyUploadRequest(
                    company_id=current_user.company_id,
                    created_by_user_id=current_user.user_id,
                    title=preview.display_title,
                    category=item["category"],
                    version=item["version"],
                )
                # A separate transaction/session per file prevents one failed
                # document from rolling back successful files in the batch.
                with SessionFactory() as session:
                    policy = PolicyService(session).create_policy_from_upload(
                        values=request,
                        filename=uploaded.name,
                        file_bytes=item["file_bytes"],
                        mime_type=uploaded.type,
                        maximum_size_bytes=(
                            settings.policy_upload_max_mb * 1024 * 1024
                        ),
                    )
                successes.append(
                    f"{_policy_id(policy)} · {policy.title} v{policy.version}"
                )
            except ValidationError as error:
                failures.append(
                    {
                        "filename": uploaded.name,
                        "message": _policy_upload_validation_message(error),
                    }
                )
            except ValueError as error:
                failures.append(
                    {
                        "filename": uploaded.name,
                        "message": str(error),
                    }
                )
            except Exception:
                failures.append(
                    {
                        "filename": uploaded.name,
                        "message": (
                            "The file could not be processed. Confirm that it "
                            "is readable and supported."
                        ),
                    }
                )

    st.session_state[_POLICY_UPLOAD_RESULT_STATE_KEY] = {
        "successes": successes,
        "failures": failures,
    }

    # Remount the uploader after every attempted batch. Successful files are
    # already committed individually; failed files can be reselected without
    # accidentally resubmitting the successful documents.
    _advance_policy_upload_state(upload_nonce)

    if successes:
        set_operation_feedback(
            f"Policy upload completed: {len(successes)} successful, "
            f"{len(failures)} failed.",
            namespace="policy",
        )

    st.rerun()


def _render_edit_policy_details(
    current_user: AuthenticatedUser,
    view: PolicyAdminView,
) -> None:
    """Edit family metadata and the selected version identifier."""

    policy = view.policy

    st.info(
        "Policy Title and Category apply to every version currently "
        "grouped under this policy. Version and Content apply only to "
        "the selected record. Saving Content regenerates the searchable "
        "sections used by Policy Q&A. The original uploaded file remains "
        "unchanged and can still be downloaded."
    )

    with st.form(
        f"edit_policy_metadata_{policy.id}"
    ):
        title = st.text_input(
            "Policy Title / Family Name *",
            value=policy.title,
            max_chars=200,
        )
        category = st.text_input(
            "Category *",
            value=policy.category,
            max_chars=100,
        )
        version = st.text_input(
            "Selected Version *",
            value=policy.version,
            max_chars=30,
        )
        content = st.text_area(
            "Editable Policy Content *",
            value=view.extracted_text,
            height=POLICY_CONTENT_EDITOR_HEIGHT,
            key=f"editable_policy_content_{policy.id}",
            help=(
                "This approved searchable text is used by the content "
                "viewer and Policy Q&A. Scroll inside the editor to review "
                "the complete content. Editing it does not replace the "
                "original uploaded file."
            ),
        )
        st.caption(
            "Saving content rebuilds searchable sections. Page-number "
            "references are removed because edited text may no longer "
            "match the original file pages exactly."
        )

        submitted = st.form_submit_button(
            "Save Policy Changes",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return

    try:
        request = PolicyMetadataUpdate(
            company_id=current_user.company_id,
            policy_id=policy.id,
            title=title,
            category=category,
            version=version,
            content=content,
        )

        with st.spinner(
            "Saving policy details…"
        ):
            with SessionFactory() as session:
                updated = PolicyService(
                    session
                ).update_policy_metadata(request)

        set_operation_feedback(
            f"Updated {_policy_id(updated)} · "
            f"{updated.title} v{updated.version}.",
            namespace="policy",
        )
        st.rerun()

    except ValidationError as error:
        render_action_warning(error)
    except ValueError as error:
        render_action_warning(error)


def _render_upload_new_version(
    current_user: AuthenticatedUser,
    view: PolicyAdminView,
) -> None:
    """Upload a new source file version for the selected policy family."""

    settings = get_settings()
    policy = view.policy
    nonce = _get_policy_version_nonce(policy.id)
    _cleanup_policy_version_state(
        policy.id,
        nonce,
    )

    st.info(
        f"Selected policy: {_policy_id(policy)} · "
        f"{policy.title} v{policy.version}. "
        "The new upload keeps the same policy family and creates "
        "a separate version record."
    )

    uploaded = st.file_uploader(
        "New Version Policy File *",
        type=[
            ext.lstrip(".")
            for ext in sorted(
                ALLOWED_POLICY_EXTENSIONS
            )
        ],
        help=(
            f"Maximum size: "
            f"{settings.policy_upload_max_mb} MB."
        ),
        key=_policy_version_widget_key(
            policy.id,
            nonce,
            "file",
        ),
    )

    if uploaded is None:
        st.caption(
            "Choose the replacement document for the new version. "
            "The current version remains unchanged."
        )
        return

    try:
        with SessionFactory() as session:
            preview = PolicyService(
                session
            ).preview_policy_upload(
                company_id=current_user.company_id,
                filename=uploaded.name,
                file_bytes=uploaded.getvalue(),
                maximum_size_bytes=(
                    settings.policy_upload_max_mb
                    * 1024
                    * 1024
                ),
                mime_type=uploaded.type,
                selected_existing_title=policy.title,
            )
    except ValueError as error:
        render_action_warning(error)
        return

    fingerprint = hashlib.sha256(
        (
            preview.parsed.sha256
            + preview.display_title
        ).encode("utf-8")
    ).hexdigest()[:12]

    category_key = _policy_version_widget_key(
        policy.id,
        nonce,
        f"category_{fingerprint}",
    )
    version_key = _policy_version_widget_key(
        policy.id,
        nonce,
        f"version_{fingerprint}",
    )

    if category_key not in st.session_state:
        st.session_state[category_key] = (
            policy.category
        )

    if version_key not in st.session_state:
        st.session_state[version_key] = ""

    columns = st.columns(3)

    with columns[0]:
        st.text_input(
            "Policy Filename / Title",
            value=policy.title,
            disabled=True,
        )

    with columns[1]:
        category = st.text_input(
            "Category *",
            key=category_key,
            max_chars=100,
        )

    with columns[2]:
        version = st.text_input(
            "New Version *",
            key=version_key,
            max_chars=30,
            placeholder=(
                f"Latest: "
                f"{preview.latest_version or policy.version}"
            ),
        )

    st.text_input(
        "Date Uploaded",
        value=_format_datetime(
            datetime.now(timezone.utc)
        ),
        disabled=True,
    )

    st.markdown("**Existing version history**")
    render_admin_table(
        [
            {
                "Policy ID": item.public_id,
                "Version": item.version,
                "Date Uploaded": _format_datetime(
                    item.uploaded_at
                ),
                "Location": (
                    "Bin"
                    if item.in_bin
                    else "Policies"
                ),
            }
            for item in preview.previous_versions
        ],
        key=(
            f"managed-version-history-"
            f"{policy.id}-{nonce}-{fingerprint}"
        ),
        min_width=700,
        column_widths=(
            "130px",
            "120px",
            "260px",
            "130px",
        ),
        compact=True,
        max_height=POLICY_VERSION_HISTORY_HEIGHT,
    )

    with st.expander(
        "New Version Document Preview",
        expanded=True,
    ):
        st.caption(
            f"{len(preview.parsed.sections)} searchable sections · "
            f"{_format_size(preview.parsed.size_bytes)} · "
            f"{preview.parsed.original_filename}"
        )
        _render_detected_headings(
            preview.parsed.sections
        )
        _render_full_section_preview(
            preview.parsed.sections
        )

    if not st.button(
        "Upload New Policy Version",
        type="primary",
        width="stretch",
        key=_policy_version_widget_key(
            policy.id,
            nonce,
            "submit",
        ),
    ):
        return

    try:
        request = PolicyUploadRequest(
            company_id=current_user.company_id,
            created_by_user_id=current_user.user_id,
            title=policy.title,
            category=category,
            version=version,
        )

        with st.spinner(
            "Uploading and publishing new policy version…"
        ):
            with SessionFactory() as session:
                created = PolicyService(
                    session
                ).create_policy_from_upload(
                    values=request,
                    filename=uploaded.name,
                    file_bytes=uploaded.getvalue(),
                    mime_type=uploaded.type,
                    maximum_size_bytes=(
                        settings.policy_upload_max_mb
                        * 1024
                        * 1024
                    ),
                )

        _advance_policy_version_state(
            policy.id,
            nonce,
        )
        set_operation_feedback(
            f"Uploaded new version "
            f"{_policy_id(created)} · "
            f"{created.title} v{created.version}.",
            namespace="policy",
        )
        st.rerun()

    except ValidationError as error:
        render_action_warning(error)
    except ValueError as error:
        render_action_warning(error)
    except Exception:
        st.error(
            "The new policy version could not be processed."
        )


def _render_permanent_delete(
    current_user: AuthenticatedUser,
    view: PolicyAdminView,
) -> None:
    """Render the protected permanent-delete action for a Bin version."""

    policy = view.policy
    public_id = _policy_id(policy)

    st.error(
        "Permanent deletion cannot be undone. It removes this exact "
        "version, its original file, extracted text, and searchable "
        "sections. Other versions remain."
    )
    st.info(
        f"Selected target: {public_id} · {policy.title} v{policy.version}"
    )

    confirmation_checkbox_key = f"permanent_delete_policy_ack_{policy.id}"
    invalidate_confirmation_on_change(
        confirmation_key=confirmation_checkbox_key,
        dependencies={"policy_id": policy.id},
        tracker_key="__policy_permanent_delete_target_confirmation",
    )
    acknowledged = st.checkbox(
        "I understand that this policy version and its file "
        "will be permanently deleted.",
        key=confirmation_checkbox_key,
    )
    submitted = st.button(
        "Delete Policy Version Permanently",
        width="stretch",
        disabled=not acknowledged,
        key=f"permanent_delete_policy_submit_{policy.id}",
    )

    if not submitted:
        return

    try:
        # The selected Bin version is the confirmation target. Keep the
        # service-level public-ID match as a defense-in-depth guard without
        # requiring the administrator to retype an ID already selected above.
        request = PolicyPermanentDeleteRequest(
            company_id=current_user.company_id,
            policy_id=policy.id,
            confirmation_public_id=public_id,
            permanent_delete_acknowledged=acknowledged,
        )

        with st.spinner(
            "Permanently deleting policy version…"
        ):
            with SessionFactory() as session:
                deleted = PolicyService(
                    session
                ).permanently_delete_from_bin(
                    request
                )

        set_operation_feedback(
            f"Permanently deleted "
            f"{deleted.public_id} · "
            f"{deleted.title} v{deleted.version}.",
            namespace="policy",
        )
        st.rerun()

    except ValidationError as error:
        render_action_warning(error)
    except ValueError as error:
        render_action_warning(error)


def _render_policy_library(
    current_user: AuthenticatedUser,
    policies,
    document_map,
) -> None:
    """Render the active policy list and an on-demand content preview.

    The library stays read-only. A policy preview is loaded only after the
    administrator explicitly clicks the preview button, so the page does not
    automatically expand into a long document viewer.
    """

    st.subheader("Policy Library")
    st.caption(
        "Review all active policy versions. The table stays inside a "
        "fixed-height scroll box. Select one policy and click Preview to "
        "read its approved extracted content below."
    )

    _render_policy_table(
        policies,
        document_map,
        key="policy-list",
        max_height=POLICY_LIBRARY_TABLE_HEIGHT,
    )

    if not policies:
        st.session_state.pop(
            _POLICY_LIBRARY_PREVIEW_STATE_KEY,
            None,
        )
        return

    options = {
        f"{_policy_id(policy)} · {policy.title} v{policy.version}": policy.id
        for policy in policies
    }
    selected_label = st.selectbox(
        "Select Policy to Preview",
        options=list(options),
        key="policy_library_preview_selector",
    )
    selected_id = options[selected_label]

    preview_column, close_column = st.columns([3, 1])

    with preview_column:
        preview_clicked = st.button(
            "Preview Selected Policy",
            type="primary",
            width="stretch",
            key="preview_selected_policy",
        )

    with close_column:
        close_clicked = st.button(
            "Close Preview",
            width="stretch",
            key="close_policy_library_preview",
        )

    if preview_clicked:
        st.session_state[
            _POLICY_LIBRARY_PREVIEW_STATE_KEY
        ] = selected_id

    if close_clicked:
        st.session_state.pop(
            _POLICY_LIBRARY_PREVIEW_STATE_KEY,
            None,
        )

    preview_id = st.session_state.get(
        _POLICY_LIBRARY_PREVIEW_STATE_KEY
    )
    active_ids = {policy.id for policy in policies}

    if preview_id not in active_ids:
        st.session_state.pop(
            _POLICY_LIBRARY_PREVIEW_STATE_KEY,
            None,
        )
        preview_id = None

    if preview_id is None:
        st.info(
            "Select a policy and click Preview Selected Policy to show "
            "its content here."
        )
        return

    try:
        with SessionFactory() as session:
            view = PolicyService(
                session
            ).get_admin_policy_view(
                company_id=current_user.company_id,
                policy_id=int(preview_id),
            )
    except (TypeError, ValueError) as error:
        st.session_state.pop(
            _POLICY_LIBRARY_PREVIEW_STATE_KEY,
            None,
        )
        render_action_warning(error)
        return

    document = view.document
    filename = (
        document.original_filename
        if document is not None
        else view.policy.title
    )

    st.divider()
    st.subheader("Policy Content Preview")
    st.caption(
        f"{_policy_id(view.policy)} · {view.policy.title} "
        f"v{view.policy.version} · {len(view.sections)} searchable "
        f"sections · {filename}"
    )

    # Match the bounded preview used by Upload Policy File. No edit, file,
    # history, or Bin actions are rendered in this read-only library view.
    _render_detected_headings(view.sections)
    _render_full_section_preview(view.sections)


def _render_manage(current_user: AuthenticatedUser, policies) -> None:
    st.subheader("Manage Existing Policy")
    if not policies:
        st.info("Upload a policy before managing existing versions.")
        return
    options = {
        f"{_policy_id(p)} · {p.title} v{p.version}": p.id
        for p in policies
    }
    selected_label = st.selectbox("Select Policy", options=list(options))
    selected_id = options[selected_label]
    try:
        with SessionFactory() as session:
            view = PolicyService(session).get_admin_policy_view(
                company_id=current_user.company_id,
                policy_id=selected_id,
            )
    except ValueError as error:
        render_action_warning(error); return

    tabs = persistent_tabs([
        "Overview",
        "Edit Details",
        "Upload New Version",
        "Extracted Content",
        "Searchable Sections",
        "Original File",
        "Version History",
        "Move to Bin",
    ], key="admin_policy_manage_detail_tab")
    with tabs[0]:
        _render_overview(view)
    with tabs[1]:
        _render_edit_policy_details(
            current_user,
            view,
        )
    with tabs[2]:
        _render_upload_new_version(
            current_user,
            view,
        )
    with tabs[3]:
        _render_extracted_content(view)
    with tabs[4]:
        _render_sections(view)
    with tabs[5]:
        _render_original_file(
            current_user,
            view,
        )
    with tabs[6]:
        _render_version_history(
            current_user,
            view,
        )
    with tabs[7]:
        _render_move_to_bin(
            current_user,
            view,
        )


def _render_bin(current_user: AuthenticatedUser, policies, document_map) -> None:
    st.subheader("Policy Bin")
    st.caption(
        "Bin versions are retained for history and can be restored. "
        "They are excluded from employee search, downloads, and Policy Q&A."
    )
    _render_policy_table(
        policies,
        document_map,
        key="policy-bin-list",
        include_bin_date=True,
    )
    if not policies:
        return
    options = {f"{_policy_id(p)} · {p.title} v{p.version}": p.id for p in policies}
    selected_label = st.selectbox("Select Bin Policy", options=list(options))
    selected_id = options[selected_label]
    with SessionFactory() as session:
        view = PolicyService(session).get_admin_policy_view(
            company_id=current_user.company_id,
            policy_id=selected_id,
        )
    tabs = persistent_tabs([
        "Overview",
        "Extracted Content",
        "Original File",
        "Version History",
        "Restore",
        "Delete Permanently",
    ], key="admin_policy_bin_detail_tab")
    with tabs[0]:
        _render_overview(view)
    with tabs[1]:
        _render_extracted_content(view)
    with tabs[2]:
        _render_original_file(
            current_user,
            view,
        )
    with tabs[3]:
        _render_version_history(
            current_user,
            view,
        )
    with tabs[4]:
        st.info(
            "Restore returns this exact version to the active "
            "Policies library."
        )
        if st.button(
            "Restore Policy Version",
            type="primary",
            width="stretch",
        ):
            try:
                with st.spinner(
                    "Restoring policy version…"
                ):
                    with SessionFactory() as session:
                        restored = PolicyService(
                            session
                        ).restore_from_bin(
                            company_id=current_user.company_id,
                            policy_id=selected_id,
                        )
                set_operation_feedback(
                    f"Restored {_policy_id(restored)} · "
                    f"{restored.title} v{restored.version}.",
                    namespace="policy",
                )
                st.rerun()
            except ValueError as error:
                render_action_warning(error)
    with tabs[5]:
        _render_permanent_delete(
            current_user,
            view,
        )


def render_admin_policies_page(current_user: AuthenticatedUser) -> None:
    """Render peer policy library, upload, management, and Bin tabs."""

    st.title("Policies")
    st.caption(
        "Upload and preview policy files, maintain company violations and "
        "disciplinary actions, track every version, and retain removed policy "
        "versions safely in the Bin."
    )
    render_operation_feedback(namespace="policy")

    with SessionFactory() as session:
        service = PolicyService(session)
        active = service.list_for_admin(current_user.company_id)
        bin_policies = service.list_bin(current_user.company_id)
        all_versions = service.list_all_versions(current_user.company_id)
        active_documents = service.get_document_map(
            company_id=current_user.company_id,
            policies=active,
        )
        bin_documents = service.get_document_map(
            company_id=current_user.company_id,
            policies=bin_policies,
        )

    policy_tab_labels = [
        "Policies",
        "Upload Policy File",
        "Manage Existing Policy",
        "Violations & Disciplinary Actions",
        f"Bin ({len(bin_policies)})",
    ]
    current_policy_tab = st.session_state.get("policies_active_tab")
    if (
        isinstance(current_policy_tab, str)
        and current_policy_tab.startswith("Bin (")
        and current_policy_tab not in policy_tab_labels
    ):
        st.session_state["policies_active_tab"] = policy_tab_labels[-1]

    policies_tab, upload_tab, manage_tab, violations_tab, bin_tab = persistent_tabs(
        policy_tab_labels,
        key="policies_active_tab",
    )

    with policies_tab:
        _render_policy_library(
            current_user,
            active,
            active_documents,
        )

    with upload_tab:
        _render_upload(
            current_user,
            all_versions,
        )

    with manage_tab:
        _render_manage(
            current_user,
            active,
        )

    with violations_tab:
        render_admin_policy_violations(current_user)

    with bin_tab:
        _render_bin(
            current_user,
            bin_policies,
            bin_documents,
        )
