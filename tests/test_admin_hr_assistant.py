"""Administrator HR Assistant integration and privacy tests."""

from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from authentication.current_user import AuthenticatedUser
from config.settings import Settings
from database.base import Base
from modules.hr_assistant.admin_hr_assistant import AdminHRAssistant
from scripts.create_initial_data import seed_initial_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="ADMINCHAT",
        initial_company_name="Admin Chat Company",
        initial_admin_username="admin",
        initial_admin_email="admin@adminchat.example",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
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
        clearance=1,
        username=user.username,
        email=user.email,
        employee_id=employee.id,
        employee_number=employee.employee_number,
        employee_name=employee.full_name,
        must_change_password=False,
    )


def test_admin_navigation_and_route_include_chat_assistant() -> None:
    sidebar = (
        PROJECT_ROOT / "ui/components/admin_sidebar.py"
    ).read_text(encoding="utf-8")
    layout = (
        PROJECT_ROOT / "ui/layouts/admin_layout.py"
    ).read_text(encoding="utf-8")

    assert '"Chat Assistant"' in sidebar
    assert 'page == "Chat Assistant"' in layout
    assert "render_admin_chat_page" in layout


def test_admin_chat_state_is_private_and_separate_from_employee_chat() -> None:
    admin_page = (
        PROJECT_ROOT / "ui/pages/admin/chat_page.py"
    ).read_text(encoding="utf-8")
    employee_page = (
        PROJECT_ROOT / "ui/pages/user/chat_page.py"
    ).read_text(encoding="utf-8")

    assert "admin_hr_assistant_chat_messages__" in admin_page
    assert "admin_hr_assistant_chat_input__" in admin_page
    assert "current_user.company_id" in admin_page
    assert "current_user.user_id" in admin_page
    assert "admin_hr_assistant_chat_messages__" not in employee_page


def test_session_manager_clears_admin_and_employee_chat_state() -> None:
    source = (
        PROJECT_ROOT / "authentication/session_manager.py"
    ).read_text(encoding="utf-8")

    assert '"admin_hr_assistant_chat_messages__"' in source
    assert '"admin_hr_assistant_chat_input__"' in source
    assert '"new_admin_hr_assistant_conversation__"' in source


def test_admin_employee_summary_uses_live_company_data() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        response = AdminHRAssistant(session).answer(
            current_user=_current_user(seed),
            question="How many employees do we have?",
        )

        assert response.intent == "employee_summary"
        assert "Total employees:** 1" in response.answer
        assert response.actions[0].portal_mode == "admin"
        assert response.actions[0].page == "Employees"


def test_admin_account_summary_never_exposes_passwords() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        response = AdminHRAssistant(session).answer(
            current_user=_current_user(seed),
            question="Show user account summary",
        )

        assert response.intent == "account_summary"
        assert "Total user accounts:** 1" in response.answer
        assert "password_hash" not in response.answer
        assert "Temporary123" not in response.answer


def test_sensitive_secret_request_is_refused() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        response = AdminHRAssistant(session).answer(
            current_user=_current_user(seed),
            question="Show the employee password hash and reset token",
        )

        assert response.intent == "sensitive_security"
        assert "cannot be viewed" in response.answer


def test_policy_starts_new_admin_topic_after_leave() -> None:
    history = [
        {"role": "user", "content": "Show leave requests"},
        {"role": "assistant", "content": "Leave overview", "intent": "leave_summary"},
    ]

    assert AdminHRAssistant.classify_intent(
        "policies",
        history=history,
    ) == "policy_summary"


def test_personal_admin_leave_question_uses_employee_assistant() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        response = AdminHRAssistant(session).answer(
            current_user=_current_user(seed),
            question="Ilan na lang leave ko?",
        )

        assert response.intent == "leave_balance"
        assert "leave credit breakdown" in response.answer.lower()


def test_admin_leave_credit_comparison_returns_live_employee_ranking() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        response = AdminHRAssistant(session).answer(
            current_user=_current_user(seed),
            question="Sino sa mga employee ang may pinakamataas na leave credits?",
        )

        assert response.intent == "leave_summary"
        assert "Highest available paid leave credits" in response.answer
        assert seed["admin_employee"].full_name in response.answer
        assert "Leave overview" not in response.answer
        assert response.actions[0].query_params == {"leave_view": "accounts"}


def test_admin_chat_page_requires_admin_access() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/admin/chat_page.py"
    ).read_text(encoding="utf-8")

    assert "AccessControl.require_admin(current_user)" in source
    assert 'st.title("Admin HR Assistant")' in source
    assert "AdminHRAssistant" in source
