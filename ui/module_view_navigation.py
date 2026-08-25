"""Exact in-module destinations for Quick Actions and assistant links."""

from __future__ import annotations

from collections.abc import Mapping

import streamlit as st


_VIEW_ROUTES: dict[
    tuple[str, str],
    tuple[str, str, dict[str, str]],
] = {
    ("admin", "Employees"): (
        "employee_view",
        "employees_active_tab",
        {
            "list": "Employee List",
            "add": "Add Employee",
            "edit": "Edit Employee",
            "disciplinary": "Violations / Disciplinary Records",
            "onboarding": "Onboarding Management",
        },
    ),
    ("admin", "Policies"): (
        "policy_view",
        "policies_active_tab",
        {
            "library": "Policies",
            "upload": "Upload Policy File",
            "manage": "Manage Existing Policy",
            "violations": "Violations & Disciplinary Actions",
        },
    ),
    ("admin", "Leave Management"): (
        "leave_view",
        "admin_leave_management_active_tab",
        {
            "overview": "Overview",
            "accounts": "Employee Leave Accounts",
            "requests": "Leave Requests",
            "rules": "Leave Rules",
        },
    ),
    ("admin", "Announcements"): (
        "announcement_view",
        "announcements_active_tab",
        {
            "overview": "Overview",
            "create": "Create Announcement",
            "manage": "Manage Announcements",
            "reminders": "Reminders",
        },
    ),
    ("admin", "Company Form/Documents"): (
        "form_view",
        "company_forms_active_tab",
        {
            "overview": "Overview",
            "upload": "Upload Form",
            "manage": "Manage Form",
        },
    ),
    ("employee", "Company Policies"): (
        "policy_view",
        "employee_policies_active_tab",
        {
            "library": "Company Policies",
            "violations": "Violations & Disciplinary Actions",
            "disciplinary": "My Disciplinary Records",
        },
    ),
    ("employee", "Dashboard"): (
        "dashboard_view",
        "employee_dashboard_active_tab",
        {
            "attendance": "Dashboard",
            "announcements": "Announcements",
        },
    ),
    ("employee", "Company Form/Documents"): (
        "form_view",
        "employee_company_forms_active_tab",
        {
            "view": "View",
            "download": "Download",
            "submit": "Fill / Submit",
            "documents": "My Documents",
        },
    ),
    ("employee", "Leave Management"): (
        "leave_view",
        "employee_leave_management_active_tab",
        {
            "overview": "My Leave Overview",
            "file": "File Leave Request",
            "requests": "My Requests",
            "pending": "Pending Approvals",
            "reviewed": "Reviewed Requests",
        },
    ),
    ("employee", "Onboarding"): (
        "onboarding_view",
        "employee_onboarding_active_tab",
        {
            "overview": "Overview",
            "checklist": "Checklist",
            "benefits": "Benefits",
        },
    ),
}


EXACT_VIEW_QUERY_KEYS = {
    config[0]
    for config in _VIEW_ROUTES.values()
} | {"leave_view"}


def prime_exact_module_view(
    *,
    portal_mode: str,
    page: str,
    query_params: Mapping[str, object] | None = None,
    force: bool = True,
) -> None:
    """Set the native Streamlit tab state for one authorized destination.

    ``force=True`` is used at click time. Layout restoration uses ``False`` so
    a user can manually change tabs without a persistent URL forcing it back.
    """

    route = _VIEW_ROUTES.get((portal_mode, page))
    if route is None:
        return

    query_key, state_key, labels = route
    if not force and state_key in st.session_state:
        return

    source = query_params if query_params is not None else st.query_params
    raw_value = source.get(query_key)
    if isinstance(raw_value, (list, tuple)):
        raw_value = raw_value[0] if raw_value else None

    target = labels.get(str(raw_value or "").strip().casefold())
    if target is not None:
        st.session_state[state_key] = target
