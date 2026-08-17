"""January accrual, tenure bonus, proration, and LWOP split tests."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from integrations.email.email_sender import OutboundEmail
from models.employee import Employee
from models.user import User
from schemas.leave_schema import (
    LeaveCreditBalanceSetInput,
    LeaveDecisionInput,
    LeaveRequestInput,
)
from scripts.create_initial_data import seed_initial_data
from services.leave_service import LeaveService


class CapturingSender:
    """Collect email messages without network access."""

    def __init__(self) -> None:
        self.messages: list[OutboundEmail] = []

    def send(self, message: OutboundEmail) -> str:
        self.messages.append(message)
        return "captured"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="AUTOLEAVE",
        initial_company_name="Automatic Leave Company",
        initial_admin_username="manager",
        initial_admin_email="manager@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="MGR-001",
        initial_admin_first_name="Mina",
        initial_admin_last_name="Manager",
        leave_attachment_dir=str(tmp_path / "leave_files"),
        password_reset_outbox_dir=str(tmp_path / "outbox"),
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _employee_with_login(session, seed, *, hire_date: date | None) -> tuple[Employee, User]:
    employee_user = User(
        company_id=seed["company"].id,
        role_id=seed["admin_user"].role_id,
        clearance=2,
        username="employee",
        email="employee@example.com",
        password_hash=seed["admin_user"].password_hash,
        is_active=True,
        must_change_password=False,
    )
    session.add(employee_user)
    session.flush()

    employee = Employee(
        company_id=seed["company"].id,
        user_id=employee_user.id,
        manager_id=seed["admin_employee"].id,
        employee_number="EMP-001",
        first_name="Ella",
        last_name="Employee",
        work_email="employee@example.com",
        employment_status="employed",
        hire_date=hire_date,
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee, employee_user


def _weekday_span(number_of_days: int) -> tuple[date, date]:
    start = date.today() + timedelta(days=10)
    while start.weekday() >= 5:
        start += timedelta(days=1)

    end = start
    counted = 1
    while counted < number_of_days:
        end += timedelta(days=1)
        if end.weekday() < 5:
            counted += 1
    return start, end


def _type(service: LeaveService, company_id: int, code: str):
    return next(
        item
        for item in service.list_leave_types(company_id)
        if item.code == code
    )


def test_base_and_five_year_entitlements(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee, _ = _employee_with_login(
            session,
            seed,
            hire_date=date(2020, 2, 14),
        )
        service = LeaveService(session, settings=settings)
        vacation = _type(service, seed["company"].id, "VACATION")
        emergency = _type(service, seed["company"].id, "EMERGENCY")
        sick = _type(service, seed["company"].id, "SICK")

        before_five = date(2025, 2, 13)
        after_five = date(2025, 2, 14)

        base_vacation = service.calculate_annual_allocation(
            employee=employee,
            leave_type=vacation,
            year=2025,
            as_of=before_five,
        )
        base_emergency = service.calculate_annual_allocation(
            employee=employee,
            leave_type=emergency,
            year=2025,
            as_of=before_five,
        )
        base_sick = service.calculate_annual_allocation(
            employee=employee,
            leave_type=sick,
            year=2025,
            as_of=before_five,
        )
        assert base_vacation == Decimal("15.00")
        assert base_emergency == Decimal("0.00")
        assert base_sick == Decimal("15.00")

        updated_vacation = service.calculate_annual_allocation(
            employee=employee,
            leave_type=vacation,
            year=2025,
            as_of=after_five,
        )
        updated_sick = service.calculate_annual_allocation(
            employee=employee,
            leave_type=sick,
            year=2025,
            as_of=after_five,
        )
        # Five completed years remains in the 1–5 bracket. The 17-day bracket
        # begins only when six years are complete on January 1.
        assert updated_vacation == Decimal("15.00")
        assert updated_sick == Decimal("15.00")
        assert service.calculate_annual_allocation(
            employee=employee,
            leave_type=vacation,
            year=2026,
            as_of=date(2026, 1, 1),
        ) == Decimal("15.00")
        assert service.calculate_annual_allocation(
            employee=employee,
            leave_type=vacation,
            year=2027,
            as_of=date(2027, 1, 1),
        ) == Decimal("17.00")


def test_hire_year_is_prorated_by_remaining_months(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee, _ = _employee_with_login(
            session,
            seed,
            hire_date=date(2026, 7, 15),
        )
        service = LeaveService(session, settings=settings)
        summary = service.entitlement_summary(
            employee=employee,
            year=2026,
            as_of=date(2026, 7, 15),
        )

        assert summary["regular_vacation"] == Decimal("7.50")
        assert summary["emergency"] == Decimal("0.00")
        assert summary["vacation_total"] == Decimal("7.50")
        assert summary["sick"] == Decimal("7.50")
        assert summary["basis"] == "Hire-year prorated"


def test_new_calendar_year_has_fresh_balances(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee, _ = _employee_with_login(
            session,
            seed,
            hire_date=date(2019, 1, 1),
        )
        service = LeaveService(session, settings=settings)
        current_year = date.today().year
        current_balances = service.list_employee_balances(
            seed["company"].id,
            employee.id,
            current_year,
        )
        current_vacation = next(
            item
            for item in current_balances
            if item.leave_type.code == "VACATION"
        )
        current_vacation.used_days = Decimal("10.00")
        session.commit()

        next_balances = service.list_employee_balances(
            seed["company"].id,
            employee.id,
            current_year + 1,
        )
        next_vacation = next(
            item
            for item in next_balances
            if item.leave_type.code == "VACATION"
        )
        next_sick = next(
            item
            for item in next_balances
            if item.leave_type.code == "SICK"
        )

        assert Decimal(next_vacation.used_days) == Decimal("0.00")
        assert Decimal(next_vacation.allocated_days) == Decimal("17.00")
        assert Decimal(next_sick.allocated_days) == Decimal("17.00")
        assert Decimal(next_vacation.carry_over_days) == Decimal("7.00")
        assert Decimal(next_vacation.available_credits) == Decimal("24.00")


def test_insufficient_vacation_is_automatically_split_to_lwop(
    tmp_path: Path,
) -> None:
    factory = _factory()
    sender = CapturingSender()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        seed["admin_employee"].work_email = "manager@example.com"
        employee, employee_user = _employee_with_login(
            session,
            seed,
            hire_date=date(2020, 1, 1),
        )
        service = LeaveService(
            session,
            settings=settings,
            email_sender=sender,
        )
        vacation_balance = next(
            item
            for item in service.list_employee_balances(
                seed["company"].id,
                employee.id,
            )
            if item.leave_type.code == "VACATION"
        )
        service.set_credit_balance(
            LeaveCreditBalanceSetInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                leave_type_id=vacation_balance.leave_type_id,
                year=date.today().year,
                new_remaining_days=Decimal("1.00"),
                reason="Test low balance",
                created_by_user_id=seed["admin_user"].id,
            )
        )
        start, end = _weekday_span(3)
        submitted = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                requested_by_user_id=employee_user.id,
                leave_type_id=vacation_balance.leave_type_id,
                start_date=start,
                end_date=end,
                reason="Family commitment",
                handover_plan="Backup will cover daily tasks.",
            )
        )

        assert Decimal(submitted.request.primary_credit_days) == Decimal("1.00")
        assert Decimal(submitted.request.lwop_days) == Decimal("2.00")

        approved = service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=submitted.request.id,
                manager_employee_id=seed["admin_employee"].id,
                manager_user_id=seed["admin_user"].id,
                decision="approve",
            )
        )
        refreshed = service.balance_repository.get_balance(
            company_id=seed["company"].id,
            employee_id=employee.id,
            leave_type_id=vacation_balance.leave_type_id,
            year=start.year,
        )

        assert Decimal(approved.primary_credit_days) == Decimal("1.00")
        assert Decimal(approved.lwop_days) == Decimal("2.00")
        assert Decimal(refreshed.reserved_days) == Decimal("1.00")
        assert "2 LWOP" in service.allocation_breakdown(approved)


def test_emergency_uses_vacation_then_lwop(tmp_path: Path) -> None:
    """Phase 4: EL uses at most three VL-funded days, then LWOP."""

    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        seed["admin_employee"].work_email = "manager@example.com"
        employee, employee_user = _employee_with_login(
            session,
            seed,
            hire_date=date(2020, 1, 1),
        )
        service = LeaveService(
            session,
            settings=settings,
            email_sender=CapturingSender(),
        )
        balances = service.list_employee_balances(
            seed["company"].id,
            employee.id,
        )
        emergency = next(
            item for item in balances if item.leave_type.code == "EMERGENCY"
        )
        vacation = next(
            item for item in balances if item.leave_type.code == "VACATION"
        )
        service.set_credit_balance(
            LeaveCreditBalanceSetInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                leave_type_id=vacation.leave_type_id,
                year=date.today().year,
                new_remaining_days=Decimal("5.00"),
                reason="Vacation funding for EL test",
                created_by_user_id=seed["admin_user"].id,
            )
        )

        start, end = _weekday_span(4)
        submitted = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                requested_by_user_id=employee_user.id,
                leave_type_id=emergency.leave_type_id,
                start_date=start,
                end_date=end,
                reason="Urgent family matter",
            )
        )

        assert Decimal(submitted.request.primary_credit_days) == Decimal("0.00")
        assert Decimal(submitted.request.fallback_credit_days) == Decimal("3.00")
        assert Decimal(submitted.request.lwop_days) == Decimal("1.00")
        assert submitted.request.fallback_leave_type.code == "VACATION"

        approved = service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=submitted.request.id,
                manager_employee_id=seed["admin_employee"].id,
                manager_user_id=seed["admin_user"].id,
                decision="approve",
            )
        )
        emergency_after = service.balance_repository.get_balance(
            company_id=seed["company"].id,
            employee_id=employee.id,
            leave_type_id=emergency.leave_type_id,
            year=start.year,
        )
        vacation_after = service.balance_repository.get_balance(
            company_id=seed["company"].id,
            employee_id=employee.id,
            leave_type_id=vacation.leave_type_id,
            year=start.year,
        )

        assert Decimal(emergency_after.reserved_days) == Decimal("0.00")
        assert Decimal(vacation_after.reserved_days) == Decimal("3.00")
        assert (
            "3 Emergency Leave (deducted from Vacation Leave) + 1 LWOP"
            == service.allocation_breakdown(approved)
        )
