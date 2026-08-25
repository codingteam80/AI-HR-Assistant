"""v8.8.173 Chat Assistant YES/NO, scope guard, and follow-up checks."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from authentication.current_user import AuthenticatedUser
from config.settings import Settings
from database.base import Base
from modules.hr_assistant.hr_assistant import HRAssistant, HRAssistantResponse
from modules.smart_ai.portal_ai import SmartPortalAssistant
from modules.smart_ai.prompts.hr_assistant_prompt import (
    OUT_OF_SCOPE_ANSWER,
    UNDETERMINED_ANSWER,
    build_hr_assistant_prompt,
)
from scripts.create_initial_data import seed_initial_data
from services.leave_service import LeaveService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="V173",
        initial_company_name="V173 Company",
        initial_admin_username="admin",
        initial_admin_email="admin@v173.example",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="Test",
        initial_admin_last_name="Employee",
    )


def _user(seed) -> AuthenticatedUser:
    user = seed["admin_user"]
    employee = seed["admin_employee"]
    return AuthenticatedUser(
        user_id=user.id,
        company_id=user.company_id,
        company_code=seed["company"].code,
        company_name=seed["company"].name,
        role_id=user.role_id,
        role_name="company_admin",
        clearance=1,
        username=user.username,
        email=user.email,
        employee_id=employee.id,
        employee_number=employee.employee_number,
        employee_name=employee.full_name,
        must_change_password=False,
    )


def _vl_history() -> list[dict]:
    return [
        {"role": "user", "content": "How many VL credits do I have?"},
        {
            "role": "assistant",
            "content": "You have 15 VL credits remaining.",
            "intent": "leave_balance",
        },
    ]


def test_yes_no_questions_are_detected_in_english_and_tagalog() -> None:
    assert SmartPortalAssistant._is_yes_no_question(
        "Can I carry over unused leave?"
    )
    assert SmartPortalAssistant._is_yes_no_question(
        "Pwede ba akong mag-file ng leave bukas?"
    )
    assert not SmartPortalAssistant._is_yes_no_question(
        "How many VL credits do I have?"
    )
    assert not SmartPortalAssistant._is_yes_no_question(
        "Could you list my leave credits?"
    )


def test_yes_no_output_is_forced_to_binary_or_safe_undetermined() -> None:
    assert SmartPortalAssistant._normalize_yes_no_answer(
        "yes, unused leave can be carried over subject to policy."
    ) == "**YES.** unused leave can be carried over subject to policy."
    assert SmartPortalAssistant._normalize_yes_no_answer(
        "**NO.** The policy does not allow it."
    ) == "**NO.** The policy does not allow it."
    assert SmartPortalAssistant._normalize_yes_no_answer(
        "It depends on information that is not available."
    ) == UNDETERMINED_ANSWER


def test_prompt_contains_exact_yes_no_scope_and_follow_up_rules() -> None:
    prompt = build_hr_assistant_prompt(
        role_rule="Use only authorized employee records.",
        history_text="User: How many VL credits do I have?",
        question="How about SL?",
        router_answer="Sick Leave balance is available.",
        context="Authorized leave data.",
        question_mode="standard",
        follow_up=True,
    )
    assert "YES/NO QUESTIONS:" in prompt
    assert UNDETERMINED_ANSWER in prompt
    assert OUT_OF_SCOPE_ANSWER in prompt
    assert "FOLLOW-UP QUESTIONS:" in prompt
    assert "YES - resolve references from recent conversation." in prompt


def test_batman_is_hard_blocked_as_out_of_scope_without_model_call() -> None:
    original = HRAssistantResponse(
        answer="Information not found in the HR Assistant portal.",
        intent="policy_fallback",
    )
    assistant = SmartPortalAssistant(None)  # retrieval/build are mocked below

    with patch(
        "modules.smart_ai.portal_ai.PortalKnowledgeBuilder.build",
        return_value=[],
    ), patch.object(
        assistant.retriever,
        "search",
        return_value=[],
    ), patch.object(
        assistant.ollama,
        "generate",
    ) as generate:
        response = assistant.enhance(
            current_user=AuthenticatedUser(
                user_id=1,
                company_id=1,
                company_code="V173",
                company_name="V173 Company",
                role_id=1,
                role_name="user",
                clearance=2,
                username="employee",
                email="employee@example.com",
                employee_id=1,
                employee_number="EMP-001",
                employee_name="Employee One",
                must_change_password=False,
            ),
            role_scope="employee",
            question="Sino si Batman?",
            history=[],
            deterministic_response=original,
        )

    generate.assert_not_called()
    assert response.intent == "out_of_scope"
    assert response.answer == OUT_OF_SCOPE_ANSWER
    assert response.actions == []
    assert response.sources == []


def test_yes_no_question_uses_grounded_model_and_starts_with_yes() -> None:
    original = HRAssistantResponse(
        answer="Leave carry-over is governed by the available company leave rules.",
        intent="leave_overview",
    )
    assistant = SmartPortalAssistant(None)

    with patch(
        "modules.smart_ai.portal_ai.PortalKnowledgeBuilder.build",
        return_value=[],
    ), patch.object(
        assistant.retriever,
        "search",
        return_value=[],
    ), patch.object(
        assistant.ollama,
        "generate",
        return_value="Yes, unused leave can be carried over subject to the configured rule.",
    ) as generate:
        response = assistant.enhance(
            current_user=AuthenticatedUser(
                user_id=1,
                company_id=1,
                company_code="V173",
                company_name="V173 Company",
                role_id=1,
                role_name="user",
                clearance=2,
                username="employee",
                email="employee@example.com",
                employee_id=1,
                employee_number="EMP-001",
                employee_name="Employee One",
                must_change_password=False,
            ),
            role_scope="employee",
            question="Can I carry over unused leave?",
            history=[],
            deterministic_response=original,
        )

    generate.assert_called_once()
    assert response.answer.startswith("**YES.**")


def test_yes_no_question_fails_closed_when_model_does_not_commit() -> None:
    original = HRAssistantResponse(
        answer="The current information is incomplete.",
        intent="policy_fallback",
    )
    assistant = SmartPortalAssistant(None)

    with patch(
        "modules.smart_ai.portal_ai.PortalKnowledgeBuilder.build",
        return_value=[],
    ), patch.object(
        assistant.retriever,
        "search",
        return_value=[],
    ), patch.object(
        assistant.ollama,
        "generate",
        return_value="It may depend on another rule.",
    ):
        response = assistant.enhance(
            current_user=AuthenticatedUser(
                user_id=1,
                company_id=1,
                company_code="V173",
                company_name="V173 Company",
                role_id=1,
                role_name="user",
                clearance=2,
                username="employee",
                email="employee@example.com",
                employee_id=1,
                employee_number="EMP-001",
                employee_name="Employee One",
                must_change_password=False,
            ),
            role_scope="employee",
            question="Can I use this benefit?",
            history=[],
            deterministic_response=original,
        )

    assert response.answer == UNDETERMINED_ANSWER


def test_how_about_sl_inherits_previous_leave_balance_context() -> None:
    assert HRAssistant.classify_intent(
        "How about SL?",
        history=_vl_history(),
    ) == "leave_balance"


def test_how_about_sl_returns_sl_not_previous_vl() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        current_user = _user(seed)
        LeaveService(session).ensure_current_year_balances(
            current_user.company_id,
            date.today().year,
        )

        response = HRAssistant(session).answer(
            current_user=current_user,
            question="How about SL?",
            history=_vl_history(),
        )

        assert response.intent == "leave_balance"
        assert "SL — Sick Leave" in response.answer
        assert "VL — Vacation Leave" not in response.answer


def test_reference_follow_up_uses_previous_question_for_retrieval() -> None:
    history = [
        {"role": "user", "content": "Show my latest leave request."},
        {
            "role": "assistant",
            "content": "Your latest leave request is pending manager approval.",
            "intent": "leave_request_status",
        },
    ]
    assert SmartPortalAssistant._is_follow_up_question(
        "Who needs to approve it?",
        history,
    )
    query = SmartPortalAssistant._contextual_search_query(
        "Who needs to approve it?",
        history,
    )
    assert "Show my latest leave request." in query
    assert "Who needs to approve it?" in query


def test_clear_new_topic_does_not_inherit_previous_context() -> None:
    assert not SmartPortalAssistant._is_follow_up_question(
        "Company policies",
        _vl_history(),
    )
    assert SmartPortalAssistant._contextual_search_query(
        "Company policies",
        _vl_history(),
    ) == "Company policies"


def test_current_version_is_v88173() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_version == "0.8.8.173"
    assert "APP_VERSION=0.8.8.173" in (
        PROJECT_ROOT / ".env.example"
    ).read_text(encoding="utf-8")
