"""v8.8.199 hierarchy-chain awareness and documentation-source checks."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models  # noqa: F401
from authentication.current_user import AuthenticatedUser
from database.base import Base
from models.company import Company
from models.department import Department
from models.employee import Employee
from models.role import Role
from models.user import User
from modules.hr_assistant.admin_hr_assistant import AdminHRAssistant
from modules.hr_assistant.hr_assistant import HRAssistant
from services.employee_hierarchy_service import EmployeeHierarchyService


ROOT = Path(__file__).resolve().parents[1]


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed_chain(session: Session, *, code: str = "MAIN"):
    company = Company(code=code, name=f"{code} Company", is_active=True)
    session.add(company)
    session.flush()

    admin_role = Role(company_id=company.id, name="company_admin", is_active=True)
    employee_role = Role(company_id=company.id, name="employee", is_active=True)
    session.add_all([admin_role, employee_role])
    session.flush()

    department = Department(
        company_id=company.id,
        name="Engineering",
        code=f"{code}-ENG",
        is_active=True,
    )
    session.add(department)
    session.flush()

    admin = User(
        company_id=company.id,
        role_id=admin_role.id,
        clearance=1,
        username=f"{code.lower()}_admin",
        email=f"{code.lower()}_admin@example.com",
        password_hash="hash",
        is_active=True,
        must_change_password=False,
    )
    users = {}
    for key in ("marie", "clara", "juan", "ana", "ben"):
        user = User(
            company_id=company.id,
            role_id=employee_role.id,
            clearance=2,
            username=f"{code.lower()}_{key}",
            email=f"{code.lower()}_{key}@example.com",
            password_hash="hash",
            is_active=True,
            must_change_password=False,
        )
        session.add(user)
        users[key] = user
    session.add(admin)
    session.flush()

    def employee(key: str, number: str, first: str, last: str, title: str):
        item = Employee(
            company_id=company.id,
            user_id=users[key].id,
            employee_number=number,
            first_name=first,
            last_name=last,
            job_title=title,
            employment_status="employed",
            department_id=department.id,
        )
        session.add(item)
        return item

    # Titles deliberately do not define hierarchy role.
    marie = employee("marie", f"{code}-001", "Marie", "Santos", "Architect")
    clara = employee("clara", f"{code}-002", "Clara", "Reyes", "Specialist")
    juan = employee("juan", f"{code}-003", "Juan", "Dela Cruz", "Engineer")
    ana = employee("ana", f"{code}-004", "Ana", "Garcia", "Team Lead")
    ben = employee("ben", f"{code}-005", "Ben", "Lopez", "Engineer")
    session.flush()

    # Juan reports upward to Marie as Manager and Clara as Leader.
    # At the same time Juan supervises people below him: Ana selects Juan as
    # Manager, while Ben selects Juan as Leader. This proves that subordinate
    # and supervisor status can coexist in the same hierarchy chain.
    juan.manager_id = marie.id
    juan.leader_id = clara.id
    ana.manager_id = juan.id
    ben.leader_id = juan.id
    session.commit()

    return company, admin, users, marie, clara, juan, ana, ben


def _current(company, user, employee=None, *, clearance: int):
    return AuthenticatedUser(
        user_id=user.id,
        company_id=company.id,
        company_code=company.code,
        company_name=company.name,
        role_id=user.role_id,
        role_name="company_admin" if clearance == 1 else "employee",
        clearance=clearance,
        username=user.username,
        email=user.email,
        employee_id=employee.id if employee is not None else None,
        employee_number=employee.employee_number if employee is not None else None,
        employee_name=employee.full_name if employee is not None else None,
        must_change_password=False,
    )


def test_hierarchy_service_derives_roles_from_reverse_assignments_across_chain() -> None:
    engine = _engine()
    try:
        with Session(engine) as session:
            company, _admin, _users, marie, clara, juan, ana, ben = _seed_chain(session)
            service = EmployeeHierarchyService(session)

            marie_snapshot = service.snapshot(company_id=company.id, employee_id=marie.id)
            clara_snapshot = service.snapshot(company_id=company.id, employee_id=clara.id)
            juan_snapshot = service.snapshot(company_id=company.id, employee_id=juan.id)
            ana_snapshot = service.snapshot(company_id=company.id, employee_id=ana.id)

            assert marie_snapshot is not None and marie_snapshot.role_label == "Manager"
            assert clara_snapshot is not None and clara_snapshot.role_label == "Leader"
            assert juan_snapshot is not None and juan_snapshot.role_label == "Manager and Leader"
            assert ana_snapshot is not None and ana_snapshot.role_label == "No supervisory assignment"

            assert juan_snapshot.manager is not None and juan_snapshot.manager.id == marie.id
            assert juan_snapshot.leader is not None and juan_snapshot.leader.id == clara.id
            assert [item.id for item in juan_snapshot.manager_reports] == [ana.id]
            assert [item.id for item in juan_snapshot.leader_members] == [ben.id]
    finally:
        engine.dispose()


def test_admin_chat_distinguishes_upward_and_downward_manager_leader_relationships() -> None:
    engine = _engine()
    try:
        with Session(engine) as session:
            company, admin, _users, _marie, _clara, juan, ana, ben = _seed_chain(session)
            current = _current(company, admin, clearance=1)
            assistant = AdminHRAssistant(session)

            for question in (
                "Sino manager ni Juan?",
                "Who is Juan's leader?",
                "Manager ba si Juan?",
                "Sino ang members ni Juan?",
            ):
                answer = assistant.answer(current_user=current, question=question)
                assert answer.intent == "employee_hierarchy"
                assert "**Hierarchy Role:** Manager and Leader" in answer.answer
                assert "**Reports to Manager:** Marie Santos" in answer.answer
                assert "**Reports to Leader:** Clara Reyes" in answer.answer
                assert ana.employee_number in answer.answer
                assert ben.employee_number in answer.answer

            marie_answer = assistant.answer(current_user=current, question="Manager ba si Marie?")
            assert marie_answer.intent == "employee_hierarchy"
            assert "**Hierarchy Role:** Manager" in marie_answer.answer
            assert juan.employee_number in marie_answer.answer

            clara_answer = assistant.answer(current_user=current, question="Leader ba si Clara?")
            assert clara_answer.intent == "employee_hierarchy"
            assert "**Hierarchy Role:** Leader" in clara_answer.answer
            assert juan.employee_number in clara_answer.answer

            info_answer = assistant.answer(current_user=current, question="Info ni Juan")
            assert info_answer.intent == "employee_lookup"
            assert "**Hierarchy Role:** Manager and Leader" in info_answer.answer
            assert "**Manager:** Marie Santos" in info_answer.answer
            assert "**Leader:** Clara Reyes" in info_answer.answer
            assert "**As Manager for:**" in info_answer.answer
            assert ana.employee_number in info_answer.answer
            assert "**As Leader for:**" in info_answer.answer
            assert ben.employee_number in info_answer.answer
    finally:
        engine.dispose()


def test_employee_chat_self_scope_covers_own_manager_leader_and_members() -> None:
    engine = _engine()
    try:
        with Session(engine) as session:
            company, _admin, users, _marie, _clara, juan, ana, ben = _seed_chain(session)
            current = _current(company, users["juan"], juan, clearance=2)
            assistant = HRAssistant(session)

            for question in ("Sino manager ko?", "Sino leader ko?", "May members ba ako?"):
                answer = assistant.answer(current_user=current, question=question)
                assert answer.intent == "employee_hierarchy"
                assert "**Hierarchy Role:** Manager and Leader" in answer.answer
                assert "**Your Manager:** Marie Santos" in answer.answer
                assert "**Your Leader:** Clara Reyes" in answer.answer
                assert ana.employee_number in answer.answer
                assert ben.employee_number in answer.answer

            blocked = assistant.answer(
                current_user=current,
                question=f"Sino manager ni {ana.employee_number}?",
            )
            assert blocked.intent == "employee_hierarchy"
            assert "only your own" in blocked.answer
    finally:
        engine.dispose()


def test_hierarchy_queries_remain_company_scoped() -> None:
    engine = _engine()
    try:
        with Session(engine) as session:
            main, main_admin, *_ = _seed_chain(session, code="MAIN")
            _other, _other_admin, _users, _marie, _clara, _juan, _ana, _ben = _seed_chain(
                session,
                code="OTHER",
            )
            current = _current(main, main_admin, clearance=1)
            answer = AdminHRAssistant(session).answer(
                current_user=current,
                question="Sino ang members ni Juan?",
            )
            assert "MAIN-004" in answer.answer
            assert "MAIN-005" in answer.answer
            assert "OTHER-004" not in answer.answer
            assert "OTHER-005" not in answer.answer
    finally:
        engine.dispose()


def test_legacy_schema_docs_defer_to_root_authoritative_files() -> None:
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    schema_readme = (ROOT / "schemas" / "README.md").read_text(encoding="utf-8")
    schema_requirements = (ROOT / "schemas" / "requirements.txt").read_text(encoding="utf-8")

    assert "single source of truth" in root_readme
    assert "../README.md" in schema_readme
    assert "../requirements.txt" in schema_readme
    assert "-r ../requirements.txt" in schema_requirements
    assert "Not implemented yet" not in schema_readme


def test_version_markers_are_v88199() -> None:
    assert 'app_version: str = "0.8.8.199"' in (ROOT / "config" / "settings.py").read_text()
    assert "APP_VERSION=0.8.8.199" in (ROOT / ".env.example").read_text()
