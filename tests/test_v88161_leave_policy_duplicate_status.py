"""Regression guards for configurable leave policy and status-only editing."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_company_leave_policy_is_persisted_and_upgraded() -> None:
    model = _source("models/company.py")
    upgrade = _source("database/schema_upgrade.py")
    for field_name in (
        "leave_reset_month",
        "leave_reset_day",
        "leave_utilization_enabled",
        "leave_utilization_percentage",
        "manager_vl_retention_limit",
    ):
        assert field_name in model
        assert field_name in upgrade


def test_leave_rules_expose_company_policy_controls() -> None:
    page = _source("ui/pages/admin/leave_management_page.py")
    assert "Leave Credit Reset Month" in page
    assert "Enable Vacation Leave Utilization" in page
    assert "Required VL Utilization (%)" in page
    assert "Manager Annual VL Retention" in page


def test_employee_duplicate_checks_ignore_case_and_spacing() -> None:
    repository = _source("repositories/employee_repository.py")
    service = _source("services/employee_service.py")
    bulk = _source("services/employee_bulk_import_service.py")
    assert "func.lower(func.trim(Employee.employee_number))" in repository
    assert "find_normalized_name_matches" in service
    assert "_normalized_employee_name" in bulk


def test_status_only_save_is_separate_from_attendance_sessions() -> None:
    service = _source("services/attendance_service.py")
    page = _source("ui/pages/user/attendance_workspace.py")
    assert "def edit_own_work_status" in service
    assert "Save Work Status Only" in page
    assert "preserved_work_status" in service
    assert "AttendanceSessionInput" not in service[
        service.index("def edit_own_work_status") : service.index("def clock_in")
    ]


def test_new_changes_do_not_reintroduce_deprecated_streamlit_apis() -> None:
    for relative_path in (
        "ui/pages/admin/leave_management_page.py",
        "ui/pages/user/attendance_workspace.py",
    ):
        source = _source(relative_path)
        assert "components.html(" not in source
        assert "st.components.v1.html(" not in source
        assert "use_container_width" not in source
