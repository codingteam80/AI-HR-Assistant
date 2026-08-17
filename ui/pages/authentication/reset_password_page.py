"""Public new-password page opened from a reset email."""

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from pydantic import ValidationError

from authentication.password_reset_service import (
    PasswordResetError,
    PasswordResetService,
)
from authentication.session_manager import AuthSessionManager
from database.session import SessionFactory
from schemas.auth_schema import (
    PasswordResetCompletionRequest,
)
from ui.auth_navigation import (
    get_reset_token,
    return_to_login,
)


def render_reset_password_page() -> None:
    """Validate one reset link and accept a new password."""

    raw_token = get_reset_token()

    st.title("Create New Password")
    st.caption(
        "Reset links expire and can be used only once."
    )

    with SessionFactory() as session:
        token_is_valid = PasswordResetService(
            session
        ).is_token_valid(raw_token)

    _, center, _ = st.columns([1, 1.4, 1])

    with center:
        if not token_is_valid:
            st.error(
                "The password reset link is invalid or expired."
            )

            if st.button(
                "Return to Sign In",
                width="stretch",
            ):
                return_to_login()

            return

        with st.form(
            "password_reset_completion_form",
            clear_on_submit=True,
        ):
            new_password = st.text_input(
                "New Password",
                type="password",
                max_chars=128,
                help="Use at least 8 characters.",
            )
            confirm_password = st.text_input(
                "Confirm New Password",
                type="password",
                max_chars=128,
            )

            submitted = st.form_submit_button(
                "Reset Password",
                width="stretch",
                type="primary",
            )

        if submitted:
            try:
                request = PasswordResetCompletionRequest(
                    new_password=new_password,
                    confirm_password=confirm_password,
                )

                with SessionFactory() as session:
                    PasswordResetService(
                        session
                    ).reset_password(
                        raw_token=raw_token,
                        new_password=request.new_password,
                    )

                # Clear any session in the browser that performed the reset.
                # Other signed sessions fail validation on their next app run
                # because the password fingerprint has changed.
                AuthSessionManager.clear_after_password_reset()

                st.session_state[
                    "password_reset_success"
                ] = True
                return_to_login()

            except ValidationError as error:
                render_action_warning(error)
            except PasswordResetError as error:
                render_action_warning(error)
            except Exception:
                st.error(
                    "The password could not be reset. "
                    "Request a new reset link."
                )
