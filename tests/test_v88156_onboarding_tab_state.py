"""Static regression checks for warning-free onboarding tab restoration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_onboarding_navigation_is_deferred_until_before_tab_instantiation() -> None:
    onboarding = _source("ui/pages/admin/onboarding_management.py")
    employees = _source("ui/pages/admin/employees_page.py")

    helper = onboarding.split("def _stay_on_onboarding", 1)[1].split(
        "def _destination_fields", 1
    )[0]
    assert 'st.session_state["employees_active_tab"]' not in helper
    assert 'st.session_state["admin_onboarding_management_active_tab"]' not in helper
    assert 'st.session_state["employees_pending_active_tab"]' in helper
    assert 'st.session_state["admin_onboarding_management_pending_active_tab"]' in helper

    employee_pending = employees.index('st.session_state.pop("employees_pending_active_tab"')
    employee_tabs = employees.index("= st.tabs(", employee_pending)
    assert employee_pending < employee_tabs

    subtab_pending = onboarding.index(
        'st.session_state.pop(\n        "admin_onboarding_management_pending_active_tab"'
    )
    subtab_widget = onboarding.index("= st.tabs(", subtab_pending)
    assert subtab_pending < subtab_widget


def test_benefit_management_actions_remain_visible_without_active_records() -> None:
    onboarding = _source("ui/pages/admin/onboarding_management.py")

    assert 'with st.expander("Add Benefit"' in onboarding
    assert 'with st.expander("Edit Benefit"' in onboarding
    assert 'with st.expander("Delete / Move Benefit to Archive"' in onboarding
    assert 'st.info("No active benefit is available to edit.")' in onboarding
    assert 'st.info("No active benefit is available to move to Archive.")' in onboarding


def test_v88156_keeps_deprecated_api_bans() -> None:
    onboarding = _source("ui/pages/admin/onboarding_management.py")
    employees = _source("ui/pages/admin/employees_page.py")
    settings = _source("config/settings.py")
    readme = _source("README.md")

    for source in (onboarding, employees):
        assert "components.html(" not in source
        assert "st.components.v1.html(" not in source
        assert "use_container_width" not in source
    assert 'app_version: str = "0.8.8.156"' in settings
    assert "v8.8.156 — Stable Onboarding Tab State and Visible Benefit Actions" in readme
