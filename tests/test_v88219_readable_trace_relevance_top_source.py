"""v8.8.219 readable terminal/log diagnostics, no-match guard, and top source UI."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
import ast

from modules.hr_assistant.hr_assistant import HRAssistantResponse
from modules.smart_ai import portal_ai
from modules.smart_ai.portal_ai import (
    KnowledgeDocument,
    RetrievedDocument,
    SmartPortalAssistant,
)
from modules.smart_ai.terminal_trace import TerminalChatTrace
from modules.smart_ai.prompts.hr_assistant_prompt import NOT_FOUND_ANSWER, OUT_OF_SCOPE_ANSWER
from services.policy_service import PolicySource, PolicyService


ROOT = Path(__file__).resolve().parents[1]


def _load_source_lines(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "_source_lines"
    )
    module = ast.Module(body=[node], type_ignores=[])
    namespace: dict[str, object] = {}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["_source_lines"]


def _doc(*, filename: str, text: str, score: float = 0.82) -> RetrievedDocument:
    return RetrievedDocument(
        KnowledgeDocument(
            document_id=f"doc:{filename}",
            text=text,
            title=filename,
            source_type="policy",
            company_id=1,
            role_scope="shared",
            metadata={
                "file_key": filename.casefold(),
                "filename": filename,
                "section": "Policy Details",
                "page_number": 2,
                "chunk_index": 1,
                "total_chunks": 4,
            },
        ),
        score,
    )


def _source(filename: str, section: str) -> PolicySource:
    return PolicySource(
        policy_id=1,
        title="Leave Policy",
        category="Leave",
        version="1.0",
        effective_date=date(2026, 1, 1),
        uploaded_at=None,
        section_heading=section,
        filename=filename,
        page_number=2,
    )


def test_terminal_trace_is_structured_and_writes_request_log(tmp_path, capsys) -> None:
    settings = SimpleNamespace(
        terminal_debug_enabled=True,
        terminal_debug_top_k=5,
        terminal_debug_excerpt_chars=320,
        terminal_debug_answer_chars=1000,
        terminal_debug_candidate_answer_chars=500,
        terminal_debug_log_enabled=True,
        terminal_debug_log_dir=str(tmp_path / "chat_assistant"),
    )
    trace = TerminalChatTrace.create(settings)
    item = _doc(
        filename="Perfect Attendance.docx",
        text="Failure to log-in and log-out automatically disqualifies the employee.",
    )

    trace.start(role_scope="employee", intent="policy", question="What happens if I forget to log out?")
    trace.question_analysis(
        yes_no=False,
        follow_up=False,
        explanation=False,
        needs_ai=True,
        token_count=8,
        evidence_profile="consequence",
        retrieval_query="What happens if I forget to log out?",
    )
    trace.candidates("CHUNK STAGE — BM25", [item], score_label="bm25")
    trace.top_source(item)
    trace.answer("FINAL CHAT ANSWER", "The employee is disqualified under the policy.")
    trace.finish("qwen-answer")

    terminal = capsys.readouterr().err
    assert "AI HR ASSISTANT — RETRIEVAL DEBUG" in terminal
    assert "QUESTION" in terminal
    assert "What happens if I forget to log out?" in terminal
    # v8.8.220 keeps the live terminal compact when the request-local log is
    # available; forensic stages remain in the log.
    assert "QUESTION ANALYSIS" not in terminal
    assert "CHUNK STAGE — BM25" not in terminal
    assert "TOP NEAREST / FINAL SOURCE" not in terminal
    assert "FINAL" in terminal
    assert "RUNTIME" in terminal
    assert "Result      : QWEN-ANSWER" in terminal

    assert trace.log_path is not None
    log_path = Path(trace.log_path)
    assert log_path.exists()
    logged = log_path.read_text(encoding="utf-8")
    assert "What happens if I forget to log out?" in logged
    assert "QUESTION ANALYSIS" in logged
    assert "CHUNK STAGE — BM25" in logged
    assert "Source       : Perfect Attendance.docx" in logged
    assert "TOP NEAREST / FINAL SOURCE" in logged
    assert "FINAL CHAT ANSWER" in logged
    assert "REQUEST SUMMARY" in logged


def test_terminal_log_failure_is_fail_safe(monkeypatch, capsys) -> None:
    original_mkdir = Path.mkdir

    def fail_for_debug_dir(self, *args, **kwargs):
        if str(self).endswith("blocked_chat_logs"):
            raise OSError("blocked")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_for_debug_dir)
    settings = SimpleNamespace(
        terminal_debug_enabled=True,
        terminal_debug_log_enabled=True,
        terminal_debug_log_dir="blocked_chat_logs",
    )
    trace = TerminalChatTrace.create(settings)
    trace.start(role_scope="admin", intent="policy", question="Leave policy")
    trace.finish("complete")
    assert trace.log_path is None
    assert "Log File : unavailable" in capsys.readouterr().err


def test_relevance_guard_rejects_unrelated_nearest_leave_policy() -> None:
    leave = _doc(
        filename="Leave Policy.docx",
        text=(
            "Vacation Leave and Sick Leave requests require manager approval. "
            "Employees must file the applicable leave request."
        ),
    )
    result = SmartPortalAssistant._retrieval_relevance_snapshot(
        query="Laptop policy",
        retrieved=[leave],
    )
    assert result["accepted"] is False
    assert "laptop" in result["anchors"]
    assert "laptop" not in result["matched"]


def test_relevance_guard_keeps_normal_leave_policy_retrieval_without_coverage_mode() -> None:
    leave = _doc(
        filename="Leave Policy.docx",
        text="The Leave Policy covers Vacation Leave, Sick Leave, filing, and approvals.",
    )
    result = SmartPortalAssistant._retrieval_relevance_snapshot(
        query="Leave policy",
        retrieved=[leave],
    )
    assert result["accepted"] is True
    assert "leave" in result["matched"]

    portal_text = (ROOT / "modules/smart_ai/portal_ai.py").read_text(encoding="utf-8")
    assert "BROAD TOPIC" not in portal_text
    assert "COVERAGE MODE" not in portal_text
    assert "coverage_expansion" not in portal_text


def test_existing_batman_out_of_scope_rule_is_retained() -> None:
    leave = _doc(
        filename="Leave Policy.docx",
        text="Employees may file Vacation Leave subject to manager approval.",
    )
    assert SmartPortalAssistant._is_out_of_scope_question(
        question="Who is Batman?",
        history=[],
        deterministic_intent="not_found",
        retrieved=[leave],
    ) is True


def test_policy_topic_guard_rejects_laptop_but_accepts_leave() -> None:
    policy = SimpleNamespace(
        title="Employee Leave Policy",
        category="Leave",
        summary="Vacation and sick leave rules.",
    )
    section = SimpleNamespace(
        policy=policy,
        heading="Leave Filing",
        text="Vacation Leave and Sick Leave requests require manager approval.",
    )
    assert PolicyService._topic_is_supported(
        question="Laptop policy",
        section=section,
    ) is False
    assert PolicyService._topic_is_supported(
        question="Leave policy",
        section=section,
    ) is True


def test_streamlit_source_display_is_one_top_source_only() -> None:
    sources = [
        _source("Business VISA.docx", "Section 4"),
        _source("Business VISA.docx", "Section 4.1"),
        _source("Business VISA.docx", "Section 7"),
    ]
    admin_source_lines = _load_source_lines(ROOT / "ui/pages/admin/chat_page.py")
    employee_source_lines = _load_source_lines(ROOT / "ui/pages/user/chat_page.py")
    admin_lines = admin_source_lines(sources)
    employee_lines = employee_source_lines(sources)
    assert len(admin_lines) == 1
    assert len(employee_lines) == 1
    assert "Section 4" in admin_lines[0]
    assert "Section 4" in employee_lines[0]


def test_top_display_source_prefers_top_retrieved_file() -> None:
    sources = [
        PolicySource(
            policy_id=10,
            title="Work Schedule",
            category="Attendance",
            version="1.0",
            effective_date=None,
            uploaded_at=None,
            section_heading="Attendance",
            filename="Work Schedule.docx",
            page_number=1,
        ),
        PolicySource(
            policy_id=20,
            title="Perfect Attendance",
            category="Attendance",
            version="1.0",
            effective_date=None,
            uploaded_at=None,
            section_heading="Perfect Attendance Criteria",
            filename="Perfect Attendance.docx",
            page_number=2,
        ),
    ]
    top = _doc(
        filename="Perfect Attendance.docx",
        text="Failure to log in and log out disqualifies the employee.",
        score=0.95,
    )
    top.document.metadata["policy_id"] = 20
    top.document.metadata["section"] = "Perfect Attendance Criteria"

    selected = SmartPortalAssistant._top_display_sources(sources, [top])
    assert len(selected) == 1
    assert selected[0].filename == "Perfect Attendance.docx"



def _assistant_settings():
    return SimpleNamespace(
        enabled=True,
        terminal_debug_enabled=False,
        history_messages=4,
        min_question_tokens=18,
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


def test_enhance_rejects_unrelated_nearest_chunk_before_qwen(monkeypatch) -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.session = None
    assistant.settings = _assistant_settings()
    leave = _doc(
        filename="Leave Policy.docx",
        text="Vacation Leave and Sick Leave requests require manager approval.",
    )
    assistant.retriever = SimpleNamespace(search=lambda *_a, **_k: [leave])
    calls = 0

    def generate(*_a, **_k):
        nonlocal calls
        calls += 1
        return "This must not be used."

    assistant.ollama = SimpleNamespace(generate=generate)
    monkeypatch.setattr(portal_ai.PortalKnowledgeBuilder, "build", lambda *_a, **_k: [])
    response = assistant.enhance(
        current_user=SimpleNamespace(company_id=1, user_id=7),
        role_scope="employee",
        question="Laptop policy",
        history=[],
        deterministic_response=HRAssistantResponse(
            answer="Nearest Leave Policy text.",
            intent="policy_fallback",
        ),
    )
    assert calls == 0
    assert response.answer == NOT_FOUND_ANSWER
    assert response.sources == []


def test_leave_policy_keeps_normal_retrieval_and_can_reach_qwen(monkeypatch) -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.session = None
    assistant.settings = _assistant_settings()
    leave = _doc(
        filename="Leave Policy.docx",
        text="The Leave Policy explains Vacation Leave, Sick Leave, and approval rules.",
    )
    assistant.retriever = SimpleNamespace(search=lambda *_a, **_k: [leave])
    calls = 0

    def generate(*_a, **_k):
        nonlocal calls
        calls += 1
        return "The Leave Policy includes Vacation Leave, Sick Leave, and approval rules."

    assistant.ollama = SimpleNamespace(generate=generate)
    monkeypatch.setattr(portal_ai.PortalKnowledgeBuilder, "build", lambda *_a, **_k: [])
    response = assistant.enhance(
        current_user=SimpleNamespace(company_id=1, user_id=7),
        role_scope="employee",
        question="Leave policy",
        history=[],
        deterministic_response=HRAssistantResponse(
            answer="Verified Leave Policy evidence.",
            intent="policy_fallback",
        ),
    )
    assert calls == 1
    assert "Leave Policy" in response.answer


def test_batman_still_rejects_before_qwen(monkeypatch) -> None:
    assistant = SmartPortalAssistant.__new__(SmartPortalAssistant)
    assistant.session = None
    assistant.settings = _assistant_settings()
    leave = _doc(
        filename="Leave Policy.docx",
        text="Vacation Leave and Sick Leave requests require manager approval.",
    )
    assistant.retriever = SimpleNamespace(search=lambda *_a, **_k: [leave])
    calls = 0

    def generate(*_a, **_k):
        nonlocal calls
        calls += 1
        return "Batman answer"

    assistant.ollama = SimpleNamespace(generate=generate)
    monkeypatch.setattr(portal_ai.PortalKnowledgeBuilder, "build", lambda *_a, **_k: [])
    response = assistant.enhance(
        current_user=SimpleNamespace(company_id=1, user_id=7),
        role_scope="employee",
        question="Who is Batman?",
        history=[],
        deterministic_response=HRAssistantResponse(
            answer="No company result.",
            intent="not_found",
        ),
    )
    assert calls == 0
    assert response.answer == OUT_OF_SCOPE_ANSWER
    assert response.sources == []

def test_v88219_version_and_log_defaults() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    chat_settings = (ROOT / "config/chat_assistant_settings.py").read_text(encoding="utf-8")
    env = (ROOT / ".env").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.219"' in settings
    assert "APP_VERSION=0.8.8.219" in env
    assert "APP_VERSION=0.8.8.219" in env_example
    assert "terminal_debug_log_enabled: bool = True" in chat_settings
    assert 'terminal_debug_log_dir: str = "logs/chat_assistant"' in chat_settings
    assert "SMART_AI_TERMINAL_DEBUG_LOG_ENABLED=true" in env
    assert "SMART_AI_TERMINAL_DEBUG_LOG_DIR=logs/chat_assistant" in env
