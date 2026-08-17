"""Context-aware HR Assistant routing and live-data tests."""

from datetime import date
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from authentication.current_user import AuthenticatedUser
from config.settings import Settings
from database.base import Base
from modules.hr_assistant.hr_assistant import HRAssistant
from scripts.create_initial_data import seed_initial_data
from services.leave_service import LeaveService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="HRCHAT",
        initial_company_name="HR Chat Company",
        initial_admin_username="admin",
        initial_admin_email="admin@hrchat.example",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="Test",
        initial_admin_last_name="Employee",
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _current_user(seed) -> AuthenticatedUser:
    user = seed["admin_user"]
    employee = seed["admin_employee"]

    return AuthenticatedUser(
        user_id=user.id,
        company_id=user.company_id,
        company_code=seed["company"].code,
        company_name=seed["company"].name,
        role_id=user.role_id,
        role_name="company_admin",
        clearance=2,
        username=user.username,
        email=user.email,
        employee_id=employee.id,
        employee_number=employee.employee_number,
        employee_name=employee.full_name,
        must_change_password=False,
    )


def test_shorthand_normalization_supports_vl_sl_el() -> None:
    normalized = HRAssistant.normalize_query("Ilan VL, SL at EL ko?")

    assert "vacation leave" in normalized
    assert "sick leave" in normalized
    assert "emergency leave" in normalized


def test_full_word_and_shorthand_classify_as_leave_balance() -> None:
    assert HRAssistant.classify_intent(
        "Ilan na lang VL ko?"
    ) == "leave_balance"
    assert HRAssistant.classify_intent(
        "How many Vacation Leave credits do I have?"
    ) == "leave_balance"


def test_file_leave_question_returns_direct_form_action() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        response = HRAssistant(session).answer(
            current_user=_current_user(seed),
            question="Paano mag-file ng VL?",
        )

        assert response.intent == "file_leave"
        assert "File Leave Request" in response.answer
        assert response.actions
        assert response.actions[0].page == "Leave Management"
        assert response.actions[0].query_params["leave_view"] == "file"


def test_live_leave_balance_returns_specific_vl_breakdown() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        current_user = _current_user(seed)
        LeaveService(session).ensure_current_year_balances(
            current_user.company_id,
            date.today().year,
        )

        response = HRAssistant(session).answer(
            current_user=current_user,
            question="Ilan na lang VL ko?",
        )

        assert response.intent == "leave_balance"
        assert "VL — Vacation Leave" in response.answer
        assert "15 available" in response.answer
        assert "SL — Sick Leave" not in response.answer
        assert response.actions[0].query_params["leave_view"] == "overview"


def test_general_leave_balance_returns_vl_sl_el_breakdown() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        response = HRAssistant(session).answer(
            current_user=_current_user(seed),
            question="What is my leave balance?",
        )

        assert "VL — Vacation Leave" in response.answer
        assert "SL — Sick Leave" in response.answer
        assert "EL — Emergency Leave" in response.answer


def test_short_follow_up_uses_previous_vl_context() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        history = [
            {"role": "user", "content": "Paano mag-file ng VL?"},
            {
                "role": "assistant",
                "content": "Open Leave Management.",
                "intent": "file_leave",
            },
        ]

        response = HRAssistant(session).answer(
            current_user=_current_user(seed),
            question="Ilan na lang?",
            history=history,
        )

        assert response.intent == "leave_balance"
        assert "VL — Vacation Leave" in response.answer
        assert "SL — Sick Leave" not in response.answer


def test_employee_profile_reads_live_employee_record() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        response = HRAssistant(session).answer(
            current_user=_current_user(seed),
            question="What is my employee number and job title?",
        )

        assert response.intent == "employee_profile"
        assert "ADMIN-001" in response.answer
        assert "Company Administrator" in response.answer


def test_document_question_routes_to_company_forms_workspace() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(session, _settings())
        response = HRAssistant(session).answer(
            current_user=_current_user(seed),
            question="Where can I request my COE document?",
        )

        assert response.intent == "documents"
        assert response.actions[0].page == "Company Form/Documents"
        assert response.actions[0].query_params == {"form_view": "view"}
        assert "My Documents" in response.answer


def test_help_lists_general_hr_capabilities() -> None:
    response = HRAssistant._help_response()

    assert "VL" in response.answer
    assert "filing leave" in response.answer.lower()
    assert "employee number" in response.answer
    assert "Approved company HR policies" in response.answer


def test_chat_page_is_not_policy_only() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/user/chat_page.py"
    ).read_text(encoding="utf-8")

    assert 'st.title("HR Assistant")' in source
    assert "HRAssistant" in source
    assert "live HR records" in source
    assert "Ask a company policy question" not in source


def test_chat_actions_use_internal_navigation() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/user/chat_page.py"
    ).read_text(encoding="utf-8")

    assert "def _open_action(" in source
    assert "set_navigation_state(" in source
    assert "query_params" in source
    assert "Open related HR page" in source


def test_leave_page_honors_assistant_deep_links() -> None:
    page_source = (
        PROJECT_ROOT / "ui/pages/user/leave_management_page.py"
    ).read_text(encoding="utf-8")
    route_source = (
        PROJECT_ROOT / "ui/module_view_navigation.py"
    ).read_text(encoding="utf-8")

    assert "def _assistant_leave_view(" in page_source
    assert 'key="employee_leave_management_active_tab"' in page_source
    assert '("employee", "Leave Management")' in route_source
    assert '"overview": "My Leave Overview"' in route_source
    assert '"file": "File Leave Request"' in route_source
    assert '"requests": "My Requests"' in route_source



def test_policy_keyword_does_not_inherit_leave_topic() -> None:
    history = [
        {
            "role": "user",
            "content": "How do I file VL?",
        },
        {
            "role": "assistant",
            "content": "File Leave Request.",
            "intent": "file_leave",
        },
    ]

    assert HRAssistant.classify_intent(
        "policy",
        history=history,
    ) == "policy"
