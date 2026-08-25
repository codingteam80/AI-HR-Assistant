"""v8.8.174 Chat Assistant response-accuracy regression checks."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from authentication.current_user import AuthenticatedUser
from config.settings import Settings
from modules.hr_assistant.admin_hr_assistant import AdminHRAssistant
from modules.hr_assistant.hr_assistant import HRAssistant
from modules.smart_ai.portal_ai import SmartPortalAssistant
from modules.smart_ai.prompts.hr_assistant_prompt import build_hr_assistant_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _user(*, role_name: str = "user") -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=1,
        company_id=1,
        company_code="V174",
        company_name="V174 Company",
        role_id=1,
        role_name=role_name,
        clearance=1 if role_name == "company_admin" else 2,
        username="tester",
        email="tester@example.com",
        employee_id=1,
        employee_number="EMP-001",
        employee_name="Test Employee",
        must_change_password=False,
    )


def _request(
    *,
    public_id: str,
    employee_id: int = 1,
    employee_number: str = "EMP-001",
    employee_name: str = "Test Employee",
    leave_name: str = "Vacation Leave",
    status: str = "completed",
    start_date: date | None = None,
    end_date: date | None = None,
    approver_name: str | None = None,
):
    selected = date.today()
    return SimpleNamespace(
        public_id=public_id,
        employee_id=employee_id,
        employee=SimpleNamespace(
            employee_number=employee_number,
            full_name=employee_name,
        ),
        leave_type=SimpleNamespace(name=leave_name),
        status=status,
        start_date=start_date or selected,
        end_date=end_date or selected,
        requested_days=Decimal("1.00"),
        current_approver=(
            SimpleNamespace(full_name=approver_name)
            if approver_name
            else None
        ),
    )


def test_non_binary_questions_are_never_yes_no_questions() -> None:
    for question in (
        "Who needs to approve it?",
        "What happens next?",
        "Show the latest pending leave request.",
        "List the employees who are on leave today.",
        "How many employees are on leave today?",
    ):
        assert not SmartPortalAssistant._is_yes_no_question(question)

    assert SmartPortalAssistant._is_yes_no_question(
        "Can I carry over unused leave?"
    )


def test_non_binary_answer_strips_accidental_yes_no_prefix() -> None:
    assert SmartPortalAssistant._normalize_standard_answer(
        "YES. The latest pending leave request is LRQ_000003."
    ) == "The latest pending leave request is LRQ_000003."
    assert SmartPortalAssistant._normalize_standard_answer(
        "**NO.** No further approval is required because the request is completed."
    ) == "No further approval is required because the request is completed."


def test_carryover_is_an_exact_deterministic_rule_and_skips_qwen() -> None:
    assert HRAssistant.classify_intent(
        "Can I carry over unused leave?"
    ) == "leave_carryover"
    deterministic = HRAssistant._leave_carryover_answer()
    assert deterministic.answer.startswith("**YES.**")
    assert "Sick Leave and Vacation Leave" in deterministic.answer
    assert "typically" not in deterministic.answer.casefold()

    assistant = SmartPortalAssistant(None)
    with patch.object(assistant.ollama, "generate") as generate:
        response = assistant.enhance(
            current_user=_user(),
            role_scope="employee",
            question="Can I carry over unused leave?",
            history=[],
            deterministic_response=deterministic,
        )
    generate.assert_not_called()
    assert response.answer == deterministic.answer


def test_employee_latest_leave_request_returns_exactly_one_record() -> None:
    assistant = HRAssistant(None)
    assistant.leave_service = MagicMock()
    assistant.leave_service.list_employee_requests.return_value = [
        _request(public_id="LRQ_NEW"),
        _request(public_id="LRQ_OLD"),
    ]

    response = assistant.answer(
        current_user=_user(),
        question="Show my latest leave request.",
        history=[],
    )

    assert "LRQ_NEW" in response.answer
    assert "LRQ_OLD" not in response.answer
    assert response.answer.count("- **") == 1


def test_employee_latest_request_follow_up_keeps_latest_single_record() -> None:
    assistant = HRAssistant(None)
    assistant.leave_service = MagicMock()
    assistant.leave_service.list_employee_requests.return_value = [
        _request(public_id="LRQ_NEW"),
        _request(public_id="LRQ_OLD"),
    ]
    history = [
        {"role": "user", "content": "Show my latest leave request."},
        {
            "role": "assistant",
            "content": "Your latest leave request is LRQ_NEW.",
            "intent": "leave_request_status",
        },
    ]

    response = assistant.answer(
        current_user=_user(),
        question="Who needs to approve it?",
        history=history,
    )

    assert "LRQ_NEW" in response.answer
    assert "LRQ_OLD" not in response.answer


def test_admin_on_leave_today_count_is_live_and_exact() -> None:
    assistant = AdminHRAssistant(None)
    assistant.leave_service = MagicMock()
    assistant.leave_service._today.return_value = date.today()
    assistant.leave_service.list_company_requests.return_value = [
        _request(public_id="LRQ_1", employee_id=1),
        _request(
            public_id="LRQ_2",
            employee_id=2,
            employee_number="EMP-002",
            employee_name="Second Employee",
            leave_name="Sick Leave",
            status="in_progress",
        ),
        # Same employee on another active request should not double-count.
        _request(public_id="LRQ_3", employee_id=1, status="approved"),
    ]

    response = assistant._leave_summary(
        _user(role_name="company_admin"),
        "How many employees are on leave today?",
    )

    assert response.intent == "leave_status"
    assert response.answer.startswith("**2** employee(s) are on leave today")


def test_admin_on_leave_today_list_returns_unique_employee_list() -> None:
    assistant = AdminHRAssistant(None)
    assistant.leave_service = MagicMock()
    assistant.leave_service._today.return_value = date.today()
    assistant.leave_service.list_company_requests.return_value = [
        _request(public_id="LRQ_1", employee_id=1),
        _request(
            public_id="LRQ_2",
            employee_id=2,
            employee_number="EMP-002",
            employee_name="Second Employee",
            leave_name="Sick Leave",
            status="in_progress",
        ),
        _request(public_id="LRQ_3", employee_id=1, status="approved"),
    ]

    response = assistant._leave_summary(
        _user(role_name="company_admin"),
        "List the employees who are on leave today.",
    )

    assert response.intent == "leave_status"
    assert response.answer.count("\n- **") == 2
    assert "EMP-001" in response.answer
    assert "EMP-002" in response.answer


def test_admin_latest_pending_returns_one_direct_record_without_yes_prefix() -> None:
    assistant = AdminHRAssistant(None)
    assistant.leave_service = MagicMock()
    assistant.leave_service._today.return_value = date.today()
    assistant.leave_service.list_company_requests.return_value = [
        _request(
            public_id="LRQ_NEW",
            status="pending_leader_approval",
            approver_name="Leader One",
        ),
        _request(
            public_id="LRQ_OLD",
            employee_id=2,
            status="pending_manager_approval",
            approver_name="Manager Two",
        ),
    ]

    response = assistant._leave_summary(
        _user(role_name="company_admin"),
        "Show the latest pending leave request.",
    )

    assert response.intent == "leave_status"
    assert response.answer.startswith("The latest pending leave request is")
    assert "LRQ_NEW" in response.answer
    assert "LRQ_OLD" not in response.answer
    assert not response.answer.startswith(("YES.", "NO.", "**YES.**", "**NO.**"))


def test_prompt_forbids_generic_unsupported_policy_filler() -> None:
    prompt = build_hr_assistant_prompt(
        role_rule="Use only authorized company records.",
        history_text="",
        question="Can I carry over unused leave?",
        router_answer="Exact company rule.",
        context="Exact company context.",
        question_mode="yes_no",
    )
    for word in ("typically", "generally", "usually", "normally", "common practice"):
        assert word in prompt
    assert "Every factual sentence must be directly supported" in prompt


def test_current_version_is_v88174() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_version == "0.8.8.174"
    assert "APP_VERSION=0.8.8.174" in (
        PROJECT_ROOT / ".env.example"
    ).read_text(encoding="utf-8")
