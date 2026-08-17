"""Tests for employee create, edit, and delete operation feedback."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    """Read one source file."""

    return (
        PROJECT_ROOT / relative_path
    ).read_text(encoding="utf-8")


def test_feedback_component_persists_across_rerun() -> None:
    """A completed result must be stored then consumed next render."""

    source = _read(
        "ui/components/operation_feedback.py"
    )

    assert "st.session_state[_FEEDBACK_STATE_KEY]" in source
    assert "st.session_state.pop(" in source
    assert "st.toast(" in source
    assert "st.success" in source


def test_add_employee_has_loading_and_success_feedback() -> None:
    """Create operation must show loading and persistent completion."""

    source = _read(
        "ui/pages/admin/employees_page.py"
    )

    assert (
        '"Creating employee record and login account…"'
        in source
    )
    assert "create_employee_with_optional_account(" in source
    assert (
        '"Employee record created successfully: "'
        in source
    )


def test_edit_employee_has_loading_and_success_feedback() -> None:
    """Edit operation must show loading and persistent completion."""

    source = _read(
        "ui/pages/admin/employees_page.py"
    )

    assert '"Saving employee changes…"' in source
    assert "update_employee_master_record(" in source
    assert (
        '"Employee record updated successfully: "'
        in source
    )


def test_delete_employee_has_loading_and_success_feedback() -> None:
    """Delete operation must show loading and persistent completion."""

    source = _read(
        "ui/pages/admin/employees_page.py"
    )

    assert (
        '"Permanently deleting employee record…"'
        in source
    )
    assert "delete_employee_master_record(" in source
    assert (
        '"Employee permanently deleted: "'
        in source
    )


def test_success_is_saved_before_each_rerun() -> None:
    """Each successful operation must queue feedback before rerunning."""

    source = _read(
        "ui/pages/admin/employees_page.py"
    )

    # Create, edit, delete, bulk import, and archive restoration all preserve
    # a completion message across their Streamlit rerun.
    assert source.count("set_operation_feedback(") == 5
    assert source.count("st.rerun()") >= 3


def test_feedback_renders_at_top_of_employees_page() -> None:
    """The result banner must render before employee data and tabs."""

    source = _read(
        "ui/pages/admin/employees_page.py"
    )

    render_position = source.rindex(
        "render_operation_feedback()"
    )
    data_position = source.rindex(
        "with SessionFactory() as session:"
    )

    assert render_position < data_position
