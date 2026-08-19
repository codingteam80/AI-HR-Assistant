"""Tests for v8.3.0 Employee Master Record."""

from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from authentication.access_control import AccessControl
from authentication.auth_service import AuthService
from config.settings import Settings
from database.base import Base
from database.schema_upgrade import upgrade_existing_schema
from models.employee_training import EmployeeTraining
from schemas.admin_management_schema import (
    EmployeeAccountCreate,
    EmployeeMasterUpdate,
    TrainingItemInput,
)
from scripts.create_initial_data import seed_initial_data
from services.admin_management_service import (
    AdminManagementService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="MASTER",
        initial_company_name="Master Company",
        initial_admin_username="admin",
        initial_admin_email="admin.master@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    return (
        engine,
        sessionmaker(
            bind=engine,
            expire_on_commit=False,
        ),
    )


def test_seeded_admin_has_clearance_one() -> None:
    engine, factory = _factory()

    with factory() as session:
        seed_initial_data(session, _settings())

        current_user = AuthService(session).authenticate(
            company_code="MASTER",
            login_identifier="admin",
            password="Temporary123!",
        )

        assert current_user.clearance == 1
        assert AccessControl.is_admin(current_user)


def test_create_employee_with_training_and_user_clearance() -> None:
    engine, factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())

        employee = AdminManagementService(
            session
        ).create_employee_with_optional_account(
            EmployeeAccountCreate(
                company_id=seed["company"].id,
                employee_number="EMP-100",
                last_name="Santos",
                first_name="Alex",
                middle_name=None,
                suffix=None,
                work_email="alex.master@example.com",
                job_title="Developer",
                department_name="Information Technology",
                employment_status="employed",
                trainings=[
                    TrainingItemInput(
                        title="Orientation",
                        is_completed=True,
                    ),
                    TrainingItemInput(
                        title="Safety",
                        is_completed=False,
                    ),
                ],
                create_login_account=True,
                username="alex.santos",
                login_email="alex.master@example.com",
                temporary_password="Temporary456!",
                clearance=2,
            )
        )

        assert employee.department.name == "Information Technology"
        assert employee.user.clearance == 2
        assert len(employee.trainings) == 2
        assert employee.trainings[0].is_completed is True
        assert employee.trainings[1].is_completed is False


def test_edit_all_employee_and_account_fields() -> None:
    engine, factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        service = AdminManagementService(session)

        employee = service.create_employee_with_optional_account(
            EmployeeAccountCreate(
                company_id=seed["company"].id,
                employee_number="EMP-200",
                last_name="Cruz",
                first_name="Jamie",
                work_email="jamie.old@example.com",
                create_login_account=True,
                username="jamie.old",
                login_email="jamie.old@example.com",
                temporary_password="Temporary456!",
                clearance=2,
            )
        )

        updated = service.update_employee_master_record(
            EmployeeMasterUpdate(
                company_id=seed["company"].id,
                employee_id=employee.id,
                expected_edit_version=employee.edit_version,
                employee_number="EMP-201",
                last_name="Reyes",
                first_name="Jordan",
                middle_name="M",
                suffix="Jr.",
                work_email="jordan.new@example.com",
                job_title="HR Administrator",
                department_name="Human Resources",
                manager_id=None,
                employment_status="employed",
                trainings=[
                    TrainingItemInput(
                        title="Data Privacy",
                        is_completed=True,
                    )
                ],
                username="jordan.reyes",
                clearance=1,
                new_temporary_password="NewTemporary789!",
            ),
            current_user_id=seed["admin_user"].id,
        )

        assert updated.employee_number == "EMP-201"
        assert updated.full_name == "Jordan M Reyes Jr."
        assert updated.job_title == "HR Administrator"
        assert updated.department.name == "Human Resources"
        assert updated.user.username == "jordan.reyes"
        assert updated.user.email == "jordan.new@example.com"
        assert updated.user.clearance == 1
        assert updated.user.must_change_password is True
        assert updated.trainings[0].title == "Data Privacy"


def test_resigned_employee_account_is_inactive() -> None:
    engine, factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        service = AdminManagementService(session)

        employee = service.create_employee_with_optional_account(
            EmployeeAccountCreate(
                company_id=seed["company"].id,
                employee_number="EMP-300",
                last_name="Lim",
                first_name="Taylor",
                work_email="taylor@example.com",
                employment_status="employed",
                create_login_account=True,
                username="taylor.lim",
                login_email="taylor@example.com",
                temporary_password="Temporary456!",
                clearance=2,
            )
        )

        updated = service.update_employee_master_record(
            EmployeeMasterUpdate(
                company_id=seed["company"].id,
                employee_id=employee.id,
                expected_edit_version=employee.edit_version,
                employee_number=employee.employee_number,
                last_name=employee.last_name,
                first_name=employee.first_name,
                work_email=employee.work_email,
                employment_status="resigned",
                username=employee.user.username,
                clearance=2,
            ),
            current_user_id=seed["admin_user"].id,
        )

        assert updated.employment_status == "resigned"
        assert updated.user.is_active is False


def test_training_rows_are_separate_in_database() -> None:
    engine, factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())

        employee = AdminManagementService(
            session
        ).create_employee_with_optional_account(
            EmployeeAccountCreate(
                company_id=seed["company"].id,
                employee_number="EMP-400",
                last_name="Tan",
                first_name="Casey",
                trainings=[
                    TrainingItemInput(
                        title="Training A",
                        is_completed=True,
                    ),
                    TrainingItemInput(
                        title="Training B",
                        is_completed=False,
                    ),
                ],
            )
        )

        rows = list(
            session.scalars(
                select(EmployeeTraining).where(
                    EmployeeTraining.employee_id == employee.id
                )
            ).all()
        )

        assert len(rows) == 2


def test_employees_page_has_no_role_or_user_tabs() -> None:
    source = (
        PROJECT_ROOT
        / "ui/pages/admin/employees_page.py"
    ).read_text(encoding="utf-8")

    assert '"Employee List"' in source
    assert '"Add Employee"' in source
    assert '"Edit Employee"' in source
    assert '"User Accounts"' in source
    assert '"Active Accounts"' in source
    assert '"Roles & Access"' not in source
    assert '"1 - Admin"' in source
    assert '"2 - User"' in source


def test_existing_sqlite_database_receives_clearance_column() -> None:
    legacy_engine = create_engine(
        "sqlite+pysqlite:///:memory:"
    )

    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE roles (
                id INTEGER PRIMARY KEY,
                name VARCHAR(80) NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                role_id INTEGER NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO roles (id, name) "
            "VALUES (1, 'company_admin'), (2, 'employee')"
        )
        connection.exec_driver_sql(
            "INSERT INTO users (id, role_id) "
            "VALUES (1, 1), (2, 2)"
        )

    upgrade_existing_schema(legacy_engine)

    columns = {
        column["name"]
        for column in inspect(
            legacy_engine
        ).get_columns("users")
    }

    assert "clearance" in columns

    with legacy_engine.connect() as connection:
        values = connection.exec_driver_sql(
            "SELECT clearance FROM users ORDER BY id"
        ).fetchall()

    assert values == [(1,), (2,)]
