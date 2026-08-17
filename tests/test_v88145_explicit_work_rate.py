"""Regression coverage for the approved v8.8.145 Work Rate formula."""

from decimal import Decimal
from pathlib import Path

from services.attendance_calculations import calculate_work_rate


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_work_rate_uses_total_hours_workdays_and_eight_paid_hours() -> None:
    assert calculate_work_rate(160, 20, 8) == Decimal("100.00")
    assert calculate_work_rate(152, 20, 8) == Decimal("95.00")


def test_work_rate_has_no_one_hundred_percent_cap() -> None:
    assert calculate_work_rate(168, 20, 8) == Decimal("105.00")


def test_work_rate_handles_empty_calendar_safely() -> None:
    assert calculate_work_rate(8, 0, 8) == Decimal("0.00")
    assert calculate_work_rate(8, 1, 0) == Decimal("0.00")


def test_service_uses_saved_monthly_workdays_without_leave_credit() -> None:
    source = (PROJECT_ROOT / "services/attendance_service.py").read_text(
        encoding="utf-8"
    )
    assert "matrix.scheduled_workdays.get(day, day.weekday() < 5)" in source
    assert "calculate_work_rate(" in source
    assert "total_hours=total_hours" in source
    assert "total_workdays=total_working_days" in source
    assert "regular_paid_hours_per_day=company.attendance_regular_hours" in source


def test_release_keeps_deprecated_streamlit_calls_out() -> None:
    production_files = [
        path
        for path in PROJECT_ROOT.rglob("*.py")
        if "tests" not in path.parts
        and ".venv" not in path.parts
        and "venv" not in path.parts
    ]
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in production_files
    )
    assert "st.components.v1.html" not in source
    assert "components.html" not in source
    assert "use_container_width" not in source
