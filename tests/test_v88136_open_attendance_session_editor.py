"""Regression checks for Attendance/DTR records without a Time Out."""

from datetime import datetime, time
from pathlib import Path

from ui.components.attendance_editor_utils import attendance_editor_clock


ROOT = Path(__file__).resolve().parents[1]

def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_missing_timestamp_uses_display_fallback_without_crashing() -> None:
    fallback = datetime(2026, 8, 13, 14, 37)
    assert attendance_editor_clock(None, fallback=fallback) == time(14, 37)


def test_existing_timestamp_remains_the_display_value() -> None:
    existing = datetime(2026, 8, 13, 17, 15)
    fallback = datetime(2026, 8, 13, 18, 0)
    assert attendance_editor_clock(existing, fallback=fallback) == time(17, 15)


def test_employee_editor_guards_missing_session_timestamps() -> None:
    source = _source("ui/pages/user/attendance_workspace.py")
    assert 'existing and existing["time_in"] is not None' in source
    assert 'existing and existing["time_out"] is not None' in source
    assert '"time_out": session_time_out if has_session_out else None' in source


def test_admin_correction_guards_open_session_time_out() -> None:
    source = _source("ui/pages/admin/attendance_dashboard.py")
    assert 'existing and existing["time_in"] is not None' in source
    assert 'existing and existing["time_out"] is not None' in source
    assert '"time_out": session_out if completed else None' in source


def test_employee_dashboard_tab_has_one_initial_value_source() -> None:
    source = _source("ui/pages/user/dashboard_page.py")
    tab_block = source[source.index("return st.tabs(") :]
    assert "key=_DASHBOARD_TAB_STATE_KEY" in tab_block
    assert "default=" not in tab_block
