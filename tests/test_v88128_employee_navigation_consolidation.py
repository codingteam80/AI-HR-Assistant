"""v8.8.128 employee sidebar and workspace consolidation checks."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_duplicate_employee_sidebar_items_are_removed() -> None:
    constants = _source("core/constants.py")
    navigation_block = constants.split("USER_NAVIGATION = (", 1)[1].split(
        ")", 1
    )[0]

    assert '"Leave Management"' in navigation_block
    assert '"Company Form/Documents"' in navigation_block
    assert '"My Requests"' not in navigation_block
    assert '"My Documents"' not in navigation_block


def test_submitted_forms_have_a_separate_my_documents_tab() -> None:
    source = _source("ui/pages/user/company_forms_documents_page.py")

    assert (
        'EMPLOYEE_FORM_TABS = ["View", "Download", "Fill / Submit", '
        '"My Documents"]' in source
    )
    assert "def _render_my_documents(" in source
    assert "_render_my_documents(current_user, submissions)" in source
    assert "def _render_fill_submit(\n    current_user: AuthenticatedUser,\n    forms,\n)" in source
    assert 'st.session_state[NEXT_TAB_KEY] = "My Documents"' in source


def test_my_requests_remains_a_stateful_leave_workspace_tab() -> None:
    leave_page = _source("ui/pages/user/leave_management_page.py")
    view_routes = _source("ui/module_view_navigation.py")

    assert 'labels = ["My Leave Overview", "File Leave Request", "My Requests"]' in leave_page
    assert 'key="employee_leave_management_active_tab"' in leave_page
    assert '("employee", "Leave Management")' in view_routes
    assert '"requests": "My Requests"' in view_routes


def test_legacy_sidebar_urls_are_redirected_to_consolidated_tabs() -> None:
    layout = _source("ui/layouts/user_layout.py")

    assert 'current_page == "My Documents"' in layout
    assert 'current_page in {"Leave Management", "My Requests"}' in layout
    assert 'current_page="Company Form/Documents"' in layout
    assert 'current_page="Leave Management"' in layout


def test_links_target_the_correct_form_workspace_view() -> None:
    quick_actions = _source("ui/components/quick_actions.py")
    topbar = _source("ui/components/topbar.py")
    assistant = _source("modules/hr_assistant/hr_assistant.py")
    routes = _source("ui/module_view_navigation.py")

    assert '"Company Form/Documents",\n            {"form_view": "view"}' in quick_actions
    assert '"documents": "My Documents"' in routes
    assert '"employee_company_forms_active_tab"' in topbar
    assert '"My Documents"\n                if "form_submission" in entity' in topbar
    assert 'page="Company Form/Documents"' in assistant
    assert 'query_params={"form_view": "view"}' in assistant
    assert 'page="My Requests"' not in assistant


def test_v88128_remains_the_immediate_report_base() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.133"' in settings
    assert "Immediate base checkpoint: 0.8.8.132" in settings
    assert "v8.8.128 — Employee Navigation Consolidation" in readme
