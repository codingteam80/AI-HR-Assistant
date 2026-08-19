"""v8.8.68 Company Form/Documents module regression tests."""

from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from modules.documents.company_form_file_storage import CompanyFormFileStorage
from repositories.role_repository import RoleRepository
from schemas.user_schema import EmployeeCreate, UserCreate
from scripts.create_initial_data import seed_initial_data
from services.company_form_service import CompanyFormService
from services.employee_service import EmployeeService
from services.user_service import UserService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="FORMS",
        initial_company_name="Forms Company",
        initial_admin_username="forms.admin",
        initial_admin_email="forms.admin@example.com",
        initial_admin_password=SecretStr("ChangeMe123!"),
        initial_admin_employee_number="ADMIN-FORMS-001",
        initial_admin_first_name="Forms",
        initial_admin_last_name="Administrator",
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _employee(session, seed):
    role = RoleRepository(session).get_by_name(
        seed["company"].id,
        "employee",
    )
    user = UserService(session).create_user(
        UserCreate(
            company_id=seed["company"].id,
            role_id=role.id,
            clearance=2,
            username="form.employee",
            email="form.employee@example.com",
            password="Employee123!",
        ),
        must_change_password=False,
    )
    employee = EmployeeService(session).create_employee(
        EmployeeCreate(
            company_id=seed["company"].id,
            user_id=user.id,
            employee_number="FORM-EMP-001",
            first_name="Form",
            last_name="Employee",
            work_email="form.employee@example.com",
        )
    )
    return user, employee


def test_admin_and_employee_tabs_and_scroll_boxes_are_present() -> None:
    admin_page = (
        PROJECT_ROOT / "ui/pages/admin/company_forms_documents_page.py"
    ).read_text(encoding="utf-8")
    employee_page = (
        PROJECT_ROOT / "ui/pages/user/company_forms_documents_page.py"
    ).read_text(encoding="utf-8")

    assert 'TAB_LABELS = ["Overview", "Upload Form", "Manage Form", "Bin"]' in admin_page
    assert (
        'EMPLOYEE_FORM_TABS = ["View", "Download", "Fill / Submit", "My Documents"]'
        in employee_page
    )
    assert "st.container(height=" in admin_page
    assert "st.container(height=" in employee_page
    assert "render_selectable_admin_table(" in admin_page
    assert "render_selectable_admin_table(" in employee_page
    assert "height=" in admin_page
    assert "height=" in employee_page


def test_employee_navigation_and_route_are_available() -> None:
    constants = (PROJECT_ROOT / "core/constants.py").read_text(encoding="utf-8")
    layout = (PROJECT_ROOT / "ui/layouts/user_layout.py").read_text(encoding="utf-8")

    assert '"Company Form/Documents"' in constants
    assert 'current_page == "Company Form/Documents"' in layout
    assert "render_employee_company_forms_documents_page" in layout


def test_upload_submit_notify_review_and_download(tmp_path: Path) -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        employee_user, employee = _employee(session, seed)
        service = CompanyFormService(
            session,
            storage=CompanyFormFileStorage(tmp_path),
        )

        form = service.upload_form(
            company_id=seed["company"].id,
            uploaded_by_user_id=seed["admin_user"].id,
            title="Employee Data Update Form",
            category="Employee Record",
            description="Update personal employee information.",
            allow_employee_submission=True,
            filename="employee_update_form.docx",
            file_bytes=b"template bytes",
            maximum_size_bytes=1024 * 1024,
        )

        assert form.public_id.startswith("FORM_")
        assert service.get_form_download(
            company_id=seed["company"].id,
            form_id=form.id,
        ).data == b"template bytes"

        submission = service.submit_completed_form(
            company_id=seed["company"].id,
            form_id=form.id,
            employee_id=employee.id,
            submitted_by_user_id=employee_user.id,
            notes="Please process my updated information.",
            filename="completed_employee_update.pdf",
            file_bytes=b"completed bytes",
            maximum_size_bytes=1024 * 1024,
        )

        assert submission.public_id.startswith("FSUB_")
        assert service.submissions.count_pending(seed["company"].id) == 1
        assert service.notifications.unread_count(
            company_id=seed["company"].id,
            user_id=seed["admin_user"].id,
        ) >= 1
        assert service.get_submission_download(
            company_id=seed["company"].id,
            submission_id=submission.id,
            employee_id=employee.id,
        ).data == b"completed bytes"

        service.update_submission_status(
            company_id=seed["company"].id,
            submission_id=submission.id,
            reviewed_by_user_id=seed["admin_user"].id,
            status="approved",
            admin_note="Approved and recorded.",
        )

        refreshed = service.submissions.get_by_id(
            submission.id,
            seed["company"].id,
        )
        assert refreshed.status == "approved"
        assert refreshed.admin_note == "Approved and recorded."
        assert service.notifications.unread_count(
            company_id=seed["company"].id,
            user_id=employee_user.id,
        ) >= 1


def test_employee_cannot_download_another_employees_submission(tmp_path: Path) -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        employee_user, employee = _employee(session, seed)
        service = CompanyFormService(
            session,
            storage=CompanyFormFileStorage(tmp_path),
        )
        form = service.upload_form(
            company_id=seed["company"].id,
            uploaded_by_user_id=seed["admin_user"].id,
            title="Security Form",
            category="Compliance",
            description="",
            allow_employee_submission=True,
            filename="security_form.pdf",
            file_bytes=b"template",
            maximum_size_bytes=1024 * 1024,
        )
        submission = service.submit_completed_form(
            company_id=seed["company"].id,
            form_id=form.id,
            employee_id=employee.id,
            submitted_by_user_id=employee_user.id,
            notes="",
            filename="completed.pdf",
            file_bytes=b"private",
            maximum_size_bytes=1024 * 1024,
        )

        try:
            service.get_submission_download(
                company_id=seed["company"].id,
                submission_id=submission.id,
                employee_id=employee.id + 999,
            )
        except ValueError as error:
            assert "another employee" in str(error)
        else:
            raise AssertionError("Cross-employee submission access was allowed.")


def test_bin_hides_form_from_employee_and_restore_returns_it(tmp_path: Path) -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        service = CompanyFormService(
            session,
            storage=CompanyFormFileStorage(tmp_path),
        )
        form = service.upload_form(
            company_id=seed["company"].id,
            uploaded_by_user_id=seed["admin_user"].id,
            title="Bin Form",
            category="General",
            description="",
            allow_employee_submission=False,
            filename="bin_form.txt",
            file_bytes=b"form",
            maximum_size_bytes=1024 * 1024,
        )
        service.move_to_bin(
            company_id=seed["company"].id,
            form_id=form.id,
            user_id=seed["admin_user"].id,
        )
        assert service.list_active_forms(seed["company"].id) == []
        assert len(service.list_bin_forms(seed["company"].id)) == 1

        service.restore_from_bin(
            company_id=seed["company"].id,
            form_id=form.id,
        )
        assert len(service.list_active_forms(seed["company"].id)) == 1


def test_notification_deep_links_target_company_forms_workspace() -> None:
    topbar = (PROJECT_ROOT / "ui/components/topbar.py").read_text(encoding="utf-8")

    assert 'return "admin", "Company Form/Documents"' in topbar
    assert 'return "employee", "Company Form/Documents"' in topbar
    assert '"company_forms_next_tab"' in topbar


def test_company_forms_regression_checkpoint_remains_covered() -> None:
    settings = (PROJECT_ROOT / "config/settings.py").read_text(encoding="utf-8")
    assert 'app_version: str = "0.8.8.' in settings
    assert (PROJECT_ROOT / "ui/pages/admin/company_forms_documents_page.py").is_file()
    assert (PROJECT_ROOT / "ui/pages/user/company_forms_documents_page.py").is_file()
