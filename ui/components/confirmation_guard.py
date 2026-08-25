"""Reusable confirmation-state invalidation for Streamlit workflows.

A confirmation/review checkbox is evidence that the user reviewed a specific
set of values. If any of those values changes, the old confirmation is no
longer valid and must be cleared before the action can continue.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any, Mapping, Sequence

import streamlit as st


def _json_safe(value: Any) -> Any:
    """Return a deterministic JSON-safe representation for dependency values."""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def dependency_fingerprint(values: Mapping[str, Any] | Sequence[Any] | Any) -> str:
    """Create a stable fingerprint for values covered by one confirmation."""

    payload = json.dumps(
        _json_safe(values),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def invalidate_confirmation_on_change(
    *,
    confirmation_key: str,
    dependencies: Mapping[str, Any] | Sequence[Any] | Any,
    tracker_key: str | None = None,
) -> bool:
    """Clear a confirmation checkbox when any covered value changed.

    Call this *before* rendering the checkbox using ``confirmation_key``.
    Returns ``True`` only when a previously tracked dependency fingerprint
    changed during the current rerun.
    """

    fingerprint_key = tracker_key or f"__confirmation_dependencies__{confirmation_key}"
    current = dependency_fingerprint(dependencies)
    previous = st.session_state.get(fingerprint_key)
    changed = previous is not None and previous != current

    if changed:
        # Safe because callers invoke this before the checkbox is instantiated
        # in the current Streamlit run.
        st.session_state[confirmation_key] = False

    st.session_state[fingerprint_key] = current
    return changed


def clear_confirmation_tracking(confirmation_key: str, *, tracker_key: str | None = None) -> None:
    """Clear both the checkbox state and its dependency tracker."""

    fingerprint_key = tracker_key or f"__confirmation_dependencies__{confirmation_key}"
    st.session_state.pop(confirmation_key, None)
    st.session_state.pop(fingerprint_key, None)
