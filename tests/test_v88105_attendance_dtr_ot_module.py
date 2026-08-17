"""Regression checks for the v8.8.105 Attendance/DTR/OT checkpoint."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_attendance_hour_rules_cover_regular_and_rest_days() -> None:
    module = runpy.run_path(str(ROOT / "services/attendance_calculations.py"))
    calculate = module["calculate_attendance_hours"]
    start = datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    assert calculate(
        start, end, scheduled_workday=True,
        regular_hours=Decimal("8"), lunch_break_minutes=60,
    ) == (Decimal("9.00"), Decimal("1.00"))
    assert calculate(
        start, end, scheduled_workday=False,
        regular_hours=Decimal("8"), lunch_break_minutes=60,
    ) == (Decimal("9.00"), Decimal("9.00"))


def test_monthly_table_has_required_colors_and_columns() -> None:
    source = _source("ui/components/attendance_table.py")
    assert "Employee Name" in source
    assert "%Y/%m/%d" in source
    service = _source("services/attendance_service.py")
    assert '"WFO": "#FFCC99"' in service
    assert '"WFH": "#92D050"' in service
    assert '"VL": "#FFCCFF"' in service
    assert 'WEEKEND_COLOR = "#BFBFBF"' in service


def test_employee_visibility_and_self_punch_security_are_explicit() -> None:
    source = _source("services/attendance_service.py")
    assert "employee.user_id != user_id" in source
    assert "Employee.manager_id == employee_id" in source
    assert "Employee.leader_id == employee_id" in source
    assert "AttendanceRecord.company_id == company_id" in _source(
        "repositories/attendance_repository.py"
    )


def test_leave_sync_admin_correction_and_reports_are_available() -> None:
    service = _source("services/attendance_service.py")
    assert 'status_source = "approved_leave"' in service
    assert "AttendanceCorrection(" in service
    assert "previous_values_json" in service
    admin = _source("ui/pages/admin/attendance_dashboard.py")
    assert "Download Excel" in admin
    assert "Download PDF" in admin
    assert "Admin Attendance Correction" in admin


def test_company_schedule_and_runtime_upgrade_are_included() -> None:
    company = _source("models/company.py")
    schema = _source("database/schema_upgrade.py")
    for field in (
        "attendance_regular_hours", "attendance_lunch_minutes",
        "work_monday", "work_saturday", "work_sunday",
    ):
        assert field in company
        assert field in schema
    assert 'app_version: str = "0.8.8.' in _source("config/settings.py")
