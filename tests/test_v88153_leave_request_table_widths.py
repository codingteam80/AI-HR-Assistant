"""Regression checks for readable Admin Leave Request table columns."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_leave_request_table_has_one_explicit_width_per_column() -> None:
    source = _source("ui/pages/admin/leave_management_page.py")
    tree = ast.parse(source)
    target = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "render_admin_table":
            continue
        keywords = {item.arg: item.value for item in node.keywords if item.arg}
        key = keywords.get("key")
        if isinstance(key, ast.JoinedStr) and "leave-request-monitoring-" in ast.unparse(key):
            target = keywords
            break

    assert target is not None
    widths = ast.literal_eval(target["column_widths"])
    assert len(widths) == 12
    assert widths[6] == "150px"  # Duration
    assert widths[7] == "70px"   # Days
    assert widths[8] == "250px"  # Reason
    assert widths[9] == "160px"  # Manager
    assert widths[10] == "170px"  # Status
    assert widths[11] == "100px"  # Email
    assert ast.literal_eval(target["min_width"]) == 1735


def test_v88153_version_and_warning_safe_change() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")
    page = _source("ui/pages/admin/leave_management_page.py")
    assert 'app_version: str = "0.8.8.153"' in settings
    assert "v8.8.153 — Readable Admin Leave Request Table" in readme
    assert "components.html(" not in page
    assert "st.components.v1.html(" not in page
    assert "use_container_width" not in page
