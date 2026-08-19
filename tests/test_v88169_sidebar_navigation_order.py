"""Regression checks for v8.8.169 portal sidebar navigation order."""

from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _tuple_assignment(source: str, name: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                value = ast.literal_eval(node.value)
                return tuple(value)
    raise AssertionError(f"{name} assignment was not found")


def test_admin_sidebar_exact_requested_order() -> None:
    actual = _tuple_assignment(_read("ui/components/admin_sidebar.py"), "ADMIN_NAVIGATION")
    assert actual == (
        "Admin Dashboard",
        "Chat Assistant",
        "Attendance Hub",
        "Leave Management",
        "Employees",
        "Reports",
        "Announcements",
        "Company Form/Documents",
        "Policies",
        "Company Profile",
        "External Notifications",
        "Audit Trail",
    )


def test_employee_sidebar_exact_requested_order() -> None:
    actual = _tuple_assignment(_read("core/constants.py"), "USER_NAVIGATION")
    assert actual == (
        "Dashboard",
        "Chat Assistant",
        "Attendance Hub",
        "Leave Management",
        "Reports",
        "Company Form/Documents",
        "Company Policies",
        "Onboarding",
        "HR Contacts",
        "FAQ",
    )


def test_sidebar_account_actions_and_divider_are_unchanged() -> None:
    admin = _read("ui/components/admin_sidebar.py")
    employee = _read("ui/components/sidebar.py")
    assert "hr-admin-account-divider" in admin
    assert '"Employee Portal"' in admin
    assert '"Log Out"' in admin
    assert '"Admin Portal"' in employee
    assert '"Log Out"' in employee


def test_v88169_version_is_current() -> None:
    settings = _read("config/settings.py")
    env = _read(".env.example")
    assert 'app_version: str = "0.8.8.169"' in settings
    assert "APP_VERSION=0.8.8.169" in env
