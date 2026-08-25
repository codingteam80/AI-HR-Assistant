"""v8.8.171 Employee HR Contacts compact card spacing checks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_employee_hr_contact_cards_use_compact_scoped_spacing() -> None:
    page = _source("ui/pages/user/hr_contacts_page.py")

    assert '.hr-contact-card-content {' in page
    assert '.hr-contact-detail {' in page
    assert 'margin: 0.24rem 0;' in page
    assert 'line-height: 1.32;' in page
    assert 'class="hr-contact-detail"' in page
    assert 'unsafe_allow_html=True' in page


def test_employee_hr_contact_values_are_escaped_and_read_only() -> None:
    page = _source("ui/pages/user/hr_contacts_page.py")

    assert 'from html import escape' in page
    assert 'escape(contact.name)' in page
    assert 'escape(contact.office_location)' in page
    assert 'escape(contact.notes)' in page
    assert 'create_contact' not in page
    assert 'update_contact' not in page
    assert 'archive_contact' not in page


def test_current_version_is_v88171() -> None:
    settings = _source("config/settings.py")
    env = _source(".env.example")

    assert 'app_version: str = "0.8.8.171"' in settings
    assert 'APP_VERSION=0.8.8.171' in env
