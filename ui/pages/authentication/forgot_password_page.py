"""Public email-only forgot-password request page."""

import streamlit as st
from pydantic import ValidationError

from authentication.password_reset_service import (
    PasswordResetService,
)
from database.session import SessionFactory
from schemas.auth_schema import ForgotPasswordRequest
from ui.auth_navigation import return_to_login


def render_forgot_password_page() -> None:
    """Request secure reset links using only the registered Login Email."""

    st.title("Forgot Password")
    st.caption(
        "Enter the registered Login Email for your account."
    )

    _, center, _ = st.columns([1, 1.4, 1])

    with center:
        st.markdown(
            """
            <div class="hr-card">
                <div class="hr-card-title">Reset Account Password</div>
                <div class="hr-card-text">
                    If an active account matches the email, a single-use
                    password-reset link will be sent automatically.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form(
            "forgot_password_form",
            clear_on_submit=False,
        ):
            email = st.text_input(
                "Registered Login Email",
                max_chars=255,
                placeholder="employee@example.com",
            )

            submitted = st.form_submit_button(
                "Send Password Reset Link",
                width="stretch",
                type="primary",
            )

        if submitted:
            try:
                request = ForgotPasswordRequest(
                    email=email,
                )

                with SessionFactory() as session:
                    result = PasswordResetService(
                        session
                    ).request_reset(
                        email=str(request.email),
                    )

                st.success(result.message)

            except ValidationError:
                st.error(
                    "Enter a valid registered email address."
                )
            except Exception:
                st.error(
                    "Password reset is temporarily unavailable. "
                    "Please contact your HR administrator."
                )

        st.caption(
            "When the same email is registered in more than one company, "
            "a separate company-labeled reset email is sent for each "
            "active account."
        )

        if st.button(
            "Back to Sign In",
            width="stretch",
        ):
            return_to_login()
