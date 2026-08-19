"""Regression check for the Audit Trail table-component import."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_audit_trail_uses_existing_data_table_component() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/admin/audit_trail_page.py"
    ).read_text(encoding="utf-8")

    assert "from ui.components.data_table import render_admin_table" in source
    assert "ui.components.admin_table" not in source
    assert (PROJECT_ROOT / "ui/components/data_table.py").is_file()
