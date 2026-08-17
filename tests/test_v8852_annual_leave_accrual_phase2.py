"""Phase 2 tests for January SL/VL annual accrual processing."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from models.employee import Employee
from models.leave_credit_transaction import LeaveCreditTransaction
from scripts.create_initial_data import seed_initial_data
from services.leave_service import LeaveService


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="PHASE2",
        initial_company_name="Phase 2 Company",
        initial_admin_username="admin",
        initial_admin_email="admin@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
        leave_attachment_dir=str(tmp_path / "leave_files"),
        password_reset_outbox_dir=str(tmp_path / "outbox"),
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _employee(session, seed, *, number: str, hire_date: date) -> Employee:
    employee = Employee(
        company_id=seed["company"].id,
        manager_id=seed["admin_employee"].id,
        employee_number=number,
        first_name="Annual",
        last_name="Employee",
        employment_status="employed",
        hire_date=hire_date,
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


def _by_code(balances):
    return {item.leave_type.code: item for item in balances}


def test_standard_january_accrual_is_15_for_sl_and_vl(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings(tmp_path))
        employee = _employee(
            session,
            seed,
            number="EMP-NEW",
            hire_date=date(2024, 1, 1),
        )
        service = LeaveService(session, settings=_settings(tmp_path))
        balances = _by_code(
            service.list_employee_balances(
                seed["company"].id,
                employee.id,
                2026,
            )
        )

        assert Decimal(balances["VACATION"].credit_days) == Decimal("15.00")
        assert Decimal(balances["SICK"].credit_days) == Decimal("15.00")
        assert Decimal(balances["EMERGENCY"].credit_days) == Decimal("0.00")
        assert Decimal(balances["HONEYMOON"].credit_days) == Decimal("0.00")
        assert Decimal(balances["MATERNITY"].credit_days) == Decimal("0.00")
        assert Decimal(balances["PATERNITY"].credit_days) == Decimal("0.00")
        assert Decimal(balances["BEREAVEMENT"].credit_days) == Decimal("0.00")


def test_five_completed_years_on_january_first_remains_15(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings(tmp_path))
        employee = _employee(
            session,
            seed,
            number="EMP-FIVE",
            hire_date=date(2020, 1, 1),
        )
        service = LeaveService(session, settings=_settings(tmp_path))
        balances = _by_code(
            service.list_employee_balances(
                seed["company"].id,
                employee.id,
                2025,
            )
        )

        assert Decimal(balances["VACATION"].credit_days) == Decimal("15.00")
        assert Decimal(balances["SICK"].credit_days) == Decimal("15.00")


def test_midyear_fifth_anniversary_applies_next_january(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings(tmp_path))
        employee = _employee(
            session,
            seed,
            number="EMP-MIDYEAR",
            hire_date=date(2020, 2, 14),
        )
        service = LeaveService(session, settings=_settings(tmp_path))
        vacation = next(
            item
            for item in service.list_leave_types(seed["company"].id)
            if item.code == "VACATION"
        )

        before_anniversary = service.calculate_annual_allocation(
            employee=employee,
            leave_type=vacation,
            year=2025,
            as_of=date(2025, 2, 13),
        )
        after_anniversary = service.calculate_annual_allocation(
            employee=employee,
            leave_type=vacation,
            year=2025,
            as_of=date(2025, 12, 31),
        )
        next_january = service.calculate_annual_allocation(
            employee=employee,
            leave_type=vacation,
            year=2026,
            as_of=date(2026, 1, 1),
        )
        sixth_year_january = service.calculate_annual_allocation(
            employee=employee,
            leave_type=vacation,
            year=2027,
            as_of=date(2027, 1, 1),
        )

        assert before_anniversary == Decimal("15.00")
        assert after_anniversary == Decimal("15.00")
        assert next_january == Decimal("15.00")
        assert sixth_year_january == Decimal("17.00")


def test_unused_sl_vl_becomes_next_year_beginning_credit(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings(tmp_path))
        employee = _employee(
            session,
            seed,
            number="EMP-CARRY",
            hire_date=date(2024, 1, 1),
        )
        service = LeaveService(session, settings=_settings(tmp_path))
        current = _by_code(
            service.list_employee_balances(
                seed["company"].id,
                employee.id,
                2026,
            )
        )
        current["VACATION"].used_days = Decimal("5.00")
        current["SICK"].used_days = Decimal("2.00")
        session.commit()

        following = _by_code(
            service.list_employee_balances(
                seed["company"].id,
                employee.id,
                2027,
            )
        )

        assert Decimal(following["VACATION"].beginning_credit_days) == Decimal("10.00")
        assert Decimal(following["VACATION"].credit_days) == Decimal("15.00")
        assert Decimal(following["VACATION"].available_credits) == Decimal("25.00")
        assert Decimal(following["SICK"].beginning_credit_days) == Decimal("13.00")
        assert Decimal(following["SICK"].credit_days) == Decimal("15.00")
        assert Decimal(following["SICK"].converted_to_cash_days) == Decimal("13.00")
        assert Decimal(following["SICK"].available_credits) == Decimal("15.00")
        assert Decimal(following["EMERGENCY"].beginning_credit_days) == Decimal("0.00")


def test_january_processing_is_idempotent(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings(tmp_path))
        employee = _employee(
            session,
            seed,
            number="EMP-ONCE",
            hire_date=date(2024, 1, 1),
        )
        service = LeaveService(session, settings=_settings(tmp_path))

        service.ensure_current_year_balances(seed["company"].id, 2026)
        first_count = session.scalar(
            select(func.count(LeaveCreditTransaction.id)).where(
                LeaveCreditTransaction.company_id == seed["company"].id,
                LeaveCreditTransaction.employee_id == employee.id,
                LeaveCreditTransaction.transaction_type == "january_annual_accrual",
            )
        )
        service.ensure_current_year_balances(seed["company"].id, 2026)
        second_count = session.scalar(
            select(func.count(LeaveCreditTransaction.id)).where(
                LeaveCreditTransaction.company_id == seed["company"].id,
                LeaveCreditTransaction.employee_id == employee.id,
                LeaveCreditTransaction.transaction_type == "january_annual_accrual",
            )
        )
        balances = _by_code(
            service.list_employee_balances(
                seed["company"].id,
                employee.id,
                2026,
            )
        )

        # Seven visible rows plus internal LWOP each receive one zero-or-value
        # ledger entry when the annual balance is first created.
        assert first_count == 8
        assert second_count == first_count
        assert Decimal(balances["VACATION"].credit_days) == Decimal("15.00")
        assert Decimal(balances["SICK"].credit_days) == Decimal("15.00")
