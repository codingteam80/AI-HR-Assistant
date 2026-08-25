"""Persist the last portal and page in safe URL query parameters.

Navigation labels are not authentication credentials. They are restored
only after cookie authentication succeeds, and administrator access is
still checked by AccessControl before an admin page is rendered.
"""

from typing import Any

from core.constants import DEFAULT_PAGE


PORTAL_QUERY_KEY = "portal"
PAGE_QUERY_KEY = "page"
VALID_PORTALS = {"admin", "employee"}

# URL/session targets that are intentionally preserved for F5/deep links but
# must not leak into a different module selected from the sidebar.
_SIDEBAR_MODULE_QUERY_KEYS = {
    "employee_view",
    "policy_view",
    "leave_view",
    "announcement_view",
    "form_view",
    "dashboard_view",
    "onboarding_view",
    "announcement_id",
    "reminder_id",
    "leave_request_id",
    "policy_id",
    "company_form_id",
    "form_submission_id",
    "employee_id",
}

_SIDEBAR_PENDING_TAB_STATE_KEYS = {
    "company_forms_next_tab",
    "employee_company_forms_next_tab",
    "announcements_next_tab",
    "reminders_next_tab",
    "employees_pending_active_tab",
    "admin_onboarding_management_pending_active_tab",
    "company_profile_pending_active_tab",
    "employee_onboarding_pending_active_tab",
    "_admin_leave_next_tabs",
    "notification_related_entity_type",
    "notification_related_entity_id",
}


def _clean_query_value(
    value: Any,
    *,
    max_length: int,
) -> str | None:
    """Return a small printable query value or None."""

    if isinstance(value, (list, tuple)):
        value = value[0] if value else None

    if not isinstance(value, str):
        return None

    cleaned = value.strip()

    if not cleaned or len(cleaned) > max_length:
        return None

    return cleaned


def initialize_navigation_state() -> None:
    """Restore portal/page values for a new Streamlit browser session."""

    import streamlit as st

    query_portal = _clean_query_value(
        st.query_params.get(PORTAL_QUERY_KEY),
        max_length=20,
    )
    query_page = _clean_query_value(
        st.query_params.get(PAGE_QUERY_KEY),
        max_length=100,
    )

    if "portal_mode" not in st.session_state:
        st.session_state.portal_mode = (
            query_portal
            if query_portal in VALID_PORTALS
            else "employee"
        )

    if "current_page" not in st.session_state:
        st.session_state.current_page = (
            query_page or DEFAULT_PAGE
        )


def set_navigation_state(
    *,
    portal_mode: str,
    current_page: str,
) -> None:
    """Update both session state and refresh-safe URL navigation."""

    import streamlit as st

    normalized_portal = (
        portal_mode
        if portal_mode in VALID_PORTALS
        else "employee"
    )
    normalized_page = (
        current_page.strip()[:100]
        if current_page.strip()
        else DEFAULT_PAGE
    )

    st.session_state.portal_mode = normalized_portal
    st.session_state.current_page = normalized_page

    if (
        st.query_params.get(PORTAL_QUERY_KEY)
        != normalized_portal
    ):
        st.query_params[PORTAL_QUERY_KEY] = normalized_portal

    if (
        st.query_params.get(PAGE_QUERY_KEY)
        != normalized_page
    ):
        st.query_params[PAGE_QUERY_KEY] = normalized_page



def reset_module_view_for_sidebar_navigation() -> None:
    """Reset horizontal/sub-tab targets after an intentional sidebar change.

    This is deliberately *not* used for normal reruns or browser refreshes.
    F5 keeps the exact active native tab through ``tab_*`` URL state, while a
    different sidebar destination starts from that module's first/default tab.
    """

    import streamlit as st

    from ui.components.persistent_tabs import clear_persistent_tab_navigation

    clear_persistent_tab_navigation()

    for query_key in _SIDEBAR_MODULE_QUERY_KEYS:
        if query_key in st.query_params:
            del st.query_params[query_key]

    for state_key in _SIDEBAR_PENDING_TAB_STATE_KEYS:
        st.session_state.pop(state_key, None)


def set_sidebar_navigation_state(
    *,
    portal_mode: str,
    current_page: str,
) -> None:
    """Navigate from the sidebar and reset the destination's inner tabs.

    A click that actually changes portal/page is different from F5. The former
    deliberately starts the selected module at its first/default horizontal
    tab; the latter must preserve the exact current tab.
    """

    import streamlit as st

    normalized_portal = (
        portal_mode if portal_mode in VALID_PORTALS else "employee"
    )
    normalized_page = (
        current_page.strip()[:100] if current_page.strip() else DEFAULT_PAGE
    )

    route_changed = (
        st.session_state.get("portal_mode") != normalized_portal
        or st.session_state.get("current_page") != normalized_page
    )

    if route_changed:
        reset_module_view_for_sidebar_navigation()

    set_navigation_state(
        portal_mode=normalized_portal,
        current_page=normalized_page,
    )

def clear_navigation_state() -> None:
    """Remove only navigation parameters while preserving theme state."""

    import streamlit as st

    for key in list(st.query_params.keys()):
        if (
            key in {PORTAL_QUERY_KEY, PAGE_QUERY_KEY}
            or str(key).startswith("tab_")
        ):
            del st.query_params[key]

    st.session_state.portal_mode = "employee"
    st.session_state.current_page = DEFAULT_PAGE
