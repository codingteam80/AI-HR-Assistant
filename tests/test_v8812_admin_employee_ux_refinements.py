"""v8.8.12 admin chat, copy shortcut, phone, and delete UX tests."""

from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from database.schema_upgrade import upgrade_existing_schema
from schemas.admin_management_schema import (
    EmployeeAccountCreate,
    EmployeeMasterUpdate,
)
from scripts.create_initial_data import seed_initial_data
from services.admin_management_service import AdminManagementService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="UX12",
        initial_company_name="UX Company",
        initial_admin_username="admin",
        initial_admin_email="admin.ux@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
    )


def test_ctrl_c_uses_native_browser_copy() -> None:
    config = (
        PROJECT_ROOT / ".streamlit/config.toml"
    ).read_text(encoding="utf-8")
    theme = (
        PROJECT_ROOT / "ui/theme/theme_loader.py"
    ).read_text(encoding="utf-8")

    assert 'toolbarMode = "viewer"' in config
    assert "bindNormalCopyShortcut" not in theme
    assert "_install_native_copy_shortcut_guard" in theme
    assert "event.stopImmediatePropagation();" in theme
    assert "event.preventDefault()" not in theme


def test_admin_chat_uses_admin_quick_actions_only() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/admin/chat_page.py"
    ).read_text(encoding="utf-8")
    actions = (
        PROJECT_ROOT / "ui/components/quick_actions.py"
    ).read_text(encoding="utf-8")

    assert "render_admin_quick_actions" in source
    assert "Admin Shortcuts" not in source
    assert "Answer Sources" not in source
    assert "Manage Employees" in actions
    assert "Review Leave Requests" in actions
    assert "Manage Policies" in actions
    assert "Create Announcement" in actions


def test_employee_forms_include_telephone_mobile_number() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/admin/employees_page.py"
    ).read_text(encoding="utf-8")

    assert source.count("Telephone / Mobile No.") >= 3
    assert "telephone_mobile_no=(" in source
    assert "telephone_mobile_no.strip()" in source
    assert "employee.telephone_mobile_no" in source


def test_phone_number_is_saved_and_edited() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        service = AdminManagementService(session)
        employee = service.create_employee_with_optional_account(
            EmployeeAccountCreate(
                company_id=seed["company"].id,
                employee_number="EMP-PHONE-001",
                first_name="Phone",
                last_name="Employee",
                work_email="phone.employee@example.com",
                telephone_mobile_no="0917-123-4567",
                create_login_account=True,
                username="phone.employee",
                login_email="phone.employee@example.com",
                temporary_password="Temporary456!",
                clearance=2,
            )
        )

        assert employee.telephone_mobile_no == "0917-123-4567"

        updated = service.update_employee_master_record(
            EmployeeMasterUpdate(
                company_id=seed["company"].id,
                employee_id=employee.id,
                expected_edit_version=employee.edit_version,
                employee_number=employee.employee_number,
                first_name=employee.first_name,
                last_name=employee.last_name,
                work_email=employee.work_email,
                telephone_mobile_no="02-8123-4567",
                employment_status="employed",
                username=employee.user.username,
                clearance=2,
            ),
            current_user_id=seed["admin_user"].id,
        )

        assert updated.telephone_mobile_no == "02-8123-4567"


def test_runtime_upgrade_adds_phone_column() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE employees "
            "DROP COLUMN telephone_mobile_no"
        )

    upgrade_existing_schema(engine)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("employees")
    }
    assert "telephone_mobile_no" in columns


def test_delete_targets_current_selected_employee_with_checkbox() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/admin/employees_page.py"
    ).read_text(encoding="utf-8")

    assert "Selected employee to delete" in source
    assert "Type the exact Employee Number to confirm" not in source
    assert "employee_delete_acknowledged_" in source
    assert "employee_delete_button_" in source
    assert "disabled=not acknowledged" in source
