"""v8.8.76 Company Theme Color cleanup regression tests."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_company_theme_color_keeps_only_logo_suggestions_and_picker() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/admin/company_page.py"
    ).read_text(encoding="utf-8")

    assert "Suggested From Company Logo" in source
    assert "extract_logo_theme_colors" in source
    assert "st.color_picker(" in source
    assert "_render_theme_preview(selected_color)" in source
    assert '"Save Theme Color"' in source
    assert '"Reset to Default Violet"' in source


def test_company_theme_color_removes_crowded_presets_and_hex_controls() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/admin/company_page.py"
    ).read_text(encoding="utf-8")

    assert "Theme Colors" not in source
    assert "Standard Colors" not in source
    assert '"HEX Color"' not in source
    assert '"Use HEX Color"' not in source
    assert "_render_color_palette(" not in source
    assert "_THEME_COLOR_ROWS" not in source
    assert "_STANDARD_COLORS" not in source
