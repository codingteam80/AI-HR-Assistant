"""v8.8.177 Company Profile and Branding UI refinement checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_company_profile_summary_uses_requested_three_metric_order() -> None:
    source = _source("ui/pages/admin/company_page.py")

    assert 'metric_columns = st.columns(3)' in source
    tenant = source.index('st.metric("Tenant ID", current_user.company_id)')
    status = source.index('st.metric("Status", company_status)')
    code = source.index('st.metric("Company Code", company_code)')
    assert tenant < status < code
    assert 'st.metric("Theme Color", company_theme_color)' not in source


def test_company_information_inputs_share_one_equal_row_with_save_below() -> None:
    source = _source("ui/pages/admin/company_page.py")

    assert 'code_column, name_column = st.columns(2, gap="medium")' in source
    assert 'with code_column:' in source
    assert 'with name_column:' in source
    assert source.index('"Company Code"') < source.index('"Company Name"')
    assert source.index('"Company Name"') < source.index('"Save Company Information"')
    assert 'width="stretch"' in source


def test_branding_logo_keeps_reference_two_column_layout() -> None:
    source = _source("ui/pages/admin/company_page.py")

    assert 'st.subheader("Company Logo")' in source
    assert 'upload_column, preview_column = st.columns(' in source
    assert '"**Upload or Replace Logo**"' in source
    assert 'label_visibility="collapsed"' in source
    assert '"Save Company Logo"' in source
    assert '"Remove Company Logo"' in source
    assert '"**Current Sidebar Logo**"' in source
    assert 'save_logo_column, remove_logo_column = st.columns(2, gap="small")' in source


def test_theme_color_matches_compact_reference_structure() -> None:
    source = _source("ui/pages/admin/company_page.py")

    assert 'st.subheader("Company Theme Color")' in source
    assert 'extract_logo_theme_colors(image_bytes, max_colors=3)' in source
    assert 'columns = st.columns(len(suggestions), gap="small")' in source
    assert 'custom_color_column, preview_column = st.columns(' in source
    assert '[1.15, 3.85]' in source
    assert 'with custom_color_column:' in source
    assert 'with preview_column:' in source
    assert '"Color Picker"' in source
    assert 'Theme Preview' in source
    assert '"Save Theme Color"' in source
    assert '"Reset to Default Violet"' in source


def test_hr_contacts_management_description_is_removed() -> None:
    source = _source("ui/pages/admin/hr_contacts_management.py")

    assert 'st.subheader("HR Contacts Management")' in source
    assert (
        "Maintain the HR contacts displayed in Employee Portal → HR Contacts."
        not in source
    )


def test_current_version_is_v88177() -> None:
    settings = _source("config/settings.py")
    env = _source(".env.example")

    assert 'app_version: str = "0.8.8.177"' in settings
    assert 'APP_VERSION=0.8.8.177' in env
