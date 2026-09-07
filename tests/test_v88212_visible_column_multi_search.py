"""v8.8.212 visible-column multi-search regressions."""

from pathlib import Path

from utils.search_utils import (
    filter_aligned_visible_rows,
    matches_visible_row,
    visible_row_values,
)

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_visible_row_search_matches_every_rendered_column_value() -> None:
    row = {
        "Policy ID": "PID_123",
        "Filename / Title": "Work Schedule.docx\nWork Schedule",
        "Version": "2.4",
        "Category": "Attendance",
    }
    assert visible_row_values(row) == tuple(row.values())
    assert matches_visible_row(("PID_123",), row)
    assert matches_visible_row(("2.4",), row)
    assert matches_visible_row(("Work Schedule.docx",), row)
    assert matches_visible_row(("Attendance",), row)
    assert not matches_visible_row(("hidden-secret",), row)


def test_visible_row_search_keeps_default_or_semantics() -> None:
    row = {"Employee": "Lander Garcia", "Department": "AI Dev"}
    assert matches_visible_row(("Lander Garcia", "Toyota-UT"), row)
    assert matches_visible_row(("Nina Flores", "AI Dev"), row)
    assert not matches_visible_row(("Nina Flores", "Toyota-UT"), row)


def test_aligned_filter_keeps_record_and_row_indexes_together() -> None:
    items = ["a", "b"]
    rows = [{"ID": "FORM-001"}, {"ID": "FORM-002"}]
    kept_items, kept_rows = filter_aligned_visible_rows(items, rows, ("FORM-002",))
    assert kept_items == ["b"]
    assert kept_rows == [rows[1]]


def test_company_form_tables_use_visible_row_multi_search() -> None:
    admin = _source("ui/pages/admin/company_forms_documents_page.py")
    employee = _source("ui/pages/user/company_forms_documents_page.py")
    assert admin.count("filter_aligned_visible_rows(") >= 4
    assert employee.count("filter_aligned_visible_rows(") >= 2
    assert "Search Employee Filled Forms" in admin
    assert "Search My Submitted Forms" in employee


def test_policy_search_includes_user_visible_identity_metadata() -> None:
    service = _source("services/policy_service.py")
    assert "self.public_id_for(policy)" in service
    assert "policy.version" in service
    assert "document.original_filename" in service
    admin = _source("ui/pages/admin/policies_page.py")
    assert '"Search Policies"' in admin
    assert "matches_visible_row(search_terms, row)" in admin


def test_disciplinary_and_violation_search_use_rendered_rows() -> None:
    disciplinary = _source("ui/components/disciplinary_records.py")
    violations = _source("ui/pages/admin/policy_violations.py")
    assert "matches_visible_row(search_terms, row)" in disciplinary
    assert "matches_visible_row(search, row)" in violations


def test_audit_search_uses_exact_table_row_columns() -> None:
    audit = _source("ui/pages/admin/audit_trail_page.py")
    assert "def _table_row(" in audit
    assert "matches_visible_row(search_terms, _table_row(item))" in audit


def test_version_markers_are_8812() -> None:
    assert 'app_version: str = "0.8.8.212"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.212" in _source(".env")
    assert "APP_VERSION=0.8.8.212" in _source(".env.example")
