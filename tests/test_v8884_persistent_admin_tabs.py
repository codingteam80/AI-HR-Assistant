"""Regression checks for v8.8.86 native stateful admin tabs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_streamlit_runtime_supports_native_tracked_tabs() -> None:
    requirements = _read("requirements.txt")

    assert "streamlit>=1.61,<2.0" in requirements


def test_primary_edit_workspaces_use_native_stateful_tabs() -> None:
    company = _read("ui/pages/admin/company_page.py")
    employees = _read("ui/pages/admin/employees_page.py")
    policies = _read("ui/pages/admin/policies_page.py")
    forms = _read("ui/pages/admin/company_forms_documents_page.py")

    for source, key in (
        (employees, "employees_active_tab"),
        (policies, "policies_active_tab"),
        (forms, "company_forms_active_tab"),
    ):
        assert "st.tabs(" in source
        assert f'key="{key}"' in source
        assert 'on_change="rerun"' in source

    assert "render_persistent_tabs" not in company
    assert "render_persistent_tabs" not in employees
    assert "render_persistent_tabs" not in policies
    assert "render_persistent_tabs" not in forms

    assert "company_profile_active_tab" not in company
    assert 'st.tabs(\n        ["Company Information", "Branding"]' not in company
    assert '_render_company_information_tab(' in company
    assert '_render_branding_sections(' in company
    assert company.count("st.divider()") >= 2
