"""v8.8.211 project-wide multi free-text search regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services.policy_violation_service import PolicyViolationService
from utils.search_utils import matches_search_terms, normalize_search_terms


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_normalize_search_terms_trims_and_deduplicates_case_insensitively() -> None:
    assert normalize_search_terms([" Lander Garcia ", "AI Dev", "lander garcia", ""]) == (
        "Lander Garcia",
        "AI Dev",
    )


def test_multi_search_matches_any_committed_term_by_default() -> None:
    values = ("QA-9015", "Nina Flores", "AI Dev", "Senior Engineer")
    assert matches_search_terms(("Lander Garcia", "AI Dev"), values)
    assert matches_search_terms(("Nina", "Toyota-UT"), values)
    assert not matches_search_terms(("Lander Garcia", "Toyota-UT"), values)


def test_multi_search_supports_all_mode_without_changing_default_or_behavior() -> None:
    values = ("Nina Flores", "AI Dev", "Senior Engineer")
    assert matches_search_terms(("Nina", "AI Dev"), values, mode="all")
    assert not matches_search_terms(("Nina", "Toyota-UT"), values, mode="all")


def test_shared_component_is_free_text_chips_not_a_selection_control() -> None:
    source = _source("ui/components/live_search.py")
    assert '"hr_portal_multi_search"' in source
    assert "hr-multi-search-chip" in source
    assert "event.key === 'Enter' || event.key === ','" in source
    assert "Remove search term" in source
    assert "Clear all search terms" in source
    assert "Press Enter or comma to add another term. Results match any chip." in source
    multi_block = source[source.index("_MULTI_SEARCH_HTML"):]
    assert "<select" not in multi_block
    assert "<datalist" not in multi_block


def test_all_explicit_portal_searches_use_shared_multi_search_control() -> None:
    pages = {
        "ui/pages/admin/employees_page.py": "Search Employees",
        "ui/pages/admin/attendance_dashboard.py": "Search Employee / Attendance / DTR / OT",
        "ui/pages/admin/leave_management_page.py": "Search Leave Requests",
        "ui/pages/admin/policies_page.py": "Find in Sections",
        "ui/pages/admin/audit_trail_page.py": "Search Audit Trail",
        "ui/pages/admin/onboarding_management.py": "Search Onboarding Progress",
        "ui/pages/admin/reports_page.py": "Search Leave Conversion",
        "ui/pages/admin/policy_violations.py": "Search Violations",
        "ui/components/disciplinary_records.py": "Search Disciplinary Records",
        "ui/pages/user/policies_page.py": "Search Policies",
        "ui/pages/user/announcements_page.py": "Search Announcements",
        "ui/pages/user/hr_contacts_page.py": "Search HR Contacts",
        "ui/pages/user/policy_violations.py": "Search Violations",
    }
    for path, label in pages.items():
        source = _source(path)
        assert "multi_search_input(" in source, path
        assert label in source, path
        assert "live_search_input(" not in source, path


def test_searchable_recipient_selection_controls_remain_selection_controls() -> None:
    source = _source("ui/pages/user/leave_management_page.py")
    assert 'st.selectbox(\n            "To *"' in source
    assert 'st.multiselect(\n            "CC"' in source
    assert 'st.selectbox(\n        "Search Team Member *"' in source


def test_policy_violation_filter_uses_or_semantics_for_multiple_terms() -> None:
    item_a = SimpleNamespace(
        violation_code="QA-V001",
        category="Attendance",
        offense_title="Repeated Tardiness",
        description="Repeated late arrival",
        severity="Minor",
        first_offense_action="Written Warning",
        second_offense_action="1-day Suspension",
        third_offense_action="3-day Suspension",
        final_action="5-day Suspension",
        notes="",
        status="active",
    )
    item_b = SimpleNamespace(
        violation_code="QA-V004",
        category="Confidentiality",
        offense_title="Unauthorized Disclosure",
        description="Confidential information disclosure",
        severity="Grave",
        first_offense_action="Final action",
        second_offense_action="Final action",
        third_offense_action="Final action",
        final_action="Termination",
        notes="",
        status="active",
    )
    service = object.__new__(PolicyViolationService)
    filtered = service.filter_items(
        [item_a, item_b],
        search_text=("Repeated Tardiness", "Confidentiality"),
        status="active",
    )
    assert filtered == [item_a, item_b]


def test_version_markers_are_v88211() -> None:
    assert 'app_version: str = "0.8.8.211"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.211" in _source(".env")
    assert "APP_VERSION=0.8.8.211" in _source(".env.example")
