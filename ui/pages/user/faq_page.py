"""Default employee Frequently Asked Questions and exact portal links."""

from __future__ import annotations

from dataclasses import dataclass, field

import streamlit as st

from authentication.current_user import AuthenticatedUser
from ui.module_view_navigation import (
    EXACT_VIEW_QUERY_KEYS,
    prime_exact_module_view,
)
from ui.navigation_state import set_navigation_state


@dataclass(frozen=True, slots=True)
class DefaultFAQ:
    """One default answer and its optional exact employee destination."""

    question: str
    answer: str
    link_label: str | None = None
    page: str | None = None
    query_params: dict[str, str] = field(default_factory=dict)


DEFAULT_FAQS = (
    DefaultFAQ(
        question="How do I record today's attendance?",
        answer=(
            "Select Today's Work Status on the Dashboard, then click Time In. "
            "The selected status is saved with your attendance. When your work "
            "is finished, return to the Dashboard and click Time Out."
        ),
        link_label="Open Dashboard",
        page="Dashboard",
        query_params={"dashboard_view": "attendance"},
    ),
    DefaultFAQ(
        question="Where can I review or correct my DTR?",
        answer=(
            "Open Attendance Hub to review your monthly DTR. Use Edit Attendance "
            "Record to update permitted dates, work status, and time entries. "
            "Every saved employee edit remains available in the admin history."
        ),
        link_label="Open Attendance Hub",
        page="Attendance Hub",
    ),
    DefaultFAQ(
        question="How do I file and monitor an overtime request?",
        answer=(
            "Open Attendance Hub and expand Overtime Request. The employee and "
            "DTR reference are read-only; verify the editable date and time fields, "
            "complete the OT details, and submit. The same section lists your "
            "overtime requests and their current status."
        ),
        link_label="Open Overtime Request",
        page="Attendance Hub",
    ),
    DefaultFAQ(
        question="How do I file a leave request?",
        answer=(
            "Open File Leave Request, select the leave type and dates, choose AM "
            "Only, PM Only, or Whole Day, then complete the standard reason and "
            "Other Reason when required. Review the chargeable workdays before "
            "submitting."
        ),
        link_label="Open File Leave Request",
        page="Leave Management",
        query_params={"leave_view": "file"},
    ),
    DefaultFAQ(
        question="Where can I check my leave balance and leave-request status?",
        answer=(
            "My Leave Overview shows your credits and utilization. My Requests "
            "shows each submitted request, approval stage, status, and available "
            "cancellation action."
        ),
        link_label="Open My Requests",
        page="Leave Management",
        query_params={"leave_view": "requests"},
    ),
    DefaultFAQ(
        question="How do I download and submit a company form?",
        answer=(
            "Use Download to obtain the editable form, then open Fill / Submit "
            "to upload the completed copy when submissions are allowed. My "
            "Documents contains the copies you submitted to administrators."
        ),
        link_label="Open Download Form",
        page="Company Form/Documents",
        query_params={"form_view": "download"},
    ),
    DefaultFAQ(
        question="Where can I read company policies?",
        answer=(
            "Open Company Policies to search and read the currently published "
            "policy versions approved by your company."
        ),
        link_label="Open Company Policies",
        page="Company Policies",
    ),
    DefaultFAQ(
        question="Where can I track onboarding and review my benefits?",
        answer=(
            "Open Onboarding for your progress Overview and Checklist. The Benefits "
            "tab contains the active company benefits, eligibility, instructions, "
            "and contact information published by your administrator."
        ),
        link_label="Open Onboarding Benefits",
        page="Onboarding",
        query_params={"onboarding_view": "benefits"},
    ),
    DefaultFAQ(
        question="Where can I find company announcements?",
        answer=(
            "Open the Announcements workspace on the Dashboard to view published "
            "company updates. Unread announcements remain reflected in the "
            "notification count until opened or marked as read."
        ),
        link_label="Open Announcements",
        page="Dashboard",
        query_params={"dashboard_view": "announcements"},
    ),
    DefaultFAQ(
        question="How do I generate my own DTR, overtime, and leave files?",
        answer=(
            "Open Reports, select a report period, and download the combined Excel "
            "workbook. It contains DTR Logs, Overtime File, and Leave File sheets "
            "for your employee record only."
        ),
        link_label="Open My Reports",
        page="Reports",
    ),
    DefaultFAQ(
        question="Where can I find HR contact information?",
        answer=(
            "Open HR Contacts for the company-provided HR contact details and "
            "available support channels."
        ),
        link_label="Open HR Contacts",
        page="HR Contacts",
    ),
)


def _open_faq_destination(item: DefaultFAQ) -> None:
    """Open the FAQ item's exact authorized employee workspace."""

    if item.page is None:
        return

    for key in {
        "announcement_id",
        "employee_id",
        "leave_request_id",
        "policy_id",
    } | EXACT_VIEW_QUERY_KEYS:
        if key in st.query_params:
            del st.query_params[key]

    prime_exact_module_view(
        portal_mode="employee",
        page=item.page,
        query_params=item.query_params,
    )
    set_navigation_state(
        portal_mode="employee",
        current_page=item.page,
    )
    for key, value in item.query_params.items():
        st.query_params[key] = value
    st.rerun()


def render_employee_faq_page(
    current_user: AuthenticatedUser,
) -> None:
    """Render default FAQs with direct answers and exact internal links."""

    st.title("Frequently Asked Questions")
    st.caption(
        "Find direct answers to common employee portal questions. Use the "
        "related button when an exact workspace is available."
    )

    for index, item in enumerate(DEFAULT_FAQS):
        with st.expander(item.question):
            st.write(item.answer)
            if item.link_label and item.page:
                if st.button(
                    item.link_label,
                    width="stretch",
                    key=(
                        "employee_default_faq_"
                        f"{current_user.company_id}_{current_user.user_id}_{index}"
                    ),
                ):
                    _open_faq_destination(item)
