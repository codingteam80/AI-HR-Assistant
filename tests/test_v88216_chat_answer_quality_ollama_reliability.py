"""v8.8.216 Chat answer-quality and Ollama reliability regressions."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from urllib import error as urllib_error
import json

import pytest

from modules.hr_assistant.hr_assistant import HRAssistantResponse
from modules.smart_ai import portal_ai
from modules.smart_ai.portal_ai import (
    HybridRetriever,
    KnowledgeDocument,
    OllamaClient,
    RetrievedDocument,
    SmartPortalAssistant,
    _focused_evidence_excerpt,
)
from modules.smart_ai.prompts.hr_assistant_prompt import HR_ASSISTANT_RULES
from services.policy_service import PolicyService
from services.runtime_connection_service import (
    RuntimeServiceModelUnavailableError,
    RuntimeServiceResponseError,
    RuntimeServiceTimeoutError,
    classify_runtime_connection_issue,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self.payload


def _doc(
    doc_id: str,
    *,
    title: str,
    text: str,
    file_key: str,
    chunk_index: int = 1,
    section: str = "Policy Details",
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=doc_id,
        text=text,
        title=title,
        source_type="policy",
        company_id=1,
        role_scope="shared",
        metadata={
            "file_key": file_key,
            "filename": title,
            "title": title,
            "section": section,
            "chunk_index": chunk_index,
            "total_chunks": 1,
        },
    )


def test_runtime_classifier_distinguishes_ollama_failures() -> None:
    generation = classify_runtime_connection_issue(
        RuntimeServiceTimeoutError(
            "ollama", operation="generation", timeout_seconds=180
        ),
        service_hint="ollama",
    )
    assert generation is not None
    assert generation.code == "ollama_response_timeout"
    assert generation.title == "AI response timed out"

    health = classify_runtime_connection_issue(
        RuntimeServiceTimeoutError(
            "ollama", operation="health_check", timeout_seconds=5
        ),
        service_hint="ollama",
    )
    assert health is not None
    assert health.code == "ollama_health_timeout"

    model = classify_runtime_connection_issue(
        RuntimeServiceModelUnavailableError(
            "ollama", model="qwen2.5:7b"
        ),
        service_hint="ollama",
    )
    assert model is not None
    assert model.code == "ollama_model_missing"
    assert "qwen2.5:7b" in model.message


def test_ollama_health_check_verifies_configured_model(monkeypatch) -> None:
    OllamaClient._availability_cache.clear()
    client = OllamaClient()
    monkeypatch.setattr(
        portal_ai.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(
            {"models": [{"name": "llama3.2:3b"}]}
        ),
    )
    with pytest.raises(RuntimeServiceModelUnavailableError) as captured:
        client.check_available()
    assert captured.value.model == "qwen2.5:7b"

    OllamaClient._availability_cache.clear()
    monkeypatch.setattr(
        portal_ai.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(
            {"models": [{"name": "qwen2.5:7b"}]}
        ),
    )
    client.check_available()


def test_ollama_generation_timeout_is_not_mislabeled_unavailable(monkeypatch) -> None:
    client = OllamaClient()

    def _timeout(*_args, **_kwargs):
        raise TimeoutError("generation took too long")

    monkeypatch.setattr(portal_ai.request, "urlopen", _timeout)
    with pytest.raises(RuntimeServiceTimeoutError) as captured:
        client.generate("hello")
    assert captured.value.operation == "generation"


def test_policy_focused_excerpt_keeps_late_matching_clause() -> None:
    prefix = "General background sentence. " * 120
    clause = (
        "Failure to log-in and log-out shall automatically disqualify the "
        "employee in the Perfect Attendance Award."
    )
    excerpt = PolicyService._focused_policy_excerpt(
        question="What happens if an employee forgets to log in or log out?",
        text=prefix + clause,
        max_chars=700,
    )
    assert "automatically disqualify" in excerpt
    assert len(excerpt) <= 700


def test_question_focused_evidence_excerpt_preserves_exact_amount() -> None:
    text = (
        "This section contains unrelated introductory guidance. " * 50
        + "The maximum taxi reimbursement is P300.00 per day. "
        + "The employee must retain the supporting receipt."
    )
    excerpt = _focused_evidence_excerpt(
        "What is the maximum taxi reimbursement per day?",
        text,
        650,
    )
    assert "P300.00" in excerpt
    assert "supporting receipt" in excerpt


def test_retrieval_keeps_distinct_applicable_policy_sources(monkeypatch) -> None:
    retriever = HybridRetriever()
    monkeypatch.setattr(retriever.vector, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(retriever.file_vector, "search", lambda *_a, **_k: [])

    documents = [
        _doc(
            "work-1",
            title="Work Schedule.docx",
            file_key="work",
            text=(
                "When an Associate has failed to login and/or log-out, the DTR "
                "System cannot verify the required hours. Regardless of frequency, "
                "the Associate will be deemed absent for that day."
            ),
        ),
        _doc(
            "perfect-1",
            title="Perfect Attendance.docx",
            file_key="perfect",
            text=(
                "Failure to log-in and log-out shall automatically disqualify "
                "the employee in the Perfect Attendance Award."
            ),
        ),
        _doc(
            "noise-1",
            title="Training & Development.docx",
            file_key="training",
            text="Employees log training attendance and submit seminar forms.",
        ),
    ]

    results = retriever.search(
        "What happens if an employee forgets to log in or log out?",
        documents,
        company_id=1,
        role_scope="employee",
        access_partition="company:1:role:employee:user:1",
    )
    filenames = {
        str(item.document.metadata.get("filename") or "") for item in results
    }
    assert "Work Schedule.docx" in filenames
    assert "Perfect Attendance.docx" in filenames


def test_rag_prompt_budget_prioritizes_multiple_evidence_blocks() -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.settings = SimpleNamespace(context_window=4096)

    history, router, context = assistant._budget_prompt_sections(
        history_text="H" * 9000,
        router_answer="R" * 14000,
        context="C" * 14000,
        rag_priority=True,
    )
    assert len(context) > len(router)
    assert len(context) > 4300
    assert len(history) >= 400


def test_evidence_context_keeps_multiple_sources_and_focuses_each() -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.settings = SimpleNamespace(evidence_excerpt_chars=520)
    retrieved = [
        RetrievedDocument(
            _doc(
                "a",
                title="Policy Statement.docx",
                file_key="a",
                section="Taxi Reimbursement",
                text=("Intro. " * 120) + "Maximum taxi reimbursement is P300.00 per day.",
            ),
            1.0,
        ),
        RetrievedDocument(
            _doc(
                "b",
                title="Work Schedule.docx",
                file_key="b",
                section="Overtime",
                text=("Background. " * 100) + "Overtime beyond 10:00 PM may trigger the stated transport rule.",
            ),
            0.9,
        ),
    ]
    context = assistant._build_evidence_context(
        query="I worked overtime beyond 10 PM. What transportation benefits apply?",
        retrieved=retrieved,
    )
    assert "Policy Statement.docx" in context
    assert "Work Schedule.docx" in context
    assert "P300.00" in context
    assert "10:00 PM" in context


def test_timeout_gets_one_compact_internal_retry(monkeypatch) -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.session = None
    assistant.settings = SimpleNamespace(
        enabled=True,
        history_messages=4,
        min_question_tokens=18,
        quality_min_question_tokens=14,
        quality_min_retrieved_documents=3,
        context_window=4096,
        evidence_excerpt_chars=650,
        ollama_timeout_retry_enabled=True,
        ollama_retry_timeout_seconds=90,
    )
    assistant.retriever = SimpleNamespace(
        search=lambda *_a, **_k: [
            RetrievedDocument(
                _doc(
                    "p",
                    title="Perfect Attendance.docx",
                    file_key="perfect",
                    text="Approved vacation leave does not automatically disqualify the employee when the policy conditions are met.",
                ),
                1.0,
            )
        ]
    )
    calls: list[dict] = []

    def _generate(_prompt, *, quality=False, timeout_seconds=None):
        calls.append({"quality": quality, "timeout": timeout_seconds})
        if len(calls) == 1:
            raise RuntimeServiceTimeoutError(
                "ollama", operation="generation", timeout_seconds=180
            )
        return "**YES.** The supplied policy evidence supports the stated condition."

    assistant.ollama = SimpleNamespace(generate=_generate)
    monkeypatch.setattr(
        portal_ai.PortalKnowledgeBuilder,
        "build",
        lambda *_a, **_k: [],
    )
    deterministic = HRAssistantResponse(
        answer="Approved vacation leave is addressed by the Perfect Attendance policy.",
        intent="policy",
    )
    current_user = SimpleNamespace(company_id=1, user_id=1)

    response = assistant.enhance(
        current_user=current_user,
        role_scope="employee",
        question="Can an employee with approved vacation leave still qualify for Perfect Attendance?",
        history=[],
        deterministic_response=deterministic,
    )
    assert len(calls) == 2
    assert calls[1]["quality"] is False
    assert calls[1]["timeout"] == 90.0
    assert response.answer.startswith("**YES.**")
    assert response.runtime_warning is None


def test_non_timeout_generation_failure_is_not_retried(monkeypatch) -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.session = None
    assistant.settings = SimpleNamespace(
        enabled=True,
        history_messages=4,
        min_question_tokens=18,
        quality_min_question_tokens=14,
        quality_min_retrieved_documents=3,
        context_window=4096,
        evidence_excerpt_chars=650,
        ollama_timeout_retry_enabled=True,
        ollama_retry_timeout_seconds=90,
    )
    evidence = RetrievedDocument(
        _doc(
            "policy-request",
            title="Applicable Request Policy.docx",
            file_key="request-policy",
            text=(
                "This applicable company policy explains the approved process "
                "for this request."
            ),
        ),
        0.9,
    )
    assistant.retriever = SimpleNamespace(search=lambda *_a, **_k: [evidence])
    calls = 0

    def _generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeServiceResponseError(
            "ollama", status_code=500, detail="runner failed"
        )

    assistant.ollama = SimpleNamespace(generate=_generate)
    monkeypatch.setattr(portal_ai.PortalKnowledgeBuilder, "build", lambda *_a, **_k: [])
    deterministic = HRAssistantResponse(
        answer="Verified company policy fallback answer.",
        intent="policy",
    )
    current_user = SimpleNamespace(company_id=1, user_id=1)
    response = assistant.enhance(
        current_user=current_user,
        role_scope="admin",
        question="Explain the applicable company policy for this request.",
        history=[],
        deterministic_response=deterministic,
    )
    assert calls == 1
    assert response.answer == "Verified company policy fallback answer."
    assert response.runtime_warning_code == "ollama_generation_failed"


def test_prompt_rules_require_cross_policy_completeness() -> None:
    assert "read every directly relevant AUTHORIZED EVIDENCE BLOCK" in HR_ASSISTANT_RULES
    assert "combine all applicable rules" in HR_ASSISTANT_RULES
    assert "Preserve conditions, exceptions, exclusions" in HR_ASSISTANT_RULES
    assert "Do not omit a second applicable rule" in HR_ASSISTANT_RULES


def test_long_file_cannot_crowd_second_selected_policy_out_of_final_evidence(monkeypatch) -> None:
    """A concise consequence policy must survive a long repeated-term file."""

    retriever = HybridRetriever()
    monkeypatch.setattr(retriever.vector, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(retriever.file_vector, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(retriever.settings, "reranker_enabled", False)

    documents = [
        _doc(
            "perfect-1",
            title="Perfect Attendance.docx",
            file_key="perfect",
            text=(
                "Failure to log-in and log-out shall automatically disqualify "
                "the employee in the Perfect Attendance Award."
            ),
        )
    ]
    for index in range(1, 18):
        documents.append(
            _doc(
                f"work-{index}",
                title="Work Schedule.docx",
                file_key="work",
                chunk_index=index,
                section=f"DTR guidance {index}",
                text=(
                    "Employees must log in and log out using the DTR system. "
                    "This work schedule guidance explains login logout records "
                    f"and daily attendance procedure example {index}."
                ),
            )
        )

    results = retriever.search(
        "What happens if an employee forgets to log in or log out?",
        documents,
        company_id=1,
        role_scope="employee",
        access_partition="company:1:role:employee:user:1",
    )
    filenames = [str(item.document.metadata.get("filename") or "") for item in results]
    assert "Work Schedule.docx" in filenames
    assert "Perfect Attendance.docx" in filenames


def test_v88216_version_markers() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert 'app_version: str = "0.8.8.216"' in (root / "config" / "settings.py").read_text(encoding="utf-8")
    assert "APP_VERSION=0.8.8.216" in (root / ".env").read_text(encoding="utf-8")
    assert "APP_VERSION=0.8.8.216" in (root / ".env.example").read_text(encoding="utf-8")


def test_v88216_ollama_and_evidence_defaults_are_hardened() -> None:
    from config.chat_assistant_settings import get_chat_assistant_settings

    settings = get_chat_assistant_settings()
    assert settings.ollama_health_timeout_seconds == 5.0
    assert settings.ollama_timeout_seconds == 180
    assert settings.ollama_retry_timeout_seconds == 90
    assert settings.ollama_timeout_retry_enabled is True
    assert settings.evidence_file_representatives == 2
    assert settings.evidence_min_score_ratio == 0.80
    assert settings.evidence_neighbor_reserve == 1
    assert settings.evidence_excerpt_chars == 900


def test_weak_unrelated_policy_is_not_forced_into_final_context(monkeypatch) -> None:
    retriever = HybridRetriever()
    monkeypatch.setattr(retriever.vector, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(retriever.file_vector, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(retriever.settings, "reranker_enabled", False)

    documents = [
        _doc(
            "taxi-1",
            title="Policy Statement.docx",
            file_key="benefits",
            text=(
                "Taxi Reimbursement: rank and file to Supervisory employees may "
                "receive up to P100.00 per day when they render overtime beyond "
                "10:00 PM, subject to the stated conditions."
            ),
        ),
        _doc(
            "work-1",
            title="Work Schedule.docx",
            file_key="work",
            text=(
                "A double-shift example states taxi reimbursement max. P100.00 "
                "for the applicable overtime period."
            ),
        ),
        _doc(
            "visa-1",
            title="Business VISA.docx",
            file_key="visa",
            text=(
                "Business trip reimbursement requests require approved forms and "
                "official receipts after company travel expenses."
            ),
        ),
    ]

    results = retriever.search(
        "What is the maximum taxi reimbursement per day?",
        documents,
        company_id=1,
        role_scope="employee",
        access_partition="company:1:role:employee:user:1",
    )
    filenames = [str(item.document.metadata.get("filename") or "") for item in results]
    assert "Policy Statement.docx" in filenames
    assert "Work Schedule.docx" in filenames
    assert "Business VISA.docx" not in filenames
