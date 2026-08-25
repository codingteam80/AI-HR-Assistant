"""v8.8.181 hard-refresh navigation persistence regression checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_persistent_tabs(fake_st):
    old = sys.modules.get("streamlit")
    sys.modules["streamlit"] = fake_st
    try:
        path = ROOT / "ui" / "components" / "persistent_tabs.py"
        spec = importlib.util.spec_from_file_location("_v88181_persistent_tabs", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if old is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = old


class _FakeStreamlit(types.SimpleNamespace):
    def __init__(self):
        super().__init__()
        self.session_state = {}
        self.query_params = {}
        self.last_tabs_call = None

    def tabs(self, labels, **kwargs):
        labels = tuple(labels)
        self.last_tabs_call = (labels, kwargs)
        self.session_state.setdefault(kwargs["key"], labels[0])
        return tuple(object() for _ in labels)


def test_query_index_restores_tab_before_native_widget_creation() -> None:
    fake = _FakeStreamlit()
    fake.query_params["tab_employees_active_tab"] = "2"
    module = _load_persistent_tabs(fake)

    module.persistent_tabs(
        ["Employee List", "Add Employee", "Edit Employee"],
        key="employees_active_tab",
    )

    assert fake.session_state["employees_active_tab"] == "Edit Employee"
    labels, kwargs = fake.last_tabs_call
    assert labels[2] == "Edit Employee"
    assert kwargs["key"] == "employees_active_tab"
    assert callable(kwargs["on_change"])
    assert "default" not in kwargs


def test_tab_change_callback_updates_refresh_safe_url_index() -> None:
    fake = _FakeStreamlit()
    module = _load_persistent_tabs(fake)
    module.persistent_tabs(
        ["Employee List", "Add Employee", "Edit Employee"],
        key="employees_active_tab",
    )

    fake.session_state["employees_active_tab"] = "Add Employee"
    _, kwargs = fake.last_tabs_call
    kwargs["on_change"](*kwargs["args"])

    assert fake.query_params["tab_employees_active_tab"] == "1"


def test_programmatic_tab_target_wins_and_is_written_to_url() -> None:
    fake = _FakeStreamlit()
    fake.query_params["tab_employees_active_tab"] = "0"
    fake.session_state["employees_active_tab"] = "Add Employee"
    module = _load_persistent_tabs(fake)

    module.persistent_tabs(
        ["Employee List", "Add Employee", "Edit Employee"],
        key="employees_active_tab",
    )

    assert fake.session_state["employees_active_tab"] == "Add Employee"
    assert fake.query_params["tab_employees_active_tab"] == "1"


def test_dynamic_tab_label_restores_by_stable_index() -> None:
    fake = _FakeStreamlit()
    fake.query_params["tab_employees_active_tab"] = "2"
    module = _load_persistent_tabs(fake)

    module.persistent_tabs(
        ["Employee List", "Add Employee", "Archive (9)"],
        key="employees_active_tab",
    )

    assert fake.session_state["employees_active_tab"] == "Archive (9)"


def test_every_portal_native_tab_uses_refresh_safe_helper() -> None:
    offenders: list[str] = []
    for path in (ROOT / "ui" / "pages").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "st.tabs(" in source:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []

    persistent_calls = 0
    for path in (ROOT / "ui" / "pages").rglob("*.py"):
        persistent_calls += path.read_text(encoding="utf-8").count("persistent_tabs(")
    assert persistent_calls >= 18


def test_browser_view_preserver_no_longer_clicks_tabs_after_render() -> None:
    source = _source("ui/components/view_state_preservation.py")
    assert "tabIntentFromEvent" not in source
    assert 'button[role="tab"]' not in source
    assert "requested.label" not in source
    assert "persistent_tabs" in source


def test_sidebar_page_refresh_still_uses_portal_and_page_query_params() -> None:
    navigation = _source("ui/navigation_state.py")
    assert 'PORTAL_QUERY_KEY = "portal"' in navigation
    assert 'PAGE_QUERY_KEY = "page"' in navigation
    assert "st.query_params[PORTAL_QUERY_KEY] = normalized_portal" in navigation
    assert "st.query_params[PAGE_QUERY_KEY] = normalized_page" in navigation



def test_logout_clears_refresh_safe_tab_query_state() -> None:
    source = _source("ui/navigation_state.py")
    assert 'str(key).startswith("tab_")' in source

def test_v88181_version_markers() -> None:
    assert 'app_version: str = "0.8.8.181"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.181" in _source(".env")
    assert "APP_VERSION=0.8.8.181" in _source(".env.example")
