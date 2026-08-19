"""Regression checks for v8.8.166 compact Employee Portal names."""

from pathlib import Path

from authentication.current_user import AuthenticatedUser


def _user(**overrides):
    values = {
        "user_id": 1,
        "company_id": 1,
        "company_code": "TGS",
        "company_name": "Tsukiden Global Solution Inc.",
        "role_id": 2,
        "role_name": "employee",
        "clearance": 2,
        "username": "lander",
        "email": "lander@example.com",
        "employee_id": 10,
        "employee_number": "90503",
        "employee_name": "Lander Edra Garcia Jr.",
        "must_change_password": False,
        "employee_first_name": "Lander",
        "employee_last_name": "Garcia",
    }
    values.update(overrides)
    return AuthenticatedUser(**values)


def test_employee_portal_display_name_excludes_middle_name_and_suffix():
    user = _user()

    assert user.employee_portal_display_name == "Lander Garcia"
    assert user.employee_name == "Lander Edra Garcia Jr."


def test_compact_name_falls_back_for_older_sessions():
    user = _user(
        employee_first_name=None,
        employee_last_name=None,
    )

    assert user.employee_portal_display_name == "Lander Edra Garcia Jr."


def test_employee_dashboard_uses_compact_portal_name():
    source = Path("ui/pages/user/dashboard_page.py").read_text(encoding="utf-8")

    assert "current_user.employee_portal_display_name" in source
    assert "current_user.employee_name\n        or current_user.username" not in source


def test_employee_topbar_receives_compact_name_without_changing_admin_default():
    user_layout = Path("ui/layouts/user_layout.py").read_text(encoding="utf-8")
    admin_layout = Path("ui/layouts/admin_layout.py").read_text(encoding="utf-8")
    topbar = Path("ui/components/topbar.py").read_text(encoding="utf-8")

    assert "display_name_override=(" in user_layout
    assert "current_user.employee_portal_display_name" in user_layout
    assert "display_name_override" not in admin_layout
    assert "display_name_override: str | None = None" in topbar


def test_internal_version_is_v88166():
    settings = Path("config/settings.py").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.166"' in settings
    assert "APP_VERSION=0.8.8.166" in env_example
