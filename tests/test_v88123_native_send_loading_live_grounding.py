"""v8.8.123 native send icon, loading, and live-grounding checks."""

from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from authentication.current_user import AuthenticatedUser
from config.settings import Settings
from database.base import Base
from models.employee import Employee
from modules.smart_ai.portal_ai import PortalKnowledgeBuilder, SmartPortalAssistant
from scripts.create_initial_data import seed_initial_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code="LIVE",
        initial_company_name="Live Company",
        initial_admin_username="admin",
        initial_admin_email="admin@example.com",
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number="ADMIN-001",
    )


def _current_user(seed, *, clearance: int, employee_id: int) -> AuthenticatedUser:
    user = seed["admin_user"]
    employee = seed["admin_employee"]
    return AuthenticatedUser(
        user_id=user.id,
        company_id=user.company_id,
        company_code=seed["company"].code,
        company_name=seed["company"].name,
        role_id=user.role_id,
        role_name="company_admin" if clearance == 1 else "employee",
        clearance=clearance,
        username=user.username,
        email=user.email,
        employee_id=employee_id,
        employee_number=employee.employee_number,
        employee_name=employee.full_name,
        must_change_password=False,
    )


def test_native_streamlit_send_arrow_is_used_with_controlled_colors() -> None:
    theme = _source("ui/theme/theme_loader.py")
    chat_input_css = theme[theme.index("CHAT ASSISTANT ALIGNMENT + INPUT CONTRAST"):]

    assert '[data-testid="stChatInput"] button > *' in chat_input_css
    assert "display: flex !important;" in chat_input_css
    assert '[data-testid="stChatInput"] button svg' in chat_input_css
    assert "content: none !important;" in chat_input_css
    assert 'content: "↑"' not in chat_input_css
    assert "fill: currentColor" not in chat_input_css
    assert "stroke: currentColor" not in chat_input_css


def test_both_chat_pages_show_assistant_side_loading_state() -> None:
    admin = _source("ui/pages/admin/chat_page.py")
    employee = _source("ui/pages/user/chat_page.py")

    for source in (admin, employee):
        loading_block = source[source.index('with st.chat_message("assistant"):', source.index("if question:")):]
        assert "with st.spinner(" in loading_block
        assert "SmartPortalAssistant(session).enhance" in loading_block


def test_live_builder_is_company_scoped_and_employee_private() -> None:
    factory = _factory()
    with factory() as session:
        seed = seed_initial_data(session, _settings())
        second_employee = Employee(
            company_id=seed["company"].id,
            employee_number="EMP-PRIVATE-002",
            first_name="Private",
            last_name="Coworker",
            employment_status="employed",
        )
        session.add(second_employee)
        session.commit()

        admin_docs = PortalKnowledgeBuilder(session).build(
            current_user=_current_user(
                seed,
                clearance=1,
                employee_id=seed["admin_employee"].id,
            ),
            role_scope="admin",
        )
        employee_docs = PortalKnowledgeBuilder(session).build(
            current_user=_current_user(
                seed,
                clearance=2,
                employee_id=seed["admin_employee"].id,
            ),
            role_scope="employee",
        )

        admin_text = "\n".join(document.text for document in admin_docs)
        employee_text = "\n".join(document.text for document in employee_docs)
        source_types = {document.source_type for document in admin_docs}

        assert "Private Coworker" in admin_text
        assert "Private Coworker" not in employee_text
        assert "live_company" in source_types
        assert "live_employee" in source_types
        assert "live_account" in source_types
        assert "password_hash" not in admin_text.casefold()
        assert seed["admin_user"].password_hash not in admin_text


def test_broad_live_intents_use_grounded_ai_path() -> None:
    assert {
        "employee_summary",
        "account_summary",
        "leave_summary",
        "announcement_summary",
        "attendance",
        "company_forms",
    }.issubset(SmartPortalAssistant._RAG_INTENTS)
    assert not SmartPortalAssistant._RAG_INTENTS.intersection(
        SmartPortalAssistant._DIRECT_LIVE_INTENTS
    )


def test_v88123_checkpoint_is_documented() -> None:
    readme = _source("README.md")

    assert "v8.8.123 — Native Send, Visible Loading" in readme
