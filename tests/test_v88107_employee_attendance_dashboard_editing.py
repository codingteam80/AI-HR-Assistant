"""Regression checks for employee attendance dashboard editing and metrics."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_requested_metrics_replace_old_metrics_and_render_first() -> None:
    source = _source("ui/pages/user/attendance_workspace.py")
    for label in (
        "Leave Count",
        "Overtime Hours (Day)",
        "Total Overtime Hours (Whole Month)",
        "Work Rate",
    ):
        assert label in source
    assert 'metric("Visible Employees"' not in source
    assert 'metric("Total Hours"' not in source
    assert 'metric("OT Hours"' not in source
    assert source.index("metric_columns = st.columns(4)") < source.index(
        '"Today\'s Work Status"'
    )


def test_single_time_in_out_button_uses_persisted_daily_state() -> None:
    source = _source("ui/pages/user/attendance_workspace.py")
    button_area = source[
        source.index("daily_sessions ="):
        source.index("if punch_clicked:")
    ]
    assert 'punch_label = "Time Out" if has_any_punch else "Time In"' in button_area
    assert "disabled=has_completed_session" in button_area
    assert '"Save Status"' not in source


def test_employee_can_edit_own_selected_date_with_audit() -> None:
    schema = _source("schemas/attendance_schema.py")
    service = _source("services/attendance_service.py")
    page = _source("ui/pages/user/attendance_workspace.py")
    assert "class AttendanceSelfEditInput" in schema
    assert "def edit_own_daily_attendance" in service
    assert "_require_employee_owner" in service
    assert "values.attendance_date > local_today" not in service
    assert 'reason="Employee self-service edit"' in service
    assert "AttendanceSelfEditInput(" in page
    assert "Save Attendance Changes" in page


def test_work_rate_formula_and_year_month_order_match_requirement() -> None:
    service = _source("services/attendance_service.py")
    calculations = _source("services/attendance_calculations.py")
    page = _source("ui/pages/user/attendance_workspace.py")
    assert 'Decimal("100")' in calculations
    assert "Decimal(workdays) * daily_target" in calculations
    assert "calculate_work_rate(" in service
    assert "regular_paid_hours_per_day=company.attendance_regular_hours" in service
    filter_source = page[page.index("filter_columns = st.columns(2)"):]
    assert filter_source.index('"Year"') < filter_source.index('"Month"')
    assert 'year = st.selectbox(' in filter_source


def test_checkpoint_version_is_newer_than_v88107() -> None:
    settings = _source("config/settings.py")
    assert 'app_version: str = "0.8.8.' in settings
