"""Shared layout for login and mandatory password change."""

from authentication.current_user import AuthenticatedUser
from config.settings import Settings
from ui.components.auth_sidebar import render_auth_sidebar
from ui.pages.authentication.change_password_page import (
    render_change_password_page,
)
from ui.pages.authentication.login_page import render_login_page
from ui.pages.authentication.forgot_password_page import (
    render_forgot_password_page,
)
from ui.pages.authentication.reset_password_page import (
    render_reset_password_page,
)


def render_login_layout(
    settings: Settings,
    *,
    company_name: str,
    default_company_code: str,
) -> None:
    """Render company-branded login and account form."""

    # The login page uses a centered full-width layout without the public
    # sidebar. Other public authentication pages retain the support sidebar.
    render_login_page(
        default_company_code=default_company_code
    )


def render_password_change_layout(
    settings: Settings,
    current_user: AuthenticatedUser,
) -> None:
    """Render mandatory password replacement in the login layout."""

    # Keep mandatory password replacement visually aligned with Login.
    # The page itself hides the sidebar and uses the same centered card,
    # background artwork, spacing, inputs, and primary action styling.
    render_change_password_page(current_user)



def render_forgot_password_layout(
    settings: Settings,
    *,
    company_name: str,
) -> None:
    """Render company-branded public reset-request page."""

    render_auth_sidebar(
        assistant_name=settings.assistant_name,
        company_name=company_name,
    )
    render_forgot_password_page()


def render_reset_password_layout(
    settings: Settings,
    *,
    company_name: str,
) -> None:
    """Render company-branded public new-password page."""

    render_auth_sidebar(
        assistant_name=settings.assistant_name,
        company_name=company_name,
    )
    render_reset_password_page()
