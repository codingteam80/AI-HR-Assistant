"""Preventive null-safety and terminal-warning regression checks."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_logo_save_never_reads_an_empty_uploader() -> None:
    source = _source("ui/pages/admin/company_page.py")
    assert "if save_logo and uploaded_logo is not None:" in source
    assert 'elif save_logo:' in source


def test_proxy_filing_label_guards_deleted_or_legacy_filer() -> None:
    source = _source("ui/pages/admin/leave_management_page.py")
    assert "filed_by_employee = request.filed_by_employee" in source
    assert "if filed_by_employee is not None and filed_by_employee.job_title" in source
    assert 'else "Leader/Manager"' in source


def test_employee_text_submission_normalizes_nullable_widget_values() -> None:
    source = _source("ui/pages/admin/employees_page.py")
    assert 'employee_number=(employee_number or "").strip()' in source
    assert 'work_email=(email or "").strip()' in source
    assert 'username=(username or "").strip()' in source
    assert "telephone_mobile_no=_optional_value(telephone_mobile_no)" in source


def test_attendance_displays_guard_missing_localized_punches() -> None:
    employee = _source("ui/pages/user/attendance_workspace.py")
    admin = _source("ui/pages/admin/attendance_dashboard.py")
    table = _source("ui/components/attendance_table.py")
    assert "if local_time is not None" in employee
    assert "if local_in is not None else" in admin
    assert 'if rounded_in else "—–"' in table
    assert 'if actual_in else "—–"' in table


def test_optional_ot_and_chroma_results_are_filtered_before_use() -> None:
    overtime = _source("services/overtime_service.py")
    smart_ai = _source("modules/smart_ai/portal_ai.py")
    assert "if local_end is not None:" in overtime
    assert 'result_ids = result.get("ids") or [[]]' in smart_ai
    assert 'result_distances = result.get("distances") or [[]]' in smart_ai


def test_no_deprecated_width_or_widget_state_default_conflict() -> None:
    widget_names = {
        "checkbox", "color_picker", "date_input", "file_uploader",
        "multiselect", "number_input", "radio", "segmented_control",
        "select_slider", "selectbox", "slider", "tabs", "text_area",
        "text_input", "time_input", "toggle",
    }
    default_names = {"value", "index", "default"}

    def canonical(node: ast.AST) -> str:
        return ast.dump(node, annotate_fields=False, include_attributes=False)

    state_writes: set[str] = set()
    widget_defaults: set[str] = set()
    for path in (ROOT / "ui").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "use_container_width" not in source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "session_state"
                    ):
                        state_writes.add(canonical(target.slice))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in widget_names
            ):
                keywords = {item.arg: item.value for item in node.keywords if item.arg}
                if "key" in keywords and default_names.intersection(keywords):
                    widget_defaults.add(canonical(keywords["key"]))
    assert state_writes.isdisjoint(widget_defaults)
