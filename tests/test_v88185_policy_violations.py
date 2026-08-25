"""v8.8.185 violation master-list regression checks."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models  # noqa: F401 - register complete metadata
from authentication.current_user import AuthenticatedUser
from database.base import Base
from models.company import Company
from models.hr_policy import HRPolicy
from models.role import Role
from models.user import User
from modules.hr_assistant.admin_hr_assistant import AdminHRAssistant
from modules.hr_assistant.hr_assistant import HRAssistant
from schemas.policy_schema import PolicyPermanentDeleteRequest
from schemas.policy_violation_schema import (
    PolicyViolationCreateRequest,
    PolicyViolationUpdateRequest,
)
from services.policy_service import PolicyService
from services.policy_violation_service import PolicyViolationService


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed_company(session: Session, *, code: str = "TEST"):
    company = Company(code=code, name=f"{code} Company", is_active=True)
    session.add(company)
    session.flush()
    role = Role(
        company_id=company.id,
        name="company_admin",
        description="Admin",
        is_active=True,
    )
    session.add(role)
    session.flush()
    user = User(
        company_id=company.id,
        role_id=role.id,
        clearance=1,
        username=f"admin_{code.lower()}",
        email=f"admin_{code.lower()}@example.com",
        password_hash="hash",
        is_active=True,
        must_change_password=False,
    )
    session.add(user)
    session.commit()
    return company.id, user.id




def _current_user(*, company_id: int, user_id: int, role_id: int = 1, clearance: int = 2):
    return AuthenticatedUser(
        user_id=user_id,
        company_id=company_id,
        company_code="TEST",
        company_name="TEST Company",
        role_id=role_id,
        role_name="employee" if clearance == 2 else "company_admin",
        clearance=clearance,
        username="tester",
        email="tester@example.com",
        employee_id=None,
        employee_number=None,
        employee_name=None,
        must_change_password=False,
    )

def _request(company_id: int, user_id: int, *, code: str = "ATT-001", **overrides):
    values = {
        "company_id": company_id,
        "created_by_user_id": user_id,
        "violation_code": code,
        "category": "Attendance",
        "offense_title": "Habitual Tardiness",
        "description": "Repeated late arrival beyond the company attendance rule.",
        "severity": "Minor",
        "first_offense_action": "Verbal Warning",
        "second_offense_action": "Written Warning",
        "third_offense_action": "Suspension",
        "final_action": "Termination",
        "effective_date": date.today(),
        "status": "active",
        "notes": "Apply together with the approved attendance policy.",
    }
    values.update(overrides)
    return PolicyViolationCreateRequest(**values)


def test_version_model_runtime_and_navigation_markers() -> None:
    assert 'app_version: str = "0.8.8.185"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.185" in _source(".env")
    assert "APP_VERSION=0.8.8.185" in _source(".env.example")
    assert '"policy_violations"' in _source("database/runtime_schema.py")
    assert 'from models.policy_violation import PolicyViolation' in _source("models/__init__.py")
    routes = _source("ui/module_view_navigation.py")
    assert '"violations": "Violations & Disciplinary Actions"' in routes
    assert '("employee", "Company Policies")' in routes


def test_create_update_duplicate_and_company_scope() -> None:
    engine = _engine()
    with Session(engine) as session:
        company_id, user_id = _seed_company(session)
        other_company_id, other_user_id = _seed_company(session, code="OTHER")

    with Session(engine) as session:
        service = PolicyViolationService(session)
        item = service.create_violation(_request(company_id, user_id, code="att-001"))
        assert item.violation_code == "ATT-001"
        assert item.public_id.startswith("VIO_")
        assert item.company_id == company_id

        with pytest.raises(ValueError, match="already exists"):
            service.create_violation(_request(company_id, user_id, code="ATT-001"))

        foreign = service.create_violation(
            _request(other_company_id, other_user_id, code="ATT-001")
        )
        assert foreign.company_id == other_company_id

        updated = service.update_violation(
            PolicyViolationUpdateRequest(
                company_id=company_id,
                violation_id=item.id,
                edited_by_user_id=user_id,
                violation_code="ATT-002",
                category="Attendance",
                offense_title="Repeated Tardiness",
                description="Repeated late arrival.",
                severity="Moderate",
                first_offense_action="Written Warning",
                second_offense_action="Final Written Warning",
                third_offense_action="Suspension",
                final_action="Termination",
                effective_date=date.today(),
                status="active",
                notes=None,
            )
        )
        assert updated.violation_code == "ATT-002"
        assert updated.severity == "Moderate"

        with pytest.raises(ValueError, match="does not belong"):
            service.update_violation(
                PolicyViolationUpdateRequest(
                    company_id=other_company_id,
                    violation_id=updated.id,
                    edited_by_user_id=other_user_id,
                    violation_code="ATT-099",
                    category="Attendance",
                    offense_title="Wrong Tenant",
                    description="Wrong tenant edit.",
                    severity="Minor",
                    first_offense_action="AA",
                    second_offense_action="BB",
                    third_offense_action="CC",
                    final_action="DD",
                    status="active",
                )
            )



def test_non_admin_cannot_mutate_violation_master_list() -> None:
    engine = _engine()
    with Session(engine) as session:
        company_id, admin_user_id = _seed_company(session)
        admin = session.get(User, admin_user_id)
        member = User(
            company_id=company_id,
            role_id=admin.role_id,
            clearance=2,
            username="member_test",
            email="member_test@example.com",
            password_hash="hash",
            is_active=True,
            must_change_password=False,
        )
        session.add(member)
        session.commit()

        with pytest.raises(ValueError, match="Only an active administrator"):
            PolicyViolationService(session).create_violation(
                _request(company_id, member.id, code="SEC-001")
            )


def test_employee_visibility_excludes_inactive_future_and_archived() -> None:
    engine = _engine()
    with Session(engine) as session:
        company_id, user_id = _seed_company(session)
        service = PolicyViolationService(session)
        visible = service.create_violation(_request(company_id, user_id, code="A-001"))
        service.create_violation(
            _request(company_id, user_id, code="A-002", status="inactive")
        )
        service.create_violation(
            _request(
                company_id,
                user_id,
                code="A-003",
                effective_date=date.today() + timedelta(days=30),
            )
        )
        archived = service.create_violation(_request(company_id, user_id, code="A-004"))
        service.archive_violation(
            company_id=company_id,
            violation_id=archived.id,
            archived_by_user_id=user_id,
        )

        items = service.list_employee_visible(
            company_id=company_id,
            as_of_date=date.today(),
        )
        assert [item.violation_code for item in items] == [visible.violation_code]

        restored = service.restore_violation(
            company_id=company_id,
            violation_id=archived.id,
            restored_by_user_id=user_id,
        )
        assert restored.archived_at is None
        assert {item.violation_code for item in service.list_employee_visible(
            company_id=company_id,
            as_of_date=date.today(),
        )} == {"A-001", "A-004"}


def test_deterministic_violation_answers_use_live_master_data() -> None:
    engine = _engine()
    with Session(engine) as session:
        company_id, user_id = _seed_company(session)
        service = PolicyViolationService(session)
        service.create_violation(_request(company_id, user_id, code="ATT-001"))
        service.create_violation(
            _request(
                company_id,
                user_id,
                code="CON-001",
                category="Conduct",
                offense_title="Insubordination",
                severity="Major",
                description="Refusal to follow a lawful company instruction.",
            )
        )

        second = service.answer_question(
            company_id=company_id,
            question="What happens on the second offense for ATT-001?",
        )
        assert "Written Warning" in second
        assert "ATT-001" in second

        major = service.answer_question(
            company_id=company_id,
            question="What are the major violations?",
        )
        assert "CON-001" in major
        assert "ATT-001" not in major

        count = service.answer_question(
            company_id=company_id,
            question="How many violations are configured?",
        )
        assert "**2**" in count

        yes = service.answer_question(
            company_id=company_id,
            question="Is ATT-001 a Minor violation?",
        )
        assert yes.startswith("**YES.**")
        assert "**Minor**" in yes

        no = service.answer_question(
            company_id=company_id,
            question="Is ATT-001 a Major violation?",
        )
        assert no.startswith("**NO.**")
        assert "**Minor**" in no
        assert "not Major" in no

        inactive = service.answer_question(
            company_id=company_id,
            question="Is ATT-001 inactive?",
        )
        assert inactive.startswith("**NO.**")


def test_related_policy_is_company_scoped_and_delete_clears_link() -> None:
    engine = _engine()
    with Session(engine) as session:
        company_id, user_id = _seed_company(session)
        other_company_id, other_user_id = _seed_company(session, code="OTHER")
        policy = HRPolicy(
            public_id="PID_TEST_1",
            company_id=company_id,
            created_by_user_id=user_id,
            title="Attendance Policy",
            category="Attendance",
            content="Attendance policy content long enough for a policy record.",
            version="1.0",
            status="trashed",
        )
        foreign_policy = HRPolicy(
            public_id="PID_OTHER_1",
            company_id=other_company_id,
            created_by_user_id=other_user_id,
            title="Other Policy",
            category="Other",
            content="Other company policy content long enough for testing.",
            version="1.0",
            status="published",
        )
        session.add_all([policy, foreign_policy])
        session.commit()
        policy_id = policy.id
        foreign_policy_id = foreign_policy.id

        violation_service = PolicyViolationService(session)
        with pytest.raises(ValueError, match="not in this company"):
            violation_service.create_violation(
                _request(
                    company_id,
                    user_id,
                    code="ATT-010",
                    related_policy_id=foreign_policy_id,
                )
            )

        # Temporarily restore the company policy to link it, then put it in Bin.
        policy.status = "published"
        session.commit()
        item = violation_service.create_violation(
            _request(
                company_id,
                user_id,
                code="ATT-011",
                related_policy_id=policy_id,
            )
        )
        policy.status = "trashed"
        session.commit()

        PolicyService(session).permanently_delete_from_bin(
            PolicyPermanentDeleteRequest(
                company_id=company_id,
                policy_id=policy_id,
                confirmation_public_id="PID_TEST_1",
                permanent_delete_acknowledged=True,
            )
        )
        session.refresh(item)
        assert item.related_policy_id is None


def test_admin_and_employee_ui_scope_and_warning_safe_confirmation() -> None:
    admin_page = _source("ui/pages/admin/policies_page.py")
    admin_workspace = _source("ui/pages/admin/policy_violations.py")
    employee_page = _source("ui/pages/user/policies_page.py")
    employee_workspace = _source("ui/pages/user/policy_violations.py")

    assert '"Violations & Disciplinary Actions"' in admin_page
    assert '"Current Violations", "Add Violation", "Edit Violation", "Archive"' in admin_workspace
    assert "archive_violation(" in admin_workspace
    assert "restore_violation(" in admin_workspace
    assert "render_operation_feedback(namespace=\"policy_violation\")" in admin_workspace
    assert 'key=confirmation_key' in admin_workspace
    assert 'st.checkbox(' in admin_workspace
    assert 'value=False' not in admin_workspace

    assert '"Company Policies"' in employee_page
    assert '"Violations & Disciplinary Actions"' in employee_page
    assert '"My Disciplinary Records"' in employee_page
    assert "list_employee_visible(" in employee_workspace
    assert "create_violation(" not in employee_workspace
    assert "update_violation(" not in employee_workspace
    assert "archive_violation(" not in employee_workspace


def test_chat_assistant_has_deterministic_and_rag_violation_grounding() -> None:
    employee = _source("modules/hr_assistant/hr_assistant.py")
    admin = _source("modules/hr_assistant/admin_hr_assistant.py")
    smart = _source("modules/smart_ai/portal_ai.py")

    assert '"violation"' in employee
    assert "self.violation_service.answer_question(" in employee
    assert 'query_params={"policy_view": "violations"}' in employee
    assert "self.violation_service.answer_question(" in admin
    assert 'query_params={"policy_view": "violations"}' in admin
    assert 'source_type="policy_violation"' in smart
    assert "list_employee_visible(" in smart
    assert '"policy_violation"' in smart.split("_NEVER_ENHANCE_INTENTS", 1)[1]



def test_employee_and_admin_chat_keep_violation_follow_up_context() -> None:
    engine = _engine()
    with Session(engine) as session:
        company_id, user_id = _seed_company(session)
        role_id = session.get(User, user_id).role_id
        PolicyViolationService(session).create_violation(
            _request(company_id, user_id, code="ATT-001")
        )

        employee_user = _current_user(
            company_id=company_id,
            user_id=user_id,
            role_id=role_id,
            clearance=2,
        )
        employee_assistant = HRAssistant(session)
        first = employee_assistant.answer(
            current_user=employee_user,
            question="What is ATT-001?",
        )
        follow = employee_assistant.answer(
            current_user=employee_user,
            question="What about the second offense?",
            history=[
                {"role": "user", "content": "What is ATT-001?"},
                {
                    "role": "assistant",
                    "content": first.answer,
                    "intent": first.intent,
                },
            ],
        )
        assert first.intent == "policy_violation"
        assert follow.intent == "policy_violation"
        assert "Written Warning" in follow.answer

        # Explicit policy follow-up context must not inherit from a different topic.
        unrelated = HRAssistant._contextual_query(
            "What about the second offense?",
            [
                {"role": "user", "content": "How many leave credits do I have?"},
                {"role": "assistant", "content": "5", "intent": "leave_balance"},
            ],
        )
        assert unrelated == "what about the second offense"

        admin_user = _current_user(
            company_id=company_id,
            user_id=user_id,
            role_id=role_id,
            clearance=1,
        )
        admin_assistant = AdminHRAssistant(session)
        admin_first = admin_assistant.answer(
            current_user=admin_user,
            question="What is ATT-001?",
        )
        admin_follow = admin_assistant.answer(
            current_user=admin_user,
            question="What about the second offense?",
            history=[
                {"role": "user", "content": "What is ATT-001?"},
                {
                    "role": "assistant",
                    "content": admin_first.answer,
                    "intent": admin_first.intent,
                },
            ],
        )
        assert admin_first.intent == "policy_violation"
        assert admin_follow.intent == "policy_violation"
        assert "Written Warning" in admin_follow.answer

def test_history_and_policy_delete_edge_cases_are_guarded() -> None:
    management = _source("services/admin_management_service.py")
    policy_service = _source("services/policy_service.py")
    audit_listener = _source("database/audit_listener.py")

    assert "PolicyViolation.created_by_user_id == user_id" in management
    assert "policy history or violation history" in management
    assert "linked_violations" in policy_service
    assert "violation.related_policy_id = None" in policy_service
    assert '"policy_violations"' not in audit_listener.split("_EXCLUDED_TABLES", 1)[1].split("}", 1)[0]
