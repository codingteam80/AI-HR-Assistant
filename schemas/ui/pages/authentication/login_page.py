"""Company-scoped login page."""

import streamlit as st
from pydantic import ValidationError

from authentication.auth_service import (
    AuthenticationError,
    AuthService,
)
from authentication.session_manager import AuthSessionManager
from database.session import SessionFactory
from schemas.auth_schema import LoginRequest


def render_login_page(default_company_code: str) -> None:
    """Render and process the login form."""

    st.title("Welcome Back")
    st.caption(
        "Sign in to access HR services and administration tools."
    )

    _, center, _ = st.columns([1, 1.4, 1])

    with center:
        st.markdown(
            """
            <div class="hr-card">
                <div class="hr-card-title">Account Login</div>
                <div class="hr-card-text">
                    Enter your company code, username or email, and password.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form(
            "login_form",
            clear_on_submit=False,
        ):
            company_code = st.text_input(
                "Company Code",
                value=default_company_code,
                max_chars=50,
            )
            login_identifier = st.text_input(
                "Username or Email",
                max_chars=255,
            )
            password = st.text_input(
                "Password",
                type="password",
                max_chars=128,
            )

            submitted = st.form_submit_button(
                "Sign In",
                width="stretch",
                type="primary",
            )

        if submitted:
            try:
                request = LoginRequest(
                    company_code=company_code,
                    login_identifier=login_identifier,
                    password=password,
                )

                with SessionFactory() as session:
                    current_user = AuthService(
                        session
                    ).authenticate(
                        company_code=request.company_code,
                        login_identifier=request.login_identifier,
                        password=request.password,
                    )

                AuthSessionManager.login(current_user)

                if current_user.role_name in {
                    "super_admin",
                    "company_admin",
                    "hr_admin",
                }:
                    st.session_state.portal_mode = "admin"
                    st.session_state.current_page = "Admin Dashboard"
                else:
                    st.session_state.portal_mode = "employee"
                    st.session_state.current_page = "Chat Assistant"

                st.rerun()

            except ValidationError as error:
                st.error(error.errors()[0]["msg"])
            except AuthenticationError as error:
                st.error(str(error))
            except Exception:
                # Do not reveal database or internal exception details.
                st.error(
                    "Login could not be completed. "
                    "Please contact your administrator."
                )
