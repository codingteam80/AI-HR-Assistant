"""Administrator-wide immutable Audit Trail workspace."""

from datetime import datetime
import json

import streamlit as st

from authentication.current_user import AuthenticatedUser
from database.session import SessionFactory
from services.audit_trail_service import AuditTrailEntry, AuditTrailService
from ui.components.data_table import render_admin_table
from ui.components.live_search import live_search_input


def _display_datetime(value: datetime) -> str:
    """Return the project's established readable audit timestamp."""

    return value.strftime("%Y-%m-%d %I:%M:%S %p")


def _json_values(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"Details": value}
    return parsed if isinstance(parsed, dict) else {"Details": parsed}


def _change_text(entry: AuditTrailEntry) -> str:
    """Format old-to-new values for search and the details panel."""

    old_values = _json_values(entry.old_values_json)
    new_values = _json_values(entry.new_values_json)
    keys = list(dict.fromkeys([*old_values, *new_values]))
    if not keys:
        return "N/A"
    return "\n".join(
        f"{key.replace('_', ' ').title()}: "
        f"{old_values.get(key, 'N/A')} → {new_values.get(key, 'N/A')}"
        for key in keys
    )


def _searchable(entry: AuditTrailEntry) -> str:
    return " ".join(
        str(value or "")
        for value in (
            entry.event_id,
            entry.module,
            entry.actor_label,
            entry.action,
            entry.entity,
            entry.result,
            entry.summary,
            _change_text(entry),
            entry.metadata_json,
            _display_datetime(entry.occurred_at),
        )
    ).casefold()


def _render_details(entry: AuditTrailEntry) -> None:
    """Show one complete immutable event without exposing secrets."""

    st.markdown("### Audit Event Details")
    metadata = _json_values(entry.metadata_json)
    summary_rows = [
        {
            "Event ID": entry.event_id,
            "Date / Time": _display_datetime(entry.occurred_at),
            "Administrator": entry.actor_label,
            "Module": entry.module,
            "Action": entry.action,
            "Result": entry.result.replace("_", " ").title(),
            "Affected Record": entry.entity,
            "Summary": entry.summary,
        }
    ]
    render_admin_table(
        summary_rows,
        key=f"audit-event-summary-{entry.event_id}",
        min_width=1500,
        column_widths=(
            "110px",
            "180px",
            "180px",
            "150px",
            "135px",
            "145px",
            "270px",
            "330px",
        ),
        compact=True,
    )

    old_values = _json_values(entry.old_values_json)
    new_values = _json_values(entry.new_values_json)
    keys = list(dict.fromkeys([*old_values, *new_values]))
    if keys:
        st.markdown("#### Before / After")
        render_admin_table(
            [
                {
                    "Field": key.replace("_", " ").title(),
                    "Before": old_values.get(key, "N/A"),
                    "After": new_values.get(key, "N/A"),
                }
                for key in keys
            ],
            key=f"audit-event-changes-{entry.event_id}",
            min_width=900,
            column_widths=("240px", "330px", "330px"),
            compact=True,
            max_height=360,
        )

    if metadata:
        st.markdown("#### Additional Details")
        render_admin_table(
            [
                {
                    "Detail": key.replace("_", " ").title(),
                    "Value": value,
                }
                for key, value in metadata.items()
                if value not in (None, "")
            ],
            key=f"audit-event-metadata-{entry.event_id}",
            min_width=760,
            column_widths=("260px", "500px"),
            compact=True,
        )


def render_audit_trail_page(current_user: AuthenticatedUser) -> None:
    """Render central searchable history for every Admin workspace."""

    st.title("Audit Trail")
    st.caption(
        "Review company-wide administrator actions, affected records, "
        "before/after values, and blocked edit conflicts. Existing module "
        "History tabs remain available as filtered workspace views."
    )

    with SessionFactory() as session:
        entries = AuditTrailService(session).list_entries(
            current_user.company_id
        )

    total_count = len(entries)
    successful_count = sum(
        1 for item in entries if item.result == "successful"
    )
    conflict_count = sum(
        1 for item in entries if item.result == "conflict_blocked"
    )
    actor_count = len(
        {
            item.actor_user_id
            for item in entries
            if item.actor_user_id is not None
        }
    )
    total_column, success_column, conflict_column, actor_column = st.columns(4)
    total_column.metric("Audit Events", total_count)
    success_column.metric("Successful", successful_count)
    conflict_column.metric("Conflicts Blocked", conflict_count)
    actor_column.metric("Administrator Accounts", actor_count)

    module_options = ["All Modules", *sorted({item.module for item in entries})]
    result_options = [
        "All Results",
        *sorted({item.result.replace("_", " ").title() for item in entries}),
    ]
    action_options = ["All Actions", *sorted({item.action for item in entries})]
    module_column, result_column, action_column = st.columns(3)
    with module_column:
        selected_module = st.selectbox(
            "Module",
            module_options,
            key="audit_trail_module_filter",
        )
    with result_column:
        selected_result = st.selectbox(
            "Result",
            result_options,
            key="audit_trail_result_filter",
        )
    with action_column:
        selected_action = st.selectbox(
            "Action",
            action_options,
            key="audit_trail_action_filter",
        )

    search_text = live_search_input(
        "Search Audit Trail",
        placeholder=(
            "Search any event, administrator, module, action, result, "
            "record, field, value, or date…"
        ),
        key="audit_trail_search",
        suggestions=(
            value
            for item in entries
            for value in (
                item.event_id,
                item.module,
                item.actor_label,
                item.action,
                item.entity,
                item.result.replace("_", " ").title(),
            )
        ),
    )
    normalized_search = search_text.strip().casefold()
    normalized_result = selected_result.casefold().replace(" ", "_")
    filtered = [
        item
        for item in entries
        if (
            (selected_module == "All Modules" or item.module == selected_module)
            and (
                selected_result == "All Results"
                or item.result.casefold() == normalized_result
            )
            and (selected_action == "All Actions" or item.action == selected_action)
            and (not normalized_search or normalized_search in _searchable(item))
        )
    ]

    st.caption(f"Showing {len(filtered)} of {len(entries)} audit event(s).")
    if not filtered:
        st.info("No audit event matches the current filters.")
        return

    render_admin_table(
        [
            {
                "Event ID": item.event_id,
                "Date / Time": _display_datetime(item.occurred_at),
                "Administrator": item.actor_label,
                "Module": item.module,
                "Action": item.action,
                "Result": item.result.replace("_", " ").title(),
                "Affected Record": item.entity,
                "Summary": item.summary,
            }
            for item in filtered
        ],
        key="central-audit-trail",
        min_width=1800,
        column_widths=(
            "110px",
            "185px",
            "190px",
            "165px",
            "145px",
            "155px",
            "330px",
            "520px",
        ),
        max_height=510,
    )

    event_options = {
        (
            f"{item.event_id} · {_display_datetime(item.occurred_at)} · "
            f"{item.actor_label} · {item.action}"
        ): item
        for item in filtered
    }
    selected_label = st.selectbox(
        "Review Audit Event",
        options=list(event_options),
        key="audit_trail_selected_event",
    )
    _render_details(event_options[selected_label])
