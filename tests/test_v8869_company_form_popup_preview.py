"""v8.8.69 Company Form/Documents popup-preview regression tests."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_selectable_table_uses_native_single_row_selection() -> None:
    source = _read("ui/components/data_table.py")

    assert "def render_selectable_admin_table(" in source
    assert 'on_select="rerun"' in source
    assert 'selection_mode="single-row"' in source
    assert "height=visible_height" in source


def test_preview_uses_large_dismissible_streamlit_dialog() -> None:
    source = _read("ui/components/file_preview.py")

    assert 'width="large"' in source
    assert "dismissible=True" in source
    assert "on_dismiss=_dismiss_file_preview" in source
    assert '"Download File"' in source


def test_preview_supports_current_company_form_file_types() -> None:
    source = _read("ui/components/file_preview.py")

    assert 'extension == ".pdf"' in source
    assert 'extension == ".docx"' in source
    assert 'extension == ".xlsx"' in source
    assert 'extension == ".csv"' in source
    assert 'extension == ".txt"' in source
    assert '{".png", ".jpg", ".jpeg"}' in source
    assert '{".doc", ".xls"}' in source


def test_admin_available_form_row_opens_preview_and_filled_form_has_view_action() -> None:
    source = _read("ui/pages/admin/company_forms_documents_page.py")

    assert "render_selectable_admin_table(" in source
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
    assert '"View Filled Form"' in source
    assert '"View Original Form"' in source
    assert "_render_pending_preview(current_user)" in source


def test_employee_available_form_row_opens_preview_and_own_copy_can_be_viewed() -> None:
    source = _read("ui/pages/user/company_forms_documents_page.py")

    assert "render_selectable_admin_table(" in source
    assert '"Click a form row to open its file preview."' in source
    assert '"Click a submission row to preview your filled file."' in source
    assert '"View Form"' in source
    assert '"View My Submitted Copy"' in source
    assert "employee_id=int(current_user.employee_id)" in source
    assert "_render_pending_preview(current_user)" in source


def test_company_form_preview_checkpoint_is_preserved() -> None:
    settings = _read("config/settings.py")
    assert 'app_version: str = "0.8.8.' in settings
    assert "Company Form Preview" in _read("README.md")
