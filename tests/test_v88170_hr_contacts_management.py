"""v8.8.170 HR Contacts display and Company Profile management checks."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from database.base import Base
from models.company import Company
from services.hr_contact_service import HRContactService


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _company(session, code: str) -> Company:
    company = Company(code=code, name=f"{code} Company", is_active=True)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


def test_hr_contacts_are_company_scoped_and_active_only() -> None:
    factory = _factory()
    with factory() as session:
        first = _company(session, "FIRST")
        second = _company(session, "SECOND")
        service = HRContactService(session)
        contact = service.create_contact(
            company_id=first.id,
            values={
                "name": "HR Help Desk",
                "job_title": "HR Operations",
                "email": "hr@example.com",
                "sort_order": 10,
            },
        )
        service.create_contact(
            company_id=second.id,
            values={
                "name": "Other Company HR",
                "phone": "+63 900 000 0000",
                "sort_order": 10,
            },
        )

        assert [row.id for row in service.list_contacts(first.id, active_only=True)] == [
            contact.id
        ]
        assert len(service.list_contacts(second.id, active_only=True)) == 1

        with pytest.raises(ValueError):
            service.update_contact(
                company_id=second.id,
                contact_id=contact.id,
                values={"name": "Wrong Tenant", "email": "wrong@example.com"},
            )


def test_hr_contact_archive_restore_and_permanent_delete_lifecycle() -> None:
    factory = _factory()
    with factory() as session:
        company = _company(session, "LIFE")
        service = HRContactService(session)
        contact = service.create_contact(
            company_id=company.id,
            values={"name": "HR Manager", "email": "manager@example.com"},
        )

        service.archive_contact(
            company_id=company.id,
            contact_id=contact.id,
            archived_by_user_id=999,
        )
        assert service.list_contacts(company.id, active_only=True) == []
        assert service.list_contacts(company.id)[0].is_active is False

        service.restore_contact(company_id=company.id, contact_id=contact.id)
        assert service.list_contacts(company.id, active_only=True)[0].id == contact.id

        with pytest.raises(ValueError):
            service.permanently_delete_contact(
                company_id=company.id,
                contact_id=contact.id,
            )

        service.archive_contact(
            company_id=company.id,
            contact_id=contact.id,
            archived_by_user_id=999,
        )
        service.permanently_delete_contact(
            company_id=company.id,
            contact_id=contact.id,
        )
        assert service.list_contacts(company.id) == []


def test_hr_contact_requires_name_and_one_contact_method() -> None:
    factory = _factory()
    with factory() as session:
        company = _company(session, "VALID")
        service = HRContactService(session)

        with pytest.raises(ValueError, match="Contact name"):
            service.create_contact(
                company_id=company.id,
                values={"name": "", "email": "hr@example.com"},
            )

        with pytest.raises(ValueError, match="email address or phone"):
            service.create_contact(
                company_id=company.id,
                values={"name": "HR Contact"},
            )


def test_employee_hr_contacts_is_a_real_read_only_page() -> None:
    layout = _source("ui/layouts/user_layout.py")
    page = _source("ui/pages/user/hr_contacts_page.py")

    assert 'elif current_page == "HR Contacts":' in layout
    assert "render_employee_hr_contacts_page(current_user)" in layout
    assert 'st.title("HR Contacts")' in page
    assert "active_only=True" in page
    assert "create_contact" not in page
    assert "update_contact" not in page
    assert "archive_contact" not in page
    assert "Permanently Delete" not in page


def test_company_profile_has_hr_contacts_management_tab_and_crud_controls() -> None:
    company_page = _source("ui/pages/admin/company_page.py")
    management = _source("ui/pages/admin/hr_contacts_management.py")

    assert '["Company Information", "Branding", "HR Contacts"]' in company_page
    assert "render_hr_contacts_management(current_user)" in company_page
    assert '"Add HR Contact"' in management
    assert '"Save HR Contact Changes"' in management
    assert '"Move HR Contact to Archive"' in management
    assert '"Restore HR Contact"' in management
    assert '"Permanently Delete"' in management
    assert 'st.session_state["company_profile_pending_active_tab"] = "HR Contacts"' in management


def test_runtime_schema_registers_hr_contacts_and_current_version() -> None:
    runtime = _source("database/runtime_schema.py")
    model_init = _source("models/__init__.py")
    settings = _source("config/settings.py")
    env = _source(".env.example")

    assert '"hr_contacts",' in runtime
    assert "from models.hr_contact import HRContact" in model_init
    assert 'app_version: str = "0.8.8.170"' in settings
    assert "APP_VERSION=0.8.8.170" in env
