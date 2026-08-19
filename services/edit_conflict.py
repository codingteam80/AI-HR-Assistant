"""Friendly optimistic edit-conflict details shared by Admin forms."""

from datetime import datetime
from typing import Any


class EditConflictError(ValueError):
    """Raised when an administrator submits an older form version."""

    def __init__(
        self,
        *,
        module: str,
        entity_label: str,
        latest_version: int,
        latest_values: dict[str, Any],
        updated_by: str,
        updated_at: datetime | None,
    ) -> None:
        self.module = module
        self.entity_label = entity_label
        self.latest_version = latest_version
        self.latest_values = latest_values
        self.updated_by = updated_by
        self.updated_at = updated_at
        timestamp = (
            updated_at.strftime("%B %d, %Y at %I:%M %p")
            if updated_at is not None
            else "an earlier time"
        )
        super().__init__(
            f"This record was updated by {updated_by} on {timestamp}. "
            "Review the latest information before saving again."
        )

