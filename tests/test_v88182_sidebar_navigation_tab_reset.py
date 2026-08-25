"""v8.8.182 sidebar-vs-refresh navigation regression checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import re


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _FakeStreamlit(types.SimpleNamespace):
    def __init__(self):
        super().__init__()
        self.session_state = _SessionState()
        self.query_params = {}
        self.last_tabs_call = None

    def tabs(self, labels, **kwargs):
        labels = tuple(labels)
        self.last_tabs_call = (labels, kwargs)
        self.session_state.setdefault(kwargs["key"], labels[0])
        return tuple(object() for _ in labels)


def _load_module(name: str, path: str, fake_st):
    old_streamlit = sys.modules.get("streamlit")
    sys.modules["streamlit"] = fake_st
    try:
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if old_streamlit is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = old_streamlit


def test_refresh_still_restores_exact_current_horizontal_tab() -> None:
    fake = _FakeStreamlit()
    fake.query_params.update(
        {
            "portal": "admin",
            "page": "Leave Management",
            "tab_admin_leave_management_active_tab": "3",
        }
    )
    module = _load_module(
        "_v88182_persistent_tabs_refresh",
        "ui/components/persistent_tabs.py",
        fake,
    )

    module.persistent_tabs(
        [
            "Overview",
            "Employee Leave Accounts",
            "Leave Requests",
            "Leave Rules",
            "History",
        ],
        key="admin_leave_management_active_tab",
    )

    assert fake.session_state["admin_leave_management_active_tab"] == "Leave Rules"
    assert fake.query_params["tab_admin_leave_management_active_tab"] == "3"
    assert fake.query_params["page"] == "Leave Management"


def test_sidebar_change_clears_saved_horizontal_and_nested_tab_state() -> None:
    fake = _FakeStreamlit()
    persistent = _load_module(
        "ui.components.persistent_tabs",
        "ui/components/persistent_tabs.py",
        fake,
    )

    # Simulate currently rendered Leave Management main and nested tabs.
    persistent.persistent_tabs(
        ["Overview", "Employee Leave Accounts", "Leave Requests", "Leave Rules"],
        key="admin_leave_management_active_tab",
    )
    fake.session_state["admin_leave_management_active_tab"] = "Leave Rules"
    persistent.persistent_tabs(
        ["Add Leave Type", "Edit Leave Type"],
        key="admin_leave_rules_editor_tab",
    )
    fake.session_state["admin_leave_rules_editor_tab"] = "Edit Leave Type"
    fake.query_params["tab_admin_leave_management_active_tab"] = "3"
    fake.query_params["tab_admin_leave_rules_editor_tab"] = "1"
    fake.query_params["leave_view"] = "rules"
    fake.query_params["leave_request_id"] = "99"
    fake.query_params["theme"] = "dark"
    fake.session_state["_admin_leave_next_tabs"] = ["Leave Rules"]
    fake.session_state.portal_mode = "admin"
    fake.session_state.current_page = "Leave Management"

    old_streamlit = sys.modules.get("streamlit")
    old_persistent = sys.modules.get("ui.components.persistent_tabs")
    sys.modules["streamlit"] = fake
    sys.modules["ui.components.persistent_tabs"] = persistent
    try:
        nav = _load_module(
            "_v88182_navigation_state",
            "ui/navigation_state.py",
            fake,
        )
        nav.set_sidebar_navigation_state(
            portal_mode="admin",
            current_page="Employees",
        )
    finally:
        if old_streamlit is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = old_streamlit
        if old_persistent is None:
            sys.modules.pop("ui.components.persistent_tabs", None)
        else:
            sys.modules["ui.components.persistent_tabs"] = old_persistent

    assert fake.session_state.portal_mode == "admin"
    assert fake.session_state.current_page == "Employees"
    assert "admin_leave_management_active_tab" not in fake.session_state
    assert "admin_leave_rules_editor_tab" not in fake.session_state
    assert "_admin_leave_next_tabs" not in fake.session_state
    assert not any(str(key).startswith("tab_") for key in fake.query_params)
    assert "leave_view" not in fake.query_params
    assert "leave_request_id" not in fake.query_params
    assert fake.query_params["portal"] == "admin"
    assert fake.query_params["page"] == "Employees"
    # Non-navigation settings are not stripped.
    assert fake.query_params["theme"] == "dark"


def test_returning_to_sidebar_module_starts_at_first_tab() -> None:
    fake = _FakeStreamlit()
    persistent = _load_module(
        "ui.components.persistent_tabs",
        "ui/components/persistent_tabs.py",
        fake,
    )

    fake.session_state.portal_mode = "admin"
    fake.session_state.current_page = "Employees"
    fake.session_state["admin_leave_management_active_tab"] = "Leave Rules"
    fake.session_state["_persistent_tab_state_keys"] = [
        "admin_leave_management_active_tab"
    ]
    fake.query_params.update(
        {
            "portal": "admin",
            "page": "Employees",
            "tab_admin_leave_management_active_tab": "3",
            "leave_view": "rules",
        }
    )

    old_streamlit = sys.modules.get("streamlit")
    old_persistent = sys.modules.get("ui.components.persistent_tabs")
    sys.modules["streamlit"] = fake
    sys.modules["ui.components.persistent_tabs"] = persistent
    try:
        nav = _load_module(
            "_v88182_navigation_state_return",
            "ui/navigation_state.py",
            fake,
        )
        nav.set_sidebar_navigation_state(
            portal_mode="admin",
            current_page="Leave Management",
        )
    finally:
        if old_streamlit is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = old_streamlit
        if old_persistent is None:
            sys.modules.pop("ui.components.persistent_tabs", None)
        else:
            sys.modules["ui.components.persistent_tabs"] = old_persistent

    persistent.persistent_tabs(
        ["Overview", "Employee Leave Accounts", "Leave Requests", "Leave Rules"],
        key="admin_leave_management_active_tab",
    )
    assert fake.session_state["admin_leave_management_active_tab"] == "Overview"
    assert fake.query_params["tab_admin_leave_management_active_tab"] == "0"


def test_same_sidebar_route_does_not_destroy_refresh_state() -> None:
    fake = _FakeStreamlit()
    persistent = _load_module(
        "ui.components.persistent_tabs",
        "ui/components/persistent_tabs.py",
        fake,
    )
    fake.session_state.portal_mode = "admin"
    fake.session_state.current_page = "Leave Management"
    fake.session_state["admin_leave_management_active_tab"] = "Leave Rules"
    fake.session_state["_persistent_tab_state_keys"] = [
        "admin_leave_management_active_tab"
    ]
    fake.query_params.update(
        {
            "portal": "admin",
            "page": "Leave Management",
            "tab_admin_leave_management_active_tab": "3",
        }
    )

    old_streamlit = sys.modules.get("streamlit")
    old_persistent = sys.modules.get("ui.components.persistent_tabs")
    sys.modules["streamlit"] = fake
    sys.modules["ui.components.persistent_tabs"] = persistent
    try:
        nav = _load_module(
            "_v88182_navigation_state_same",
            "ui/navigation_state.py",
            fake,
        )
        nav.set_sidebar_navigation_state(
            portal_mode="admin",
            current_page="Leave Management",
        )
    finally:
        if old_streamlit is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = old_streamlit
        if old_persistent is None:
            sys.modules.pop("ui.components.persistent_tabs", None)
        else:
            sys.modules["ui.components.persistent_tabs"] = old_persistent

    assert fake.session_state["admin_leave_management_active_tab"] == "Leave Rules"
    assert fake.query_params["tab_admin_leave_management_active_tab"] == "3"


def test_sidebar_uses_reset_navigation_but_deep_links_keep_exact_navigation() -> None:
    admin_sidebar = _source("ui/components/admin_sidebar.py")
    employee_sidebar = _source("ui/components/sidebar.py")
    quick_actions = _source("ui/components/quick_actions.py")
    topbar = _source("ui/components/topbar.py")

    assert "set_sidebar_navigation_state(" in admin_sidebar
    assert "set_sidebar_navigation_state(" in employee_sidebar
    assert "set_sidebar_navigation_state(" not in quick_actions
    assert "set_sidebar_navigation_state(" not in topbar
    assert "set_navigation_state(" in quick_actions
    assert "set_navigation_state(" in topbar


def test_sidebar_reset_covers_deep_link_and_one_shot_tab_targets() -> None:
    source = _source("ui/navigation_state.py")
    for query_key in (
        "leave_view",
        "form_view",
        "announcement_view",
        "policy_view",
        "dashboard_view",
        "onboarding_view",
        "leave_request_id",
        "announcement_id",
        "reminder_id",
        "company_form_id",
        "form_submission_id",
        "employee_id",
    ):
        assert f'"{query_key}"' in source

    for state_key in (
        "company_forms_next_tab",
        "employee_company_forms_next_tab",
        "announcements_next_tab",
        "reminders_next_tab",
        "employees_pending_active_tab",
        "admin_onboarding_management_pending_active_tab",
        "company_profile_pending_active_tab",
        "employee_onboarding_pending_active_tab",
        "_admin_leave_next_tabs",
    ):
        assert f'"{state_key}"' in source


def test_no_new_widget_default_session_state_conflict_pattern() -> None:
    """Keep the v8.8.180 warning-cleanup guard active in the new patch."""

    source = _source("ui/components/persistent_tabs.py")
    assert "default=" not in source.split("return st.tabs(", 1)[1].split(")", 1)[0]

    leave = _source("ui/pages/admin/leave_management_page.py")
    reset_day_call = leave.split('"Leave Credit Reset Day"', 1)[1].split(")", 1)[0]
    assert re.search(r"(?<![A-Za-z0-9_])value\s*=", reset_day_call) is None


def test_v88182_version_markers() -> None:
    assert 'app_version: str = "0.8.8.182"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.182" in _source(".env")
    assert "APP_VERSION=0.8.8.182" in _source(".env.example")
