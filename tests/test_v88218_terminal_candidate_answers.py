"""v8.8.218 terminal-only candidate answer diagnostics."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from modules.hr_assistant.hr_assistant import HRAssistantResponse
from modules.smart_ai import portal_ai
from modules.smart_ai.portal_ai import KnowledgeDocument, RetrievedDocument, SmartPortalAssistant
from modules.smart_ai.terminal_trace import TerminalChatTrace


ROOT = Path(__file__).resolve().parents[1]


def _evidence() -> RetrievedDocument:
    document = KnowledgeDocument(
        document_id="policy-perfect-attendance-1",
        text=(
            "Failure to log-in and log-out shall automatically disqualify "
            "the employee from the Perfect Attendance Award."
        ),
        title="Perfect Attendance.docx",
        source_type="policy",
        company_id=1,
        role_scope="shared",
        metadata={
            "file_key": "perfect-attendance",
            "filename": "Perfect Attendance.docx",
            "section": "Perfect Attendance Criteria",
            "page_number": 2,
            "chunk_index": 3,
            "total_chunks": 5,
        },
    )
    return RetrievedDocument(document, 0.812345)


def test_terminal_trace_prints_candidate_answer_score_source_and_hint(capsys) -> None:
    trace = TerminalChatTrace(
        enabled=True,
        trace_id="cand218",
        top_k=5,
        excerpt_chars=320,
        answer_chars=1000,
        candidate_answer_chars=420,
    )
    trace.answer_candidates(
        [
            {
                "retrieval_score": 0.812345,
                "answer_fit": 0.734567,
                "source": "Perfect Attendance.docx",
                "section": "Perfect Attendance Criteria",
                "page": 2,
                "chunk": "3/5",
                "possible_answer": (
                    "Failure to log-in and log-out shall automatically disqualify "
                    "the employee from the Perfect Attendance Award."
                ),
            }
        ]
    )
    trace.answer_selection(selected="qwen", reason="qwen-answer")

    output = capsys.readouterr().err
    assert "CANDIDATE ANSWERS — RETRIEVED EVIDENCE" in output
    assert "Retrieval Score : 0.812345" in output
    assert "Answer Fit      : 0.734567" in output
    assert "Source          : Perfect Attendance.docx" in output
    assert "Section         : Perfect Attendance Criteria" in output
    assert "Page            : 2" in output
    assert "Chunk           : 3/5" in output
    assert "Failure to log-in" in output
    assert "Selected : qwen" in output
    assert "Reason   : qwen-answer" in output


def test_candidate_answer_trace_is_silent_when_disabled(capsys) -> None:
    trace = TerminalChatTrace(enabled=False, trace_id="silent218")
    trace.answer_candidates([{"possible_answer": "must never print"}])
    trace.answer_selection(selected="qwen", reason="qwen-answer")
    assert capsys.readouterr().err == ""


def test_smart_assistant_prints_evidence_candidates_and_answer_options(
    monkeypatch,
    capsys,
) -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.session = None
    assistant.settings = SimpleNamespace(
        enabled=True,
        terminal_debug_enabled=True,
        terminal_debug_top_k=10,
        terminal_debug_excerpt_chars=320,
        terminal_debug_answer_chars=1000,
        terminal_debug_candidate_answer_chars=500,
        history_messages=4,
        min_question_tokens=3,
        quality_min_question_tokens=14,
        quality_min_retrieved_documents=3,
        context_window=4096,
        evidence_excerpt_chars=900,
        ollama_timeout_retry_enabled=True,
        ollama_retry_timeout_seconds=90,
        ollama_timeout_seconds=180,
        ollama_model="qwen2.5:7b",
        quality_ollama_model="qwen2.5:7b",
    )
    evidence = _evidence()
    assistant.retriever = SimpleNamespace(search=lambda *_a, **_k: [evidence])
    assistant.ollama = SimpleNamespace(
        generate=lambda *_a, **_k: (
            "The employee is disqualified from the Perfect Attendance Award "
            "if the required log-in/log-out is missing."
        )
    )
    monkeypatch.setattr(portal_ai.PortalKnowledgeBuilder, "build", lambda *_a, **_k: [])

    response = assistant.enhance(
        current_user=SimpleNamespace(company_id=1, user_id=7),
        role_scope="employee",
        question="What happens if an employee forgets to log in or log out?",
        history=[],
        deterministic_response=HRAssistantResponse(
            answer="Verified attendance policy evidence applies.",
            intent="policy",
        ),
    )

    assert "disqualified" in response.answer.lower()
    output = capsys.readouterr().err
    assert "CANDIDATE ANSWERS — RETRIEVED EVIDENCE" in output
    assert "Perfect Attendance.docx" in output
    assert "Possible Answer" in output
    assert "ANSWER OPTION — ROUTER" in output
    assert "ANSWER OPTION — QWEN" in output
    assert "Selected : qwen" in output
    assert "FINAL CHAT ANSWER" in output



def test_candidate_diagnostics_do_not_change_chat_answer(monkeypatch) -> None:
    def make_assistant(enabled: bool):
        assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
        assistant.session = None
        assistant.settings = SimpleNamespace(
            enabled=True,
            terminal_debug_enabled=enabled,
            terminal_debug_top_k=10,
            terminal_debug_excerpt_chars=320,
            terminal_debug_answer_chars=1000,
            terminal_debug_candidate_answer_chars=500,
            history_messages=4,
            min_question_tokens=3,
            quality_min_question_tokens=14,
            quality_min_retrieved_documents=3,
            context_window=4096,
            evidence_excerpt_chars=900,
            ollama_timeout_retry_enabled=True,
            ollama_retry_timeout_seconds=90,
            ollama_timeout_seconds=180,
            ollama_model="qwen2.5:7b",
            quality_ollama_model="qwen2.5:7b",
        )
        assistant.retriever = SimpleNamespace(search=lambda *_a, **_k: [_evidence()])
        assistant.ollama = SimpleNamespace(
            generate=lambda *_a, **_k: (
                "The employee is disqualified from the Perfect Attendance Award "
                "if the required log-in/log-out is missing."
            )
        )
        return assistant

    monkeypatch.setattr(portal_ai.PortalKnowledgeBuilder, "build", lambda *_a, **_k: [])
    kwargs = dict(
        current_user=SimpleNamespace(company_id=1, user_id=7),
        role_scope="employee",
        question="What happens if an employee forgets to log in or log out?",
        history=[],
        deterministic_response=HRAssistantResponse(
            answer="Verified attendance policy evidence applies.",
            intent="policy",
        ),
    )
    with_trace = make_assistant(True).enhance(**kwargs)
    without_trace = make_assistant(False).enhance(**kwargs)

    assert with_trace.answer == without_trace.answer
    assert with_trace.intent == without_trace.intent
    assert with_trace.sources == without_trace.sources

def test_candidate_trace_does_not_add_streamlit_ui_or_response_fields() -> None:
    admin = (ROOT / "ui/pages/admin/chat_page.py").read_text(encoding="utf-8")
    employee = (ROOT / "ui/pages/user/chat_page.py").read_text(encoding="utf-8")
    combined = admin + "\n" + employee
    assert "CANDIDATE ANSWERS" not in combined
    assert "possible_answer" not in combined
    assert "TerminalChatTrace" not in combined

    response_annotations = getattr(HRAssistantResponse, "__annotations__", {})
    assert "candidate_answers" not in response_annotations
    assert "retrieval_debug" not in response_annotations


def test_v88218_version_and_candidate_debug_defaults() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    chat_settings = (ROOT / "config/chat_assistant_settings.py").read_text(encoding="utf-8")
    env = (ROOT / ".env").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.218"' in settings
    assert "APP_VERSION=0.8.8.218" in env
    assert "APP_VERSION=0.8.8.218" in env_example
    assert "terminal_debug_candidate_answer_chars: int = 760" in chat_settings
    assert "SMART_AI_TERMINAL_DEBUG_CANDIDATE_ANSWER_CHARS=760" in env
    assert "SMART_AI_TERMINAL_DEBUG_CANDIDATE_ANSWER_CHARS=760" in env_example
