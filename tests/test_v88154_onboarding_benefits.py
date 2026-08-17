"""Static regression checks for consolidated onboarding and benefits."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_employee_navigation_consolidates_benefits_into_onboarding() -> None:
    constants = _source("core/constants.py")
    layout = _source("ui/layouts/user_layout.py")
    page = _source("ui/pages/user/onboarding_page.py")

    navigation = constants.split("USER_NAVIGATION = (", 1)[1].split(")", 1)[0]
    assert '"Onboarding"' in navigation
    assert '"Benefits"' not in navigation
    assert 'current_page in {"Onboarding", "Benefits"}' in layout
    assert 'st.query_params["onboarding_view"] = "benefits"' in layout
    assert '["Overview", "Checklist", "Benefits"]' in page


def test_admin_employees_contains_onboarding_management() -> None:
    employees = _source("ui/pages/admin/employees_page.py")
    admin_page = _source("ui/pages/admin/onboarding_management.py")
    routes = _source("ui/module_view_navigation.py")

    assert '"Onboarding Management"' in employees
    assert "render_onboarding_management(current_user)" in employees
    assert '["Employee Progress", "Checklist Setup", "Benefits Management"]' in admin_page
    assert '"onboarding": "Onboarding Management"' in routes
    assert '"benefits": "Benefits"' in routes


def test_onboarding_data_is_company_scoped_and_bootstrapped() -> None:
    model = _source("models/onboarding.py")
    service = _source("services/onboarding_service.py")
    runtime = _source("database/runtime_schema.py")

    assert 'ForeignKey("companies.id", ondelete="CASCADE")' in model
    assert 'UniqueConstraint(\n            "company_id",\n            "employee_id"' in model
    assert '"onboarding_checklist_items"' in runtime
    assert '"employee_onboarding_progress"' in runtime
    assert '"company_benefits"' in runtime
    assert "ensure_default_checklist" in service
    assert 'auto_rule == "password_changed"' in service
    assert 'auto_rule == "first_time_in"' in service
    assert 'auto_rule == "training_complete"' in service


def test_exact_links_and_warning_free_component_rules_are_preserved() -> None:
    paths = (
        "ui/pages/admin/onboarding_management.py",
        "ui/pages/user/onboarding_page.py",
        "services/onboarding_service.py",
    )
    combined = "\n".join(_source(path) for path in paths)
    assistant = _source("modules/hr_assistant/hr_assistant.py")
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert 'query_params={"onboarding_view": "benefits"}' in assistant
    assert "components.v1.html" not in combined
    assert "components.html" not in combined
    assert "use_container_width" not in combined
    assert 'app_version: str = "0.8.8.' in settings
    assert "v8.8.154 — Consolidated Employee Onboarding and Benefits" in readme
