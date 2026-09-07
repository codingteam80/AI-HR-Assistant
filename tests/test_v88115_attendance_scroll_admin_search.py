"""Regression checks for v8.8.115 bounded DTR rows and admin search."""

from pathlib import Path

from ui.components.attendance_table import (
    ATTENDANCE_HEADER_HEIGHT,
    ATTENDANCE_ROW_HEIGHT,
    ATTENDANCE_VIEWPORT_HEIGHT,
    ATTENDANCE_VISIBLE_ROWS,
)


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_monthly_attendance_viewport_shows_seven_rows_then_scrolls() -> None:
    source = _source("ui/components/attendance_table.py")

    assert ATTENDANCE_VISIBLE_ROWS == 7
    assert ATTENDANCE_VIEWPORT_HEIGHT == (
        ATTENDANCE_HEADER_HEIGHT
        + (ATTENDANCE_VISIBLE_ROWS * ATTENDANCE_ROW_HEIGHT)
    )
    assert "overflow:auto" in source
    assert "max-height:{ATTENDANCE_VIEWPORT_HEIGHT}px" in source
    assert "position:sticky; top:0" in source


def test_shared_table_applies_to_admin_manager_and_leader_views() -> None:
    admin = _source("ui/pages/admin/attendance_dashboard.py")
    employee = _source("ui/pages/user/attendance_workspace.py")
    service = _source("services/attendance_service.py")

    assert "render_attendance_matrix(" in admin
    assert "render_attendance_matrix(" in employee
    assert "Employee.manager_id == employee_id" in service
    assert "Employee.leader_id == employee_id" in service


def test_admin_monthly_dtr_has_case_insensitive_employee_search() -> None:
    source = _source("ui/pages/admin/attendance_dashboard.py")

    assert '"Search Employee / Attendance / DTR / OT"' in source
    assert 'key="admin_dtr_employee_search"' in source
    assert "multi_search_input(" in source
    assert "text_matches_search_terms(search_terms, searchable_employee(employee))" in source
    assert "total_employee_count" in source
    assert "employee(s) shown" in source


def test_announcement_description_only_scrolls_vertically() -> None:
    source = _source("ui/components/announcement_description.py")

    assert "white-space: pre-wrap" in source
    assert "overflow-x: hidden" in source
    assert "overflow-y: visible" in source
    assert "overflow-wrap: anywhere" in source


def test_checkpoint_keeps_v88115_release_notes() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert (
        "v8.8.115 — Seven-Row Attendance Views and Admin Search"
        in readme
    )
