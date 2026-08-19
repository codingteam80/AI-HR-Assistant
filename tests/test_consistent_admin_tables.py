"""Tests for consistent theme-aware administration tables."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (
        PROJECT_ROOT / relative_path
    ).read_text(encoding="utf-8")


def test_reusable_table_uses_hr_theme_tokens() -> None:
    source = _read(
        "ui/components/data_table.py"
    )

    assert "var(--hr-surface)" in source
    assert "var(--hr-surface-secondary)" in source
    assert "var(--hr-border)" in source
    assert "var(--hr-text-primary)" in source
    assert "var(--hr-text-secondary)" in source


def test_reusable_table_wraps_and_scrolls() -> None:
    source = _read(
        "ui/components/data_table.py"
    )

    assert "white-space: normal" in source
    assert "overflow-wrap: break-word" in source
    assert "word-break: normal" in source
    assert "table-layout: auto" in source
    assert "overflow-x: auto" in source
    assert "position: sticky" in source


def test_reusable_table_escapes_dynamic_content() -> None:
    source = _read(
        "ui/components/data_table.py"
    )

    assert "from html import escape" in source
    assert "escape(str(value))" in source
    assert "escape(str(header))" in source


def test_policies_page_no_longer_uses_dataframe() -> None:
    source = _read(
        "ui/pages/admin/policies_page.py"
    )

    assert "st.dataframe(" not in source
    assert "pd.DataFrame" not in source
    assert 'key="policy-list"' in source
    assert "render_admin_table(" in source


def test_visible_admin_pages_use_consistent_table_component() -> None:
    for relative_path in [
        "ui/pages/admin/integrations_page.py",
        "ui/pages/admin/policies_page.py",
    ]:
        source = _read(relative_path)

        assert "render_admin_table(" in source
        assert "st.dataframe(" not in source


def test_employee_table_uses_correct_hr_variables() -> None:
    source = _read(
        "ui/pages/admin/employees_page.py"
    )

    assert "var(--hr-surface)" in source
    assert "var(--hr-border)" in source
    assert "var(--surface)" not in source
    assert "var(--border)" not in source
