"""Company-scoped login page."""

from textwrap import dedent
from pathlib import Path
import base64

import streamlit as st
from ui.components.validation_feedback import render_action_warning

from authentication.access_control import AccessControl
from pydantic import ValidationError

from authentication.auth_service import (
    AuthenticationError,
    AuthService,
)
from authentication.session_manager import AuthSessionManager
from authentication.signed_cookie_auth_service import SignedCookieAuthService
from database.session import SessionFactory
from schemas.auth_schema import LoginRequest
from ui.auth_navigation import (
    PUBLIC_COMPANY_KEY,
    open_forgot_password,
)


def _render_login_page_styles() -> None:
    """Apply the exact approved login composition and wave artwork."""

    project_root = Path(__file__).resolve().parents[3]
    background_path = (
        project_root
        / "assets"
        / "backgrounds"
        / "login_wave_background.png"
    )
    background_data = base64.b64encode(
        background_path.read_bytes()
    ).decode("ascii")

    login_css = dedent(
        f"""
        <style id="hr-login-page-styles">
        html, body, .stApp {{
            width: 100% !important;
            min-height: 100% !important;
            margin: 0 !important;
            overflow-x: hidden !important;
        }}

        section[data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"] {{
            display: none !important;
            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;
        }}

        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {{
            position: fixed !important;
            inset: 0 !important;
            width: 100vw !important;
            max-width: 100vw !important;
            min-height: 100vh !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow-y: auto !important;
            background-color: #f2f4f7 !important;
            background-image: url("data:image/png;base64,{background_data}") !important;
            background-size: 100% 100% !important;
            background-position: center top !important;
            background-repeat: no-repeat !important;
        }}

        [data-testid="stAppViewContainer"] > .main,
        [data-testid="stMain"] {{
            width: 100vw !important;
            max-width: 100vw !important;
            min-height: 100vh !important;
            margin: 0 !important;
            padding: 0 !important;
            background: transparent !important;
        }}

        [data-testid="stMainBlockContainer"],
        [data-testid="stMain"] .block-container,
        [data-testid="stAppViewContainer"] .main .block-container {{
            box-sizing: border-box !important;
            width: min(590px, calc(100vw - 32px)) !important;
            max-width: 590px !important;
            min-height: 100vh !important;
            margin: 0 auto !important;
            padding: 32px 0 !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
        }}

        .hr-login-hero {{
            margin: 0 0 30px !important;
            text-align: center !important;
            transform: translateY(clamp(-52px, -5vh, -36px)) !important;
        }}

        [data-testid="stForm"] {{
            transform: translateY(clamp(-52px, -5vh, -36px)) !important;
        }}

        .hr-login-title {{
            margin: 0 !important;
            color: #101d35 !important;
            font-size: clamp(2.55rem, 4vw, 3.2rem) !important;
            line-height: 1.08 !important;
            letter-spacing: -.035em !important;
            font-weight: 820 !important;
        }}

        .hr-login-subtitle {{
            margin: 14px 0 0 !important;
            color: #53637d !important;
            font-size: 1.06rem !important;
            line-height: 1.45 !important;
        }}

        [data-testid="stForm"] {{
            box-sizing: border-box !important;
            width: 100% !important;
            padding: 38px 34px 28px !important;
            background: rgba(255,255,255,.965) !important;
            border: 1px solid rgba(209,216,225,.92) !important;
            border-radius: 20px !important;
            box-shadow:
                0 34px 66px rgba(29,43,62,.20),
                0 14px 28px rgba(29,43,62,.13),
                0 3px 8px rgba(29,43,62,.07) !important;
            backdrop-filter: blur(12px) !important;
            -webkit-backdrop-filter: blur(12px) !important;
        }}

        .hr-login-card-heading {{
            margin: 0 0 6px !important;
            color: #101d35 !important;
            font-size: 1.34rem !important;
            font-weight: 790 !important;
        }}

        .hr-login-card-copy {{
            margin: 0 0 24px !important;
            color: #5b6b84 !important;
            font-size: .96rem !important;
        }}

        [data-testid="stTextInput"] {{
            margin-bottom: 8px !important;
        }}

        [data-testid="stTextInput"] label p {{
            color: #17233a !important;
            font-weight: 720 !important;
        }}

        [data-testid="stTextInput"] input {{
            min-height: 52px !important;
            border-radius: 10px !important;
            font-size: 1rem !important;
        }}

        [data-testid="stFormSubmitButton"] button[kind="primary"],
        [data-testid="stFormSubmitButton"] button[data-testid="stBaseButton-primaryFormSubmit"] {{
            min-height: 52px !important;
            margin-top: 10px !important;
            border-radius: 10px !important;
            background: linear-gradient(90deg, #079b12, #12b21d) !important;
            color: #ffffff !important;
            border: 0 !important;
            font-size: 1.04rem !important;
            font-weight: 760 !important;
            box-shadow: 0 7px 14px rgba(9,157,20,.18) !important;
        }}

        [data-testid="stFormSubmitButton"] button[kind="secondary"],
        [data-testid="stFormSubmitButton"] button[data-testid="stBaseButton-secondaryFormSubmit"] {{
            min-height: 40px !important;
            margin-top: 9px !important;
            background: transparent !important;
            border-color: transparent !important;
            color: #53637d !important;
            box-shadow: none !important;
            font-weight: 670 !important;
        }}

        [data-testid="stFormSubmitButton"] button[kind="secondary"]:hover,
        [data-testid="stFormSubmitButton"] button[data-testid="stBaseButton-secondaryFormSubmit"]:hover {{
            background: rgba(28,165,42,.08) !important;
            color: #101d35 !important;
        }}

        .st-key-login_forgot_password_button button,
        div[class*="st-key-login_forgot_password_button"] button {{
            min-height: 40px !important;
            margin-top: 9px !important;
            color: #53637d !important;
            -webkit-text-fill-color: #53637d !important;
            background: transparent !important;
            background-color: transparent !important;
            border: 0 !important;
            border-color: transparent !important;
            box-shadow: none !important;
            font-weight: 670 !important;
        }}

        .st-key-login_forgot_password_button button *,
        div[class*="st-key-login_forgot_password_button"] button * {{
            color: inherit !important;
            -webkit-text-fill-color: inherit !important;
        }}

        .st-key-login_forgot_password_button button:hover,
        .st-key-login_forgot_password_button button:focus-visible,
        div[class*="st-key-login_forgot_password_button"] button:hover,
        div[class*="st-key-login_forgot_password_button"] button:focus-visible {{
            color: #101d35 !important;
            -webkit-text-fill-color: #101d35 !important;
            background: rgba(28,165,42,.08) !important;
            background-color: rgba(28,165,42,.08) !important;
            border: 0 !important;
            box-shadow: none !important;
        }}

        @media (max-width: 680px) {{
            [data-testid="stMainBlockContainer"],
            [data-testid="stMain"] .block-container {{
                width: calc(100vw - 22px) !important;
                padding: 36px 0 24px !important;
            }}

            .hr-login-hero {{
                margin-bottom: 24px !important;
            }}

            [data-testid="stForm"] {{
                padding: 30px 21px 22px !important;
                border-radius: 17px !important;
            }}

            .hr-login-title {{
                font-size: 2.25rem !important;
            }}

            .hr-login-subtitle {{
                font-size: .95rem !important;
            }}
        }}

        @media (max-height: 760px) {{
            .hr-login-hero,
            [data-testid="stForm"] {{
                transform: translateY(-12px) !important;
            }}
        }}
        </style>
        """
    ).strip()
    st.markdown(login_css, unsafe_allow_html=True)


def render_login_page(default_company_code: str) -> None:
    """Render and process the login form."""

    _render_login_page_styles()

    if st.session_state.pop(
        "password_reset_success",
        False,
    ):
        st.success(
            "Your password was reset successfully. "
            "Sign in using the new password."
        )

    st.markdown(
        """
        <div class="hr-login-hero">
            <h1 class="hr-login-title">Welcome Back</h1>
            <p class="hr-login-subtitle">
                Sign in to access HR services and administration tools.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form(
            "login_form",
            clear_on_submit=False,
    ):
        st.markdown(
            """
            <div class="hr-login-card-heading">Account Login</div>
            <div class="hr-login-card-copy">
                Enter your company code, username or email, and password.
            </div>
            """,
            unsafe_allow_html=True,
        )

        company_code = st.text_input(
            "Company Code",
            value=default_company_code,
            max_chars=50,
            key="login_company_code",
            help=(
                "Enter the company code assigned by your administrator."
            ),
        )
        login_identifier = st.text_input(
            "Username or Email",
            max_chars=255,
            key="login_identifier",
        )
        password = st.text_input(
            "Password",
            type="password",
            max_chars=128,
            key="login_password",
        )

        submitted = st.form_submit_button(
            "Sign In",
            width="stretch",
            type="primary",
        )
        forgot_password = st.form_submit_button(
            "Forgot Password?",
            width="stretch",
            type="secondary",
            key="login_forgot_password_button",
        )

    if forgot_password:
        open_forgot_password()
        return

    if submitted:
        try:
            normalized_company_code = company_code.strip().upper()
            st.session_state["public_company_code"] = (
                normalized_company_code
            )

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

                signed_token = SignedCookieAuthService(
                    session
                ).issue_token(current_user)

            # Do not update query parameters or start a Streamlit rerun
            # before the browser has committed the signed cookie.
            if AccessControl.is_admin(current_user):
                st.session_state.portal_mode = "admin"
                st.session_state.current_page = "Admin Dashboard"
            else:
                st.session_state.portal_mode = "employee"
                st.session_state.current_page = "Dashboard"

            AuthSessionManager.complete_login(
                current_user,
                signed_token=signed_token,
            )

        except ValidationError as error:
            render_action_warning(error)
        except AuthenticationError as error:
            render_action_warning(error)
        except Exception:
            # Do not reveal database or internal exception details.
            st.error(
                "Login could not be completed. "
                "Please contact your administrator."
            )
