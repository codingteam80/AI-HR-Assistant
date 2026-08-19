"""Regression checks for v8.8.164.3 project-wide table readability."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_shared_admin_table_prevents_character_by_character_wrapping() -> None:
    source = _read("ui/components/data_table.py")

    assert "table-layout: auto;" in source
    assert "overflow-wrap: break-word;" in source
    assert "word-break: normal;" in source
    assert "overflow-wrap: anywhere;" not in source
    assert "def _recommended_column_width" in source
    assert "effective_min_width" in source
    assert "min-width: {minimum_pixels}px;" in source


def test_employee_my_requests_defines_width_for_every_visible_column() -> None:
    source = _read("ui/pages/user/leave_management_page.py")
    block = source.split('key="employee-leave-requests"', 1)[1].split(")\n\n    options", 1)[0]

    expected_widths = (
        '"125px"',
        '"160px"',
        '"200px"',
        '"120px"',
        '"190px"',
        '"90px"',
        '"170px"',
        '"300px"',
        '"180px"',
        '"130px"',
        '"170px"',
        '"100px"',
        '"300px"',
    )
    for width in expected_widths:
        assert width in block
    assert "min_width=2235" in block


def test_employee_custom_tables_use_readable_word_wrapping() -> None:
    source = _read("ui/pages/admin/employees_page.py")

    assert "overflow-wrap: break-word;" in source
    assert "word-break: normal;" in source
    assert ".employee-workspace-table" in source
    assert "table-layout: auto;" in source


def test_attendance_matrix_retains_fixed_readable_date_cells() -> None:
    source = _read("ui/components/attendance_table.py")

    assert "min-width:118px" in source
    assert "min-width:190px" in source
    assert "overflow:auto" in source


def test_version_is_v881643() -> None:
    settings = _read("config/settings.py")
    env_example = _read(".env.example")

    assert 'app_version: str = "0.8.8.164.3"' in settings
    assert "APP_VERSION=0.8.8.164.3" in env_example
