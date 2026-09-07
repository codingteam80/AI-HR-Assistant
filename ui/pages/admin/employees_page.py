"""Editable Employee Master Record administration page.

The page intentionally combines employee profile, training checklist, and
login-account information. Roles are no longer administered separately.
"""

from datetime import date
from html import escape
import json
import re

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from ui.components.persistent_tabs import persistent_tabs
from ui.components.confirmation_guard import invalidate_confirmation_on_change
from ui.components.employee_profile_photo import render_profile_photo_manager
from ui.components.disciplinary_records import render_admin_disciplinary_records
from pydantic import ValidationError

from authentication.current_user import AuthenticatedUser
from core.constants import CLEARANCE_LABELS
from database.session import SessionFactory
from schemas.admin_management_schema import (
    EmployeeAccountCreate,
    EmployeeDeleteRequest,
    EmployeeMasterUpdate,
    TrainingItemInput,
)
from services.admin_management_service import (
    AdminManagementService,
)
from services.employee_bulk_import_service import (
    ACCOUNT_PREVIEW_COLUMNS,
    EmployeeBulkImportService,
)
from services.edit_conflict import EditConflictError
from ui.components.live_search import multi_search_input
from utils.search_utils import filter_aligned_visible_rows, matches_visible_row
from ui.components.operation_feedback import (
    render_operation_feedback,
    set_operation_feedback,
)
from ui.pages.admin.onboarding_management import render_onboarding_management


EMPLOYMENT_STATUS_OPTIONS = {
    "Employed — Account Active": "employed",
    "Resigned — Account Inactive": "resigned",
}

GENDER_OPTIONS = ["Male", "Female"]
CIVIL_STATUS_OPTIONS = [
    "N/A",
    "Single",
    "Married",
    "Widowed",
    "Separated",
    "Divorced",
]
MISSING_VALUE_TOKENS = {"", "n/a", "na", "none", "null", "-", "—"}


def _optional_value(value: str | None) -> str | None:
    """Normalize blank and N/A-like optional form values to ``None``."""

    if value is None:
        return None

    normalized = str(value).strip()
    if normalized.casefold() in MISSING_VALUE_TOKENS:
        return None
    return normalized


def _display_value(value: object) -> str:
    """Display one missing table/detail value consistently as N/A."""

    if value is None:
        return "N/A"
    text = str(value).strip()
    return text if text and text.casefold() not in MISSING_VALUE_TOKENS else "N/A"


def _calculate_age(date_of_birth: date | None) -> int | None:
    """Calculate current age without storing a value that becomes stale."""

    if date_of_birth is None:
        return None
    today = date.today()
    return (
        today.year
        - date_of_birth.year
        - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
    )


def _parse_training_text(
    value: str,
) -> list[TrainingItemInput]:
    """Parse one checklist item per line.

    Accepted examples:
    [x] Safety Orientation
    [ ] Data Privacy
    Orientation
    """

    items: list[TrainingItemInput] = []

    for raw_line in value.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        completed = False

        completed_match = re.match(
            r"^\[(x|X|✓)\]\s*(.+)$",
            line,
        )
        pending_match = re.match(
            r"^\[\s\]\s*(.+)$",
            line,
        )

        if completed_match:
            completed = True
            title = completed_match.group(2).strip()
        elif pending_match:
            title = pending_match.group(1).strip()
        else:
            title = line.lstrip("•-").strip()

        if title:
            items.append(
                TrainingItemInput(
                    title=title,
                    is_completed=completed,
                )
            )

    return items


def _training_editor_value(employee) -> str:
    """Convert stored training rows into editable checklist text."""

    return "\n".join(
        (
            "[x] "
            if item.is_completed
            else "[ ] "
        )
        + item.title
        for item in employee.trainings
    )


def _training_cell(employee) -> str:
    """Combine training rows into one table cell."""

    if not employee.trainings:
        return "N/A"

    return "\n".join(
        (
            "☑ "
            if item.is_completed
            else "☐ "
        )
        + item.title
        for item in employee.trainings
    )


def _account_cell(employee) -> str:
    """Build one compact account summary cell."""

    if employee.user is None:
        return "N/A"

    clearance_label = CLEARANCE_LABELS.get(
        employee.user.clearance,
        "Unknown",
    )

    account_status = (
        "Active"
        if employee.user.is_active
        else "Inactive"
    )

    return (
        f"ID: {employee.user.id}\n"
        f"Username: {employee.user.username}\n"
        f"Clearance: {employee.user.clearance} - "
        f"{clearance_label}\n"
        f"Account: {account_status}"
    )


def _employee_rows(
    employees,
) -> list[dict[str, object]]:
    """Build employee rows with consistent N/A and clean full names."""

    rows: list[dict[str, object]] = []
    for employee in employees:
        rows.append(
            {
                "Employee Number": _display_value(employee.employee_number),
                "Full Name": employee.full_name or "N/A",
                "Job Title / Position": _display_value(employee.job_title),
                "Hired Date": (
                    employee.hire_date.isoformat()
                    if employee.hire_date
                    else "N/A"
                ),
                "Years of Service": _display_value(employee.years_of_service),
                "Department": _display_value(
                    employee.department.name if employee.department else None
                ),
                "Manager": _display_value(
                    employee.manager.full_name if employee.manager else None
                ),
                "Leader": _display_value(
                    employee.leader.full_name if employee.leader else None
                ),
                "Gender": _display_value(employee.gender),
                "Civil Status": _display_value(employee.civil_status),
                "Date of Birth": (
                    employee.date_of_birth.isoformat()
                    if employee.date_of_birth
                    else "N/A"
                ),
                "Age": _display_value(employee.age),
                "Email / Telephone / Mobile No.": (
                    f"Email: {_display_value(employee.work_email)}\n"
                    f"Tel/Mobile: {_display_value(employee.telephone_mobile_no)}"
                ),
                "Status": (
                    "Employed\nAccount Active"
                    if employee.employment_status == "employed"
                    else "Resigned\nAccount Inactive"
                ),
                "Training": _training_cell(employee),
                "Account": _account_cell(employee),
            }
        )
    return rows

def _filter_employees(
    employees,
    search_terms,
):
    """Filter Employee Master rows across every value shown in the table."""

    rows = _employee_rows(employees)
    filtered, _ = filter_aligned_visible_rows(employees, rows, search_terms)
    return filtered


def _assignment_options(
    employees,
    *,
    empty_label: str,
    exclude_employee_id: int | None = None,
) -> dict[str, int | None]:
    """Return employee choices with a role-specific empty option label."""

    return {
        empty_label: None,
        **{
            (
                f"{employee.employee_number} — "
                f"{employee.full_name}"
            ): employee.id
            for employee in employees
            if (
                exclude_employee_id is None
                or employee.id != exclude_employee_id
            )
            and employee.employment_status == "employed"
        },
    }


def _manager_options(
    employees,
    *,
    exclude_employee_id: int | None = None,
) -> dict[str, int | None]:
    """Return manager choices with the correct empty-state label."""

    return _assignment_options(
        employees,
        empty_label="No Manager",
        exclude_employee_id=exclude_employee_id,
    )


def _leader_options(
    employees,
    *,
    exclude_employee_id: int | None = None,
) -> dict[str, int | None]:
    """Return leader choices with the correct empty-state label."""

    return _assignment_options(
        employees,
        empty_label="No Leader",
        exclude_employee_id=exclude_employee_id,
    )


def _html_cell(value: object) -> str:
    """Escape one table value and preserve its line breaks safely."""

    if value is None:
        return ""

    escaped = escape(str(value))

    return escaped.replace("\n", "<br>")


def _render_wrapped_employee_table(
    rows: list[dict[str, object]],
) -> None:
    """Render all matching employees in a five-record scroll viewport."""

    headers = list(rows[0].keys())

    header_html = "".join(
        f"<th>{escape(header)}</th>"
        for header in headers
    )

    body_rows: list[str] = []

    for row in rows:
        cells = "".join(
            (
                "<td><div class=\"employee-table-cell\">"
                f"{_html_cell(row.get(header, ''))}"
                "</div></td>"
            )
            for header in headers
        )

        body_rows.append(
            f"<tr>{cells}</tr>"
        )

    table_html = f"""
    <style>
        .employee-table-shell {{
            width: 100%;
            height: auto;
            max-height: 432px;
            overflow-x: scroll;
            overflow-y: scroll;
            scrollbar-gutter: stable both-edges;
            scrollbar-width: auto;
            scrollbar-color: var(--hr-primary) var(--hr-border);
            border: 1px solid var(--hr-border);
            border-radius: 14px;
            background: var(--hr-surface);
        }}

        .employee-table-shell::-webkit-scrollbar {{
            width: 13px;
            height: 13px;
        }}

        .employee-table-shell::-webkit-scrollbar-track {{
            background: var(--hr-background);
            border: 1px solid var(--hr-border);
            border-radius: 10px;
        }}

        .employee-table-shell::-webkit-scrollbar-thumb {{
            min-height: 36px;
            background: var(--hr-primary);
            border: 2px solid var(--hr-background);
            border-radius: 10px;
        }}

        .employee-table-shell::-webkit-scrollbar-corner {{
            background: var(--hr-background);
        }}

        .employee-master-table {{
            width: 100%;
            min-width: 2440px;
            border-collapse: separate;
            border-spacing: 0;
            table-layout: fixed;
            font-size: 0.84rem;
        }}

        .employee-master-table th {{
            position: sticky;
            top: 0;
            z-index: 2;
            height: 46px;
            padding: 8px 10px;
            border-right: 1px solid var(--hr-border);
            border-bottom: 1px solid var(--hr-border);
            background: var(--hr-surface);
            color: var(--hr-text-primary);
            text-align: left;
            vertical-align: middle;
            white-space: normal;
            overflow-wrap: break-word;
            word-break: normal;
            line-height: 1.3;
        }}

        .employee-master-table tbody tr {{
            height: 72px;
        }}

        .employee-master-table td {{
            height: 72px;
            padding: 8px 10px;
            border-right: 1px solid var(--hr-border);
            border-bottom: 1px solid var(--hr-border);
            color: var(--hr-text-secondary);
            text-align: left;
            vertical-align: top;
            white-space: normal;
            overflow-wrap: break-word;
            word-break: normal;
            line-height: 1.4;
            transition:
                color 0.14s ease,
                background-color 0.14s ease;
        }}

        .employee-table-cell {{
            max-height: 56px;
            overflow: hidden;
        }}

        .employee-master-table th:last-child,
        .employee-master-table td:last-child {{
            border-right: 0;
        }}

        .employee-master-table tbody tr:hover td {{
            color: var(--hr-text-primary);
            background: var(--hr-primary-soft);
        }}

        .employee-master-table th:nth-child(1),
        .employee-master-table td:nth-child(1) {{ width: 130px; }}

        .employee-master-table th:nth-child(2),
        .employee-master-table td:nth-child(2) {{ width: 180px; }}

        .employee-master-table th:nth-child(3),
        .employee-master-table td:nth-child(3) {{ width: 165px; }}

        .employee-master-table th:nth-child(4),
        .employee-master-table td:nth-child(4) {{ width: 130px; }}

        .employee-master-table th:nth-child(5),
        .employee-master-table td:nth-child(5) {{ width: 120px; }}

        .employee-master-table th:nth-child(6),
        .employee-master-table td:nth-child(6) {{ width: 145px; }}

        .employee-master-table th:nth-child(7),
        .employee-master-table td:nth-child(7) {{ width: 165px; }}

        .employee-master-table th:nth-child(8),
        .employee-master-table td:nth-child(8) {{ width: 165px; }}

        .employee-master-table th:nth-child(9),
        .employee-master-table td:nth-child(9) {{ width: 125px; }}

        .employee-master-table th:nth-child(10),
        .employee-master-table td:nth-child(10) {{ width: 145px; }}

        .employee-master-table th:nth-child(11),
        .employee-master-table td:nth-child(11) {{ width: 145px; }}

        .employee-master-table th:nth-child(12),
        .employee-master-table td:nth-child(12) {{ width: 90px; }}

        .employee-master-table th:nth-child(13),
        .employee-master-table td:nth-child(13) {{ width: 250px; }}

        .employee-master-table th:nth-child(14),
        .employee-master-table td:nth-child(14) {{ width: 150px; }}

        .employee-master-table th:nth-child(15),
        .employee-master-table td:nth-child(15) {{ width: 230px; }}

        .employee-master-table th:nth-child(16),
        .employee-master-table td:nth-child(16) {{ width: 240px; }}
    </style>

    <div class="employee-table-shell" role="region"
         aria-label="Scrollable employee list" tabindex="0">
        <table class="employee-master-table">
            <thead>
                <tr>{header_html}</tr>
            </thead>
            <tbody>
                {''.join(body_rows)}
            </tbody>
        </table>
    </div>
    """

    st.markdown(
        table_html,
        unsafe_allow_html=True,
    )


def _render_employee_workspace_table(
    rows: list[dict[str, object]],
    *,
    aria_label: str,
    min_width: int,
    max_height: int,
) -> None:
    """Render a safe scrollable table without changing the master-list grid."""

    if not rows:
        return
    headers = list(rows[0])
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_html = "".join(
        "<tr>"
        + "".join(f"<td>{_html_cell(row.get(header, ''))}</td>" for header in headers)
        + "</tr>"
        for row in rows
    )
    st.markdown(
        f"""
        <style>
            .employee-workspace-table-shell {{
                width: 100%;
                max-height: {max_height}px;
                overflow: auto;
                border: 1px solid var(--hr-border);
                border-radius: 14px;
                background: var(--hr-surface);
                scrollbar-color: var(--hr-primary) var(--hr-border);
            }}
            .employee-workspace-table {{
                width: 100%;
                min-width: {min_width}px;
                border-collapse: separate;
                border-spacing: 0;
                table-layout: auto;
                font-size: 0.84rem;
            }}
            .employee-workspace-table th {{
                position: sticky;
                top: 0;
                z-index: 2;
                padding: 9px 10px;
                border-right: 1px solid var(--hr-border);
                border-bottom: 1px solid var(--hr-border);
                background: var(--hr-surface);
                color: var(--hr-text-primary);
                text-align: left;
            }}
            .employee-workspace-table td {{
                padding: 9px 10px;
                border-right: 1px solid var(--hr-border);
                border-bottom: 1px solid var(--hr-border);
                color: var(--hr-text-secondary);
                vertical-align: top;
                white-space: normal;
                overflow-wrap: break-word;
                word-break: normal;
                line-height: 1.4;
            }}
            .employee-workspace-table th:last-child,
            .employee-workspace-table td:last-child {{ border-right: 0; }}
            .employee-workspace-table tbody tr:hover td {{
                color: var(--hr-text-primary);
                background: var(--hr-primary-soft);
            }}
        </style>
        <div class="employee-workspace-table-shell" role="region"
             aria-label="{escape(aria_label)}" tabindex="0">
            <table class="employee-workspace-table">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{body_html}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_employee_list(
    current_user: AuthenticatedUser,
    employees,
    users,
) -> None:
    """Display a searchable list with five records visible at a time."""

    st.subheader("Employee List")
    st.caption(
        "Search any employee, account, department, manager, or training. "
        "Five records are visible; scroll for more rows. Detailed name "
        "fields remain available in Add/Edit Employee."
    )

    metric_columns = st.columns(4)
    metric_values = (
        ("Employees", len(employees)),
        ("User Accounts", len(users)),
        ("Active Accounts", sum(1 for user in users if user.is_active)),
        ("Role", "Admin" if current_user.clearance == 1 else "User"),
    )
    for column, (label, value) in zip(metric_columns, metric_values):
        with column:
            st.metric(label, value)

    search_terms = multi_search_input(
        "Search Employees",
        placeholder=(
            "Type any value shown in the employee table, then press Enter…"
        ),
        key="employee_master_search",
    )

    filtered = _filter_employees(
        employees,
        search_terms,
    )
    rows = _employee_rows(filtered)

    st.caption(
        f"Showing {len(filtered)} of {len(employees)} employee record(s)."
    )

    if not rows:
        st.info(
            "No employee record matches the current search."
        )
        return

    _render_wrapped_employee_table(rows)


def _render_bulk_employee_upload(current_user: AuthenticatedUser) -> None:
    """Render template download, validated preview, and atomic Excel import."""

    preview_key = "employee_bulk_import_preview"
    result_key = "employee_bulk_import_result"
    filename_key = "employee_bulk_import_filename"

    with st.expander("Upload Employees via Excel", expanded=False):
        st.caption(
            "Download the exact template, enter employee information, then "
            "validate the file. Hover Excel column headers to see field guidance "
            "and complete valid selections; closed choices also have dropdowns. "
            "User ID is generated after saving; Clearance, User Name, and "
            "Temporary Password remain editable in the preview."
        )
        with SessionFactory() as session:
            template_data = EmployeeBulkImportService(session).build_company_template(
                company_id=current_user.company_id
            )
        st.download_button(
            "Download Employee Excel Template",
            data=template_data,
            file_name="Employee_Import_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="content",
            key="employee_bulk_template_download",
        )

        uploaded_file = st.file_uploader(
            "Upload Completed Employee Template",
            type=["xlsx"],
            accept_multiple_files=False,
            key="employee_bulk_upload_file",
            help="Only the downloadable .xlsx template is accepted.",
        )
        validate_clicked = st.button(
            "Validate and Preview Employees",
            width="stretch",
            disabled=uploaded_file is None,
            key="employee_bulk_validate",
        )
        if validate_clicked and uploaded_file is not None:
            try:
                if uploaded_file.size > 10 * 1024 * 1024:
                    raise ValueError("The employee Excel file must not exceed 10 MB.")
                with st.spinner("Validating employee and account information…"):
                    with SessionFactory() as session:
                        preview = EmployeeBulkImportService(session).prepare_preview(
                            uploaded_file.getvalue(),
                            filename=uploaded_file.name,
                            company_id=current_user.company_id,
                        )
                st.session_state[preview_key] = preview
                st.session_state[filename_key] = uploaded_file.name
                st.session_state.pop(result_key, None)
            except ValueError as error:
                st.session_state.pop(preview_key, None)
                render_action_warning(error)

        preview_rows = st.session_state.get(preview_key)
        if isinstance(preview_rows, list) and preview_rows:
            st.markdown("#### Employee and Account Preview")
            st.caption(
                "Employee values come from Excel. Review the calculated Hired "
                "Date/Years of Service and edit only the three account defaults."
            )
            display_rows = [
                {column: row.get(column, "") for column in ACCOUNT_PREVIEW_COLUMNS}
                for row in preview_rows
            ]
            edited_data = st.data_editor(
                display_rows,
                width="stretch",
                hide_index=True,
                disabled=[
                    "Row",
                    "Employee Number",
                    "Employee Name",
                    "Hired Date",
                    "Years of Service",
                    "User ID",
                    "Validation",
                ],
                column_config={
                    "Clearance": st.column_config.SelectboxColumn(
                        "Clearance",
                        options=["1 - Admin", "2 - User"],
                        required=True,
                    ),
                    "User Name": st.column_config.TextColumn(
                        "User Name",
                        required=True,
                        max_chars=100,
                    ),
                    "Temporary Password": st.column_config.TextColumn(
                        "Temporary Password",
                        required=True,
                        max_chars=128,
                    ),
                },
                key="employee_bulk_account_editor",
            )
            edited_records = (
                edited_data
                if isinstance(edited_data, list)
                else edited_data.to_dict(orient="records")
            )
            edited_by_row = {
                int(item["Row"]): item
                for item in edited_records
            }
            merged_preview: list[dict[str, object]] = []
            for original in preview_rows:
                merged = dict(original)
                edited = edited_by_row.get(int(original["Row"]), {})
                for field in ("Clearance", "User Name", "Temporary Password"):
                    if field in edited:
                        merged[field] = edited[field]
                merged_preview.append(merged)
            st.session_state[preview_key] = merged_preview

            invalid_count = sum(
                str(row.get("Validation", "")) != "Ready"
                for row in merged_preview
            )
            if invalid_count:
                st.error(
                    f"{invalid_count} row(s) contain validation errors. "
                    "Correct the Excel file and validate it again."
                )
            import_clicked = st.button(
                "Import Employees",
                type="primary",
                width="stretch",
                disabled=invalid_count > 0,
                key="employee_bulk_import_submit",
            )
            if import_clicked:
                try:
                    with st.spinner("Creating employee records and login accounts…"):
                        with SessionFactory() as session:
                            service = EmployeeBulkImportService(session)
                            results = service.import_preview_rows(
                                merged_preview,
                                company_id=current_user.company_id,
                                current_user_id=current_user.user_id,
                                filename=str(st.session_state.get(filename_key) or "employee_import.xlsx"),
                            )
                            result_data = service.build_import_result(results)
                    st.session_state[result_key] = {
                        "data": result_data,
                        "count": len(results),
                    }
                    st.session_state.pop(preview_key, None)
                    set_operation_feedback(
                        f"Successfully imported {len(results)} employee record(s) and login account(s)."
                    )
                    st.rerun()
                except (ValidationError, ValueError) as error:
                    render_action_warning(error)
                except Exception:
                    st.error(
                        "The employee batch could not be imported. No employee "
                        "from this batch was saved."
                    )

        import_result = st.session_state.get(result_key)
        if isinstance(import_result, dict) and import_result.get("data"):
            st.success(
                f"{int(import_result.get('count', 0))} employee account(s) were imported. "
                "Download the controlled initial-credentials result now."
            )
            st.download_button(
                "Download Employee Import Result",
                data=import_result["data"],
                file_name="Employee_Import_Result.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="content",
                key="employee_bulk_result_download",
            )


def _render_add_employee(
    current_user: AuthenticatedUser,
    employees,
) -> None:
    """Create one employee using the requested real-time profile layout."""

    st.subheader("Add Employee")
    st.caption(
        "All employee and account values are entered in one workspace. "
        "The Email field is also used as the login email."
    )

    _render_bulk_employee_upload(current_user)
    st.divider()
    st.markdown("#### Add One Employee Manually")

    manager_people = _manager_options(employees)
    leader_people = _leader_options(employees)

    with st.container(border=True, key="employee_create_information_card"):
        st.markdown("### Employee Information")

        number_column, _ = st.columns([1.0, 5.0])
        with number_column:
            employee_number = st.text_input(
                "Employee Number *", max_chars=80, key="create_employee_number"
            )

        last_column, first_column, middle_column, suffix_column = st.columns(4)
        with last_column:
            last_name = st.text_input(
                "Last Name *", max_chars=100, key="create_last_name"
            )
        with first_column:
            first_name = st.text_input(
                "First Name *", max_chars=100, key="create_first_name"
            )
        with middle_column:
            middle_name = st.text_input(
                "Middle Name", max_chars=100, key="create_middle_name"
            )
        with suffix_column:
            suffix = st.text_input(
                "Suffix", max_chars=30, key="create_suffix"
            )

        gender_column, civil_column, birth_column, age_column = st.columns(4)
        with gender_column:
            gender_label = st.selectbox(
                "Gender", options=GENDER_OPTIONS, key="create_gender"
            )
        with civil_column:
            civil_status_label = st.selectbox(
                "Civil Status",
                options=CIVIL_STATUS_OPTIONS,
                key="create_civil_status",
            )
        with birth_column:
            date_of_birth = st.date_input(
                "Date of Birth",
                value=None,
                min_value=date(1900, 1, 1),
                max_value=date.today(),
                key="create_date_of_birth",
            )
        with age_column:
            st.text_input(
                "Age",
                value=_display_value(_calculate_age(date_of_birth)),
                disabled=True,
                key=f"create_age_display_{date_of_birth or 'none'}",
            )

        email_column, telephone_column, _ = st.columns([2.0, 2.0, 2.0])
        with email_column:
            email = st.text_input(
                "Email *", max_chars=255, key="create_email"
            )
        with telephone_column:
            telephone_mobile_no = st.text_input(
                "Telephone / Mobile No.",
                max_chars=50,
                key="create_telephone_mobile",
            )

        department_column, manager_column, leader_column, position_column = st.columns(4)
        with department_column:
            department_name = st.text_input(
                "Department",
                max_chars=150,
                key="create_department",
                help=(
                    "Enter an existing or new department name. "
                    "Matching is case-insensitive, and a new department record is created "
                    "automatically when needed."
                ),
            )
        with manager_column:
            manager_label = st.selectbox(
                "Manager", options=list(manager_people), key="create_manager"
            )
        with leader_column:
            leader_label = st.selectbox(
                "Leader", options=list(leader_people), key="create_leader"
            )
        with position_column:
            job_title = st.text_input(
                "Job Title / Position",
                max_chars=150,
                key="create_job_title",
            )

        status_column, hire_column, _ = st.columns([1.4, 0.8, 3.8])
        with status_column:
            status_label = st.selectbox(
                "Employment Status",
                options=list(EMPLOYMENT_STATUS_OPTIONS),
                key="create_employment_status",
                help=(
                    "Employed keeps the login account active. Resigned "
                    "automatically deactivates the account."
                ),
            )
        with hire_column:
            hire_date = st.date_input(
                "Hired Date", value=date.today(), key="create_hire_date"
            )

        st.markdown("### Training Checklist")
        training_text = st.text_area(
            "Training",
            height=150,
            key="create_training",
            placeholder=(
                "[x] Company Orientation\n"
                "[ ] Data Privacy Training\n"
                "[ ] Safety Training"
            ),
            help="Use one training per line. [x] means completed and [ ] means pending.",
        )

    with st.container(border=True, key="employee_create_account_card"):
        st.markdown("### Account Information")
        user_id_column, clearance_column = st.columns(2)
        with user_id_column:
            st.text_input(
                "User ID",
                value="Generated automatically after saving",
                disabled=True,
                key="create_user_id_display",
            )
        with clearance_column:
            clearance_label = st.selectbox(
                "Clearance *",
                options=["1 - Admin", "2 - User"],
                index=1,
                key="create_clearance",
            )

        username_column, password_column = st.columns(2)
        with username_column:
            username = st.text_input(
                "User Name *", max_chars=100, key="create_username"
            )
        with password_column:
            temporary_password = st.text_input(
                "Temporary Password *",
                type="password",
                max_chars=128,
                key="create_temporary_password",
                help="The employee must change this password during first login.",
            )

    submitted = st.button(
        "Create Employee Record",
        type="primary",
        width="stretch",
        key="create_employee_submit",
    )

    if not submitted:
        return

    try:
        request = EmployeeAccountCreate(
            company_id=current_user.company_id,
            employee_number=(employee_number or "").strip(),
            last_name=(last_name or "").strip(),
            first_name=(first_name or "").strip(),
            middle_name=_optional_value(middle_name),
            suffix=_optional_value(suffix),
            job_title=_optional_value(job_title),
            department_name=_optional_value(department_name),
            manager_id=manager_people[manager_label],
            leader_id=leader_people[leader_label],
            work_email=(email or "").strip(),
            telephone_mobile_no=_optional_value(telephone_mobile_no),
            gender=_optional_value(gender_label),
            civil_status=_optional_value(civil_status_label),
            date_of_birth=date_of_birth,
            employment_status=EMPLOYMENT_STATUS_OPTIONS[status_label],
            hire_date=hire_date,
            trainings=_parse_training_text(training_text or ""),
            create_login_account=True,
            username=(username or "").strip(),
            login_email=(email or "").strip(),
            temporary_password=temporary_password or "",
            clearance=int(clearance_label[0]),
        )

        with st.spinner("Creating employee record and login account…"):
            with SessionFactory() as session:
                employee = AdminManagementService(
                    session
                ).create_employee_with_optional_account(
                    request,
                    current_user_id=current_user.user_id,
                )

        set_operation_feedback(
            "Employee record created successfully: "
            f"{employee.employee_number} — {employee.full_name}"
        )
        for key in list(st.session_state):
            if key.startswith("create_"):
                del st.session_state[key]
        st.rerun()
    except ValidationError as error:
        render_action_warning(error)
    except ValueError as error:
        render_action_warning(error)


def _render_delete_employee(
    current_user: AuthenticatedUser,
    *,
    employee_id: int,
    employee_number: str,
    full_name: str,
    user_id: int | None,
) -> None:
    """Delete the currently selected employee after one acknowledgment."""

    st.divider()

    with st.expander(
        "Danger Zone — Delete Employee Record",
        expanded=False,
    ):
        st.warning(
            "Permanent deletion removes the employee profile, profile photo, "
            "training records, and linked login account. This action cannot be "
            "undone. Department records are preserved."
        )

        if user_id == current_user.user_id:
            st.info(
                "Your own active administrator employee/account cannot "
                "be deleted while you are signed in."
            )
            return

        st.caption(
            "Selected employee to delete: "
            f"{employee_number} — {full_name}"
        )

        delete_confirmation_key = f"employee_delete_acknowledged_{employee_id}"
        invalidate_confirmation_on_change(
            confirmation_key=delete_confirmation_key,
            dependencies={"employee_id": employee_id},
            tracker_key="__employee_permanent_delete_target_confirmation",
        )
        acknowledged = st.checkbox(
            "I understand that this permanently deletes the selected "
            "employee record and linked login account.",
            key=delete_confirmation_key,
        )

        delete_submitted = st.button(
            "Delete Employee Permanently",
            type="primary",
            width="stretch",
            disabled=not acknowledged,
            key=(
                "employee_delete_button_"
                f"{employee_id}"
            ),
        )

        if not delete_submitted:
            return

        try:
            request = EmployeeDeleteRequest(
                company_id=current_user.company_id,
                employee_id=employee_id,
                permanent_delete_acknowledged=acknowledged,
            )

            with st.spinner(
                "Permanently deleting employee record…"
            ):
                with SessionFactory() as session:
                    result = AdminManagementService(
                        session
                    ).delete_employee_master_record(
                        request,
                        current_user_id=current_user.user_id,
                    )

            st.session_state.pop(
                "employee_master_edit_selection",
                None,
            )
            st.session_state.pop(
                "employee_delete_acknowledged_"
                f"{employee_id}",
                None,
            )

            set_operation_feedback(
                "Employee permanently deleted: "
                f"{result.employee_number} — "
                f"{result.full_name}"
            )
            st.rerun()

        except ValidationError as error:
            render_action_warning(error)
        except ValueError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "The employee record could not be deleted. "
                "No deletion was completed."
            )

def _render_edit_employee(
    current_user: AuthenticatedUser,
    employees,
) -> None:
    """Edit employee profile with real-time age calculation."""

    st.subheader("Edit Employee")
    st.caption(
        "Every displayed employee field is editable. Leave New Temporary "
        "Password blank to keep the current password."
    )
    if not employees:
        st.info("There is no employee available to edit.")
        return

    employee_options = {
        f"{employee.employee_number} — {employee.full_name}": employee.id
        for employee in employees
    }
    selected_label = st.selectbox(
        "Select Employee",
        options=list(employee_options),
        key="employee_master_edit_selection",
    )
    selected_id = employee_options[selected_label]

    with SessionFactory() as session:
        selected = AdminManagementService(session).get_employee(
            company_id=current_user.company_id,
            employee_id=selected_id,
        )
        values = {
            "edit_version": selected.edit_version,
            "employee_number": selected.employee_number,
            "last_name": selected.last_name,
            "first_name": selected.first_name,
            "middle_name": selected.middle_name or "",
            "suffix": selected.suffix or "",
            "email": selected.work_email or "",
            "telephone_mobile_no": selected.telephone_mobile_no or "",
            "job_title": selected.job_title or "",
            "department": selected.department.name if selected.department else "",
            "manager_id": selected.manager_id,
            "leader_id": selected.leader_id,
            "gender": selected.gender or "N/A",
            "civil_status": selected.civil_status or "N/A",
            "date_of_birth": selected.date_of_birth,
            "status": selected.employment_status,
            "hire_date": selected.hire_date or date.today(),
            "training": _training_editor_value(selected),
            "user_id": selected.user.id if selected.user else None,
            "username": selected.user.username if selected.user else "",
            "clearance": selected.user.clearance if selected.user else 2,
            "manager_name": selected.manager.full_name if selected.manager else None,
            "leader_name": selected.leader.full_name if selected.leader else None,
        }

    with st.expander("Profile Photo", expanded=False):
        render_profile_photo_manager(
            current_user=current_user,
            employee_id=selected_id,
            employee_display_name=selected.full_name,
            employee_number=selected.employee_number,
            key_prefix=f"admin_employee_{selected_id}",
            admin_mode=True,
        )

    manager_people = _manager_options(
        employees, exclude_employee_id=selected_id
    )
    leader_people = _leader_options(
        employees, exclude_employee_id=selected_id
    )

    def option_index(
        options: dict[str, int | None],
        target_id: int | None,
    ) -> int:
        for index, person_id in enumerate(options.values()):
            if person_id == target_id:
                return index
        return 0

    prefix = f"edit_{selected_id}_"

    pending_reset_key = "employee_edit_pending_state_reset"
    if st.session_state.get(pending_reset_key) == selected_id:
        for state_key in list(st.session_state):
            if str(state_key).startswith(prefix):
                st.session_state.pop(state_key, None)
        st.session_state.pop(pending_reset_key, None)

    version_key = prefix + "opened_edit_version"
    original_key = prefix + "opened_values"
    conflict_key = prefix + "conflict"
    review_key = prefix + "review_latest"
    reload_confirm_key = prefix + "reload_confirm"

    original_values = {
        "Employee Number": values["employee_number"],
        "Last Name": values["last_name"],
        "First Name": values["first_name"],
        "Middle Name": values["middle_name"],
        "Suffix": values["suffix"],
        "Email": values["email"],
        "Telephone / Mobile No.": values["telephone_mobile_no"],
        "Job Title / Position": values["job_title"],
        "Department": values["department"],
        "Manager": values["manager_name"],
        "Leader": values["leader_name"],
        "Gender": values["gender"],
        "Civil Status": values["civil_status"],
        "Date of Birth": (
            values["date_of_birth"].isoformat()
            if values["date_of_birth"]
            else None
        ),
        "Employment Status": values["status"],
        "Hired Date": values["hire_date"].isoformat() if values["hire_date"] else None,
        "Training": values["training"],
        "User Name": values["username"],
        "Clearance": values["clearance"],
    }
    st.session_state.setdefault(version_key, int(values["edit_version"]))
    st.session_state.setdefault(original_key, original_values)

    conflict = st.session_state.get(conflict_key)
    conflict_active = isinstance(conflict, dict)

    def _reload_latest_record() -> None:
        """Discard this browser's stale form state and load current values."""

        # Clear on the next rerun before any keyed form widget is instantiated.
        # This avoids Streamlit's "cannot modify after widget creation" error.
        st.session_state[pending_reset_key] = selected_id
        st.rerun()

    if conflict_active:
        st.warning(str(conflict.get("message") or "This record changed while you were editing."))
        st.caption(
            "The form is temporarily read-only. No pending value was saved "
            "and the newer administrator update was not overwritten."
        )
        review_column, reload_column = st.columns(2)
        with review_column:
            if st.button(
                "Review Latest Information",
                type="primary",
                width="stretch",
                key=prefix + "review_latest_button",
            ):
                st.session_state[review_key] = True
        with reload_column:
            if st.button(
                "Reload Latest Record",
                width="stretch",
                key=prefix + "reload_latest_button",
            ):
                st.session_state[reload_confirm_key] = True

        if st.session_state.get(reload_confirm_key):
            st.warning(
                "Reloading will discard your pending unsaved changes and "
                "replace the form with the latest saved record."
            )
            confirm_column, keep_column = st.columns(2)
            with confirm_column:
                if st.button(
                    "Confirm Reload",
                    type="primary",
                    width="stretch",
                    key=prefix + "confirm_reload_button",
                ):
                    _reload_latest_record()
            with keep_column:
                if st.button(
                    "Keep Reviewing",
                    width="stretch",
                    key=prefix + "keep_reviewing_button",
                ):
                    st.session_state[reload_confirm_key] = False
                    st.rerun()

        if st.session_state.get(review_key):
            st.markdown("### Review Latest Information")
            previous_values = conflict.get("previous_values") or {}
            pending_values = conflict.get("pending_values") or {}
            latest_values = conflict.get("latest_values") or {}
            fields = list(
                dict.fromkeys(
                    [*previous_values, *pending_values, *latest_values]
                )
            )
            comparison_rows = [
                {
                    "Field": field,
                    "Opened Value": _display_value(previous_values.get(field)),
                    "My Pending Change": _display_value(pending_values.get(field)),
                    "Latest Saved Value": _display_value(latest_values.get(field)),
                }
                for field in fields
            ]
            _render_employee_workspace_table(
                comparison_rows,
                aria_label="Employee edit conflict comparison",
                min_width=1250,
                max_height=420,
            )
            st.caption(
                "Continue Editing Latest Version reloads the latest record "
                "as the new editable base. Review and reapply only the "
                "changes that are still needed."
            )
            if st.button(
                "Continue Editing Latest Version",
                type="primary",
                width="stretch",
                key=prefix + "continue_latest_button",
            ):
                _reload_latest_record()

    with st.container(border=True, key=f"employee_edit_information_card_{selected_id}"):
        st.markdown("### Employee Information")

        number_column, _ = st.columns([1.0, 5.0])
        with number_column:
            employee_number = st.text_input(
                "Employee Number *",
                value=values["employee_number"],
                max_chars=80,
                key=prefix + "employee_number",
                disabled=conflict_active,
            )

        last_column, first_column, middle_column, suffix_column = st.columns(4)
        with last_column:
            last_name = st.text_input(
                "Last Name *", value=values["last_name"], max_chars=100, key=prefix + "last_name",
                disabled=conflict_active,
            )
        with first_column:
            first_name = st.text_input(
                "First Name *", value=values["first_name"], max_chars=100, key=prefix + "first_name",
                disabled=conflict_active,
            )
        with middle_column:
            middle_name = st.text_input(
                "Middle Name", value=values["middle_name"], max_chars=100, key=prefix + "middle_name",
                disabled=conflict_active,
            )
        with suffix_column:
            suffix = st.text_input(
                "Suffix", value=values["suffix"], max_chars=30, key=prefix + "suffix",
                disabled=conflict_active,
            )

        gender_column, civil_column, birth_column, age_column = st.columns(4)
        with gender_column:
            gender_label = st.selectbox(
                "Gender",
                options=GENDER_OPTIONS,
                index=GENDER_OPTIONS.index(values["gender"]) if values["gender"] in GENDER_OPTIONS else 0,
                key=prefix + "gender",
                disabled=conflict_active,
            )
        with civil_column:
            civil_status_label = st.selectbox(
                "Civil Status",
                options=CIVIL_STATUS_OPTIONS,
                index=CIVIL_STATUS_OPTIONS.index(values["civil_status"]) if values["civil_status"] in CIVIL_STATUS_OPTIONS else 0,
                key=prefix + "civil_status",
                disabled=conflict_active,
            )
        with birth_column:
            date_of_birth = st.date_input(
                "Date of Birth",
                value=values["date_of_birth"],
                min_value=date(1900, 1, 1),
                max_value=date.today(),
                key=prefix + "date_of_birth",
                disabled=conflict_active,
            )
        with age_column:
            st.text_input(
                "Age",
                value=_display_value(_calculate_age(date_of_birth)),
                disabled=True,
                key=prefix + f"age_display_{date_of_birth or 'none'}",
            )

        email_column, telephone_column, _ = st.columns([2.0, 2.0, 2.0])
        with email_column:
            email = st.text_input(
                "Email *", value=values["email"], max_chars=255, key=prefix + "email",
                disabled=conflict_active,
            )
        with telephone_column:
            telephone_mobile_no = st.text_input(
                "Telephone / Mobile No.",
                value=values["telephone_mobile_no"],
                max_chars=50,
                key=prefix + "telephone_mobile",
                disabled=conflict_active,
            )

        department_column, manager_column, leader_column, position_column = st.columns(4)
        with department_column:
            department_name = st.text_input(
                "Department",
                value=values["department"],
                max_chars=150,
                key=prefix + "department",
                disabled=conflict_active,
                help=(
                    "Edit the department directly. Existing names are "
                    "reused case-insensitively; new names create department records automatically."
                ),
            )
        with manager_column:
            manager_label = st.selectbox(
                "Manager",
                options=list(manager_people),
                index=option_index(manager_people, values["manager_id"]),
                key=prefix + "manager",
                disabled=conflict_active,
            )
        with leader_column:
            leader_label = st.selectbox(
                "Leader",
                options=list(leader_people),
                index=option_index(leader_people, values["leader_id"]),
                key=prefix + "leader",
                disabled=conflict_active,
            )
        with position_column:
            job_title = st.text_input(
                "Job Title / Position",
                value=values["job_title"],
                max_chars=150,
                key=prefix + "job_title",
                disabled=conflict_active,
            )

        status_labels = list(EMPLOYMENT_STATUS_OPTIONS)
        current_status_label = (
            "Employed — Account Active"
            if values["status"] == "employed"
            else "Resigned — Account Inactive"
        )
        status_column, hire_column, _ = st.columns([1.4, 0.8, 3.8])
        with status_column:
            status_label = st.selectbox(
                "Employment Status",
                options=status_labels,
                index=status_labels.index(current_status_label),
                key=prefix + "employment_status",
                disabled=conflict_active,
                help=(
                    "Changing to Resigned deactivates the login account. "
                    "Changing back to Employed reactivates it."
                ),
            )
        with hire_column:
            hire_date = st.date_input(
                "Hired Date", value=values["hire_date"], key=prefix + "hire_date",
                disabled=conflict_active,
            )

        st.markdown("### Training Checklist")
        training_text = st.text_area(
            "Training",
            value=values["training"],
            height=180,
            key=prefix + "training",
            help="Use [x] for completed and [ ] for pending.",
            disabled=conflict_active,
        )

    with st.container(border=True, key=f"employee_edit_account_card_{selected_id}"):
        st.markdown("### Account Information")
        user_id_column, clearance_column = st.columns(2)
        with user_id_column:
            st.text_input(
                "User ID",
                value=str(values["user_id"]) if values["user_id"] is not None else "Will be generated",
                disabled=True,
                key=prefix + "user_id_display",
            )
        with clearance_column:
            clearance_label = st.selectbox(
                "Clearance *",
                options=["1 - Admin", "2 - User"],
                index=0 if values["clearance"] == 1 else 1,
                key=prefix + "clearance",
                disabled=conflict_active,
            )

        username_column, password_column = st.columns(2)
        with username_column:
            username = st.text_input(
                "User Name *", value=values["username"], max_chars=100, key=prefix + "username",
                disabled=conflict_active,
            )
        with password_column:
            new_password = st.text_input(
                "New Temporary Password",
                type="password",
                max_chars=128,
                key=prefix + "new_password",
                help="Leave blank to keep the current password.",
                disabled=conflict_active,
            )

    submitted = st.button(
        "Save Employee Changes",
        type="primary",
        width="stretch",
        key=prefix + "submit",
        disabled=conflict_active,
    )

    if not submitted:
        return

    try:
        request = EmployeeMasterUpdate(
            company_id=current_user.company_id,
            employee_id=selected_id,
            expected_edit_version=int(st.session_state[version_key]),
            employee_number=(employee_number or "").strip(),
            last_name=(last_name or "").strip(),
            first_name=(first_name or "").strip(),
            middle_name=_optional_value(middle_name),
            suffix=_optional_value(suffix),
            work_email=(email or "").strip(),
            telephone_mobile_no=_optional_value(telephone_mobile_no),
            job_title=_optional_value(job_title),
            department_name=_optional_value(department_name),
            manager_id=manager_people[manager_label],
            leader_id=leader_people[leader_label],
            gender=_optional_value(gender_label),
            civil_status=_optional_value(civil_status_label),
            date_of_birth=date_of_birth,
            employment_status=EMPLOYMENT_STATUS_OPTIONS[status_label],
            hire_date=hire_date,
            trainings=_parse_training_text(training_text or ""),
            username=(username or "").strip(),
            clearance=int(clearance_label[0]),
            new_temporary_password=new_password or None,
        )

        manager_id = manager_people[manager_label]
        leader_id = leader_people[leader_label]
        employee_by_id = {employee.id: employee for employee in employees}
        pending_values = {
            "Employee Number": (employee_number or "").strip(),
            "Last Name": (last_name or "").strip(),
            "First Name": (first_name or "").strip(),
            "Middle Name": _optional_value(middle_name),
            "Suffix": _optional_value(suffix),
            "Email": (email or "").strip(),
            "Telephone / Mobile No.": _optional_value(telephone_mobile_no),
            "Job Title / Position": _optional_value(job_title),
            "Department": _optional_value(department_name),
            "Manager": (
                employee_by_id[manager_id].full_name
                if manager_id in employee_by_id
                else None
            ),
            "Leader": (
                employee_by_id[leader_id].full_name
                if leader_id in employee_by_id
                else None
            ),
            "Gender": _optional_value(gender_label),
            "Civil Status": _optional_value(civil_status_label),
            "Date of Birth": date_of_birth.isoformat() if date_of_birth else None,
            "Employment Status": EMPLOYMENT_STATUS_OPTIONS[status_label],
            "Hired Date": hire_date.isoformat() if hire_date else None,
            "Training": training_text or "",
            "User Name": (username or "").strip(),
            "Clearance": int(clearance_label[0]),
        }

        with st.spinner("Saving employee changes…"):
            with SessionFactory() as session:
                employee = AdminManagementService(session).update_employee_master_record(
                    request, current_user_id=current_user.user_id
                )

        set_operation_feedback(
            "Employee record updated successfully: "
            f"{employee.employee_number} — {employee.full_name}"
        )
        st.session_state[pending_reset_key] = selected_id
        st.rerun()
    except EditConflictError as error:
        st.session_state[conflict_key] = {
            "message": str(error),
            "previous_values": st.session_state.get(original_key, {}),
            "pending_values": pending_values,
            "latest_values": error.latest_values,
            "latest_version": error.latest_version,
            "updated_by": error.updated_by,
            "updated_at": (
                error.updated_at.isoformat()
                if error.updated_at is not None
                else None
            ),
        }
        st.session_state[review_key] = False
        st.session_state[reload_confirm_key] = False
        st.rerun()
    except ValidationError as error:
        render_action_warning(error)
    except ValueError as error:
        render_action_warning(error)


def _history_changes(history) -> str:
    """Return a readable old-to-new change list from safe audit JSON."""

    try:
        old_values = json.loads(history.old_values_json or "{}")
        new_values = json.loads(history.new_values_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return "N/A"
    keys = list(dict.fromkeys([*old_values, *new_values]))
    if not keys:
        return "N/A"
    return "\n".join(
        f"{key.replace('_', ' ').title()}: "
        f"{_display_value(old_values.get(key))} → "
        f"{_display_value(new_values.get(key))}"
        for key in keys
    )


def _render_employee_history(history_rows, user_labels: dict[int, str]) -> None:
    """Render searchable employee creation, edit, upload, and archive history."""

    st.subheader("Employee History")
    st.caption(
        "Employee creation, Excel uploads, profile/account edits, archiving, "
        "and restoration are retained here. Plain-text passwords are never audited."
    )
    search_terms = multi_search_input(
        "Search Employee History",
        placeholder="Type any value shown in the history table, then press Enter…",
        key="employee_history_search",
    )
    filtered = []
    for history in history_rows:
        actor = user_labels.get(history.performed_by_user_id, "System / Former User")
        changes = _history_changes(history)
        row = {
            "Date / Time": history.created_at.strftime("%Y-%m-%d %I:%M %p"),
            "Employee": f"{history.employee_number} — {history.employee_name}",
            "Action": history.action_type.replace("_", " ").title(),
            "Source": history.source.replace("_", " ").title(),
            "Performed By": actor,
            "Summary": history.summary,
            "Changes": changes,
            "Upload File": _display_value(history.upload_filename),
        }
        if matches_visible_row(search_terms, row):
            filtered.append(row)
    st.caption(f"Showing {len(filtered)} of {len(history_rows)} history record(s).")
    if not filtered:
        st.info("No employee history matches the current search.")
        return
    _render_employee_workspace_table(
        filtered,
        aria_label="Scrollable employee history",
        min_width=1900,
        max_height=430,
    )


def _render_employee_archive(
    current_user: AuthenticatedUser,
    archived_employees,
) -> None:
    """Render retained resigned records and a confirmed restoration action."""

    st.subheader("Employee Archive")
    st.caption(
        "Resigned employees remain available with all related attendance, leave, "
        "OT, documents, and history. Restoring reuses the same employee and account records."
    )
    search_terms = multi_search_input(
        "Search Archived Employees",
        placeholder="Type any value shown in the archive table, then press Enter…",
        key="employee_archive_search",
    )
    archive_rows = [
        {
            "Employee Number": employee.employee_number,
            "Employee Name": employee.full_name,
            "Hired Date": employee.hire_date.isoformat() if employee.hire_date else "N/A",
            "Years of Service": _display_value(employee.years_of_service),
            "Department": _display_value(employee.department.name if employee.department else None),
            "Position": _display_value(employee.job_title),
            "Email": _display_value(employee.work_email),
            "Account": "Inactive",
            "Archived Date": (
                employee.archived_at.strftime("%Y-%m-%d %I:%M %p")
                if employee.archived_at
                else "N/A"
            ),
        }
        for employee in archived_employees
    ]
    filtered, archive_rows = filter_aligned_visible_rows(
        archived_employees, archive_rows, search_terms
    )
    st.caption(
        f"Showing {len(filtered)} of {len(archived_employees)} archived employee record(s)."
    )
    if not filtered:
        st.info("No archived employee matches the current search.")
        return
    _render_employee_workspace_table(
        archive_rows,
        aria_label="Scrollable archived employee list",
        min_width=1420,
        max_height=390,
    )

    with st.expander("Restore Archived Employee", expanded=False):
        options = {
            f"{employee.employee_number} — {employee.full_name}": employee.id
            for employee in filtered
        }
        selected_label = st.selectbox(
            "Select Archived Employee",
            options=list(options),
            key="employee_archive_restore_selection",
        )
        selected_id = options[selected_label]
        restore_confirmation_key = f"employee_archive_restore_confirm_{selected_id}"
        invalidate_confirmation_on_change(
            confirmation_key=restore_confirmation_key,
            dependencies={"archived_employee_id": selected_id},
            tracker_key="__employee_restore_target_confirmation",
        )
        confirmed = st.checkbox(
            "Restore this employee as Employed and reactivate the linked login account.",
            key=restore_confirmation_key,
        )
        restore_clicked = st.button(
            "Restore Employee Record",
            type="primary",
            width="stretch",
            disabled=not confirmed,
            key=f"employee_archive_restore_button_{selected_id}",
        )
        if restore_clicked:
            try:
                with st.spinner("Restoring employee and linked account…"):
                    with SessionFactory() as session:
                        restored = AdminManagementService(session).restore_archived_employee(
                            company_id=current_user.company_id,
                            employee_id=selected_id,
                            current_user_id=current_user.user_id,
                        )
                st.session_state.pop(f"employee_archive_restore_confirm_{selected_id}", None)
                set_operation_feedback(
                    f"Employee restored successfully: {restored.employee_number} — {restored.full_name}"
                )
                st.rerun()
            except ValueError as error:
                render_action_warning(error)


def render_employees_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render the complete Employee Master Record workspace."""

    st.title("Employees")
    st.caption(
        "Manage employee information, training, login accounts, onboarding, "
        "benefits, and clearance in one place."
    )

    # Show the completed result after Streamlit refreshes the page.
    render_operation_feedback()

    with SessionFactory() as session:
        service = AdminManagementService(session)
        employees = service.list_employees(current_user.company_id)
        archived_employees = service.list_archived_employees(current_user.company_id)
        history_rows = service.list_employee_history(current_user.company_id)
        users = service.list_users(current_user.company_id)
        user_labels = {
            user.id: (
                user.employee.full_name
                if user.employee is not None
                else user.username
            )
            for user in users
        }

    pending_tab = st.session_state.pop("employees_pending_active_tab", None)
    if pending_tab in {
        "Employee List",
        "Add Employee",
        "Edit Employee",
        "Violations / Disciplinary Records",
        "Onboarding Management",
        "History",
        f"Archive ({len(archived_employees)})",
    }:
        st.session_state["employees_active_tab"] = pending_tab

    (
        list_tab,
        add_tab,
        edit_tab,
        disciplinary_tab,
        onboarding_tab,
        history_tab,
        archive_tab,
    ) = persistent_tabs(
        [
            "Employee List",
            "Add Employee",
            "Edit Employee",
            "Violations / Disciplinary Records",
            "Onboarding Management",
            "History",
            f"Archive ({len(archived_employees)})",
        ],
        key="employees_active_tab",
    )

    with list_tab:
        _render_employee_list(current_user, employees, users)

    with add_tab:
        _render_add_employee(
            current_user,
            employees,
        )

    with edit_tab:
        _render_edit_employee(
            current_user,
            employees,
        )

    with disciplinary_tab:
        render_admin_disciplinary_records(current_user)

    with onboarding_tab:
        render_onboarding_management(current_user)

    with history_tab:
        _render_employee_history(history_rows, user_labels)

    with archive_tab:
        _render_employee_archive(current_user, archived_employees)
