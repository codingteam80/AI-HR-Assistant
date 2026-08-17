"""Regression coverage for the reviewed-request manager attribute hotfix."""

from pathlib import Path

from models.leave_request import LeaveRequest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEAVE_PAGE = PROJECT_ROOT / "ui" / "pages" / "user" / "leave_management_page.py"


def test_leave_request_exposes_manager_employee_id_not_manager_id():
    """The ORM model uses the explicit manager_employee_id field."""

    assert hasattr(LeaveRequest, "manager_employee_id")
    assert not hasattr(LeaveRequest, "manager_id")


def test_reviewed_request_detail_uses_the_real_manager_attribute():
    """The employee portal must not access the removed manager_id name."""

    source = LEAVE_PAGE.read_text(encoding="utf-8")

    assert "request.manager_employee_id" in source
    assert "request.manager_id" not in source
