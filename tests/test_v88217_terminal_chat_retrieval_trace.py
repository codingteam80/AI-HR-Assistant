"""v8.8.217 terminal-only Chat Assistant retrieval diagnostics."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from modules.hr_assistant.hr_assistant import HRAssistantResponse
from modules.smart_ai import portal_ai
from modules.smart_ai.portal_ai import (
    HybridRetriever,
    KnowledgeDocument,
    RetrievedDocument,
    SmartPortalAssistant,
)
from modules.smart_ai.terminal_trace import TerminalChatTrace


ROOT = Path(__file__).resolve().parents[1]


def _doc(doc_id: str, *, filename: str, text: str, file_key: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=doc_id,
        text=text,
        title=filename,
        source_type="policy",
        company_id=1,
        role_scope="shared",
        metadata={
            "file_key": file_key,
            "filename": filename,
            "section": "Policy Rule",
            "page_number": 2,
            "chunk_index": 1,
            "total_chunks": 3,
        },
    )


def test_terminal_trace_prints_rank_score_source_and_chunk(capsys) -> None:
    trace = TerminalChatTrace(
        enabled=True,
        trace_id="abc12345",
        top_k=5,
        excerpt_chars=240,
        answer_chars=600,
    )
    item = RetrievedDocument(
        _doc(
            "policy-1",
            filename="Perfect Attendance.docx",
            file_key="perfect-attendance",
            text="Failure to log-in and log-out shall automatically disqualify the employee.",
        ),
        0.912345,
    )

    trace.start(role_scope="employee", intent="policy", question="What happens if I forget to log out?")
    trace.candidates(
        "CHUNK STAGE — VECTOR NEAREST (cosine similarity)",
        [item],
        score_label="cosine",
    )
    trace.answer("FINAL CHAT ANSWER", "The employee is disqualified under the stated rule.")
    trace.finish("qwen-answer")

    output = capsys.readouterr().err
    assert "Trace ID : abc12345" in output
    assert "VECTOR NEAREST" in output
    assert "COSINE      : 0.912345" in output
    assert "Source       : Perfect Attendance.docx" in output
    assert "Section      : Policy Rule" in output
    assert "Page         : 2" in output
    assert "Chunk        : 1/3" in output
    assert "Failure to log-in" in output
    assert "FINAL CHAT ANSWER" in output


def test_terminal_trace_can_be_disabled_without_output(capsys) -> None:
    trace = TerminalChatTrace(enabled=False, trace_id="silent")
    trace.start(role_scope="admin", intent="policy", question="Question")
    trace.line("RETRIEVAL QUERY", "query")
    trace.finish()
    assert capsys.readouterr().err == ""


def test_hybrid_retriever_terminal_trace_shows_bm25_vector_hybrid_and_final(
    monkeypatch,
    capsys,
) -> None:
    retriever = HybridRetriever()
    monkeypatch.setattr(retriever.vector, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(retriever.file_vector, "search", lambda *_a, **_k: [])
    monkeypatch.setattr(retriever.settings, "reranker_enabled", False)

    documents = [
        _doc(
            "perfect-1",
            filename="Perfect Attendance.docx",
            file_key="perfect",
            text="Failure to log-in and log-out automatically disqualifies the employee from Perfect Attendance.",
        ),
        _doc(
            "work-1",
            filename="Work Schedule.docx",
            file_key="work",
            text="Failure to log in or log out prevents verification of required working hours.",
        ),
    ]
    trace = TerminalChatTrace(
        enabled=True,
        trace_id="retrieval",
        top_k=10,
        excerpt_chars=260,
        answer_chars=600,
    )

    results = retriever.search(
        "What happens if an employee forgets to log in or log out?",
        documents,
        company_id=1,
        role_scope="employee",
        access_partition="company:1:role:employee:user:1",
        trace=trace,
    )

    assert results
    output = capsys.readouterr().err
    assert "FILE STAGE — BM25" in output
    assert "FILE STAGE — VECTOR NEAREST" in output
    assert "FILE STAGE — HYBRID RRF + ANSWER FIT" in output
    assert "CHUNK STAGE — BM25" in output
    assert "CHUNK STAGE — VECTOR NEAREST" in output
    assert "CHUNK STAGE — HYBRID RRF + ANSWER FIT" in output
    assert "FINAL EVIDENCE TO QWEN" in output
    assert "BM25        " in output
    assert "HYBRID      " in output
    assert "Perfect Attendance.docx" in output


def test_smart_assistant_trace_includes_router_qwen_final_answer_and_timing(
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
        history_messages=4,
        min_question_tokens=3,
        quality_min_question_tokens=14,
        quality_min_retrieved_documents=3,
        context_window=4096,
        evidence_excerpt_chars=650,
        ollama_timeout_retry_enabled=True,
        ollama_retry_timeout_seconds=90,
        ollama_timeout_seconds=180,
        ollama_model="qwen2.5:7b",
        quality_ollama_model="qwen2.5:7b",
    )
    evidence = RetrievedDocument(
        _doc(
            "service-1",
            filename="Service Award.docx",
            file_key="service",
            text="After five years of service, the employee receives the stated service award benefits.",
        ),
        0.9,
    )
    assistant.retriever = SimpleNamespace(search=lambda *_a, **_k: [evidence])
    assistant.ollama = SimpleNamespace(
        generate=lambda *_a, **_k: "Employees receive the five-year service award benefits listed in the policy."
    )
    monkeypatch.setattr(portal_ai.PortalKnowledgeBuilder, "build", lambda *_a, **_k: [])

    response = assistant.enhance(
        current_user=SimpleNamespace(company_id=1, user_id=7),
        role_scope="employee",
        question="Explain the five year service award benefits.",
        history=[],
        deterministic_response=HRAssistantResponse(
            answer="Verified Service Award policy evidence.",
            intent="policy",
        ),
    )

    assert "service award benefits" in response.answer.lower()
    output = capsys.readouterr().err
    assert "DETERMINISTIC / ROUTER ANSWER" in output
    assert "Retrieval Query:" in output
    assert "OLLAMA REQUEST" in output
    assert "model=qwen2.5:7b" in output
    assert "OLLAMA RESULT" in output
    assert "QWEN RAW ANSWER" in output
    assert "FINAL CHAT ANSWER" in output


def test_terminal_trace_is_not_rendered_in_streamlit_chat_ui() -> None:
    admin = (ROOT / "ui/pages/admin/chat_page.py").read_text(encoding="utf-8")
    employee = (ROOT / "ui/pages/user/chat_page.py").read_text(encoding="utf-8")
    combined = admin + "\n" + employee
    assert "TerminalChatTrace" not in combined
    assert "CHAT-TRACE" not in combined
    assert "retrieval_debug" not in combined
    assert "Debug Chunks" not in combined


def test_v88217_version_and_terminal_debug_defaults() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    chat_settings = (ROOT / "config/chat_assistant_settings.py").read_text(encoding="utf-8")
    env = (ROOT / ".env").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    # v8.8.217 feature regression: later checkpoints may increment APP_VERSION.
    assert '# Immediate base checkpoint: app_version: str = "0.8.8.217"' in settings
    assert "SMART_AI_TERMINAL_DEBUG_ENABLED=true" in env
    assert "SMART_AI_TERMINAL_DEBUG_ENABLED=true" in env_example
    assert "terminal_debug_enabled: bool = True" in chat_settings
    assert "SMART_AI_TERMINAL_DEBUG_ENABLED=true" in env
    assert "SMART_AI_TERMINAL_DEBUG_ENABLED=true" in env_example
