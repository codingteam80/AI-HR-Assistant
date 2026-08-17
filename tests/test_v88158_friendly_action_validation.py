"""Regression checks for project-wide friendly action warnings."""

from pathlib import Path

from pydantic import ValidationError

from schemas.attendance_schema import AttendanceSelfEditInput
from ui.components.validation_feedback import action_warning_messages


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_attendance_model_error_is_converted_to_a_readable_warning() -> None:
    try:
        AttendanceSelfEditInput.model_validate(
            {
                "company_id": 1,
                "employee_id": 1,
                "user_id": 1,
                "attendance_date": "2026-08-14",
                "work_status": "WFO",
                "sessions": [
                    {
                        "work_status": "WFO",
                        "time_in": "2026-08-14T08:00:00+08:00",
                        "time_out": None,
                    },
                    {
                        "work_status": "WFH",
                        "time_in": "2026-08-14T13:00:00+08:00",
                        "time_out": None,
                    },
                ],
            }
        )
    except ValidationError as error:
        messages = action_warning_messages(error)
    else:
        raise AssertionError("Expected attendance validation to fail")

    assert messages == [
        "Complete the Time Out for every attendance session before the final "
        "session. Only the final session may remain open."
    ]
    assert "errors.pydantic.dev" not in " ".join(messages)
    assert "input_value" not in " ".join(messages)


def test_ui_pages_do_not_render_raw_expected_exception_strings() -> None:
    page_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "ui" / "pages").rglob("*.py")
    )
    assert "st.error(str(error))" not in page_sources
    assert 'st.error(error.errors()[0]["msg"])' not in page_sources
    assert "st.error(_validation_message(error))" not in page_sources
    assert page_sources.count("render_action_warning(error)") >= 70


def test_v88158_preserves_warning_free_api_rules_and_version() -> None:
    component = _source("ui/components/validation_feedback.py")
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert "include_url=False" in component
    assert "include_input=False" in component
    assert "components.html(" not in component
    assert "st.components.v1.html(" not in component
    assert "use_container_width" not in component
    assert 'app_version: str = "0.8.8.158"' in settings
    assert "v8.8.158 — Project-wide Friendly Action Validation" in readme
