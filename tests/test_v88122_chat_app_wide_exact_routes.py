"""Ephemeral welcome, exact routes, and app-wide assistant regression tests."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_welcome_is_display_only_and_disappears_after_first_message() -> None:
    for relative_path in (
        "ui/pages/admin/chat_page.py",
        "ui/pages/user/chat_page.py",
    ):
        source = _source(relative_path)
        initial = source.split("def _initial_messages", 1)[1].split(
            "def render_", 1
        )[0]
        assert "return []" in initial
        assert "Good day, how can I assist you today?" in source
        assert "if not messages:" in source
        assert 'messages[0].get("intent") == "welcome"' in source


def test_v88122_controlled_arrow_change_remains_documented() -> None:
    readme = _source("README.md")

    checkpoint = readme.split(
        "## v8.8.122 — Ephemeral Welcome, Exact Routes, and App-Wide Answers",
        1,
    )[1].split("## v8.8.123", 1)[0]
    assert "controlled white `↑`" in checkpoint


def test_quick_actions_use_exact_module_view_parameters() -> None:
    quick_actions = _source("ui/components/quick_actions.py")
    routes = _source("ui/module_view_navigation.py")

    assert '{"leave_view": "requests"}' in quick_actions
    assert '{"policy_view": "manage"}' in quick_actions
    assert '{"announcement_view": "create"}' in quick_actions
    assert '{"employee_view": "list"}' in quick_actions
    assert '"requests": "Leave Requests"' in routes
    assert '"manage": "Manage Existing Policy"' in routes
    assert '"create": "Create Announcement"' in routes


def test_native_admin_pages_have_stateful_exact_route_tabs() -> None:
    leave = _source("ui/pages/admin/leave_management_page.py")
    announcements = _source("ui/pages/admin/announcements_page.py")

    assert 'key="admin_leave_management_active_tab"' in leave
    assert 'key="announcements_active_tab"' in announcements


def test_company_scoped_leave_credit_comparisons_use_live_balances() -> None:
    admin = _source("modules/hr_assistant/admin_hr_assistant.py")

    assert "def _leave_credit_ranking" in admin
    assert "list_company_balances" in admin
    assert '"pinakamataas"' in admin
    assert 'query_params={"leave_view": "accounts"}' in admin


def test_admin_and_employee_cover_attendance_and_company_forms() -> None:
    admin = _source("modules/hr_assistant/admin_hr_assistant.py")
    employee = _source("modules/hr_assistant/hr_assistant.py")
    smart_ai = _source("modules/smart_ai/portal_ai.py")

    for source in (admin, employee):
        assert 'return "attendance"' in source
        assert 'return "company_forms"' in source
    assert "App-wide answer boundary" in smart_ai
    assert "must not use outside knowledge" in smart_ai


def test_v88122_checkpoint_is_documented() -> None:
    readme = _source("README.md")

    assert "v8.8.122 — Ephemeral Welcome, Exact Routes" in readme
