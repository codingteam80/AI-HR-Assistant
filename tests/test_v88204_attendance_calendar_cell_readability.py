"""Regression checks for v8.8.204 attendance calendar cell readability."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_attendance_matrix_uses_requested_date_width_and_middle_alignment() -> None:
    source = _source("ui/components/attendance_table.py")

    assert "ATTENDANCE_DATE_COLUMN_WIDTH = 170" in source
    assert "ATTENDANCE_EMPLOYEE_COLUMN_WIDTH = 190" in source
    assert "width:{ATTENDANCE_DATE_COLUMN_WIDTH}px" in source
    assert "min-width:{ATTENDANCE_DATE_COLUMN_WIDTH}px" in source
    assert "vertical-align:middle" in source
    assert "vertical-align:top" not in source
    assert "overflow:auto" in source


def test_same_shared_matrix_is_used_by_admin_dashboard_hub_and_employee_portal() -> None:
    admin_dashboard = _source("ui/pages/admin/admin_dashboard_page.py")
    admin_hub = _source("ui/pages/admin/attendance_hub_page.py")
    admin_attendance = _source("ui/pages/admin/attendance_dashboard.py")
    employee_dashboard = _source("ui/pages/user/dashboard_page.py")
    employee_hub = _source("ui/pages/user/attendance_hub_page.py")
    employee_workspace = _source("ui/pages/user/attendance_workspace.py")

    assert "render_admin_attendance_dashboard(" in admin_dashboard
    assert "render_admin_attendance_dashboard(" in admin_hub
    assert "render_attendance_matrix(" in admin_attendance
    assert "render_employee_attendance_workspace(" in employee_dashboard
    assert "render_employee_attendance_workspace(" in employee_hub
    assert "render_attendance_matrix(" in employee_workspace


def test_v88204_version_marker_is_consistent() -> None:
    settings = _source("config/settings.py")
    env_example = _source(".env.example")

    assert 'app_version: str = "0.8.8.204"' in settings
    assert "APP_VERSION=0.8.8.204" in env_example
