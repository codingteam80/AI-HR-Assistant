"""Protected employee application layout."""

import streamlit as st

from authentication.current_user import AuthenticatedUser
from config.settings import Settings
from ui.components.sidebar import render_sidebar
from ui.components.topbar import render_topbar
from ui.components.view_state_preservation import preserve_current_view
from ui.module_view_navigation import prime_exact_module_view
from ui.pages.user.chat_page import render_chat_page
from ui.pages.user.company_forms_documents_page import (
    render_employee_company_forms_documents_page,
)
from ui.pages.user.dashboard_page import (
    render_employee_dashboard_page,
)
from ui.pages.user.attendance_hub_page import render_employee_attendance_hub_page
from ui.pages.user.faq_page import render_employee_faq_page
from ui.pages.user.placeholder_page import render_placeholder_page
from ui.pages.user.policies_page import render_employee_policies_page
from ui.pages.user.reports_page import render_employee_reports_page
from ui.pages.user.leave_management_page import render_employee_leave_management_page
from ui.pages.user.onboarding_page import render_employee_onboarding_page
from ui.navigation_state import set_navigation_state


def render_user_layout(
    settings: Settings,
    current_user: AuthenticatedUser,
) -> None:
    """Render employee sidebar, topbar, and selected page."""

    render_sidebar(
        assistant_name=settings.assistant_name,
        current_user=current_user,
    )
    render_topbar(
        company_name=current_user.company_name,
        current_user=current_user,
    )

    current_page = st.session_state.current_page
    view_page = {
        "Announcements": "Dashboard",
        "Company Announcements": "Dashboard",
        "My Documents": "Company Form/Documents",
        "My Requests": "Leave Management",
        "Benefits": "Onboarding",
    }.get(current_page, current_page)
    preserve_current_view(
        current_user=current_user,
        portal_mode="employee",
        page=view_page,
    )
    prime_exact_module_view(
        portal_mode="employee",
        page=current_page,
        force=False,
    )

    if current_page == "Dashboard":
        render_employee_dashboard_page(current_user)
    elif current_page == "Attendance Hub":
        render_employee_attendance_hub_page(current_user)
    elif current_page == "Reports":
        render_employee_reports_page(current_user)
    elif current_page in {
        "Announcements",
        "Company Announcements",
    }:
        # Preserve old saved URLs while opening the Dashboard sub-tab.
        st.session_state["employee_dashboard_active_tab"] = "Announcements"
        st.session_state.current_page = "Dashboard"
        st.query_params["page"] = "Dashboard"
        render_employee_dashboard_page(current_user)
    elif current_page == "Chat Assistant":
        render_chat_page(current_user)
    elif current_page == "Company Form/Documents":
        render_employee_company_forms_documents_page(current_user)
    elif current_page == "My Documents":
        # Refresh-safe compatibility for links saved before the duplicate
        # sidebar item was consolidated into Company Form/Documents.
        st.session_state["employee_company_forms_active_tab"] = "My Documents"
        st.session_state["employee_company_forms_next_tab"] = "My Documents"
        set_navigation_state(
            portal_mode="employee",
            current_page="Company Form/Documents",
        )
        st.query_params["form_view"] = "documents"
        render_employee_company_forms_documents_page(current_user)
    elif current_page == "Company Policies":
        render_employee_policies_page(current_user)
    elif current_page == "FAQ":
        render_employee_faq_page(current_user)
    elif current_page in {"Onboarding", "Benefits"}:
        if current_page == "Benefits":
            # Preserve older bookmarks after Benefits moved into Onboarding.
            st.session_state["employee_onboarding_active_tab"] = "Benefits"
            set_navigation_state(
                portal_mode="employee",
                current_page="Onboarding",
            )
            st.query_params["onboarding_view"] = "benefits"
        render_employee_onboarding_page(current_user)
    elif current_page in {"Leave Management", "My Requests"}:
        if current_page == "My Requests":
            # Preserve old bookmarks while keeping a single sidebar module.
            st.session_state[
                "employee_leave_management_active_tab"
            ] = "My Requests"
            set_navigation_state(
                portal_mode="employee",
                current_page="Leave Management",
            )
            st.query_params["leave_view"] = "requests"
        render_employee_leave_management_page(current_user)
    else:
        render_placeholder_page(current_page)
