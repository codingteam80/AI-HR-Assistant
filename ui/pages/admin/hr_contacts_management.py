"""Administrator HR contact directory management workspace."""

from __future__ import annotations

import streamlit as st

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from services.hr_contact_bulk_import_service import (
    HR_CONTACT_PREVIEW_COLUMNS,
    HRContactBulkImportService,
)
from services.hr_contact_service import HRContactService
from ui.components.data_table import render_admin_table
from ui.components.confirmation_guard import invalidate_confirmation_on_change
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)
from ui.components.validation_feedback import render_action_warning
from ui.components.persistent_tabs import persistent_tabs


_ACTIVE_TAB_KEY = "company_hr_contacts_active_tab"
_PENDING_TAB_KEY = "company_hr_contacts_pending_tab"
_ADD_NONCE_KEY = "company_hr_contacts_add_nonce"
_BULK_PREVIEW_KEY = "company_hr_contacts_bulk_preview"
_BULK_FILENAME_KEY = "company_hr_contacts_bulk_filename"


def _stay_on_hr_contacts(subtab: str) -> None:
    st.session_state["company_profile_pending_active_tab"] = "HR Contacts"
    st.session_state[_PENDING_TAB_KEY] = subtab


def _form_values(prefix: str, contact=None) -> dict[str, object]:
    """Render the compact horizontal Add/Edit HR Contact form."""

    name_col, name_spacer = st.columns([1.7, 4.3])
    with name_col:
        name = st.text_input(
            "Contact Name *",
            value=contact.name if contact else "",
            max_chars=180,
            key=f"{prefix}_name",
        )
    with name_spacer:
        st.empty()

    title_col, team_col = st.columns(2)
    with title_col:
        job_title = st.text_input(
            "Position / Role",
            value=contact.job_title if contact else "",
            max_chars=180,
            key=f"{prefix}_job_title",
        )
    with team_col:
        team = st.text_input(
            "Department / Team",
            value=contact.team if contact else "",
            max_chars=180,
            key=f"{prefix}_team",
        )

    email_col, phone_col, contact_spacer = st.columns([1.7, 1.7, 2.6])
    with email_col:
        email = st.text_input(
            "Email",
            value=contact.email if contact else "",
            max_chars=255,
            key=f"{prefix}_email",
        )
    with phone_col:
        phone = st.text_input(
            "Phone / Mobile",
            value=contact.phone if contact else "",
            max_chars=80,
            key=f"{prefix}_phone",
        )
    with contact_spacer:
        st.empty()

    location_col, availability_col = st.columns(2)
    with location_col:
        office_location = st.text_input(
            "Office / Location",
            value=contact.office_location if contact else "",
            max_chars=255,
            key=f"{prefix}_office_location",
        )
    with availability_col:
        availability = st.text_input(
            "Availability / Office Hours",
            value=contact.availability if contact else "",
            max_chars=255,
            key=f"{prefix}_availability",
        )

    notes = st.text_area(
        "Notes / Support Coverage",
        value=contact.notes if contact else "",
        height=110,
        max_chars=2000,
        key=f"{prefix}_notes",
        help="Optional guidance such as payroll, benefits, leave, or employee-relations support.",
    )

    st.caption(
        "Contact Name and at least one Email or Phone / Mobile are required. "
        "Display order is assigned automatically."
    )
    return {
        "name": name,
        "job_title": job_title,
        "team": team,
        "email": email,
        "phone": phone,
        "office_location": office_location,
        "availability": availability,
        "notes": notes,
    }


def _active_table(active_contacts) -> None:
    if not active_contacts:
        st.info("No active HR contacts. Add a contact or restore one from Archive.")
        return

    render_admin_table(
        [
            {
                "Order": contact.sort_order,
                "Contact Name": contact.name,
                "Position / Role": contact.job_title or "—",
                "Department / Team": contact.team or "—",
                "Email": contact.email or "—",
                "Phone / Mobile": contact.phone or "—",
                "Office / Location": contact.office_location or "—",
                "Availability": contact.availability or "—",
            }
            for contact in active_contacts
        ],
        key="admin-company-hr-contacts-active",
        min_width=1500,
        column_widths=(
            "85px",
            "220px",
            "210px",
            "200px",
            "260px",
            "170px",
            "220px",
            "220px",
        ),
        max_height=255,
    )


def _render_bulk_contact_upload(current_user: AuthenticatedUser) -> None:
    """Render template download, validation preview, and atomic Excel import."""

    with st.expander("Upload HR Contacts via Excel", expanded=False):
        st.caption(
            "Download the HR Contact template, enter the contact directory, "
            "then validate and preview before importing. Hover Excel column "
            "headers for field requirements; these contact fields are free text "
            "and have no hidden fixed selection list. Display Order is assigned "
            "automatically by the system."
        )
        template_data = HRContactBulkImportService.build_template()
        st.download_button(
            "Download HR Contact Excel Template",
            data=template_data,
            file_name="HR_Contact_Import_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="content",
            key="hr_contact_bulk_template_download",
        )

        uploaded_file = st.file_uploader(
            "Upload Completed HR Contact Template",
            type=["xlsx"],
            accept_multiple_files=False,
            key="hr_contact_bulk_upload_file",
            help="Only the downloadable .xlsx template is accepted.",
        )
        validate_clicked = st.button(
            "Validate and Preview HR Contacts",
            width="stretch",
            disabled=uploaded_file is None,
            key="hr_contact_bulk_validate",
        )
        if validate_clicked and uploaded_file is not None:
            try:
                if uploaded_file.size > 10 * 1024 * 1024:
                    raise ValueError("The HR Contact Excel file must not exceed 10 MB.")
                with st.spinner("Validating HR contact information…"):
                    with SessionFactory() as session:
                        preview = HRContactBulkImportService(session).prepare_preview(
                            uploaded_file.getvalue(),
                            filename=uploaded_file.name,
                            company_id=current_user.company_id,
                        )
                st.session_state[_BULK_PREVIEW_KEY] = preview
                st.session_state[_BULK_FILENAME_KEY] = uploaded_file.name
            except ValueError as error:
                st.session_state.pop(_BULK_PREVIEW_KEY, None)
                render_action_warning(error)

        preview_rows = st.session_state.get(_BULK_PREVIEW_KEY)
        if isinstance(preview_rows, list) and preview_rows:
            st.markdown("#### HR Contact Preview")
            st.caption(
                "Review every row before importing. Invalid rows must be "
                "corrected in Excel and validated again."
            )
            display_rows = [
                {column: row.get(column, "") for column in HR_CONTACT_PREVIEW_COLUMNS}
                for row in preview_rows
            ]
            st.data_editor(
                display_rows,
                width="stretch",
                hide_index=True,
                disabled=list(HR_CONTACT_PREVIEW_COLUMNS),
                key="hr_contact_bulk_preview_editor",
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
                "Import HR Contacts",
                type="primary",
                width="stretch",
                disabled=invalid_count > 0,
                key="hr_contact_bulk_import_submit",
            )
            if import_clicked:
                try:
                    with st.spinner("Importing HR contacts…"):
                        with SessionFactory() as session:
                            contacts = HRContactBulkImportService(session).import_preview_rows(
                                preview_rows,
                                company_id=current_user.company_id,
                            )
                    st.session_state.pop(_BULK_PREVIEW_KEY, None)
                    st.session_state.pop(_BULK_FILENAME_KEY, None)
                    _stay_on_hr_contacts("Active Contacts")
                    set_operation_feedback(
                        f"Successfully imported {len(contacts)} HR contact(s).",
                        namespace="hr_contacts",
                    )
                    st.rerun()
                except ValueError as error:
                    render_action_warning(error)
                except Exception:
                    st.error(
                        "The HR Contact batch could not be imported. No contact "
                        "from this batch was saved."
                    )


def _render_add(current_user: AuthenticatedUser) -> None:
    st.subheader("Add HR Contact")
    st.caption("Publish new HR contacts to the Employee Portal directory.")

    _render_bulk_contact_upload(current_user)
    st.divider()
    st.markdown("#### Add One HR Contact Manually")

    nonce = int(st.session_state.get(_ADD_NONCE_KEY, 0))
    values = _form_values(f"company_hr_contact_add_{nonce}")
    if st.button(
        "Add HR Contact",
        type="primary",
        width="stretch",
        key=f"company_hr_contact_add_submit_{nonce}",
    ):
        try:
            with SessionFactory() as session:
                contact = HRContactService(session).create_contact(
                    company_id=current_user.company_id,
                    values=values,
                )
            st.session_state[_ADD_NONCE_KEY] = nonce + 1
            _stay_on_hr_contacts("Active Contacts")
            set_operation_feedback(
                f"HR contact added: {contact.name}",
                namespace="hr_contacts",
            )
            st.rerun()
        except ValueError as error:
            render_action_warning(error)


def _render_edit(current_user: AuthenticatedUser, active_contacts) -> None:
    st.subheader("Edit HR Contact")
    if not active_contacts:
        st.info("No active HR contact is available to edit.")
        return

    options = {
        f"{contact.name} — {contact.job_title or 'HR Contact'} (ID {contact.id})": contact
        for contact in active_contacts
    }
    selected_label = st.selectbox(
        "Select HR Contact",
        options=list(options),
        key="company_hr_contact_edit_selection",
    )
    contact = options[selected_label]
    values = _form_values(f"company_hr_contact_edit_{contact.id}", contact)

    if st.button(
        "Save HR Contact Changes",
        type="primary",
        width="stretch",
        key=f"company_hr_contact_edit_submit_{contact.id}",
    ):
        try:
            with SessionFactory() as session:
                updated = HRContactService(session).update_contact(
                    company_id=current_user.company_id,
                    contact_id=contact.id,
                    values=values,
                )
            _stay_on_hr_contacts("Active Contacts")
            set_operation_feedback(
                f"HR contact updated: {updated.name}",
                namespace="hr_contacts",
            )
            st.rerun()
        except ValueError as error:
            render_action_warning(error)


def _render_archive(current_user: AuthenticatedUser, active_contacts, archived_contacts) -> None:
    st.subheader("Delete / Archive HR Contact")
    st.caption(
        "Archive is the safe-delete action. Archived contacts immediately stop "
        "appearing in Employee Portal → HR Contacts."
    )

    if not active_contacts:
        st.info("No active HR contact is available to archive.")
    else:
        archive_options = {
            f"{contact.name} (ID {contact.id})": contact.id
            for contact in active_contacts
        }
        archive_label = st.selectbox(
            "Select Active HR Contact",
            options=list(archive_options),
            key="company_hr_contact_archive_selection",
        )
        archive_id = archive_options[archive_label]
        archive_confirmation_key = f"company_hr_contact_archive_confirm_{archive_id}"
        invalidate_confirmation_on_change(
            confirmation_key=archive_confirmation_key,
            dependencies={"contact_id": archive_id},
            tracker_key="__hr_contact_archive_target_confirmation",
        )
        archive_confirmed = st.checkbox(
            "I confirm that this HR contact should be moved to Archive.",
            key=archive_confirmation_key,
        )
        if st.button(
            "Move HR Contact to Archive",
            width="stretch",
            disabled=not archive_confirmed,
            key=f"company_hr_contact_archive_submit_{archive_id}",
        ):
            try:
                with SessionFactory() as session:
                    name = HRContactService(session).archive_contact(
                        company_id=current_user.company_id,
                        contact_id=archive_id,
                        archived_by_user_id=current_user.user_id,
                    )
                _stay_on_hr_contacts("Archive")
                set_operation_feedback(
                    f"HR contact moved to Archive: {name}",
                    namespace="hr_contacts",
                )
                st.rerun()
            except ValueError as error:
                render_action_warning(error)

    st.divider()
    st.markdown(f"#### Archived HR Contacts ({len(archived_contacts)})")
    if not archived_contacts:
        st.info("No archived HR contacts.")
        return

    render_admin_table(
        [
            {
                "Order": contact.sort_order,
                "Contact Name": contact.name,
                "Position / Role": contact.job_title or "—",
                "Email": contact.email or "—",
                "Phone / Mobile": contact.phone or "—",
                "Archived": (
                    contact.archived_at.strftime("%Y-%m-%d %H:%M")
                    if contact.archived_at
                    else "—"
                ),
            }
            for contact in archived_contacts
        ],
        key="admin-company-hr-contacts-archive",
        min_width=1050,
        column_widths=("85px", "240px", "220px", "260px", "180px", "170px"),
        max_height=320,
    )

    archived_options = {
        f"{contact.name} (ID {contact.id})": contact.id
        for contact in archived_contacts
    }
    archived_label = st.selectbox(
        "Select Archived HR Contact",
        options=list(archived_options),
        key="company_hr_contact_archived_selection",
    )
    archived_id = archived_options[archived_label]

    restore_col, delete_col = st.columns(2)
    with restore_col:
        if st.button(
            "Restore HR Contact",
            type="primary",
            width="stretch",
            key=f"company_hr_contact_restore_submit_{archived_id}",
        ):
            try:
                with SessionFactory() as session:
                    name = HRContactService(session).restore_contact(
                        company_id=current_user.company_id,
                        contact_id=archived_id,
                    )
                _stay_on_hr_contacts("Active Contacts")
                set_operation_feedback(
                    f"HR contact restored: {name}",
                    namespace="hr_contacts",
                )
                st.rerun()
            except ValueError as error:
                render_action_warning(error)

    with delete_col:
        delete_confirmation_key = f"company_hr_contact_delete_confirm_{archived_id}"
        invalidate_confirmation_on_change(
            confirmation_key=delete_confirmation_key,
            dependencies={"archived_contact_id": archived_id},
            tracker_key="__hr_contact_permanent_delete_target_confirmation",
        )
        delete_confirmed = st.checkbox(
            "Permanently delete selected archived contact",
            key=delete_confirmation_key,
        )
        if st.button(
            "Permanently Delete",
            width="stretch",
            disabled=not delete_confirmed,
            key=f"company_hr_contact_delete_submit_{archived_id}",
        ):
            try:
                with SessionFactory() as session:
                    name = HRContactService(session).permanently_delete_contact(
                        company_id=current_user.company_id,
                        contact_id=archived_id,
                    )
                _stay_on_hr_contacts("Archive")
                set_operation_feedback(
                    f"HR contact permanently deleted: {name}",
                    namespace="hr_contacts",
                )
                st.rerun()
            except ValueError as error:
                render_action_warning(error)


def render_hr_contacts_management(current_user: AuthenticatedUser) -> None:
    """Render Company Profile → HR Contacts management controls."""

    st.subheader("HR Contacts Management")
    render_operation_feedback(namespace="hr_contacts")

    with SessionFactory() as session:
        contacts = HRContactService(session).list_contacts(current_user.company_id)

    active_contacts = [contact for contact in contacts if contact.is_active]
    archived_contacts = [contact for contact in contacts if not contact.is_active]

    pending_tab = st.session_state.pop(_PENDING_TAB_KEY, None)
    allowed_tabs = {"Active Contacts", "Add Contact", "Edit Contact", "Archive"}
    if pending_tab in allowed_tabs:
        st.session_state[_ACTIVE_TAB_KEY] = pending_tab

    active_tab, add_tab, edit_tab, archive_tab = persistent_tabs(
        ["Active Contacts", "Add Contact", "Edit Contact", "Archive"],
        key=_ACTIVE_TAB_KEY,
    )

    with active_tab:
        st.caption(
            f"{len(active_contacts)} active contact"
            f"{'s' if len(active_contacts) != 1 else ''} currently published."
        )
        _active_table(active_contacts)

    with add_tab:
        _render_add(current_user)

    with edit_tab:
        _render_edit(current_user, active_contacts)

    with archive_tab:
        _render_archive(current_user, active_contacts, archived_contacts)
