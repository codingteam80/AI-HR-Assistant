"""Static regression checks for onboarding and benefit safe archive."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_checklist_safe_archive_and_restore_are_available() -> None:
    page = _source("ui/pages/admin/onboarding_management.py")
    service = _source("services/onboarding_service.py")

    assert '"Delete / Move Checklist Item to Archive"' in page
    assert '"Move Checklist Item to Archive"' in page
    assert '"Restore Checklist Item"' in page
    assert "archive_checklist_item" in service
    assert "restore_checklist_item" in service
    assert "item.is_active = False" in service
    assert "item.is_active = True" in service
    assert "self.session.delete(item)" not in service


def test_benefit_add_edit_archive_and_restore_are_available() -> None:
    page = _source("ui/pages/admin/onboarding_management.py")
    service = _source("services/onboarding_service.py")

    assert 'with st.expander("Add Benefit"' in page
    assert 'with st.expander("Edit Benefit"' in page
    assert '"Delete / Move Benefit to Archive"' in page
    assert '"Move Benefit to Archive"' in page
    assert '"Restore Benefit"' in page
    assert "archive_benefit" in service
    assert "restore_benefit" in service
    assert "benefit.is_active = False" in service
    assert "benefit.is_active = True" in service
    assert "self.session.delete(benefit)" not in service


def test_archive_actions_preserve_view_and_warning_free_rules() -> None:
    page = _source("ui/pages/admin/onboarding_management.py")
    settings = _source("config/settings.py")
    readme = _source("README.md")

    assert '_stay_on_onboarding("Checklist Setup")' in page
    assert '_stay_on_onboarding("Benefits Management")' in page
    assert "disabled=not archive_confirmed" in page
    assert "components.html(" not in page
    assert "st.components.v1.html(" not in page
    assert "use_container_width" not in page
    assert 'app_version: str = "0.8.8.155"' in settings
    assert "v8.8.155 — Onboarding and Benefits Safe Archive" in readme
