"""Regression checks for v8.8.89 company forms overview and preview polish."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_overview_metrics_are_directly_above_the_active_forms_table() -> None:
    source = _read("ui/pages/admin/company_forms_documents_page.py")
    overview = source.split("def _render_overview", 1)[1].split(
        "def _render_upload", 1
    )[0]

    assert 'st.subheader("Available Company Forms")' not in overview
    assert (
        'st.caption("Click anywhere on a form row to open its file preview.")'
        in overview
    )
    assert overview.index("metrics = st.columns(4)") < overview.index(
        "render_selectable_admin_table("
    )
    assert "with st.container(height=310, border=True)" not in overview


def test_selectable_table_uses_row_aware_height_and_light_runtime_theme() -> None:
    table = _read("ui/components/data_table.py")
    config = _read(".streamlit/config.toml")

    assert "visible_height = min(" in table
    assert "44 + (len(frame) * 42)" in table
    assert "height=visible_height" in table
    assert '[theme]' in config
    assert 'base = "light"' in config


def test_file_preview_is_bounded_with_internal_scrolling() -> None:
    source = _read("ui/components/file_preview.py")

    assert "_PREVIEW_CONTENT_HEIGHT = 600" in source
    assert "_PREVIEW_WIDGET_HEIGHT = 560" in source
    assert "height=_PREVIEW_CONTENT_HEIGHT" in source
    assert 'key="company_file_preview_content"' in source
    assert '"Download File"' in source
    assert "dismissible=True" in source
    assert "on_dismiss=_dismiss_file_preview" in source
    assert "def _dismiss_file_preview()" in source
    assert '"Close Preview"' not in source
