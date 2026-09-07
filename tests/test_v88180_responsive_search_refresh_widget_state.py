"""v8.8.180 responsive search, refresh-safe tabs, and widget-state checks."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_employee_hr_contacts_uses_same_live_search_engine_as_employee_master() -> None:
    contacts = _source("ui/pages/user/hr_contacts_page.py")
    employees = _source("ui/pages/admin/employees_page.py")
    assert "from ui.components.live_search import multi_search_input" in contacts
    assert 'multi_search_input(\n        "Search HR Contacts"' in contacts
    assert 'multi_search_input(\n        "Search Employees"' in employees
    assert 'st.text_input(\n        "Search HR Contacts"' not in contacts


def test_no_portal_page_uses_native_text_input_for_a_literal_search_field() -> None:
    """All actual Search ... fields avoid native text_input and use the shared search component."""

    offenders: list[str] = []
    for path in (ROOT / "ui" / "pages").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "st"
                and func.attr == "text_input"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            if node.args[0].value.strip().casefold().startswith("search"):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_view_preserver_records_clicked_tab_before_streamlit_rerun() -> None:
    source = _source("ui/components/view_state_preservation.py")
    assert "const tabIntentFromEvent = (event) =>" in source
    assert "writeState(true, tabIntentFromEvent(event))" in source
    assert "tabs[tabIntent.group]" in source
    assert "sessionStorage.setItem" in source
    assert 'button[role="tab"]' in source
    assert "requested.label" in source


def test_sidebar_page_refresh_state_still_uses_query_parameters() -> None:
    navigation = _source("ui/navigation_state.py")
    admin_sidebar = _source("ui/components/admin_sidebar.py")
    employee_sidebar = _source("ui/components/sidebar.py")
    assert 'PAGE_QUERY_KEY = "page"' in navigation
    assert 'PORTAL_QUERY_KEY = "portal"' in navigation
    assert "st.query_params[PAGE_QUERY_KEY] = normalized_page" in navigation
    assert "set_navigation_state(" in admin_sidebar
    assert "set_navigation_state(" in employee_sidebar


def test_leave_reset_day_has_one_widget_value_source() -> None:
    source = _source("ui/pages/admin/leave_management_page.py")
    assert "if day_key not in st.session_state:" in source
    reset_day_widget = source[source.index('st.number_input(\n                    "Leave Credit Reset Day"'):]
    reset_day_widget = reset_day_widget[: reset_day_widget.index(")\n            )")]
    assert "\n                    value=" not in reset_day_widget
    assert "key=day_key" in reset_day_widget


def test_confirmation_guard_checkboxes_do_not_mix_value_default_with_session_state_reset() -> None:
    announcements = _source("ui/pages/admin/announcements_page.py")
    for key in (
        "delete_confirmation_key",
        "move_confirmation_key",
        "permanent_confirmation_key",
    ):
        marker = f"key={key}"
        index = announcements.index(marker)
        nearby = announcements[max(0, index - 260): index + len(marker)]
        assert "value=False" not in nearby


def test_announcements_tabs_omit_default_when_session_state_already_primes_widget() -> None:
    source = _source("ui/pages/admin/announcements_page.py")
    assert '"announcements_active_tab" not in st.session_state' in source
    assert 'announcement_tab_options["default"] = announcement_default_tab' in source
    assert "**announcement_tab_options" in source


def test_static_widget_state_audit_has_no_direct_default_and_session_state_collision() -> None:
    """Catch the Streamlit warning pattern reported for Leave Reset Day."""

    widgets = {
        "text_input",
        "number_input",
        "selectbox",
        "multiselect",
        "checkbox",
        "radio",
        "date_input",
        "time_input",
        "slider",
        "select_slider",
        "toggle",
        "tabs",
    }
    defaults = {"value", "index", "default"}
    offenders: list[str] = []

    for path in (ROOT / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assigned: set[str] = set()
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for target in targets:
                if not isinstance(target, ast.Subscript):
                    continue
                base = target.value
                if (
                    isinstance(base, ast.Attribute)
                    and isinstance(base.value, ast.Name)
                    and base.value.id == "st"
                    and base.attr == "session_state"
                ):
                    assigned.add(ast.unparse(target.slice))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "st"
                and func.attr in widgets
            ):
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            if "key" not in keywords or not defaults.intersection(keywords):
                continue
            key_expr = ast.unparse(keywords["key"])
            if key_expr in assigned:
                offenders.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:{func.attr}:{key_expr}"
                )

    assert offenders == []


def test_v88180_version_markers() -> None:
    assert 'app_version: str = "0.8.8.180"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.180" in _source(".env")
    assert "APP_VERSION=0.8.8.180" in _source(".env.example")
