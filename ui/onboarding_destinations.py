"""Approved employee portal destinations for onboarding links."""

from __future__ import annotations


ONBOARDING_DESTINATIONS: dict[str, tuple[str | None, str | None, str | None]] = {
    "No related workspace": (None, None, None),
    "Dashboard — Attendance": ("Dashboard", "dashboard_view", "attendance"),
    "Attendance Hub": ("Attendance Hub", None, None),
    "Leave Management — Overview": ("Leave Management", "leave_view", "overview"),
    "Leave Management — File Request": ("Leave Management", "leave_view", "file"),
    "Company Forms — View": ("Company Form/Documents", "form_view", "view"),
    "Company Forms — Download": ("Company Form/Documents", "form_view", "download"),
    "Company Forms — Fill / Submit": ("Company Form/Documents", "form_view", "submit"),
    "Company Policies": ("Company Policies", None, None),
    "Onboarding — Checklist": ("Onboarding", "onboarding_view", "checklist"),
    "Onboarding — Benefits": ("Onboarding", "onboarding_view", "benefits"),
    "Reports": ("Reports", None, None),
    "HR Contacts": ("HR Contacts", None, None),
    "FAQ": ("FAQ", None, None),
}


def destination_label(
    page: str | None,
    query_key: str | None,
    query_value: str | None,
) -> str:
    """Return the selectbox label for a stored destination."""

    target = (page, query_key, query_value)
    for label, values in ONBOARDING_DESTINATIONS.items():
        if values == target:
            return label
    return "No related workspace"
