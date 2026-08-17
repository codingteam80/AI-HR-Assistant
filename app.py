"""AI HR Assistant Streamlit entry point.

Routing:
1. Initialize UI and authentication state.
2. Apply the fixed Light Mode theme.
3. Show login when logged out.
4. Force temporary-password replacement.
5. Route administrators and employees to protected layouts.
"""

import streamlit as st

from authentication.access_control import AccessControl
from authentication.password_reset_service import (
    PasswordResetService,
)
from authentication.session_manager import AuthSessionManager
from config.settings import get_settings
from core.constants import DEFAULT_COMPANY_THEME_COLOR
from database.runtime_schema import initialize_runtime_schema
from database.session import SessionFactory
from ui.auth_navigation import (
    get_auth_action,
    get_public_company_code,
    get_reset_token,
)
from ui.layouts.admin_layout import render_admin_layout
from ui.layouts.auth_layout import (
    render_forgot_password_layout,
    render_login_layout,
    render_password_change_layout,
    render_reset_password_layout,
)
from ui.layouts.user_layout import render_user_layout
from ui.session_state import initialize_session_state
from services.announcement_service import AnnouncementService
from services.event_reminder_service import EventReminderService
from services.leave_service import LeaveService
from services.organization_service import OrganizationService
from ui.theme.theme_loader import apply_theme


def _clean_public_company_code(
    value: object,
) -> str | None:
    """Return a normalized, bounded company code."""

    if not isinstance(value, str):
        return None

    cleaned = value.strip().upper()

    if not cleaned or len(cleaned) > 50:
        return None

    return cleaned


def _load_public_company_brand(
    settings,
    *,
    reset_token: str = "",
) -> tuple[str, str, str]:
    """Resolve company name, accent, and code for public auth pages."""

    try:
        with SessionFactory() as session:
            company = None

            if reset_token:
                company = (
                    PasswordResetService
                    .get_company_for_valid_token(
                        session,
                        reset_token,
                    )
                )

            if company is None:
                requested_code = (
                    get_public_company_code()
                    or _clean_public_company_code(
                        st.session_state.get(
                            "public_company_code"
                        )
                    )
                    or settings.initial_company_code
                )

                company = OrganizationService(
                    session
                ).resolve_public_company(
                    requested_code
                )

        if company is not None:
            return (
                company.name,
                company.theme_primary_color
                or DEFAULT_COMPANY_THEME_COLOR,
                company.code,
            )

    except Exception:
        # Public authentication remains usable if branding lookup fails.
        pass

    return (
        settings.company_name,
        DEFAULT_COMPANY_THEME_COLOR,
        settings.initial_company_code,
    )


def _load_company_theme_color(
    company_id: int,
) -> str:
    """Load the company accent with a safe default fallback."""

    try:
        with SessionFactory() as session:
            company = OrganizationService(
                session
            ).get_company(company_id)

        return (
            company.theme_primary_color
            or DEFAULT_COMPANY_THEME_COLOR
        )
    except Exception:
        # Authentication and routing remain usable if branding lookup fails.
        return DEFAULT_COMPANY_THEME_COLOR



def _reconcile_announcements(
    company_id: int,
) -> None:
    """Publish due announcements and send due admin planning reminders."""

    try:
        with SessionFactory() as session:
            AnnouncementService(
                session
            ).reconcile_publications(
                company_id=company_id
            )

        with SessionFactory() as session:
            EventReminderService(
                session
            ).reconcile_due(
                company_id=company_id
            )
    except Exception:
        # Login and routing remain usable if publication reconciliation fails.
        return


def _reconcile_leave_credits(
    company_id: int,
) -> None:
    """Catch up approved leave dates whenever the app is opened."""

    try:
        with SessionFactory() as session:
            service = LeaveService(session)
            # Post elapsed leave first so December 31 VL is included before
            # an unmet utilization target is finalized and carried forward.
            service.reconcile_approved_leave(
                company_id=company_id
            )
            # Creates the new calendar-year balances every January and also
            # applies service-anniversary entitlement increases when due.
            service.ensure_current_year_balances(company_id)
            service.reconcile_leave_utilization(
                company_id=company_id
            )
    except Exception:
        # Routing and login must remain usable if reconciliation fails.
        # The scheduled reconciliation script can retry later.
        return


def main() -> None:
    """Start the application and route the current browser session."""

    settings = get_settings()

    st.set_page_config(
        page_title=settings.app_name,
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Create newly introduced tables without deleting existing data.
    initialize_runtime_schema()

    initialize_session_state()

    # Forgot/reset pages remain public even when a stale browser cookie
    # exists. Their branding is resolved before authentication.
    auth_action = get_auth_action()
    reset_token = (
        get_reset_token()
        if auth_action == "reset"
        else ""
    )
    (
        public_company_name,
        public_primary_color,
        public_company_code,
    ) = _load_public_company_brand(
        settings,
        reset_token=reset_token,
    )

    if auth_action == "forgot":
        apply_theme(
            primary_color=public_primary_color
        )
        render_forgot_password_layout(
            settings,
            company_name=public_company_name,
        )
        return

    if auth_action == "reset":
        apply_theme(
            primary_color=public_primary_color
        )
        render_reset_password_layout(
            settings,
            company_name=public_company_name,
        )
        return

    # Browser refresh creates a new Streamlit session. Wait for the
    # persistent browser token before deciding to show Login.
    AuthSessionManager.restore_from_browser()

    if not AuthSessionManager.is_authenticated():
        if st.session_state.get(
            AuthSessionManager.LOGOUT_PENDING_KEY,
            False,
        ):
            AuthSessionManager.complete_logout_transition()
        apply_theme(
            primary_color=public_primary_color
        )
        render_login_layout(
            settings,
            company_name=public_company_name,
            default_company_code=public_company_code,
        )
        return

    current_user = AuthSessionManager.get_current_user()

    # A successful form submit enters the portal immediately. Browser-token
    # persistence is completed non-blockingly from the protected page.
    AuthSessionManager.flush_pending_browser_token()

    if current_user is None:
        AuthSessionManager.logout()
        st.rerun()

    _reconcile_announcements(
        current_user.company_id
    )
    _reconcile_leave_credits(
        current_user.company_id
    )

    apply_theme(
        primary_color=_load_company_theme_color(
            current_user.company_id
        )
    )

    if current_user.must_change_password:
        render_password_change_layout(
            settings,
            current_user,
        )
        return

    portal_query_exists = "portal" in st.query_params
    page_query_exists = "page" in st.query_params

    portal_mode = st.session_state.get(
        "portal_mode",
        "admin"
        if AccessControl.is_admin(current_user)
        else "employee",
    )

    # First cookie restore has no saved route yet. Open the correct default
    # portal based on the restored role.
    if (
        not portal_query_exists
        and not page_query_exists
        and AccessControl.is_admin(current_user)
    ):
        st.session_state.portal_mode = "admin"
        st.session_state.current_page = "Admin Dashboard"
        portal_mode = "admin"

    # A query parameter can request admin navigation, but authorization is
    # still enforced here before rendering any administrator page.
    if (
        portal_mode == "admin"
        and not AccessControl.is_admin(current_user)
    ):
        st.session_state.portal_mode = "employee"
        st.session_state.current_page = "Dashboard"
        portal_mode = "employee"

    if (
        portal_mode == "admin"
        and AccessControl.is_admin(current_user)
    ):
        render_admin_layout(settings, current_user)
        return

    render_user_layout(settings, current_user)


if __name__ == "__main__":
    main()
