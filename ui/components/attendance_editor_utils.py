"""Small, dependency-free helpers shared by Attendance/DTR editors."""

from datetime import datetime, time


def attendance_editor_clock(
    value: datetime | time | None,
    *,
    fallback: datetime | time,
) -> time:
    """Return a safe clock value for a possibly incomplete attendance punch."""

    selected = value if value is not None else fallback
    return time(selected.hour, selected.minute)

