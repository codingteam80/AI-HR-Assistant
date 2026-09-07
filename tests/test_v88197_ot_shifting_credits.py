"""v8.8.197 OT dinner deduction and configurable shifting-credit rules."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from models.attendance_record import AttendanceRecord
from models.leave_credit_transaction import LeaveCreditTransaction
from schemas.attendance_schema import CompanyOvertimeRulesInput
from schemas.overtime_schema import OvertimeRequestInput, OvertimeReviewInput
from scripts.create_initial_data import seed_initial_data
from services.attendance_service import AttendanceService
from services.overtime_service import OvertimeService


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="V88197",
        initial_company_name="OT Shifting Company",
        initial_admin_username="admin",
        initial_admin_email="admin@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-197",
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _record(seed, rendered: date, hours: Decimal) -> AttendanceRecord:
    return AttendanceRecord(
        company_id=seed["company"].id,
        employee_id=seed["admin_employee"].id,
        attendance_date=rendered,
        time_in=datetime(rendered.year, rendered.month, rendered.day, 0, 0, tzinfo=timezone.utc),
        time_out=datetime(rendered.year, rendered.month, rendered.day, 12, 0, tzinfo=timezone.utc),
        work_status="WFO",
        scheduled_workday=True,
        regular_hours_target=Decimal("8.00"),
        lunch_break_minutes=60,
        total_hours=Decimal("8.00") + hours,
        ot_hours=hours,
    )


def _request(seed, rendered: date, hours: Decimal, *, dinner: bool = False):
    start = datetime(rendered.year, rendered.month, rendered.day, 17, 0)
    end = start + timedelta(hours=float(hours))
    return OvertimeRequestInput(
        company_id=seed["company"].id,
        employee_id=seed["admin_employee"].id,
        requested_by_user_id=seed["admin_user"].id,
        date_rendered=rendered,
        ot_time_start=start,
        ot_time_end=end,
        estimated_hours=hours,
        ot_type="Regular Overtime",
        ot_purpose="Shifting credit test",
        dinner_break_flag=dinner,
    )


def _approve(service, seed, request):
    return service.review(
        OvertimeReviewInput(
            company_id=seed["company"].id,
            overtime_request_id=request.id,
            reviewed_by_user_id=seed["admin_user"].id,
            reviewer_employee_id=seed["admin_employee"].id,
            clearance=1,
            decision="approved",
        )
    )


def test_dinner_break_deducts_point_75_from_payable_ot() -> None:
    factory = _factory()
    rendered = date(2026, 8, 24)
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        session.add(_record(seed, rendered, Decimal("5.00")))
        session.commit()
        request = OvertimeService(session).submit(
            _request(seed, rendered, Decimal("5.00"), dinner=True)
        )
        assert Decimal(request.estimated_hours) == Decimal("5.00")
        assert Decimal(request.payable_hours) == Decimal("4.25")


def test_two_four_hour_blocks_pair_within_cutoff_and_leave_excess_payable() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        first_date = date(2026, 8, 24)
        second_date = date(2026, 8, 26)
        session.add_all([
            _record(seed, first_date, Decimal("5.00")),
            _record(seed, second_date, Decimal("4.00")),
        ])
        session.commit()
        service = OvertimeService(session)
        first = service.submit(_request(seed, first_date, Decimal("5.00")))
        _approve(service, seed, first)
        assert Decimal(first.payable_hours) == Decimal("5.00")
        second = service.submit(_request(seed, second_date, Decimal("4.00")))
        _approve(service, seed, second)
        session.refresh(first)
        assert Decimal(first.shifting_credit_hours) == Decimal("4.00")
        assert Decimal(first.payable_hours) == Decimal("1.00")
        assert Decimal(second.shifting_credit_hours) == Decimal("4.00")
        assert Decimal(second.payable_hours) == Decimal("0.00")
        assert first.shifting_credit_group == second.shifting_credit_group


def test_eight_hour_ot_converts_to_half_vl_and_is_not_payable_by_default() -> None:
    factory = _factory()
    rendered = date(2026, 8, 28)
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        session.add(_record(seed, rendered, Decimal("8.00")))
        session.commit()
        service = OvertimeService(session)
        request = service.submit(_request(seed, rendered, Decimal("8.00")))
        _approve(service, seed, request)
        assert Decimal(request.payable_hours) == Decimal("0.00")
        assert Decimal(request.shifting_credit_hours) == Decimal("0.00")
        assert Decimal(request.additional_vl_days) == Decimal("0.50")
        assert request.straight_vl_also_payable is False
        tx = session.scalar(
            select(LeaveCreditTransaction).where(
                LeaveCreditTransaction.company_id == seed["company"].id,
                LeaveCreditTransaction.employee_id == seed["admin_employee"].id,
                LeaveCreditTransaction.transaction_type == "overtime_additional_vl",
            )
        )
        assert tx is not None
        assert Decimal(tx.amount_days) == Decimal("0.50")


def test_straight_eight_hour_can_also_remain_payable_when_enabled() -> None:
    factory = _factory()
    rendered = date(2026, 8, 29)
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        AttendanceService(session).save_overtime_rules(
            CompanyOvertimeRulesInput(
                company_id=seed["company"].id,
                dinner_break_deduction_hours=Decimal("0.75"),
                shifting_credits_enabled=True,
                shifting_credit_block_hours=Decimal("4.00"),
                shifting_credit_required_blocks=2,
                shifting_credit_cutoff_day=15,
                additional_vl_threshold_hours=Decimal("8.00"),
                additional_vl_days=Decimal("0.50"),
                additional_vl_also_payable=True,
                excluded_positions=["Trainee", "Design Engineer I", "Design Engineer II"],
            )
        )
        session.add(_record(seed, rendered, Decimal("8.00")))
        session.commit()
        service = OvertimeService(session)
        request = service.submit(_request(seed, rendered, Decimal("8.00"), dinner=True))
        _approve(service, seed, request)
        assert Decimal(request.payable_hours) == Decimal("7.25")
        assert Decimal(request.additional_vl_days) == Decimal("0.50")
        assert request.straight_vl_also_payable is True


def test_excluded_design_engineer_i_does_not_receive_shifting_or_vl() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        seed["admin_employee"].job_title = "DE1"
        session.add(_record(seed, date(2026, 8, 24), Decimal("8.00")))
        session.commit()
        service = OvertimeService(session)
        request = service.submit(
            _request(seed, date(2026, 8, 24), Decimal("8.00"))
        )
        _approve(service, seed, request)
        assert Decimal(request.payable_hours) == Decimal("8.00")
        assert Decimal(request.additional_vl_days) == Decimal("0.00")


def test_ot_shifting_settings_are_editable_and_persisted() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        company = AttendanceService(session).save_overtime_rules(
            CompanyOvertimeRulesInput(
                company_id=seed["company"].id,
                dinner_break_deduction_hours=Decimal("0.50"),
                shifting_credits_enabled=True,
                shifting_credit_block_hours=Decimal("3.50"),
                shifting_credit_required_blocks=2,
                shifting_credit_cutoff_day=14,
                additional_vl_threshold_hours=Decimal("7.00"),
                additional_vl_days=Decimal("0.50"),
                additional_vl_also_payable=True,
                excluded_positions=["Trainee", "Design Engineer I", "Design Engineer II"],
            )
        )
        assert Decimal(company.ot_dinner_break_deduction_hours) == Decimal("0.50")
        assert Decimal(company.shifting_credit_block_hours) == Decimal("3.50")
        assert company.shifting_credit_cutoff_day == 14
        assert company.shifting_credit_additional_vl_also_payable is True


def test_four_hour_blocks_do_not_pair_across_cutoff_boundary() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        first_date = date(2026, 8, 15)
        second_date = date(2026, 8, 16)
        session.add_all([
            _record(seed, first_date, Decimal("4.00")),
            _record(seed, second_date, Decimal("4.00")),
        ])
        session.commit()
        service = OvertimeService(session)
        first = service.submit(_request(seed, first_date, Decimal("4.00")))
        _approve(service, seed, first)
        second = service.submit(_request(seed, second_date, Decimal("4.00")))
        _approve(service, seed, second)
        assert Decimal(first.shifting_credit_hours) == Decimal("0.00")
        assert Decimal(second.shifting_credit_hours) == Decimal("0.00")
        assert Decimal(first.payable_hours) == Decimal("4.00")
        assert Decimal(second.payable_hours) == Decimal("4.00")


def test_eight_hour_dinner_break_uses_gross_hours_for_vl_but_net_payable_ot() -> None:
    factory = _factory()
    rendered = date(2026, 8, 31)
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        session.add(_record(seed, rendered, Decimal("8.00")))
        session.commit()
        service = OvertimeService(session)
        request = service.submit(
            _request(seed, rendered, Decimal("8.00"), dinner=True)
        )
        _approve(service, seed, request)
        assert Decimal(request.payable_hours) == Decimal("0.00")
        assert Decimal(request.additional_vl_days) == Decimal("0.50")
        assert request.straight_vl_also_payable is False
