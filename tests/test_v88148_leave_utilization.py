"""Regression coverage for v8.8.148 Vacation Leave utilization."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from database.base import Base
from models.company import Company
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_credit_transaction import LeaveCreditTransaction
from models.leave_request import LeaveRequest
from models.leave_type import LeaveType
from models.notification import Notification
from models.role import Role
from models.user import User
from schemas.leave_schema import LeaveDecisionInput, LeaveRequestInput
from services.leave_service import LeaveService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _NoopSender:
    def send(self, message):
        return "test"


class _FixedDateLeaveService(LeaveService):
    selected_today = date(2026, 1, 5)

    def _today(self) -> date:
        return self.selected_today


def _build_company(session):
    company = Company(code="UTIL", name="Utilization Company")
    role = Role(company=company, name="User", is_system_role=True, is_active=True)
    session.add_all([company, role])
    session.flush()

    def account(username: str, clearance: int = 2) -> User:
        value = User(
            company=company,
            role=role,
            clearance=clearance,
            username=username,
            email=f"{username}@util.test",
            password_hash="test",
            is_active=True,
            must_change_password=False,
        )
        session.add(value)
        session.flush()
        return value

    admin_user = account("admin", 1)
    manager_user = account("manager")
    leader_user = account("leader")
    employee_user = account("employee")
    admin = Employee(
        company=company,
        user=admin_user,
        employee_number="A-001",
        first_name="System",
        last_name="Admin",
        employment_status="employed",
    )
    manager = Employee(
        company=company,
        user=manager_user,
        employee_number="M-001",
        first_name="Mina",
        last_name="Manager",
        employment_status="employed",
    )
    leader = Employee(
        company=company,
        user=leader_user,
        employee_number="L-001",
        first_name="Lina",
        last_name="Leader",
        employment_status="employed",
    )
    employee = Employee(
        company=company,
        user=employee_user,
        manager=manager,
        leader=leader,
        employee_number="E-001",
        first_name="Erin",
        last_name="Employee",
        employment_status="employed",
        hire_date=date(2019, 1, 1),
    )
    vacation = LeaveType(
        company_id=company.id,
        code="VACATION",
        name="Vacation Leave",
        annual_credits=Decimal("15.00"),
        is_paid=True,
        carry_over_limit=Decimal("0.00"),
        requires_attachment=False,
        handover_plan_requirement="optional",
        minimum_notice_days=0,
        is_active=True,
    )
    sick = LeaveType(
        company_id=company.id,
        code="SICK",
        name="Sick Leave",
        annual_credits=Decimal("15.00"),
        is_paid=True,
        carry_over_limit=Decimal("0.00"),
        requires_attachment=False,
        handover_plan_requirement="optional",
        minimum_notice_days=0,
        is_active=True,
    )
    session.add_all([admin, manager, leader, employee, vacation, sick])
    session.flush()
    return company, employee, vacation, sick


def _balance(session, *, company, employee, leave_type, year, beginning, credit, used):
    value = LeaveBalance(
        company_id=company.id,
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        year=year,
        allocated_days=credit,
        carry_over_days=beginning,
        adjustment_days=Decimal("0.00"),
        used_days=used,
        reserved_days=Decimal("0.00"),
        beginning_credit_days=beginning,
        credit_days=credit,
        converted_to_cash_days=Decimal("0.00"),
    )
    session.add(value)
    session.flush()
    return value


def _vl_request(session, *, company, employee, vacation, public_id, start, end, days):
    request = LeaveRequest(
        company_id=company.id,
        public_id=public_id,
        employee_id=employee.id,
        filed_by_employee_id=employee.id,
        filed_by_user_id=employee.user_id,
        leave_type_id=vacation.id,
        manager_employee_id=employee.manager_id,
        leader_employee_id=employee.leader_id,
        approval_stage="completed",
        start_date=start,
        end_date=end,
        requested_days=days,
        duration_code="90503",
        reason_code="12",
        reason="REST",
        primary_credit_days=days,
        fallback_credit_days=Decimal("0.00"),
        lwop_days=Decimal("0.00"),
        posted_working_days=days,
        status="completed",
        manager_email="manager@util.test",
        to_emails_json="[]",
        cc_emails_json="[]",
        email_status="sent",
    )
    session.add(request)
    session.flush()
    return request


def test_full_2026_through_2028_utilization_carryover_and_cash_flow() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        company, employee, vacation, _ = _build_company(session)
        service = LeaveService(session)

        balance_2026 = _balance(
            session,
            company=company,
            employee=employee,
            leave_type=vacation,
            year=2026,
            beginning=Decimal("20.00"),
            credit=Decimal("17.00"),
            used=Decimal("3.00"),
        )
        _vl_request(
            session,
            company=company,
            employee=employee,
            vacation=vacation,
            public_id="VL-2026",
            start=date(2026, 8, 20),
            end=date(2026, 8, 24),
            days=Decimal("3.00"),
        )
        session.commit()

        summary_2026 = service.leave_utilization_summary(
            balance=balance_2026,
            as_of=date(2026, 12, 31),
        )
        assert summary_2026.required_days == Decimal("8.50")
        assert summary_2026.used_days == Decimal("3.00")
        assert balance_2026.available_credits == Decimal("34.00")
        service.reconcile_leave_utilization(
            company_id=company.id,
            through_date=date(2026, 12, 31),
        )
        service.reconcile_leave_utilization(
            company_id=company.id,
            through_date=date(2026, 12, 31),
        )
        assert balance_2026.adjustment_days == Decimal("-5.50")
        assert balance_2026.available_credits == Decimal("28.50")
        marker_count = session.scalar(
            select(func.count(LeaveCreditTransaction.id)).where(
                LeaveCreditTransaction.leave_balance_id == balance_2026.id,
                LeaveCreditTransaction.transaction_type
                == "leave_utilization_year_end",
            )
        )
        assert marker_count == 1

        balance_2027 = service._ensure_balance(
            company_id=company.id,
            employee_id=employee.id,
            leave_type=vacation,
            year=2027,
            employee=employee,
            as_of=date(2027, 1, 1),
        )
        assert balance_2027.beginning_credit_days == Decimal("28.50")
        assert balance_2027.credit_days == Decimal("17.00")
        assert balance_2027.converted_to_cash_days == Decimal("0.50")
        assert balance_2027.available_credits == Decimal("45.00")
        balance_2027.used_days = Decimal("5.00")
        _vl_request(
            session,
            company=company,
            employee=employee,
            vacation=vacation,
            public_id="VL-2027",
            start=date(2027, 2, 1),
            end=date(2027, 2, 5),
            days=Decimal("5.00"),
        )
        session.commit()
        service.reconcile_leave_utilization(
            company_id=company.id,
            through_date=date(2027, 12, 31),
        )
        assert balance_2027.adjustment_days == Decimal("-3.50")
        assert balance_2027.available_credits == Decimal("36.50")

        balance_2028 = service._ensure_balance(
            company_id=company.id,
            employee_id=employee.id,
            leave_type=vacation,
            year=2028,
            employee=employee,
            as_of=date(2028, 1, 1),
        )
        assert balance_2028.beginning_credit_days == Decimal("36.50")
        assert balance_2028.credit_days == Decimal("17.00")
        assert balance_2028.converted_to_cash_days == Decimal("8.50")
        assert balance_2028.available_credits == Decimal("45.00")
        balance_2028.used_days = Decimal("8.50")
        _vl_request(
            session,
            company=company,
            employee=employee,
            vacation=vacation,
            public_id="VL-2028",
            start=date(2028, 3, 1),
            end=date(2028, 3, 13),
            days=Decimal("8.50"),
        )
        session.commit()
        service.reconcile_leave_utilization(
            company_id=company.id,
            through_date=date(2028, 12, 31),
        )
        assert balance_2028.adjustment_days == Decimal("0.00")
        assert balance_2028.available_credits == Decimal("36.50")


def test_utilization_notifications_are_idempotent_for_all_required_roles() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        company, employee, vacation, _ = _build_company(session)
        balance = _balance(
            session,
            company=company,
            employee=employee,
            leave_type=vacation,
            year=2026,
            beginning=Decimal("20.00"),
            credit=Decimal("17.00"),
            used=Decimal("0.00"),
        )
        session.commit()
        service = LeaveService(session)
        for _ in range(2):
            service.reconcile_leave_utilization(
                company_id=company.id,
                through_date=date(2026, 12, 15),
            )
        count = session.scalar(
            select(func.count(Notification.id)).where(
                Notification.event_type == "leave_utilization_reminder_final",
                Notification.related_entity_id == balance.id,
            )
        )
        assert count == 4  # employee, leader, manager, and active admin


def test_january_start_uses_the_official_vl_ledger_and_excludes_other_leave() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        company, employee, vacation, sick = _build_company(session)
        balance = _balance(
            session,
            company=company,
            employee=employee,
            leave_type=vacation,
            year=2026,
            beginning=Decimal("0.00"),
            credit=Decimal("17.00"),
            used=Decimal("1.50"),
        )
        sick_balance = _balance(
            session,
            company=company,
            employee=employee,
            leave_type=sick,
            year=2026,
            beginning=Decimal("0.00"),
            credit=Decimal("17.00"),
            used=Decimal("1.00"),
        )
        _vl_request(
            session,
            company=company,
            employee=employee,
            vacation=vacation,
            public_id="VL-BEFORE",
            start=date(2026, 8, 10),
            end=date(2026, 8, 10),
            days=Decimal("1.00"),
        )
        half_day = _vl_request(
            session,
            company=company,
            employee=employee,
            vacation=vacation,
            public_id="VL-HALF",
            start=date(2026, 8, 18),
            end=date(2026, 8, 18),
            days=Decimal("0.50"),
        )
        half_day.duration_code = "90501"
        session.commit()
        service = LeaveService(session)
        summary = service.leave_utilization_summary(
            balance=balance,
            as_of=date(2026, 12, 31),
        )
        assert summary is not None
        assert summary.required_days == Decimal("8.50")
        assert summary.used_days == Decimal("1.50")
        assert summary.remaining_days == Decimal("7.00")
        assert service.leave_utilization_summary(
            balance=sick_balance,
            as_of=date(2026, 12, 31),
        ) is None


def test_visible_used_four_matches_utilization_used_four() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        company, employee, vacation, _ = _build_company(session)
        balance = _balance(
            session,
            company=company,
            employee=employee,
            leave_type=vacation,
            year=2026,
            beginning=Decimal("30.00"),
            credit=Decimal("17.00"),
            used=Decimal("4.00"),
        )
        balance.converted_to_cash_days = Decimal("2.00")
        session.commit()

        summary = LeaveService(session).leave_utilization_summary(
            balance=balance,
            as_of=date(2026, 8, 14),
        )
        assert balance.used_days == Decimal("4.00")
        assert summary is not None
        assert summary.required_days == Decimal("8.50")
        assert summary.used_days == Decimal("4.00")
        assert summary.remaining_days == Decimal("4.50")
        assert balance.available_credits == Decimal("41.00")


def test_full_leave_lifecycle_updates_only_qualifying_vl_utilization() -> None:
    """Exercise filing, approval, AM leave, EL, rejection, and LWP."""

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        company, employee, vacation, _ = _build_company(session)
        service = _FixedDateLeaveService(
            session,
            email_sender=_NoopSender(),
        )
        service.ensure_current_year_balances(company.id, 2026)
        vacation_balance = service.balance_repository.get_balance(
            company_id=company.id,
            employee_id=employee.id,
            leave_type_id=vacation.id,
            year=2026,
        )

        def utilization_used() -> Decimal:
            summary = service.leave_utilization_summary(
                balance=vacation_balance,
                as_of=service.selected_today,
            )
            assert summary is not None
            return summary.used_days

        def file_and_decide(
            *,
            selected_date: date,
            duration_code: str = "90503",
            leave_type_id: int = vacation.id,
            decision: str = "approve",
        ):
            submitted = service.submit_leave_request(
                LeaveRequestInput(
                    company_id=company.id,
                    employee_id=employee.id,
                    requested_by_user_id=employee.user_id,
                    filed_by_employee_id=employee.id,
                    leave_type_id=leave_type_id,
                    start_date=selected_date,
                    end_date=selected_date,
                    duration_code=duration_code,
                    reason_code="12",
                    reason="REST",
                )
            ).request
            # Filing and pending approval never count as consumed VL.
            utilization_before_decision = utilization_used()
            first_decision = (
                "approve" if decision == "approve" else decision
            )
            reviewed = service.decide_leave_request(
                LeaveDecisionInput(
                    company_id=company.id,
                    request_id=submitted.id,
                    manager_employee_id=submitted.current_approver_employee_id,
                    manager_user_id=submitted.current_approver.user_id,
                    decision=first_decision,
                )
            )
            if reviewed.status == "pending_manager_approval":
                reviewed = service.decide_leave_request(
                    LeaveDecisionInput(
                        company_id=company.id,
                        request_id=submitted.id,
                        manager_employee_id=employee.manager_id,
                        manager_user_id=employee.manager.user_id,
                        decision=decision,
                    )
                )
            if decision == "reject":
                assert utilization_used() == utilization_before_decision
            return reviewed

        whole = file_and_decide(selected_date=date(2026, 1, 6))
        assert whole.status == "scheduled"
        assert utilization_used() == Decimal("0.00")
        service.selected_today = date(2026, 1, 6)
        service.reconcile_approved_leave(
            company_id=company.id,
            through_date=service.selected_today,
        )
        assert utilization_used() == Decimal("1.00")

        half = file_and_decide(
            selected_date=date(2026, 1, 7),
            duration_code="90501",
        )
        assert Decimal(half.requested_days) == Decimal("0.50")
        service.selected_today = date(2026, 1, 7)
        service.reconcile_approved_leave(
            company_id=company.id,
            through_date=service.selected_today,
        )
        assert utilization_used() == Decimal("1.50")

        rejected = file_and_decide(
            selected_date=date(2026, 1, 8),
            decision="reject",
        )
        assert rejected.status == "rejected"
        assert utilization_used() == Decimal("1.50")

        emergency = service.leave_type_repository.get_by_code(
            company.id,
            "EMERGENCY",
        )
        assert emergency is not None
        approved_el = file_and_decide(
            selected_date=date(2026, 1, 9),
            leave_type_id=emergency.id,
        )
        assert approved_el.fallback_leave_type_id == vacation.id
        service.selected_today = date(2026, 1, 9)
        service.reconcile_approved_leave(
            company_id=company.id,
            through_date=service.selected_today,
        )
        assert Decimal(vacation_balance.used_days) == Decimal("2.50")
        # EL consumes the VL credit ledger but not the VL utilization target.
        assert utilization_used() == Decimal("1.50")

        # With no paid VL left, an approved request becomes LWP and must not
        # increase utilization even after its date is reconciled.
        vacation_balance.adjustment_days -= Decimal(
            vacation_balance.available_credits
        )
        session.commit()
        lwop = file_and_decide(selected_date=date(2026, 1, 12))
        assert Decimal(lwop.primary_credit_days) == Decimal("0.00")
        assert Decimal(lwop.lwop_days) == Decimal("1.00")
        service.selected_today = date(2026, 1, 12)
        service.reconcile_approved_leave(
            company_id=company.id,
            through_date=service.selected_today,
        )
        assert utilization_used() == Decimal("1.50")


def test_leave_utilization_column_is_vl_only_and_warning_free() -> None:
    employee_ui = (PROJECT_ROOT / "ui/pages/user/leave_management_page.py").read_text()
    admin_ui = (PROJECT_ROOT / "ui/pages/admin/leave_management_page.py").read_text()
    service = (PROJECT_ROOT / "services/leave_service.py").read_text()
    settings = (PROJECT_ROOT / "config/settings.py").read_text()
    assert '"Leave Utilization"' in employee_ui
    assert '"Leave Utilization"' in admin_ui
    assert "LEAVE_UTILIZATION_2026_TARGETS" in service
    assert "leave_utilization_year_end" in service
    assert 'app_version: str = "0.8.8.149"' in settings
    for source in (employee_ui, admin_ui, service):
        assert "st.components.v1.html" not in source
        assert "components.html" not in source
        assert "use_container_width" not in source
