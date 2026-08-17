"""Phase 3 tests for automatic January SL/VL cash conversion."""

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
        initial_company_code="PHASE3",
        initial_company_name="Phase 3 Company",
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
        first_name="Cash",
        last_name="Conversion",
        employment_status="employed",
        hire_date=hire_date,
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


def _by_code(balances):
    return {item.leave_type.code: item for item in balances}


def test_sick_leave_excess_is_converted_above_15(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee = _employee(
            session,
            seed,
            number="EMP-SL",
            hire_date=date(2024, 1, 1),
        )
        service = LeaveService(session, settings=settings)

        service.list_employee_balances(seed["company"].id, employee.id, 2026)
        following = _by_code(
            service.list_employee_balances(
                seed["company"].id,
                employee.id,
                2027,
            )
        )

        sick = following["SICK"]
        assert Decimal(sick.beginning_credit_days) == Decimal("15.00")
        assert Decimal(sick.credit_days) == Decimal("15.00")
        assert Decimal(sick.converted_to_cash_days) == Decimal("15.00")
        assert Decimal(sick.available_credits) == Decimal("15.00")


def test_vacation_leave_converts_only_after_exceeding_45(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee = _employee(
            session,
            seed,
            number="EMP-VL",
            hire_date=date(2024, 1, 1),
        )
        service = LeaveService(session, settings=settings)

        year_2024 = _by_code(
            service.list_employee_balances(
                seed["company"].id, employee.id, 2024
            )
        )
        year_2025 = _by_code(
            service.list_employee_balances(
                seed["company"].id, employee.id, 2025
            )
        )
        year_2026 = _by_code(
            service.list_employee_balances(
                seed["company"].id, employee.id, 2026
            )
        )
        year_2027 = _by_code(
            service.list_employee_balances(
                seed["company"].id, employee.id, 2027
            )
        )

        assert Decimal(year_2024["VACATION"].available_credits) == Decimal("15.00")
        assert Decimal(year_2025["VACATION"].available_credits) == Decimal("30.00")
        assert Decimal(year_2026["VACATION"].available_credits) == Decimal("45.00")
        assert Decimal(year_2026["VACATION"].converted_to_cash_days) == Decimal("0.00")
        assert Decimal(year_2027["VACATION"].beginning_credit_days) == Decimal("45.00")
        assert Decimal(year_2027["VACATION"].credit_days) == Decimal("15.00")
        assert Decimal(year_2027["VACATION"].converted_to_cash_days) == Decimal("15.00")
        assert Decimal(year_2027["VACATION"].available_credits) == Decimal("45.00")


def test_six_year_tenure_credit_keeps_fixed_cash_limits(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee = _employee(
            session,
            seed,
            number="EMP-BONUS",
            hire_date=date(2019, 1, 1),
        )
        service = LeaveService(session, settings=settings)
        balances = _by_code(
            service.list_employee_balances(
                seed["company"].id,
                employee.id,
                2025,
            )
        )

        assert Decimal(balances["SICK"].credit_days) == Decimal("17.00")
        assert Decimal(balances["SICK"].converted_to_cash_days) == Decimal("2.00")
        assert Decimal(balances["SICK"].available_credits) == Decimal("15.00")
        assert Decimal(balances["VACATION"].credit_days) == Decimal("17.00")
        assert Decimal(balances["VACATION"].converted_to_cash_days) == Decimal("0.00")
        assert Decimal(balances["VACATION"].available_credits) == Decimal("17.00")


def test_converted_amount_is_not_carried_into_next_year(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee = _employee(
            session,
            seed,
            number="EMP-CARRY",
            hire_date=date(2024, 1, 1),
        )
        service = LeaveService(session, settings=settings)

        for year in (2024, 2025, 2026, 2027):
            service.list_employee_balances(
                seed["company"].id,
                employee.id,
                year,
            )

        next_year = _by_code(
            service.list_employee_balances(
                seed["company"].id,
                employee.id,
                2028,
            )
        )

        assert Decimal(next_year["VACATION"].beginning_credit_days) == Decimal("45.00")
        assert Decimal(next_year["SICK"].beginning_credit_days) == Decimal("15.00")


def test_cash_conversion_processing_is_idempotent(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee = _employee(
            session,
            seed,
            number="EMP-ONCE",
            hire_date=date(2024, 1, 1),
        )
        service = LeaveService(session, settings=settings)

        service.ensure_current_year_balances(seed["company"].id, 2026)
        first_count = session.scalar(
            select(func.count(LeaveCreditTransaction.id)).where(
                LeaveCreditTransaction.company_id == seed["company"].id,
                LeaveCreditTransaction.employee_id == employee.id,
                LeaveCreditTransaction.transaction_type
                == "january_cash_conversion",
            )
        )
        service.ensure_current_year_balances(seed["company"].id, 2026)
        second_count = session.scalar(
            select(func.count(LeaveCreditTransaction.id)).where(
                LeaveCreditTransaction.company_id == seed["company"].id,
                LeaveCreditTransaction.employee_id == employee.id,
                LeaveCreditTransaction.transaction_type
                == "january_cash_conversion",
            )
        )

        # One marker each for Vacation Leave and Sick Leave.
        assert first_count == 2
        assert second_count == first_count


def test_annual_processing_is_committed_automatically(tmp_path: Path) -> None:
    factory = _factory()
    settings = _settings(tmp_path)

    with factory() as session:
        seed = seed_initial_data(session, settings)
        employee = _employee(
            session,
            seed,
            number="EMP-COMMIT",
            hire_date=date(2024, 1, 1),
        )
        company_id = seed["company"].id
        employee_id = employee.id
        LeaveService(session, settings=settings).ensure_current_year_balances(
            company_id,
            2026,
        )

    with factory() as session:
        balances = _by_code(
            LeaveService(session, settings=settings).list_employee_balances(
                company_id,
                employee_id,
                2026,
            )
        )
        assert Decimal(balances["VACATION"].credit_days) == Decimal("15.00")
        assert Decimal(balances["SICK"].credit_days) == Decimal("15.00")
