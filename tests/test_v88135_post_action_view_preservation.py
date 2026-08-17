"""Application-wide post-action view and warning regression checks."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_both_protected_layouts_install_current_view_preservation() -> None:
    admin = _source("ui/layouts/admin_layout.py")
    employee = _source("ui/layouts/user_layout.py")
    assert "preserve_current_view(" in admin
    assert 'portal_mode="admin"' in admin
    assert "preserve_current_view(" in employee
    assert 'portal_mode="employee"' in employee


def test_preserver_keeps_scroll_tabs_and_expanders_without_widget_state() -> None:
    source = _source("ui/components/view_state_preservation.py")
    assert "scrollTop" in source
    assert 'button[role="tab"]' in source
    assert 'data-testid="stExpander"' in source
    assert "sessionStorage" in source
    assert 'addEventListener("pointerdown"' in source
    assert "removeEventListener" in source
    assert "controllerKey" in source
    assert "st.session_state" not in source
    assert "use_container_width" not in source


def test_no_literal_widget_uses_both_default_and_assigned_session_key() -> None:
    """Guard the exact Streamlit warning pattern seen in earlier builds."""

    assigned: set[str] = set()
    widgets_with_defaults: set[str] = set()
    widget_names = {
        "selectbox",
        "multiselect",
        "radio",
        "number_input",
        "text_input",
        "text_area",
        "date_input",
        "time_input",
        "checkbox",
        "toggle",
        "slider",
        "tabs",
        "segmented_control",
    }
    for path in (ROOT / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "session_state"
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        assigned.add(target.slice.value)
                    elif (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "session_state"
                    ):
                        assigned.add(target.attr)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in widget_names
            ):
                keywords = {item.arg: item.value for item in node.keywords if item.arg}
                key = keywords.get("key")
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and {"value", "default", "index"}.intersection(keywords)
                ):
                    widgets_with_defaults.add(key.value)
    assert assigned.isdisjoint(widgets_with_defaults)


def test_company_form_tabs_and_leave_detail_use_one_initial_value_source() -> None:
    admin_forms = _source("ui/pages/admin/company_forms_documents_page.py")
    employee_forms = _source("ui/pages/user/company_forms_documents_page.py")
    leave = _source("ui/pages/user/leave_management_page.py")
    assert 'key="company_forms_active_tab",\n        default=' not in admin_forms
    assert 'key="employee_company_forms_active_tab",\n        default=' not in employee_forms
    detail_start = leave.index('selected_id = st.selectbox(')
    detail_block = leave[detail_start:leave.index("with SessionFactory()", detail_start)]
    assert 'key="employee_request_detail"' in detail_block
    assert "index=selected_index" not in detail_block
