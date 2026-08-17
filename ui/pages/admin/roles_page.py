"""Administrator role-management page.

System roles are protected because authentication and routing depend on
them. Administrators may add and manage custom company roles.
"""

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from pydantic import ValidationError

from authentication.current_user import AuthenticatedUser
from ui.components.data_table import render_admin_table
from database.session import SessionFactory
from schemas.organization_schema import RoleCreateRequest
from services.organization_service import OrganizationService


def _role_rows(roles) -> list[dict[str, object]]:
    """Convert role models into display-safe table rows."""

    return [
        {
            "Role ID": role.id,
            "Role": role.name,
            "Description": role.description or "",
            "Type": (
                "System" if role.is_system_role else "Custom"
            ),
            "Status": (
                "Active" if role.is_active else "Inactive"
            ),
        }
        for role in roles
    ]


def render_roles_page(
    current_user: AuthenticatedUser,
    *,
    embedded: bool = False,
) -> None:
    """List roles and manage custom role creation/status.

    ``embedded=True`` renders this module inside the Employees workspace.
    """

    if embedded:
        st.subheader("Roles & Access")
        st.caption(
            "Manage the roles assigned to employee login accounts."
        )
    else:
        st.title("Roles")
        st.caption(
            "Manage company roles used by login accounts."
        )

    with SessionFactory() as session:
        roles = OrganizationService(session).list_roles(
            current_user.company_id
        )

    rows = _role_rows(roles)

    render_admin_table(
        rows,
        key="role-list",
        min_width=860,
        column_widths=(
            "90px",
            "170px",
            "340px",
            "120px",
            "140px",
        ),
    )

    st.subheader("Add Custom Role")

    with st.form(
        "custom_role_create_form",
        clear_on_submit=True,
    ):
        role_name = st.text_input(
            "Role Name *",
            max_chars=80,
            help="Stored in lowercase for consistent permission checks.",
        )

        role_description = st.text_area(
            "Description",
            max_chars=255,
        )

        create_submitted = st.form_submit_button(
            "Create Custom Role",
            type="primary",
            width="stretch",
        )

    if create_submitted:
        try:
            request = RoleCreateRequest(
                company_id=current_user.company_id,
                name=role_name,
                description=role_description or None,
            )

            with SessionFactory() as session:
                role = OrganizationService(
                    session
                ).create_custom_role(request)

            st.success(f"Custom role created: {role.name}")
            st.rerun()

        except ValidationError as error:
            render_action_warning(error)
        except ValueError as error:
            render_action_warning(error)
        except Exception:
            st.error("The custom role could not be created.")

    st.subheader("Custom Role Status")

    custom_role_options = {
        (
            f"{role.name} "
            f"({'Active' if role.is_active else 'Inactive'})"
        ): role
        for role in roles
        if not role.is_system_role
    }

    if not custom_role_options:
        st.info(
            "Create a custom role before changing role status."
        )
        return

    with st.form("role_status_form"):
        selected_label = st.selectbox(
            "Custom Role",
            options=list(custom_role_options),
        )

        new_status = st.selectbox(
            "New Status",
            options=("Active", "Inactive"),
        )

        status_submitted = st.form_submit_button(
            "Update Role Status",
            type="primary",
            width="stretch",
        )

    if status_submitted:
        selected_role = custom_role_options[selected_label]

        try:
            with SessionFactory() as session:
                OrganizationService(
                    session
                ).set_role_active_status(
                    company_id=current_user.company_id,
                    role_id=selected_role.id,
                    is_active=new_status == "Active",
                )

            st.success("Custom role status updated.")
            st.rerun()

        except ValueError as error:
            render_action_warning(error)
        except Exception:
            st.error("The role status could not be updated.")
