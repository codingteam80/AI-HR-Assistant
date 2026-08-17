"""Static regression checks for the compact employee onboarding checklist."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_checklist_uses_one_compact_aligned_row_without_losing_actions() -> None:
    page = _source("ui/pages/user/onboarding_page.py")

    checklist = page.split("def _render_checklist", 1)[1].split(
        "def _render_benefits", 1
    )[0]
    assert "detail_column" in checklist
    assert "status_column" in checklist
    assert "workspace_column" in checklist
    assert "completion_column" in checklist
    assert 'vertical_alignment="center"' in checklist
    assert '"Open Related Workspace"' in checklist
    assert '"Mark as Completed"' in checklist
    assert '"Mark as Pending"' in checklist
    assert "OnboardingService(session).set_progress(" in checklist
    assert "employee_self_service=True" in checklist


def test_employee_checklist_tab_restore_is_deferred_before_widget_creation() -> None:
    page = _source("ui/pages/user/onboarding_page.py")

    checklist = page.split("def _render_checklist", 1)[1].split(
        "def _render_benefits", 1
    )[0]
    assert 'st.session_state["employee_onboarding_active_tab"]' not in checklist
    assert '"employee_onboarding_pending_active_tab"' in checklist

    pending = page.index(
        'st.session_state.pop(\n        "employee_onboarding_pending_active_tab"'
    )
    tabs = page.index("= st.tabs(", pending)
    assert pending < tabs


def test_v88157_preserves_warning_free_rules_and_version() -> None:
    page = _source("ui/pages/user/onboarding_page.py")
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert "components.html(" not in page
    assert "st.components.v1.html(" not in page
    assert "use_container_width" not in page
    assert 'app_version: str = "0.8.8.157"' in settings
    assert "v8.8.157 — Compact Employee Checklist and Safe Tab Restore" in readme
