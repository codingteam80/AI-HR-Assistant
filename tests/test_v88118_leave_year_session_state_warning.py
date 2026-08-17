"""Regression checks for v8.8.118 Leave Year widget state."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _leave_year_widget_block() -> str:
    source = _source("ui/pages/admin/leave_management_page.py")
    return source.split(
        "selected_year = int(", 1
    )[1].split(
        "with SessionFactory() as session:", 1
    )[0]


def test_leave_year_widget_has_only_one_value_source() -> None:
    source = _source("ui/pages/admin/leave_management_page.py")
    widget = _leave_year_widget_block()

    assert 'st.session_state["leave_management_year"] = notification_year' in source
    assert '"leave_management_year" not in st.session_state' in source
    assert 'st.session_state["leave_management_year"] = _current_leave_year()' in source
    assert 'key="leave_management_year"' in widget
    assert "\n            value=" not in widget


def test_leave_year_design_and_range_are_unchanged() -> None:
    widget = _leave_year_widget_block()

    assert '"Leave Year"' in widget
    assert "min_value=2000" in widget
    assert "max_value=2200" in widget
    assert "step=1" in widget
    assert "The selected year applies to Overview" in widget


def test_v88118_release_remains_documented_after_later_checkpoints() -> None:
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.118 — Warning-Free Leave Year State" in readme
