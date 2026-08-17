"""Administrator page for company-scoped login accounts."""

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from pydantic import ValidationError

from authentication.current_user import AuthenticatedUser
from ui.components.data_table import render_admin_table
from authentication.password_reset_service import (
    PasswordResetError,
    PasswordResetService,
)
from database.session import SessionFactory
from schemas.auth_schema import (
    AdminTemporaryPasswordRequest,
)
from services.admin_management_service import (
    AdminManagementService,
)


def _build_user_rows(users) -> list[dict[str, object]]:
    """Convert user models into table-safe rows."""

    return [
        {
            "User ID": user.id,
            "Username": user.username,
            "Email": user.email,
            "Role": user.role.name,
            "Employee": (
                user.employee.full_name
                if user.employee
                else "Not linked"
            ),
            "Active": user.is_active,
            "Must Change Password": (
                user.must_change_password
            ),
        }
        for user in users
    ]


def render_users_page(
    current_user: AuthenticatedUser,
    *,
    embedded: bool = False,
) -> None:
    """Manage account status and administrator-assisted resets.

    ``embedded=True`` places this module inside the Employees workspace
    without repeating a full page title.
    """

    if embedded:
        st.subheader("User Accounts")
        st.caption(
            "Manage employee login status and assisted password resets."
        )
    else:
        st.title("Users")
        st.caption(
            "Manage login accounts inside the current company."
        )

    with SessionFactory() as session:
        users = AdminManagementService(
            session
        ).list_users(current_user.company_id)

    rows = _build_user_rows(users)

    if rows:
        render_admin_table(
            rows,
            key="user-account-list",
            min_width=1180,
            column_widths=(
                "90px",
                "170px",
                "250px",
                "150px",
                "220px",
                "110px",
                "170px",
            ),
        )
    else:
        st.info("No user accounts were found.")

    options = {
        f"{user.username} — {user.role.name}": user.id
        for user in users
    }

    st.subheader("Account Status")

    if not options:
        st.info(
            "There are no accounts available to update."
        )
        return

    with st.form("user_status_form"):
        selected = st.selectbox(
            "User Account",
            options=list(options),
        )
        desired_status = st.selectbox(
            "New Status",
            options=("Active", "Inactive"),
        )
        submitted = st.form_submit_button(
            "Update Account Status",
            type="primary",
            width="stretch",
        )

    if submitted:
        try:
            with SessionFactory() as session:
                AdminManagementService(
                    session
                ).set_user_active_status(
                    company_id=current_user.company_id,
                    user_id=options[selected],
                    is_active=(
                        desired_status == "Active"
                    ),
                    current_user_id=current_user.user_id,
                )

            st.success(
                "Account status updated successfully."
            )
            st.rerun()

        except ValueError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "The account status could not be updated."
            )

    st.divider()
    st.subheader("Administrator-Assisted Password Reset")
    st.caption(
        "Use this only when the employee cannot access the registered "
        "Login Email. The existing password is never displayed. The "
        "employee must replace this temporary password after login."
    )

    reset_options = {
        label: user_id
        for label, user_id in options.items()
        if user_id != current_user.user_id
    }

    if not reset_options:
        st.info(
            "No other account is available for password reset."
        )
        return

    with st.form(
        "admin_temporary_password_form",
        clear_on_submit=True,
    ):
        reset_selected = st.selectbox(
            "User Account",
            options=list(reset_options),
            key="password_reset_user",
        )
        temporary_password = st.text_input(
            "Temporary Password",
            type="password",
            max_chars=128,
        )
        confirm_password = st.text_input(
            "Confirm Temporary Password",
            type="password",
            max_chars=128,
        )

        reset_submitted = st.form_submit_button(
            "Set Temporary Password",
            type="primary",
            width="stretch",
        )

    if reset_submitted:
        try:
            request = AdminTemporaryPasswordRequest(
                temporary_password=temporary_password,
                confirm_password=confirm_password,
            )

            with SessionFactory() as session:
                PasswordResetService(
                    session
                ).set_temporary_password_by_admin(
                    company_id=current_user.company_id,
                    user_id=reset_options[reset_selected],
                    current_admin_user_id=current_user.user_id,
                    temporary_password=(
                        request.temporary_password
                    ),
                )

            st.success(
                "Temporary password set successfully. "
                "The employee must change it on the next login."
            )
            st.rerun()

        except ValidationError as error:
            render_action_warning(error)
        except PasswordResetError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "The temporary password could not be set."
            )
