"""Regression checks for v8.8.91 whole-row company-form previews."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_selectable_admin_table_uses_whole_row_selection() -> None:
    source = (ROOT / "ui/components/data_table.py").read_text(encoding="utf-8")

    assert 'on_select="rerun"' in source
    assert 'selection_mode="single-row"' in source
    assert '[data-testid="stDataFrame"] canvas' in source
    assert 'cursor: pointer !important' in source
    assert "Clicking anywhere on a data row selects that row" in source


def test_all_admin_company_form_tables_explain_whole_row_action() -> None:
    source = (
        ROOT / "ui/pages/admin/company_forms_documents_page.py"
    ).read_text(encoding="utf-8")

    assert "Click anywhere on a form row to open its file preview." in source
    assert (
        "Click anywhere on a submission row to preview the filled file."
        in source
    )
    assert (
        "Click anywhere on a form row to preview and select it for editing."
        in source
    )
    assert (
        "Click anywhere on a Bin row to preview and select the stored form."
        in source
    )


def test_checkpoint_version_is_v8891() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.91 — Whole-Row Company Form Preview" in readme
