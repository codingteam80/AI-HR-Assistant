"""Regression checks for v8.8.98 clean nested-form container borders."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_nested_form_workspaces_do_not_draw_outer_borders() -> None:
    source = _read("ui/pages/admin/company_forms_documents_page.py")

    assert "with st.container(height=560, border=False):" in source
    assert "with st.container(height=620, border=False):" in source
    assert "with st.container(height=660, border=False):" in source
    assert 'with st.form("company_form_upload", clear_on_submit=True):' in source
    assert 'with st.form(f"manage_company_form_{selected.id}"):' in source


def test_employee_fill_submit_keeps_form_but_not_outer_border() -> None:
    source = _read("ui/pages/user/company_forms_documents_page.py")

    assert "with st.container(height=720, border=False):" in source
    assert '"employee_company_form_submit"' in source
    assert "clear_on_submit=True" in source


def test_intentional_non_form_borders_are_preserved() -> None:
    admin_forms = _read("ui/pages/admin/company_forms_documents_page.py")
    preview = _read("ui/components/file_preview.py")
    employees = _read("ui/pages/admin/employees_page.py")

    assert "with st.container(height=580, border=True):" in admin_forms
    assert "border=True," in preview
    assert 'border=True, key="employee_create_information_card"' in employees


def test_checkpoint_version_is_v8898() -> None:
    settings = _read("config/settings.py")
    readme = _read("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.98 — Clean Form Container Borders" in readme
