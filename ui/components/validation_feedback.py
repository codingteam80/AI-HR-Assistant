"""Readable warning messages for expected form and action failures."""

from __future__ import annotations

import re
from collections.abc import Iterable

import streamlit as st
from pydantic import ValidationError


_TECHNICAL_LINE_PREFIXES = (
    "for further information visit",
    "input_value=",
    "input_type=",
    "traceback",
    "file \"",
)

_MESSAGE_OVERRIDES = {
    "Only the final attendance session may remain open.": (
        "Complete the Time Out for every attendance session before the final "
        "session. Only the final session may remain open."
    ),
    "Attendance sessions cannot overlap.": (
        "Adjust the Time In and Time Out values so attendance sessions do not overlap."
    ),
}


def _field_label(location: Iterable[object]) -> str:
    """Convert a Pydantic location into a short user-facing field label."""

    parts = list(location)
    if not parts or parts in (["__root__"], ["root"]):
        return ""
    labels: list[str] = []
    for index, part in enumerate(parts):
        if part in {"__root__", "root"}:
            continue
        if isinstance(part, int):
            if labels and labels[-1] == "Sessions":
                labels[-1] = f"Session {part + 1}"
            else:
                labels.append(f"Item {part + 1}")
            continue
        label = str(part).replace("_", " ").strip().title()
        if label:
            labels.append(label)
    return " / ".join(labels)


def _clean_message(value: object) -> str:
    """Remove Pydantic prefixes, URLs, and internal diagnostic fragments."""

    raw = str(value or "").strip()
    raw = re.sub(r"^Value error,\s*", "", raw, flags=re.IGNORECASE)
    lines = []
    for line in raw.splitlines():
        cleaned = line.strip()
        lowered = cleaned.casefold()
        if not cleaned or lowered.startswith(_TECHNICAL_LINE_PREFIXES):
            continue
        if re.match(r"^\d+ validation errors? for\b", lowered):
            continue
        cleaned = re.sub(r"https?://\S+", "", cleaned).strip()
        if "[type=" in cleaned or "input_value=" in cleaned:
            continue
        lines.append(cleaned)
    message = " ".join(lines).strip()
    message = _MESSAGE_OVERRIDES.get(message, message)
    return message[:800]


def action_warning_messages(error: Exception) -> list[str]:
    """Return de-duplicated, input-safe messages for an expected exception."""

    messages: list[str] = []
    if isinstance(error, ValidationError):
        for detail in error.errors(include_url=False, include_input=False):
            message = _clean_message(detail.get("msg", ""))
            if not message:
                continue
            field = _field_label(detail.get("loc", ()))
            rendered = f"{field}: {message}" if field else message
            if rendered not in messages:
                messages.append(rendered)
    elif isinstance(error, FileNotFoundError):
        messages.append(
            "The requested file is unavailable. Refresh the page or contact an administrator."
        )
    elif error.__class__.__name__ == "EmailDeliveryError":
        messages.append(
            "The email could not be sent. Check the email integration settings and try again."
        )
    else:
        message = _clean_message(error)
        if message:
            messages.append(message)

    return messages or [
        "The supplied information could not be accepted. Review the fields and try again."
    ]


def render_action_warning(
    error: Exception,
    *,
    heading: str = "Unable to complete this action. Please review the following:",
) -> None:
    """Render expected validation/service failures without technical details."""

    messages = action_warning_messages(error)
    bullets = "\n".join(f"- {message}" for message in messages)
    st.warning(f"{heading}\n\n{bullets}")
