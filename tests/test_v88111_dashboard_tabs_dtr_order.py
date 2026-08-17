"""Regression checks for the v8.8.111 employee Dashboard refinement."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_extra_dashboard_introduction_is_removed() -> None:
    dashboard = _source("ui/pages/user/dashboard_page.py")

    assert "View and maintain your attendance record" not in dashboard
    assert "separate Announcements workspace" not in dashboard


def test_announcements_are_a_persistent_dashboard_subtab() -> None:
    constants = _source("core/constants.py")
    dashboard = _source("ui/pages/user/dashboard_page.py")
    sidebar = _source("ui/components/sidebar.py")
    announcements = _source("ui/pages/user/announcements_page.py")

    navigation = constants.split("USER_NAVIGATION = (", 1)[1].split(")", 1)[0]
    assert '"Announcements"' not in navigation
    assert "nav_Announcements" not in sidebar
    assert "st.tabs(" in dashboard
    assert 'on_change="rerun"' in dashboard
    assert 'options = ("Dashboard", "Announcements")' in dashboard
    assert "employeeAnnouncementTabShake" in dashboard
    assert "load_employee_announcement_state" in dashboard
    assert "mark_announcements_read" in announcements


def test_monthly_table_appears_before_attendance_editor() -> None:
    attendance = _source("ui/pages/user/attendance_workspace.py")

    filter_position = attendance.index("filter_columns = st.columns(2)")
    matrix_position = attendance.index("render_attendance_matrix(")
    editor_position = attendance.index(
        'with st.expander("Edit Attendance Record", expanded=True):'
    )
    assert filter_position < matrix_position < editor_position


def test_announcement_notification_opens_dashboard_tab() -> None:
    topbar = _source("ui/components/topbar.py")
    layout = _source("ui/layouts/user_layout.py")

    assert 'return "employee", "Dashboard"' in topbar
    assert '"employee_dashboard_active_tab"' in topbar
    assert '"employee_dashboard_active_tab"' in layout
    assert 'st.query_params["page"] = "Dashboard"' in layout


def test_checkpoint_keeps_v88111_release_notes() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.111 — Dashboard Tabs and DTR Layout Polish" in readme
