"""Automatic, transaction-safe audit capture for administrator writes."""

from datetime import date, datetime, time
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from services.audit_context import get_audit_actor


_INSTALLED = False

# Employee Master Record actions already have a purpose-built immutable
# EmployeeHistory row. They are merged into the central Audit Trail page,
# which avoids duplicate entries while retaining the richer summaries.
_EXCLUDED_TABLES = {
    "audit_events",
    "employee_history",
    "employees",
    "employee_trainings",
    "users",
    "auth_sessions",
    "auth_session_navigation",
    "auth_session_preferences",
    "password_reset_tokens",
}

_SENSITIVE_FRAGMENTS = {
    "password",
    "secret",
    "token_hash",
    "cookie",
}


def _safe_value(value: Any) -> Any:
    """Return JSON-safe audit data without exposing secret objects."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return str(value)


def _is_sensitive(column_name: str) -> bool:
    normalized = column_name.casefold()
    return any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)


def _new_snapshot(instance) -> dict[str, Any]:
    state = inspect(instance)
    output: dict[str, Any] = {}
    for attribute in state.mapper.column_attrs:
        key = attribute.key
        if _is_sensitive(key):
            continue
        try:
            output[key] = _safe_value(getattr(instance, key))
        except Exception:
            continue
    return output


def _changed_snapshot(instance) -> tuple[dict[str, Any], dict[str, Any]]:
    state = inspect(instance)
    old_values: dict[str, Any] = {}
    new_values: dict[str, Any] = {}
    for attribute in state.mapper.column_attrs:
        key = attribute.key
        if _is_sensitive(key):
            continue
        history = state.attrs[key].history
        if not history.has_changes():
            continue
        old_values[key] = _safe_value(
            history.deleted[0] if history.deleted else None
        )
        new_values[key] = _safe_value(
            history.added[0]
            if history.added
            else getattr(instance, key, None)
        )
    return old_values, new_values


def _entity_label(instance) -> str | None:
    for attribute in (
        "public_id",
        "employee_number",
        "title",
        "name",
        "username",
    ):
        value = getattr(instance, attribute, None)
        if value not in (None, ""):
            return str(value)[:350]
    return None


def _stage_event(
    session: Session,
    *,
    instance,
    action: str,
    old_values: dict[str, Any] | None,
    new_values: dict[str, Any] | None,
) -> None:
    actor = get_audit_actor()
    if actor is None:
        return

    table_name = getattr(getattr(instance, "__table__", None), "name", "")
    if not table_name or table_name in _EXCLUDED_TABLES:
        return

    company_id = getattr(instance, "company_id", None)
    if company_id is None or int(company_id) != actor.company_id:
        return

    from models.audit_event import AuditEvent

    entity_type = type(instance).__name__
    entity_id = getattr(instance, "id", None)
    label = _entity_label(instance)
    readable_entity = entity_type.replace("_", " ")
    session.add(
        AuditEvent(
            company_id=actor.company_id,
            actor_user_id=actor.user_id,
            module=actor.module,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            entity_label=label,
            result="successful",
            summary=(
                f"{readable_entity} {action.lower()} successfully"
                + (f": {label}" if label else ".")
            ),
            old_values_json=(
                json.dumps(old_values, sort_keys=True)
                if old_values
                else None
            ),
            new_values_json=(
                json.dumps(new_values, sort_keys=True)
                if new_values
                else None
            ),
        )
    )


def install_audit_listener() -> None:
    """Install one global ORM listener for successful Admin transactions."""

    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(Session, "before_flush")
    def _capture_admin_changes(session, _flush_context, _instances) -> None:
        if get_audit_actor() is None:
            return

        for instance in list(session.new):
            _stage_event(
                session,
                instance=instance,
                action="Created",
                old_values=None,
                new_values=_new_snapshot(instance),
            )

        for instance in list(session.dirty):
            if not session.is_modified(instance, include_collections=False):
                continue
            old_values, new_values = _changed_snapshot(instance)
            if not old_values and not new_values:
                continue
            _stage_event(
                session,
                instance=instance,
                action="Updated",
                old_values=old_values,
                new_values=new_values,
            )

        for instance in list(session.deleted):
            _stage_event(
                session,
                instance=instance,
                action="Deleted",
                old_values=_new_snapshot(instance),
                new_values=None,
            )

    _INSTALLED = True

