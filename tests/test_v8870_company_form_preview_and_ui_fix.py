"""v8.8.70 Company Form preview and simplified UI regression tests."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_pdf_preview_uses_supported_streamlit_viewer() -> None:
    preview = _read("ui/components/file_preview.py")
    requirements = _read("requirements.txt")

    assert "st.pdf(data, height=_PREVIEW_WIDGET_HEIGHT)" in preview
    assert "render_browser_bridge(component)" in preview
    assert "base64.b64encode(data)" in preview
    assert "streamlit>=1.61,<2.0" in requirements
    assert "streamlit-pdf>=1.0.5,<3.0" in requirements


def test_category_and_description_are_removed_from_company_form_ui() -> None:
    admin = _read("ui/pages/admin/company_forms_documents_page.py")
    employee = _read("ui/pages/user/company_forms_documents_page.py")

    assert 'st.selectbox("Category"' not in admin
    assert '"Description",' not in admin
    assert '"Category": item.category' not in admin
    assert '"Category": item.category' not in employee
    assert '"Description": item.description' not in employee
    assert '**Category:**' not in employee
    assert '**Description:**' not in employee
    assert 'category="General"' in admin
    assert 'category=selected.category' in admin


def test_selectable_tables_use_project_light_table_palette() -> None:
    table = _read("ui/components/data_table.py")
    config = _read(".streamlit/config.toml")

    assert "row_height=42" in table
    assert 'border: 1px solid var(--hr-border)' in table
    assert 'border-radius: 14px' in table
    assert 'background: var(--hr-surface)' in table
    assert 'frame.style' in table
    assert '"background-color": "#FFFFFF"' in table
    assert '("background-color", "#F3F5FA")' in table
    assert '"color": "#5C6680"' in table
    assert '[theme]' in config


def test_dialog_text_contrast_and_version() -> None:
    theme = _read("ui/theme/theme_loader.py")
    settings = _read("config/settings.py")

    assert '[data-testid="stDialog"] h2' in theme
    assert '-webkit-text-fill-color: #10172A' in theme
    assert 'app_version: str = "0.8.8.' in settings
