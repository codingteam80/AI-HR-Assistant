"""Admin Leave Management startup-syntax regression checks."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_leave_management_page_parses_as_python() -> None:
    path = ROOT / "ui/pages/admin/leave_management_page.py"
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_proxy_filing_source_avoids_nested_multiline_f_string() -> None:
    source = (ROOT / "ui/pages/admin/leave_management_page.py").read_text(
        encoding="utf-8"
    )
    assert 'filing_source = f"{filer_role} Filed on Behalf"' in source
    assert '"Value": filing_source' in source
    assert 'f"{(' not in source
