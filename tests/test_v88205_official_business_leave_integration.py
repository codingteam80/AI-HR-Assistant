"""v8.8.205 Official Business leave integration and compact calendar checks."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from integrations.email.email_sender import OutboundEmail
from models.employee import Employee
from models.shifting_credit import ShiftingCredit
from models.user import User
from schemas.attendance_schema import AttendancePunchInput, AttendanceSelfEditInput, AttendanceSessionInput
from schemas.leave_schema import (
    LeaveCancellationRequestInput,
    LeaveDecisionInput,
    LeaveRequestInput,
)
from scripts.create_initial_data import seed_initial_data
from services.attendance_service import AttendanceService
from services.leave_service import LeaveService


ROOT = Path(__file__).resolve().parents[1]


class CapturingSender:
    def __init__(self) -> None:
        self.messages: list[OutboundEmail] = []

    def send(self, message: OutboundEmail) -> str:
        self.messages.append(message)
        return "captured"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="V88205",
        initial_company_name="Official Business Company",
        initial_admin_username="admin",
        initial_admin_email="admin@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-205",
        leave_attachment_dir=str(tmp_path / "leave_files"),
        password_reset_outbox_dir=str(tmp_path / "outbox"),
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _next_weekday(day: date) -> date:
    selected = day
    while selected.weekday() >= 5:
        selected += timedelta(days=1)
    return selected


def _employee_with_login(session, seed):
    manager = seed["admin_employee"]
    manager.work_email = "manager@example.com"
    user = User(
        company_id=seed["company"].id,
        role_id=seed["admin_user"].role_id,
        clearance=2,
        username="ob.employee",
        email="ob.employee@example.com",
        password_hash="test-hash",
        is_active=True,
        must_change_password=False,
    )
    session.add(user)
    session.flush()
    employee = Employee(
        company_id=seed["company"].id,
        department_id=manager.department_id,
        manager_id=manager.id,
        user_id=user.id,
        employee_number="EMP-OB-205",
        first_name="Official",
        last_name="Business",
        work_email="ob.employee@example.com",
        job_title="Staff",
        employment_status="employed",
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee, user


def _available_credit(session, seed, employee, usage_date: date, group: str) -> ShiftingCredit:
    credit = ShiftingCredit(
        company_id=seed["company"].id,
        employee_id=employee.id,
        group_key=group,
        cutoff_start=usage_date - timedelta(days=60),
        cutoff_end=usage_date - timedelta(days=45),
        earned_date=usage_date - timedelta(days=45),
        availability_date=usage_date - timedelta(days=30),
        expiration_date=usage_date + timedelta(days=90),
        qualifying_hours=Decimal("8.00"),
        ob_credit_days=Decimal("1.00"),
        status="available",
    )
    session.add(credit)
    session.commit()
    return credit


def test_ob_default_leave_type_and_live_balance_are_system_managed(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings(tmp_path))
        employee, _user = _employee_with_login(session, seed)
        service = LeaveService(session, settings=_settings(tmp_path), email_sender=CapturingSender())
        usage = _next_weekday(service._today() + timedelta(days=1))
        _available_credit(session, seed, employee, usage, "OB205-A")

        leave_types = service.list_leave_types(seed["company"].id)
        ob_type = next(item for item in leave_types if item.code == "OB")
        assert ob_type.name == "Official Business (OB)"
        assert Decimal(ob_type.annual_credits) == Decimal("0.00")

        balances = service.list_employee_balances(seed["company"].id, employee.id)
        ob_balance = next(item for item in balances if item.leave_type.code == "OB")
        assert Decimal(ob_balance.available_credits) == Decimal("1.00")
        rows = service.credit_table_rows(
            company_id=seed["company"].id,
            employee_id=employee.id,
            year=service.leave_cycle_year(seed["company"].id),
            balances=balances,
        )
        ob_row = next(item for item in rows if item.leave_type.code == "OB")
        assert ob_row.available_credits == Decimal("1.00")


def test_ob_leave_request_reserves_approves_and_reflects_in_attendance(tmp_path: Path) -> None:
    factory = _factory()
    sender = CapturingSender()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee, user = _employee_with_login(session, seed)
        service = LeaveService(session, settings=settings, email_sender=sender)
        usage = _next_weekday(service._today() + timedelta(days=1))
        credit = _available_credit(session, seed, employee, usage, "OB205-B")
        ob_type = next(
            item for item in service.list_leave_types(seed["company"].id)
            if item.code == "OB"
        )

        result = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                requested_by_user_id=user.id,
                leave_type_id=ob_type.id,
                start_date=usage,
                end_date=usage,
                duration_code="90503",
                reason="Official business assignment",
            )
        )
        request = result.request
        session.refresh(credit)
        assert credit.status == "reserved"
        assert credit.leave_request_id == request.id
        assert credit.usage_date == usage

        service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=request.id,
                manager_employee_id=seed["admin_employee"].id,
                manager_user_id=seed["admin_user"].id,
                decision="approve",
                manager_comment="Approved OB",
            )
        )
        session.refresh(credit)
        assert credit.status == "used"

        AttendanceService(session).sync_approved_leaves(
            seed["company"].id,
            usage,
            usage,
        )
        record = AttendanceService(session).get_daily(
            company_id=seed["company"].id,
            employee_id=employee.id,
            attendance_date=usage,
        )
        assert record is not None
        assert record.work_status == "OB"
        assert record.leave_request_id == request.id
        session.refresh(credit)
        assert credit.usage_attendance_record_id == record.id


def test_pending_ob_cancellation_releases_reserved_credit(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee, user = _employee_with_login(session, seed)
        service = LeaveService(session, settings=settings, email_sender=CapturingSender())
        usage = _next_weekday(service._today() + timedelta(days=2))
        credit = _available_credit(session, seed, employee, usage, "OB205-C")
        ob_type = next(
            item for item in service.list_leave_types(seed["company"].id)
            if item.code == "OB"
        )
        request = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                requested_by_user_id=user.id,
                leave_type_id=ob_type.id,
                start_date=usage,
                end_date=usage,
                duration_code="90503",
                reason="Official business assignment",
            )
        ).request
        service.request_leave_cancellation(
            LeaveCancellationRequestInput(
                company_id=seed["company"].id,
                request_id=request.id,
                requested_by_user_id=user.id,
                requested_by_employee_id=employee.id,
                reason="Business assignment was cancelled",
            )
        )
        session.refresh(credit)
        assert credit.status == "available"
        assert credit.leave_request_id is None
        assert credit.usage_date is None


def test_ob_rejects_partial_or_multi_day_request(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee, user = _employee_with_login(session, seed)
        service = LeaveService(session, settings=settings, email_sender=CapturingSender())
        usage = _next_weekday(service._today() + timedelta(days=1))
        _available_credit(session, seed, employee, usage, "OB205-D")
        ob_type = next(
            item for item in service.list_leave_types(seed["company"].id)
            if item.code == "OB"
        )
        with pytest.raises(ValueError, match="one whole Regular Workday"):
            service.submit_leave_request(
                LeaveRequestInput(
                    company_id=seed["company"].id,
                    employee_id=employee.id,
                    requested_by_user_id=user.id,
                    leave_type_id=ob_type.id,
                    start_date=usage,
                    end_date=usage,
                    duration_code="90501",
                    reason="Official business assignment",
                )
            )



def test_ob_final_approval_blocks_existing_work_attendance(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee, user = _employee_with_login(session, seed)
        service = LeaveService(session, settings=settings, email_sender=CapturingSender())
        usage = _next_weekday(service._today() + timedelta(days=1))
        credit = _available_credit(session, seed, employee, usage, "OB205-E")
        ob_type = next(
            item for item in service.list_leave_types(seed["company"].id)
            if item.code == "OB"
        )
        request = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                requested_by_user_id=user.id,
                leave_type_id=ob_type.id,
                start_date=usage,
                end_date=usage,
                duration_code="90503",
                reason="Official business assignment",
            )
        ).request
        AttendanceService(session).clock_in(
            AttendancePunchInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                user_id=user.id,
                attendance_date=usage,
                work_status="WFO",
                occurred_at=datetime.now(timezone.utc),
            )
        )

        with pytest.raises(ValueError, match="already has WFO/WFH attendance time"):
            service.decide_leave_request(
                LeaveDecisionInput(
                    company_id=seed["company"].id,
                    request_id=request.id,
                    manager_employee_id=seed["admin_employee"].id,
                    manager_user_id=seed["admin_user"].id,
                    decision="approve",
                    manager_comment="Review conflict",
                )
            )
        session.rollback()
        session.refresh(credit)
        assert credit.status == "reserved"
        assert credit.leave_request_id == request.id


def test_approved_ob_cannot_be_overwritten_with_work_session(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        employee, user = _employee_with_login(session, seed)
        service = LeaveService(session, settings=settings, email_sender=CapturingSender())
        usage = _next_weekday(service._today() + timedelta(days=1))
        _available_credit(session, seed, employee, usage, "OB205-F")
        ob_type = next(
            item for item in service.list_leave_types(seed["company"].id)
            if item.code == "OB"
        )
        request = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                requested_by_user_id=user.id,
                leave_type_id=ob_type.id,
                start_date=usage,
                end_date=usage,
                duration_code="90503",
                reason="Official business assignment",
            )
        ).request
        service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=request.id,
                manager_employee_id=seed["admin_employee"].id,
                manager_user_id=seed["admin_user"].id,
                decision="approve",
                manager_comment="Approved OB",
            )
        )
        AttendanceService(session).sync_approved_leaves(seed["company"].id, usage, usage)

        start = datetime(usage.year, usage.month, usage.day, 9, 0)
        end = datetime(usage.year, usage.month, usage.day, 18, 0)
        with pytest.raises(ValueError, match="controlled by Leave Management"):
            AttendanceService(session).edit_own_daily_attendance(
                AttendanceSelfEditInput(
                    company_id=seed["company"].id,
                    employee_id=employee.id,
                    user_id=user.id,
                    attendance_date=usage,
                    work_status="WFO",
                    sessions=[
                        AttendanceSessionInput(
                            work_status="WFO",
                            time_in=start,
                            time_out=end,
                        )
                    ],
                )
            )


def test_v88205_calendar_is_compact_and_versioned() -> None:
    source = (ROOT / "ui/pages/admin/attendance_dashboard.py").read_text(encoding="utf-8")
    assert "compact_grid = [1.5, 1, 1, 1, 1, 1, 1, 1, 1.5]" in source
    assert "gap: 0.18rem !important" in source
    assert "gap: 0.35rem !important" in source
    assert 'app_version: str = "0.8.8.205"' in (ROOT / "config/settings.py").read_text(encoding="utf-8")
    assert "APP_VERSION=0.8.8.205" in (ROOT / ".env.example").read_text(encoding="utf-8")
