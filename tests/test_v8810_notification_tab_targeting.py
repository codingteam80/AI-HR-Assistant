"""Notification links select the correct tab and request record."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_admin_notification_keeps_full_leave_workspace() -> None:
    source = (ROOT / "ui/pages/admin/leave_management_page.py").read_text(encoding="utf-8")
    assert "overview_tab, accounts_tab, requests_tab, rules_tab = st.tabs(" in source
    assert "selected_request_id=notification_request_id" in source
    assert '_activate_leave_tab("Leave Requests")' in source
    assert "Leave Requests / Specific Request" not in source
    assert "Back to All Leave Requests" not in source


def test_admin_request_selector_targets_notification_record() -> None:
    source = (ROOT / "ui/pages/admin/leave_management_page.py").read_text(encoding="utf-8")
    assert "st.session_state[selector_key] = selected_request_id" in source
    assert "inside the Leave Requests tab" in source
    assert 'f"leave_request_department_{year}"' in source
    assert 'f"leave_request_employee_search_{year}"' in source


def test_notification_year_matches_related_request() -> None:
    source = (ROOT / "ui/pages/admin/leave_management_page.py").read_text(encoding="utf-8")
    assert "def _notification_request_year(" in source
    assert "request.start_date.year" in source
    assert 'st.session_state["leave_management_year"]' in source


def test_employee_notification_selects_correct_tab() -> None:
    source = (ROOT / "ui/pages/user/leave_management_page.py").read_text(encoding="utf-8")
    assert '"requests": "My Requests"' in source
    assert '"pending": "Pending Approvals"' in source
    assert '"reviewed": "Reviewed Requests"' in source
    assert "_activate_employee_leave_tab(target_label)" in source
    assert 'key="employee_leave_management_active_tab"' in source
