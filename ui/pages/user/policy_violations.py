"""Employee read-only browser for active company violation rules."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from database.session import SessionFactory
from services.policy_service import PolicyService
from services.policy_violation_service import PolicyViolationService, VIOLATION_SEVERITIES
from ui.components.live_search import multi_search_input
from utils.search_utils import matches_search_terms


def render_employee_policy_violations(
    current_user: AuthenticatedUser,
) -> None:
    """Show only active, effective, non-archived company violation rules."""

    st.subheader("Violations & Disciplinary Actions")
    st.caption(
        "Read-only company violation/offense rules and their configured "
        "disciplinary actions. Individual employee disciplinary records are not "
        "shown here."
    )

    today = datetime.now(ZoneInfo(get_settings().display_timezone)).date()
    with SessionFactory() as session:
        violation_service = PolicyViolationService(session)
        items = violation_service.list_employee_visible(
            company_id=current_user.company_id,
            as_of_date=today,
        )
        published_policies = PolicyService(session).list_published(
            current_user.company_id
        )
    policy_labels = {
        policy.id: f"{policy.title} · v{policy.version}"
        for policy in published_policies
    }

    categories = sorted({item.category for item in items})
    search = multi_search_input(
        "Search Violations",
        placeholder="Type code, violation, category, severity, or action, then press Enter…",
        key="employee_policy_violation_search"
    )
    cols = st.columns(2)
    with cols[0]:
        category = st.selectbox(
            "Category",
            ["All Categories", *categories],
            key="employee_policy_violation_category",
        )
    with cols[1]:
        severity = st.selectbox(
            "Severity",
            ["All Severities", *VIOLATION_SEVERITIES],
            key="employee_policy_violation_severity",
        )

    filtered = []
    for item in items:
        if category != "All Categories" and item.category != category:
            continue
        if severity != "All Severities" and item.severity != severity:
            continue
        related_policy = (
            policy_labels.get(item.related_policy_id, "Unavailable / not linked")
            if item.related_policy_id else "Not linked"
        )
        visible_values = (
            item.violation_code, item.offense_title, item.severity, item.category,
            item.effective_date.isoformat() if item.effective_date else "Immediate",
            related_policy, item.description, item.first_offense_action,
            item.second_offense_action, item.third_offense_action, item.final_action,
            item.notes or "",
        )
        if matches_search_terms(search, visible_values):
            filtered.append(item)

    st.caption(f"{len(filtered)} of {len(items)} active violation rule(s) shown.")
    if not filtered:
        st.info("No matching active violation rules were found.")
        return

    for item in filtered:
        with st.expander(
            f"{item.violation_code} · {item.offense_title} · {item.severity}"
        ):
            related_policy = (
                policy_labels.get(item.related_policy_id, "Unavailable / not linked")
                if item.related_policy_id
                else "Not linked"
            )
            st.caption(
                f"Category: {item.category} · "
                f"Effective: {item.effective_date.isoformat() if item.effective_date else 'Immediate'} · "
                f"Related Policy: {related_policy}"
            )
            st.markdown(f"**Description:** {item.description}")
            st.markdown(
                "\n".join(
                    [
                        "**Disciplinary Actions**",
                        f"1. **1st Offense:** {item.first_offense_action}",
                        f"2. **2nd Offense:** {item.second_offense_action}",
                        f"3. **3rd Offense:** {item.third_offense_action}",
                        f"4. **Final / Maximum Action:** {item.final_action}",
                    ]
                )
            )
            if item.notes:
                st.markdown(f"**Notes:** {item.notes}")
