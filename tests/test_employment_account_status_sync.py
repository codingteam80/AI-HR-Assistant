"""Employment status and login-account synchronization tests."""

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from schemas.admin_management_schema import (
    EmployeeAccountCreate,
    EmployeeMasterUpdate,
)
from scripts.create_initial_data import seed_initial_data
from services.admin_management_service import (
    AdminManagementService,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="STATUS",
        initial_company_name="Status Company",
        initial_admin_username="admin",
        initial_admin_email="admin.status@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )


def _create_employee(
    service: AdminManagementService,
    company_id: int,
    *,
    number: str,
    username: str,
    email: str,
    status: str,
):
    return service.create_employee_with_optional_account(
        EmployeeAccountCreate(
            company_id=company_id,
            employee_number=number,
            first_name="Test",
            last_name="Employee",
            work_email=email,
            employment_status=status,
            create_login_account=True,
            username=username,
            login_email=email,
            temporary_password="Temporary456!",
            clearance=2,
        )
    )


def _change_status(
    service: AdminManagementService,
    employee,
    *,
    status: str,
    current_user_id: int,
):
    return service.update_employee_master_record(
        EmployeeMasterUpdate(
            company_id=employee.company_id,
            employee_id=employee.id,
            expected_edit_version=employee.edit_version,
            employee_number=employee.employee_number,
            first_name=employee.first_name,
            middle_name=employee.middle_name,
            last_name=employee.last_name,
            suffix=employee.suffix,
            work_email=employee.work_email,
            job_title=employee.job_title,
            hire_date=employee.hire_date,
            employment_status=status,
            department_name=(
                employee.department.name
                if employee.department
                else None
            ),
            manager_id=employee.manager_id,
            trainings=[],
            username=employee.user.username,
            clearance=employee.user.clearance,
        ),
        current_user_id=current_user_id,
    )


def test_employed_account_is_active_when_created() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        employee = _create_employee(
            AdminManagementService(session),
            seed["company"].id,
            number="EMP-101",
            username="active.employee",
            email="active@example.com",
            status="employed",
        )

        assert employee.employment_status == "employed"
        assert employee.user.is_active is True


def test_resigned_account_is_inactive_when_created() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        employee = _create_employee(
            AdminManagementService(session),
            seed["company"].id,
            number="EMP-102",
            username="resigned.employee",
            email="resigned@example.com",
            status="resigned",
        )

        assert employee.employment_status == "resigned"
        assert employee.user.is_active is False


def test_employed_to_resigned_deactivates_account() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        service = AdminManagementService(session)
        employee = _create_employee(
            service,
            seed["company"].id,
            number="EMP-103",
            username="leaving.employee",
            email="leaving@example.com",
            status="employed",
        )

        updated = _change_status(
            service,
            employee,
            status="resigned",
            current_user_id=seed["admin_user"].id,
        )

        assert updated.employment_status == "resigned"
        assert updated.user.is_active is False


def test_resigned_to_employed_reactivates_account() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        service = AdminManagementService(session)
        employee = _create_employee(
            service,
            seed["company"].id,
            number="EMP-104",
            username="returning.employee",
            email="returning@example.com",
            status="resigned",
        )

        updated = _change_status(
            service,
            employee,
            status="employed",
            current_user_id=seed["admin_user"].id,
        )

        assert updated.employment_status == "employed"
        assert updated.user.is_active is True
