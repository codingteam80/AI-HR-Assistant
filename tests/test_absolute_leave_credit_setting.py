"""Regression tests for exact, non-negative leave-credit setting."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from models.employee import Employee
from schemas.leave_schema import LeaveCreditBalanceSetInput
from scripts.create_initial_data import seed_initial_data
from services.leave_service import LeaveService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="ABSLEAVE",
        initial_company_name="Absolute Leave Company",
        initial_admin_username="admin",
        initial_admin_email="absolute.leave@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
        leave_attachment_dir=str(
            tmp_path / "leave_files"
        ),
        password_reset_outbox_dir=str(
            tmp_path / "outbox"
        ),
    )


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:"
    )
    Base.metadata.create_all(engine)

    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )


def _employee(session, seed) -> Employee:
    employee = Employee(
        company_id=seed["company"].id,
        manager_id=seed["admin_employee"].id,
        employee_number="EMP-ABS-001",
        first_name="Liza",
        last_name="Santos",
        work_email="liza@example.com",
        employment_status="employed",
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)

    return employee


def test_setting_10_changes_15_to_exactly_10(
    tmp_path: Path,
) -> None:
    factory = _factory()

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee = _employee(session, seed)
        service = LeaveService(
            session,
            settings=settings,
        )
        vacation = next(
            item
            for item in service.list_employee_balances(
                seed["company"].id,
                employee.id,
            )
            if item.leave_type.code == "VACATION"
        )

        assert Decimal(vacation.remaining_days) == Decimal(
            "15.00"
        )

        result = service.set_credit_balance(
            LeaveCreditBalanceSetInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                leave_type_id=vacation.leave_type_id,
                year=date.today().year,
                new_remaining_days=Decimal("10.00"),
                reason="Correct employee balance",
                created_by_user_id=seed["admin_user"].id,
            )
        )

        assert result.previous_remaining == Decimal("15.00")
        assert result.new_remaining == Decimal("10.00")
        assert Decimal(
            result.balance.remaining_days
        ) == Decimal("10.00")

        history = service.list_credit_history(
            seed["company"].id,
            employee.id,
        )
        entry = next(
            item
            for item in history
            if item.transaction_type
            == "manual_balance_set"
        )

        assert Decimal(entry.amount_days) == Decimal("10.00")
        assert "Previous balance: 15.00 days" in entry.note
        assert "New balance: 10.00 days" in entry.note
        assert "Correct employee balance" not in entry.note


def test_setting_25_changes_15_to_exactly_25(
    tmp_path: Path,
) -> None:
    factory = _factory()

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee = _employee(session, seed)
        service = LeaveService(
            session,
            settings=settings,
        )
        vacation = next(
            item
            for item in service.list_employee_balances(
                seed["company"].id,
                employee.id,
            )
            if item.leave_type.code == "VACATION"
        )

        result = service.set_credit_balance(
            LeaveCreditBalanceSetInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                leave_type_id=vacation.leave_type_id,
                year=date.today().year,
                new_remaining_days=Decimal("25.00"),
                reason="Approved balance update",
                created_by_user_id=seed["admin_user"].id,
            )
        )

        assert Decimal(
            result.balance.remaining_days
        ) == Decimal("25.00")


def test_negative_new_balance_is_rejected() -> None:
    try:
        LeaveCreditBalanceSetInput(
            company_id=1,
            employee_id=1,
            leave_type_id=1,
            year=2026,
            new_remaining_days=Decimal("-1.00"),
            reason="Invalid value",
            created_by_user_id=1,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError(
            "A negative leave-credit value was accepted."
        )


def test_same_balance_does_not_create_history(
    tmp_path: Path,
) -> None:
    factory = _factory()

    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee = _employee(session, seed)
        service = LeaveService(
            session,
            settings=settings,
        )
        vacation = next(
            item
            for item in service.list_employee_balances(
                seed["company"].id,
                employee.id,
            )
            if item.leave_type.code == "VACATION"
        )

        try:
            service.set_credit_balance(
                LeaveCreditBalanceSetInput(
                    company_id=seed["company"].id,
                    employee_id=employee.id,
                    leave_type_id=vacation.leave_type_id,
                    year=date.today().year,
                    new_remaining_days=Decimal("15.00"),
                    reason="No actual change",
                    created_by_user_id=seed["admin_user"].id,
                )
            )
        except ValueError as error:
            assert "already has" in str(error)
        else:
            raise AssertionError(
                "An unchanged balance should not be saved."
            )


def test_admin_ui_uses_absolute_non_negative_input() -> None:
    source = (
        PROJECT_ROOT
        / "ui/pages/admin/leave_management_page.py"
    ).read_text(encoding="utf-8")

    editor = source.split(
        "def _render_credit_balance_editor(",
        1,
    )[1].split(
        "def _credit_history_entry(",
        1,
    )[0]

    assert '"New Leave Credits"' in editor
    assert "min_value=0.0" in editor
    assert "value=_nonnegative_editor_value(current_remaining)" in editor
    assert '"Save Leave Credits"' in editor
    assert "set_credit_balance(values)" in editor
    assert "Adjustment Days" not in editor
    assert "Positive values add credits" not in editor
    assert "negative values" not in editor.lower()


def test_visible_breakdown_does_not_inflate_credit_with_adjustment() -> None:
    source = (
        PROJECT_ROOT
        / "ui/pages/admin/leave_management_page.py"
    ).read_text(encoding="utf-8")

    breakdown = source.split(
        "def _render_credit_breakdown(",
        1,
    )[1].split(
        "def _render_credit_balance_editor(",
        1,
    )[0]

    assert '"Current Credits"' in breakdown
    assert '"Adjustment":' not in breakdown
    assert "credit_days" in breakdown
    assert "adjustment_days" not in breakdown
    assert "corrections affect Available" in breakdown


def test_employee_tab_is_named_set_leave_credits() -> None:
    source = (
        PROJECT_ROOT
        / "ui/pages/admin/leave_management_page.py"
    ).read_text(encoding="utf-8")

    assert '"Set Leave Credits"' in source
    assert '"Adjust Credits"' not in source


def test_credit_form_has_no_reason_field() -> None:
    source = (
        PROJECT_ROOT
        / "ui/pages/admin/leave_management_page.py"
    ).read_text(encoding="utf-8")

    editor = source.split(
        "def _render_credit_balance_editor(",
        1,
    )[1].split(
        "def _credit_history_entry(",
        1,
    )[0]

    assert "Reason for Change" not in editor
    assert "Adjustment Reason" not in editor
    assert "st.text_input(" not in editor
    assert 'reason="Manual leave credit update"' in editor

