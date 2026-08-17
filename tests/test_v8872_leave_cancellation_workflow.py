"""Leave cancellation before and after final approval regression."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from config.settings import Settings
from database.base import Base
from models.employee import Employee
from models.leave_credit_transaction import LeaveCreditTransaction
from models.notification import Notification
from models.user import User
from schemas.leave_schema import (
    LeaveCancellationDecisionInput,
    LeaveCancellationRequestInput,
    LeaveDecisionInput,
    LeaveRequestInput,
)
from scripts.create_initial_data import seed_initial_data
from services.leave_service import LeaveService


class FixedTodayLeaveService(LeaveService):
    selected_today = date(2030, 1, 8)

    def _today(self) -> date:
        return self.selected_today


class NoopSender:
    def send(self, message):
        return "noop"


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="V8872",
        initial_company_name="Cancellation Company",
        initial_admin_username="manager",
        initial_admin_email="manager@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="MGR-001",
        initial_admin_first_name="Mara",
        initial_admin_last_name="Manager",
        leave_attachment_dir=str(tmp_path / "leave"),
        password_reset_outbox_dir=str(tmp_path / "outbox"),
    )


def _employee_user(session, seed, *, number="EMP-001", username="employee"):
    user = User(
        company_id=seed["company"].id,
        role_id=seed["admin_user"].role_id,
        clearance=2,
        username=username,
        email=f"{username}@example.com",
        password_hash=seed["admin_user"].password_hash,
        is_active=True,
        must_change_password=False,
    )
    session.add(user)
    session.flush()
    employee = Employee(
        company_id=seed["company"].id,
        user_id=user.id,
        manager_id=seed["admin_employee"].id,
        employee_number=number,
        first_name="Ella",
        last_name="Employee",
        work_email=user.email,
        employment_status="employed",
        hire_date=date(2020, 1, 1),
        gender="Female",
    )
    session.add(employee)
    session.flush()
    return user, employee


def _sick(service, company_id, employee_id):
    return next(
        balance.leave_type
        for balance in service.list_employee_balances(company_id, employee_id, 2030)
        if balance.leave_type.code == "SICK"
    )


def _submit_and_approve(service, seed, user, employee, *, start, end):
    sick = _sick(service, seed["company"].id, employee.id)
    request = service.submit_leave_request(
        LeaveRequestInput(
            company_id=seed["company"].id,
            employee_id=employee.id,
            requested_by_user_id=user.id,
            filed_by_employee_id=employee.id,
            leave_type_id=sick.id,
            start_date=start,
            end_date=end,
            reason="Medical leave request",
        )
    ).request
    return service.decide_leave_request(
        LeaveDecisionInput(
            company_id=seed["company"].id,
            request_id=request.id,
            manager_employee_id=seed["admin_employee"].id,
            manager_user_id=seed["admin_user"].id,
            decision="approve",
        )
    )


def test_pending_request_cancels_immediately_without_credit_change(tmp_path: Path):
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        seed["admin_employee"].work_email = "manager@example.com"
        user, employee = _employee_user(session, seed)
        session.commit()
        service = FixedTodayLeaveService(session, settings=settings, email_sender=NoopSender())
        sick = _sick(service, seed["company"].id, employee.id)
        request = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                requested_by_user_id=user.id,
                filed_by_employee_id=employee.id,
                leave_type_id=sick.id,
                start_date=date(2030, 1, 14),
                end_date=date(2030, 1, 14),
                reason="Medical appointment",
            )
        ).request
        balance = service.balance_repository.get_balance(
            company_id=seed["company"].id,
            employee_id=employee.id,
            leave_type_id=sick.id,
            year=2030,
        )
        reserved_before = Decimal(balance.reserved_days)
        cancelled = service.request_leave_cancellation(
            LeaveCancellationRequestInput(
                company_id=seed["company"].id,
                request_id=request.id,
                requested_by_user_id=user.id,
                requested_by_employee_id=employee.id,
                reason="Appointment was moved",
            )
        )
        assert cancelled.status == "cancelled"
        assert cancelled.cancellation_status == "cancelled"
        assert cancelled.current_approver_employee_id is None
        assert Decimal(balance.reserved_days) == reserved_before
        events = session.scalars(
            select(Notification).where(
                Notification.event_type == "leave_request_cancelled_before_approval"
            )
        ).all()
        assert events


def test_future_approved_leave_restores_reserved_credit_after_cancellation_approval(tmp_path: Path):
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        seed["admin_employee"].work_email = "manager@example.com"
        user, employee = _employee_user(session, seed, username="future")
        session.commit()
        service = FixedTodayLeaveService(session, settings=settings, email_sender=NoopSender())
        approved = _submit_and_approve(
            service, seed, user, employee,
            start=date(2030, 1, 14), end=date(2030, 1, 16),
        )
        sick = approved.leave_type
        balance = service.balance_repository.get_balance(
            company_id=seed["company"].id,
            employee_id=employee.id,
            leave_type_id=sick.id,
            year=2030,
        )
        assert Decimal(balance.reserved_days) == Decimal("3.00")

        requested = service.request_leave_cancellation(
            LeaveCancellationRequestInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                requested_by_user_id=user.id,
                requested_by_employee_id=employee.id,
                reason="Leave is no longer required",
            )
        )
        assert requested.cancellation_status == "requested"
        assert requested.status == "scheduled"
        assert Decimal(balance.reserved_days) == Decimal("3.00")

        cancelled = service.decide_leave_cancellation(
            LeaveCancellationDecisionInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                reviewer_user_id=seed["admin_user"].id,
                reviewer_employee_id=seed["admin_employee"].id,
                decision="approve",
                comment="Coverage restored",
            )
        )
        assert cancelled.status == "cancelled"
        assert cancelled.cancellation_status == "approved"
        assert Decimal(cancelled.cancellation_restored_primary_days) == Decimal("3.00")
        assert Decimal(balance.reserved_days) == Decimal("0.00")
        transactions = session.scalars(
            select(LeaveCreditTransaction).where(
                LeaveCreditTransaction.leave_request_id == approved.id,
                LeaveCreditTransaction.transaction_type
                == "leave_cancellation_credit_restored",
            )
        ).all()
        assert sum(Decimal(item.amount_days) for item in transactions) == Decimal("3.00")


def test_ongoing_leave_keeps_elapsed_days_used_and_restores_future_days(tmp_path: Path):
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        seed["admin_employee"].work_email = "manager@example.com"
        user, employee = _employee_user(session, seed, username="ongoing")
        session.commit()
        service = FixedTodayLeaveService(session, settings=settings, email_sender=NoopSender())
        # Monday Jan 7 through Friday Jan 11; fixed today is Tuesday Jan 8.
        approved = _submit_and_approve(
            service, seed, user, employee,
            start=date(2030, 1, 7), end=date(2030, 1, 11),
        )
        balance = service.balance_repository.get_balance(
            company_id=seed["company"].id,
            employee_id=employee.id,
            leave_type_id=approved.leave_type_id,
            year=2030,
        )
        assert Decimal(approved.posted_working_days) == Decimal("2.00")
        assert Decimal(balance.used_days) == Decimal("2.00")
        assert Decimal(balance.reserved_days) == Decimal("3.00")

        requested = service.request_leave_cancellation(
            LeaveCancellationRequestInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                requested_by_user_id=user.id,
                requested_by_employee_id=employee.id,
                reason="Employee returned earlier than planned",
            )
        )
        assert requested.cancellation_effective_date == date(2030, 1, 9)
        partial = service.decide_leave_cancellation(
            LeaveCancellationDecisionInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                reviewer_user_id=seed["admin_user"].id,
                reviewer_employee_id=seed["admin_employee"].id,
                decision="approve",
            )
        )
        assert partial.status == "partially_cancelled"
        assert Decimal(partial.cancellation_restored_primary_days) == Decimal("3.00")
        assert Decimal(balance.used_days) == Decimal("2.00")
        assert Decimal(balance.reserved_days) == Decimal("0.00")


def test_rejected_cancellation_keeps_approved_leave_and_reservation(tmp_path: Path):
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        seed["admin_employee"].work_email = "manager@example.com"
        user, employee = _employee_user(session, seed, username="rejectedcancel")
        session.commit()
        service = FixedTodayLeaveService(session, settings=settings, email_sender=NoopSender())
        approved = _submit_and_approve(
            service, seed, user, employee,
            start=date(2030, 1, 14), end=date(2030, 1, 14),
        )
        balance = service.balance_repository.get_balance(
            company_id=seed["company"].id,
            employee_id=employee.id,
            leave_type_id=approved.leave_type_id,
            year=2030,
        )
        service.request_leave_cancellation(
            LeaveCancellationRequestInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                requested_by_user_id=user.id,
                requested_by_employee_id=employee.id,
                reason="Personal schedule changed",
            )
        )
        rejected = service.decide_leave_cancellation(
            LeaveCancellationDecisionInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                reviewer_user_id=seed["admin_user"].id,
                reviewer_employee_id=seed["admin_employee"].id,
                decision="reject",
                comment="Staffing coverage cannot be changed",
            )
        )
        assert rejected.status == "scheduled"
        assert rejected.cancellation_status == "rejected"
        assert Decimal(balance.reserved_days) == Decimal("1.00")


def test_ui_contains_cancel_options_and_cancellation_review() -> None:
    root = Path(__file__).resolve().parents[1]
    employee_source = (root / "ui/pages/user/leave_management_page.py").read_text()
    admin_source = (root / "ui/pages/admin/leave_change_review.py").read_text()
    assert "Request Leave Cancellation" in employee_source
    assert "Cancel Request Now" in employee_source
    assert "Approve Cancellation" in employee_source
    assert "HR Cancellation Review" in admin_source
    topbar_source = (root / "ui/components/topbar.py").read_text()
    assert '"leave_cancellation_requested"' in topbar_source


def test_emergency_cancellation_restores_vacation_reservation_and_el_allowance(tmp_path: Path):
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        seed["admin_employee"].work_email = "manager@example.com"
        user, employee = _employee_user(session, seed, username="emergencycancel")
        session.commit()
        service = FixedTodayLeaveService(session, settings=settings, email_sender=NoopSender())
        emergency = next(
            balance.leave_type
            for balance in service.list_employee_balances(seed["company"].id, employee.id, 2030)
            if balance.leave_type.code == "EMERGENCY"
        )
        request = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                requested_by_user_id=user.id,
                filed_by_employee_id=employee.id,
                leave_type_id=emergency.id,
                start_date=date(2030, 1, 14),
                end_date=date(2030, 1, 15),
                reason="Urgent family matter",
            )
        ).request
        approved = service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=request.id,
                manager_employee_id=seed["admin_employee"].id,
                manager_user_id=seed["admin_user"].id,
                decision="approve",
            )
        )
        vacation_balance = next(
            balance
            for balance in service.list_employee_balances(seed["company"].id, employee.id, 2030)
            if balance.leave_type.code == "VACATION"
        )
        assert Decimal(vacation_balance.reserved_days) == Decimal("2.00")
        assert service.emergency_allowance_summary(
            company_id=seed["company"].id,
            employee_id=employee.id,
            year=2030,
        ).remaining_days == Decimal("1.00")
        service.request_leave_cancellation(
            LeaveCancellationRequestInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                requested_by_user_id=user.id,
                requested_by_employee_id=employee.id,
                reason="Emergency was resolved",
            )
        )
        service.decide_leave_cancellation(
            LeaveCancellationDecisionInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                reviewer_user_id=seed["admin_user"].id,
                reviewer_employee_id=seed["admin_employee"].id,
                decision="approve",
            )
        )
        assert Decimal(vacation_balance.reserved_days) == Decimal("0.00")
        assert service.emergency_allowance_summary(
            company_id=seed["company"].id,
            employee_id=employee.id,
            year=2030,
        ).remaining_days == Decimal("3.00")


def test_full_unused_honeymoon_cancellation_reverses_event_grant(tmp_path: Path):
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        seed["admin_employee"].work_email = "manager@example.com"
        user, employee = _employee_user(session, seed, username="honeymooncancel")
        session.commit()
        service = FixedTodayLeaveService(session, settings=settings, email_sender=NoopSender())
        honeymoon = next(
            balance.leave_type
            for balance in service.list_employee_balances(seed["company"].id, employee.id, 2030)
            if balance.leave_type.code == "HONEYMOON"
        )
        request = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=employee.id,
                requested_by_user_id=user.id,
                filed_by_employee_id=employee.id,
                leave_type_id=honeymoon.id,
                start_date=date(2030, 1, 14),
                end_date=date(2030, 1, 18),
                reason="Marriage leave event",
            )
        ).request
        approved = service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=request.id,
                manager_employee_id=seed["admin_employee"].id,
                manager_user_id=seed["admin_user"].id,
                decision="approve",
            )
        )
        balance = service.balance_repository.get_balance(
            company_id=seed["company"].id,
            employee_id=employee.id,
            leave_type_id=honeymoon.id,
            year=2030,
        )
        assert Decimal(balance.allocated_days) == Decimal("5.00")
        assert Decimal(balance.reserved_days) == Decimal("5.00")
        service.request_leave_cancellation(
            LeaveCancellationRequestInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                requested_by_user_id=user.id,
                requested_by_employee_id=employee.id,
                reason="Event leave dates were cancelled",
            )
        )
        cancelled = service.decide_leave_cancellation(
            LeaveCancellationDecisionInput(
                company_id=seed["company"].id,
                request_id=approved.id,
                reviewer_user_id=seed["admin_user"].id,
                reviewer_employee_id=seed["admin_employee"].id,
                decision="approve",
            )
        )
        assert cancelled.status == "cancelled"
        assert Decimal(balance.allocated_days) == Decimal("0.00")
        assert Decimal(balance.reserved_days) == Decimal("0.00")
        assert service.event_leave_preview_entitlement(
            company_id=seed["company"].id,
            employee_id=employee.id,
            leave_type=honeymoon,
        ) == Decimal("5.00")
        reversals = session.scalars(
            select(LeaveCreditTransaction).where(
                LeaveCreditTransaction.leave_request_id == approved.id,
                LeaveCreditTransaction.transaction_type == "event_leave_entitlement_reversal",
            )
        ).all()
        assert len(reversals) == 1
