"""v8.8.127 live search and autosuggest regression checks."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_component_filters_while_typing_without_enter() -> None:
    source = _source("ui/components/live_search.py")

    assert 'getattr(st, "components", None)' in source
    assert '"v2"' in source
    assert "_components_v2.component(" in source
    assert "input.oninput" in source
    assert "setStateValue('value', input.value)" in source
    assert "window.setTimeout(" in source
    legacy = source[: source.index("# ---------------------------------------------------------------------------\n# Free-text multi-search chips")]
    assert "event.key === 'Enter'" not in legacy


def test_clear_button_and_escape_restore_empty_search_immediately() -> None:
    source = _source("ui/components/live_search.py")

    assert 'aria-label="Clear search"' in source
    assert "clearButton.onclick" in source
    assert "event.key === 'Escape'" in source
    assert "input.value = '';" in source
    assert "commit();" in source


def test_all_explicit_portal_searches_use_shared_live_control() -> None:
    expected = {
        "ui/pages/admin/employees_page.py": (
            'multi_search_input(\n        "Search Employees"',
            'key="employee_master_search"',
        ),
        "ui/pages/admin/attendance_dashboard.py": (
            'multi_search_input(\n            "Search Employee / Attendance / DTR / OT"',
            'key="admin_dtr_employee_search"',
        ),
        "ui/pages/admin/leave_management_page.py": (
            'multi_search_input(\n        "Search Leave Requests"',
            'key=f"leave_request_employee_search_{year}"',
        ),
        "ui/pages/admin/policies_page.py": (
            'multi_search_input(\n        "Find in Sections"',
            'key=f"section_search_{view.policy.id}"',
        ),
        "ui/pages/user/policies_page.py": (
            'multi_search_input(\n            "Search Policies"',
            'key="employee_policy_search"',
        ),
        "ui/pages/user/announcements_page.py": (
            'multi_search_input(\n            "Search Announcements"',
            'key="employee_announcement_search"',
        ),
    }

    for relative_path, required_text in expected.items():
        source = _source(relative_path)
        assert "from ui.components.live_search import" in source
        for text in required_text:
            assert text in source


def test_searches_use_manual_free_text_chips_without_autosuggestions() -> None:
    pages = (
        "ui/pages/admin/employees_page.py",
        "ui/pages/admin/attendance_dashboard.py",
        "ui/pages/admin/leave_management_page.py",
        "ui/pages/admin/policies_page.py",
        "ui/pages/user/policies_page.py",
        "ui/pages/user/announcements_page.py",
    )

    assert all("suggestions=(" not in _source(path) for path in pages)
    assert all("multi_search_input(" in _source(path) for path in pages)


def test_native_searchable_recipient_controls_remain_unchanged() -> None:
    source = _source("ui/pages/user/leave_management_page.py")

    assert 'st.selectbox(\n            "To *"' in source
    assert 'st.multiselect(\n            "CC"' in source
    assert 'st.selectbox(\n        "Search Team Member *"' in source


def test_v88127_remains_the_live_search_base_without_audit_draft() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.133"' in settings
    assert "Immediate base checkpoint: 0.8.8.132" in settings
    assert "v8.8.127 — Live Search and Autosuggest" in readme
    assert not (PROJECT_ROOT / "models/audit_log.py").exists()
    assert not (PROJECT_ROOT / "database/audit_events.py").exists()
