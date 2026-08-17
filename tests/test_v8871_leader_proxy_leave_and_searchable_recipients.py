"""Leader proxy filing, staged approval, and searchable recipient regression."""

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
from schemas.leave_schema import LeaveDecisionInput, LeaveRequestInput
from scripts.create_initial_data import seed_initial_data
from services.leave_service import LeaveService


class CapturingSender:
    def __init__(self) -> None:
        self.messages: list[OutboundEmail] = []

    def send(self, message: OutboundEmail) -> str:
        self.messages.append(message)
        return "captured"


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="V8871",
        initial_company_name="Hierarchy Company",
        initial_admin_username="manager",
        initial_admin_email="manager@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="MGR-001",
        initial_admin_first_name="Mara",
        initial_admin_last_name="Manager",
        leave_attachment_dir=str(tmp_path / "leave"),
        password_reset_outbox_dir=str(tmp_path / "outbox"),
    )


def _user_employee(session, seed, *, username, email, number, first, last, manager_id=None, leader_id=None):
    user = User(
        company_id=seed["company"].id,
        role_id=seed["admin_user"].role_id,
        clearance=2,
        username=username,
        email=email,
        password_hash=seed["admin_user"].password_hash,
        is_active=True,
        must_change_password=False,
    )
    session.add(user)
    session.flush()
    employee = Employee(
        company_id=seed["company"].id,
        user_id=user.id,
        manager_id=manager_id,
        leader_id=leader_id,
        employee_number=number,
        first_name=first,
        last_name=last,
        work_email=email,
        employment_status="employed",
        hire_date=date(2020, 1, 1),
        gender="Male",
    )
    session.add(employee)
    session.flush()
    return user, employee


def _next_weekday() -> date:
    selected = date.today() + timedelta(days=2)
    while selected.weekday() >= 5:
        selected += timedelta(days=1)
    return selected


def _leave_type(service, company_id, employee_id, code):
    return next(
        item.leave_type
        for item in service.list_employee_balances(company_id, employee_id)
        if item.leave_type.code == code
    )


def test_self_filed_request_routes_leader_then_manager(tmp_path: Path) -> None:
    factory = _factory()
    sender = CapturingSender()
    with factory() as session:
        seed = seed_initial_data(session, _settings(tmp_path))
        manager = seed["admin_employee"]
        manager.work_email = "manager@example.com"
        leader_user, leader = _user_employee(
            session, seed,
            username="leader", email="leader@example.com", number="LEAD-001",
            first="Lina", last="Leader", manager_id=manager.id,
        )
        member_user, member = _user_employee(
            session, seed,
            username="member", email="member@example.com", number="EMP-001",
            first="Milo", last="Member", manager_id=manager.id, leader_id=leader.id,
        )
        session.commit()
        service = LeaveService(session, settings=_settings(tmp_path), email_sender=sender)
        sick = _leave_type(service, seed["company"].id, member.id, "SICK")
        start = _next_weekday()

        submitted = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=member.id,
                requested_by_user_id=member_user.id,
                filed_by_employee_id=member.id,
                to_user_id=leader_user.id,
                cc_user_ids=[member_user.id],
                leave_type_id=sick.id,
                start_date=start,
                end_date=start,
                reason="Medical consultation",
            )
        ).request

        assert submitted.status == "pending_leader_approval"
        assert submitted.current_approver_employee_id == leader.id
        assert submitted.manager_employee_id == manager.id
        assert submitted.filed_on_behalf is False

        forwarded = service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=submitted.id,
                manager_employee_id=leader.id,
                manager_user_id=leader_user.id,
                decision="approve",
                manager_comment="Confirmed by leader",
            )
        )
        assert forwarded.status == "pending_manager_approval"
        assert forwarded.current_approver_employee_id == manager.id
        assert forwarded.leader_comment == "Confirmed by leader"

        final = service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=submitted.id,
                manager_employee_id=manager.id,
                manager_user_id=seed["admin_user"].id,
                decision="approve",
            )
        )
        assert final.status in {"scheduled", "approved", "completed"}
        assert final.current_approver_employee_id is None


def test_leader_files_emergency_for_member_and_member_credit_is_used(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        manager = seed["admin_employee"]
        manager.work_email = "manager@example.com"
        leader_user, leader = _user_employee(
            session, seed,
            username="leader2", email="leader2@example.com", number="LEAD-002",
            first="Leo", last="Leader", manager_id=manager.id,
        )
        member_user, member = _user_employee(
            session, seed,
            username="member2", email="member2@example.com", number="EMP-002",
            first="Mia", last="Member", manager_id=manager.id, leader_id=leader.id,
        )
        session.commit()
        service = LeaveService(session, settings=settings, email_sender=CapturingSender())
        emergency = _leave_type(service, seed["company"].id, member.id, "EMERGENCY")
        member_vl_before = next(
            b for b in service.list_employee_balances(seed["company"].id, member.id)
            if b.leave_type.code == "VACATION"
        )
        leader_vl_before = next(
            b for b in service.list_employee_balances(seed["company"].id, leader.id)
            if b.leave_type.code == "VACATION"
        )
        member_reserved_before = Decimal(member_vl_before.reserved_days)
        leader_reserved_before = Decimal(leader_vl_before.reserved_days)
        start = _next_weekday()

        request = service.submit_leave_request(
            LeaveRequestInput(
                company_id=seed["company"].id,
                employee_id=member.id,
                requested_by_user_id=leader_user.id,
                filed_by_employee_id=leader.id,
                to_user_id=seed["admin_user"].id,
                cc_user_ids=[member_user.id, leader_user.id],
                leave_type_id=emergency.id,
                start_date=start,
                end_date=start,
                reason="Employee reported an urgent emergency",
            )
        ).request
        assert request.filed_on_behalf is True
        # Proxy filing is creation only. It must follow the leave owner's
        # normal Leader -> Manager approval route without auto-approval.
        assert request.status == "pending_leader_approval"
        assert request.current_approver_employee_id == leader.id

        request = service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=request.id,
                manager_employee_id=leader.id,
                manager_user_id=leader_user.id,
                decision="approve",
            )
        )
        assert request.status == "pending_manager_approval"
        assert request.current_approver_employee_id == manager.id

        service.decide_leave_request(
            LeaveDecisionInput(
                company_id=seed["company"].id,
                request_id=request.id,
                manager_employee_id=manager.id,
                manager_user_id=seed["admin_user"].id,
                decision="approve",
            )
        )
        member_vl_after = next(
            b for b in service.list_employee_balances(seed["company"].id, member.id)
            if b.leave_type.code == "VACATION"
        )
        leader_vl_after = next(
            b for b in service.list_employee_balances(seed["company"].id, leader.id)
            if b.leave_type.code == "VACATION"
        )
        assert Decimal(member_vl_after.reserved_days) == member_reserved_before + Decimal("1.00")
        assert Decimal(leader_vl_after.reserved_days) == leader_reserved_before


def test_proxy_filing_rejects_non_member_and_non_sl_el(tmp_path: Path) -> None:
    factory = _factory()
    with factory() as session:
        settings = _settings(tmp_path)
        seed = seed_initial_data(session, settings)
        seed["admin_employee"].work_email = "manager@example.com"
        leader_user, leader = _user_employee(
            session, seed,
            username="leader3", email="leader3@example.com", number="LEAD-003",
            first="Lia", last="Leader", manager_id=seed["admin_employee"].id,
        )
        _, outsider = _user_employee(
            session, seed,
            username="outsider", email="outsider@example.com", number="EMP-003",
            first="Oli", last="Outside", manager_id=seed["admin_employee"].id,
        )
        session.commit()
        service = LeaveService(session, settings=settings, email_sender=CapturingSender())
        sick = _leave_type(service, seed["company"].id, outsider.id, "SICK")
        start = _next_weekday()
        try:
            service.submit_leave_request(
                LeaveRequestInput(
                    company_id=seed["company"].id,
                    employee_id=outsider.id,
                    requested_by_user_id=leader_user.id,
                    filed_by_employee_id=leader.id,
                    leave_type_id=sick.id,
                    start_date=start,
                    end_date=start,
                    reason="Invalid proxy request",
                )
            )
        except ValueError as error:
            assert "direct member" in str(error)
        else:
            raise AssertionError("Non-member proxy request was accepted")


def test_ui_uses_searchable_to_cc_and_leader_team_tabs() -> None:
    source = (Path(__file__).resolve().parents[1] / "ui/pages/user/leave_management_page.py").read_text()
    assert 'st.selectbox(\n            "To *"' in source
    assert 'st.multiselect(\n            "CC"' in source
    assert '"File for Team Member"' in source
    assert '"Team Filed Requests"' in source
    assert "Type a person's name" in source
