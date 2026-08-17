"""Administrator department-management page."""

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from pydantic import ValidationError

from authentication.current_user import AuthenticatedUser
from ui.components.data_table import render_admin_table
from database.session import SessionFactory
from schemas.organization_schema import DepartmentCreate
from services.organization_service import OrganizationService


def _department_rows(departments) -> list[dict[str, object]]:
    """Convert department models into table-safe dictionaries."""

    return [
        {
            "Department ID": department.id,
            "Code": department.code or "",
            "Department": department.name,
            "Status": (
                "Active" if department.is_active else "Inactive"
            ),
        }
        for department in departments
    ]


def render_departments_page(
    current_user: AuthenticatedUser,
) -> None:
    """List, create, activate, and deactivate departments."""

    st.title("Departments")
    st.caption(
        "Manage company departments used by employee profiles."
    )

    with SessionFactory() as session:
        departments = OrganizationService(
            session
        ).list_departments(current_user.company_id)

    rows = _department_rows(departments)

    if rows:
        render_admin_table(
            rows,
            key="department-list",
            min_width=680,
            column_widths=(
                "120px",
                "120px",
                "300px",
                "140px",
            ),
        )
    else:
        st.info("No departments have been created.")

    st.subheader("Add Department")

    with st.form(
        "department_create_form",
        clear_on_submit=True,
    ):
        columns = st.columns(2)

        with columns[0]:
            department_name = st.text_input(
                "Department Name *",
                max_chars=150,
            )

        with columns[1]:
            department_code = st.text_input(
                "Department Code",
                max_chars=50,
                help="Optional short code, such as HR or IT.",
            )

        create_submitted = st.form_submit_button(
            "Create Department",
            type="primary",
            width="stretch",
        )

    if create_submitted:
        try:
            request = DepartmentCreate(
                company_id=current_user.company_id,
                name=department_name,
                code=department_code or None,
            )

            with SessionFactory() as session:
                department = OrganizationService(
                    session
                ).create_department(request)

            st.success(
                f"Department created: {department.name}"
            )
            st.rerun()

        except ValidationError as error:
            render_action_warning(error)
        except ValueError as error:
            render_action_warning(error)
        except Exception:
            st.error("The department could not be created.")

    st.subheader("Department Status")

    department_options = {
        (
            f"{department.name} "
            f"({'Active' if department.is_active else 'Inactive'})"
        ): department
        for department in departments
    }

    if not department_options:
        st.info("Create a department before changing status.")
        return

    with st.form("department_status_form"):
        selected_label = st.selectbox(
            "Department",
            options=list(department_options),
        )

        new_status = st.selectbox(
            "New Status",
            options=("Active", "Inactive"),
        )

        status_submitted = st.form_submit_button(
            "Update Department Status",
            type="primary",
            width="stretch",
        )

    if status_submitted:
        selected_department = department_options[selected_label]

        try:
            with SessionFactory() as session:
                OrganizationService(
                    session
                ).set_department_active_status(
                    company_id=current_user.company_id,
                    department_id=selected_department.id,
                    is_active=new_status == "Active",
                )

            st.success("Department status updated.")
            st.rerun()

        except ValueError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "The department status could not be updated."
            )
