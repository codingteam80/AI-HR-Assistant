"""Mandatory temporary-password replacement page."""

from textwrap import dedent

import streamlit as st
from ui.components.validation_feedback import render_action_warning
from pydantic import ValidationError

from authentication.auth_service import (
    AuthenticationError,
    AuthService,
)
from authentication.current_user import AuthenticatedUser
from authentication.session_manager import AuthSessionManager
from authentication.signed_cookie_auth_service import SignedCookieAuthService
from database.session import SessionFactory
from schemas.auth_schema import PasswordChangeRequest
from ui.pages.authentication.login_page import _render_login_page_styles


def _render_password_change_styles() -> None:
    """Reuse the login composition and add password-page-only styling."""

    _render_login_page_styles()

    st.markdown(
        dedent(
            """
            <style id="hr-password-change-page-styles">
            [data-testid="stMainBlockContainer"],
            [data-testid="stMain"] .block-container,
            [data-testid="stAppViewContainer"] .main .block-container {
                min-height: 100vh !important;
                padding-top: 32px !important;
                padding-bottom: 32px !important;
                display: flex !important;
                flex-direction: column !important;
                justify-content: center !important;
            }

            .hr-password-change-note {
                box-sizing: border-box !important;
                width: 100% !important;
                margin: 0 0 22px !important;
                padding: 13px 14px !important;
                color: #554b13 !important;
                background: #fff9cf !important;
                border: 1px solid #f0e6a3 !important;
                border-radius: 10px !important;
                font-size: .94rem !important;
                line-height: 1.45 !important;
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )


def render_change_password_page(
    current_user: AuthenticatedUser,
) -> None:
    """Block protected pages until the password is replaced."""

    _render_password_change_styles()

    st.markdown(
        """
        <div class="hr-login-hero">
            <h1 class="hr-login-title">Change Your Password</h1>
            <p class="hr-login-subtitle">
                Secure your account before continuing to HR services.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form(
        "forced_password_change_form",
        clear_on_submit=True,
    ):
        st.markdown(
            """
            <div class="hr-login-card-heading">Account Security</div>
            <div class="hr-password-change-note">
                You must change your temporary password before continuing.<br>
                Replace it with a password only you know.
            </div>
            """,
            unsafe_allow_html=True,
        )

        current_password = st.text_input(
            "Current Password",
            type="password",
            max_chars=128,
        )
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
            "Update Password",
            width="stretch",
            type="primary",
        )

    if submitted:
        try:
            request = PasswordChangeRequest(
                current_password=current_password,
                new_password=new_password,
                confirm_password=confirm_password,
            )

            with SessionFactory() as session:
                updated_user = AuthService(
                    session
                ).change_password(
                    company_id=current_user.company_id,
                    user_id=current_user.user_id,
                    current_password=request.current_password,
                    new_password=request.new_password,
                )

                # Password changes invalidate the old fingerprint, so a
                # new signed cookie is issued immediately.
                signed_token = SignedCookieAuthService(
                    session
                ).issue_token(updated_user)

            AuthSessionManager.complete_password_change(
                updated_user,
                signed_token=signed_token,
            )

        except ValidationError as error:
            render_action_warning(error)
        except AuthenticationError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "The password could not be updated. "
                "Please contact your administrator."
            )
