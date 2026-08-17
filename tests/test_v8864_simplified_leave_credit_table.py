"""Regression tests for the simplified leave-credit presentation."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_adjustment_is_hidden_from_admin_and_employee_tables() -> None:
    for relative_path in (
        "ui/pages/admin/leave_management_page.py",
        "ui/pages/user/leave_management_page.py",
    ):
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert '"Adjustment":' not in source
        assert 'Decimal(' in source
        assert 'Credit shows only the annual or approved event allocation' in source
        assert 'corrections affect Available' in source


def test_admin_editor_uses_plain_language_for_internal_correction() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/admin/leave_management_page.py"
    ).read_text(encoding="utf-8")
    editor = source.split(
        "def _render_credit_balance_editor(", 1
    )[1].split("def _credit_history_entry(", 1)[0]

    assert "recorded in Adjustment" not in editor
    assert "through Adjustment" not in editor
    assert "records any difference " in editor
    assert "internally so the annual and event grants remain auditable" in editor


def test_v8864_release_note_is_preserved() -> None:
    release = PROJECT_ROOT / "RELEASE_v8_8_64.md"
    assert release.exists()
    assert "Simplified Leave Credit Table" in release.read_text(
        encoding="utf-8"
    )
