"""Reusable Employee and Admin HR Assistant quick actions."""

import streamlit as st

from ui.navigation_state import set_navigation_state
from ui.module_view_navigation import (
    EXACT_VIEW_QUERY_KEYS,
    prime_exact_module_view,
)


def _open_quick_action(
    *,
    portal_mode: str,
    page: str,
    query_params: dict[str, str] | None = None,
) -> None:
    """Navigate to one exact employee or administrator module view."""

    for key in {
        "announcement_id",
        "employee_id",
        "leave_request_id",
        "policy_id",
    } | EXACT_VIEW_QUERY_KEYS:
        if key in st.query_params:
            del st.query_params[key]

    params = query_params or {}
    prime_exact_module_view(
        portal_mode=portal_mode,
        page=page,
        query_params=params,
    )
    set_navigation_state(portal_mode=portal_mode, current_page=page)

    for key, value in params.items():
        st.query_params[key] = value

    st.rerun()


def render_quick_actions() -> None:
    """Render clickable Employee Portal quick-action cards."""

    st.subheader("Quick Actions")
    actions = (
        (
            "Apply for Leave",
            "Submit a new leave request",
            "Leave Management",
            {"leave_view": "file"},
        ),
        (
            "Check Leave Balance",
            "View your leave entitlement",
            "Leave Management",
            {"leave_view": "overview"},
        ),
        (
            "Request Document",
            "View available company forms and documents",
            "Company Form/Documents",
            {"form_view": "view"},
        ),
        (
            "Raise a Concern",
            "Open the company HR contact workspace",
            "HR Contacts",
            {},
        ),
    )

    for index, (title, description, page, params) in enumerate(actions):
        with st.container(
            border=True,
            key=f"employee_quick_action_card_{index}",
        ):
            st.markdown(f"**{title}**")
            st.caption(description)
            if st.button(
                f"Open {title}",
                width="stretch",
                key=f"employee_quick_action_button_{index}",
            ):
                _open_quick_action(
                    portal_mode="employee",
                    page=page,
                    query_params=params,
                )


def _open_admin_quick_action(
    *,
    page: str,
    query_params: dict[str, str] | None = None,
) -> None:
    """Open one admin module and remove stale deep-link parameters."""

    for key in {
        "announcement_id",
        "employee_id",
        "leave_request_id",
        "policy_id",
    } | EXACT_VIEW_QUERY_KEYS:
        if key in st.query_params:
            del st.query_params[key]

    params = query_params or {}
    prime_exact_module_view(
        portal_mode="admin",
        page=page,
        query_params=params,
    )
    set_navigation_state(
        portal_mode="admin",
        current_page=page,
    )

    for key, value in params.items():
        st.query_params[key] = value

    st.rerun()


def render_admin_quick_actions() -> None:
    """Render clickable admin actions using the Employee card pattern."""

    st.subheader("Quick Actions")

    actions = (
        (
            "Manage Employees",
            "Create, edit, search, or review employee records",
            "Employees",
            {"employee_view": "list"},
        ),
        (
            "Review Leave Requests",
            "Open the company leave-request workspace",
            "Leave Management",
            {"leave_view": "requests"},
        ),
        (
            "Manage Policies",
            "Upload, review, publish, or archive policies",
            "Policies",
            {"policy_view": "manage"},
        ),
        (
            "Create Announcement",
            "Prepare and publish a company announcement",
            "Announcements",
            {"announcement_view": "create"},
        ),
    )

    for index, (title, description, page, params) in enumerate(actions):
        with st.container(
            border=True,
            key=f"admin_quick_action_card_{index}",
        ):
            st.markdown(f"**{title}**")
            st.caption(description)

            if st.button(
                f"Open {title}",
                width="stretch",
                key=f"admin_quick_action_button_{index}",
            ):
                _open_admin_quick_action(
                    page=page,
                    query_params=params,
                )
