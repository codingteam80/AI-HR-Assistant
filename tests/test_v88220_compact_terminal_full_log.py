"""v8.8.220 compact terminal + full request-log regression coverage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from modules.smart_ai.portal_ai import KnowledgeDocument, RetrievedDocument
from modules.smart_ai.terminal_trace import TerminalChatTrace


ROOT = Path(__file__).resolve().parents[1]


def _item(
    *,
    filename: str = "Perfect Attendance.docx",
    chunk_index: int = 3,
    total_chunks: int = 5,
    score: float = 0.812345,
) -> RetrievedDocument:
    document = KnowledgeDocument(
        document_id=f"policy:{filename}:{chunk_index}",
        text=(
            "Failure to log-in and log-out automatically disqualifies "
            "the employee from the Perfect Attendance Award."
        ),
        title=filename,
        source_type="policy",
        company_id=1,
        role_scope="shared",
        metadata={
            "file_key": filename.casefold(),
            "filename": filename,
            "section": "Perfect Attendance Criteria",
            "page_number": 2,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
        },
    )
    return RetrievedDocument(document, score)


def _settings(tmp_path: Path):
    return SimpleNamespace(
        terminal_debug_enabled=True,
        terminal_debug_top_k=10,
        terminal_debug_excerpt_chars=520,
        terminal_debug_answer_chars=1800,
        terminal_debug_candidate_answer_chars=760,
        terminal_debug_log_enabled=True,
        terminal_debug_log_dir=str(tmp_path / "chat_assistant"),
    )


def test_compact_terminal_shows_only_quick_diagnostics_while_log_keeps_full_trace(
    tmp_path,
    capsys,
) -> None:
    trace = TerminalChatTrace.create(_settings(tmp_path))
    top = _item()

    trace.start(
        role_scope="employee",
        intent="policy",
        question="What happens if an employee forgets to log in or log out?",
    )
    trace.question_analysis(
        yes_no=False,
        follow_up=False,
        explanation=False,
        needs_ai=True,
        token_count=12,
        evidence_profile="consequence",
        retrieval_query="employee forgets log in log out consequence",
    )
    trace.counts(
        files_searched=10,
        chunk_stage_search_space=171,
        matched_files=2,
        matched_chunks=7,
        final_evidence_chunks=3,
        selected_files=2,
    )
    trace.file_ranking(
        file_scores={"perfect": 0.9412, "work": 0.8234},
        grouped={
            "perfect": [top.document] * 5,
            "work": [
                KnowledgeDocument(
                    document_id=f"work:{index}",
                    text="Attendance record rule.",
                    title="Work Schedule.docx",
                    source_type="policy",
                    company_id=1,
                    role_scope="shared",
                    metadata={
                        "file_key": "work",
                        "filename": "Work Schedule.docx",
                        "chunk_index": index,
                        "total_chunks": 31,
                    },
                )
                for index in range(1, 32)
            ],
        },
        selected_keys={"perfect", "work"},
        matched_chunk_counts={"perfect": 3, "work": 4},
        best_chunks={"perfect": "3/5", "work": "18/31"},
    )
    trace.candidates("CHUNK STAGE — BM25", [top], score_label="bm25")
    trace.retrieval_summary()
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
                    "Failure to log in or log out automatically disqualifies "
                    "the employee from the Perfect Attendance Award."
                ),
            },
            {
                "retrieval_score": 0.701111,
                "answer_fit": 0.612222,
                "source": "Work Schedule.docx",
                "section": "Attendance Recording",
                "page": 4,
                "chunk": "18/31",
                "possible_answer": "Employees must properly record login and logout.",
            },
        ]
    )
    trace.top_source(top)
    trace.line(
        "OLLAMA REQUEST",
        "model=qwen2.5:7b; quality=False; prompt_chars=2200; timeout=180s",
    )
    trace.line("OLLAMA RESULT", "primary completed in 6.84s")
    trace.answer("ANSWER OPTION — ROUTER", "Verified company policy evidence applies.")
    trace.answer("ANSWER OPTION — QWEN", "The employee is disqualified.")
    trace.answer_selection(selected="qwen", reason="qwen-answer")
    trace.answer(
        "FINAL CHAT ANSWER",
        "Failure to log in or log out automatically disqualifies the employee.",
    )
    trace.finish("qwen-answer")

    terminal = capsys.readouterr().err
    assert "RETRIEVAL" in terminal
    assert "Files Searched    : 10" in terminal
    assert "Chunks Searched   : 171" in terminal
    assert "Matched Chunks    : 7" in terminal
    assert "Final Chunks Used : 3" in terminal
    assert "TOP SOURCES" in terminal
    assert "Perfect Attendance.docx" in terminal
    assert "Source Score : 0.941200" in terminal
    assert "Chunks: 3/5 matched" in terminal
    assert "Best: 3/5" in terminal
    assert "CANDIDATE ANSWERS" in terminal
    assert "Answer Score: 0.734567" in terminal
    assert "Retrieval: 0.812345" in terminal
    assert "FINAL" in terminal
    assert "Final Score : 0.812345" in terminal
    assert "RUNTIME" in terminal
    assert "Ollama      : SUCCESS" in terminal
    assert "Retry       : NO" in terminal
    assert "Full Log    :" in terminal

    # No noisy forensic stages in the live terminal when log evidence exists.
    assert "QUESTION ANALYSIS" not in terminal
    assert "CHUNK STAGE — BM25" not in terminal
    assert "ANSWER OPTION — ROUTER" not in terminal
    assert "ANSWER OPTION — QWEN" not in terminal
    assert "TOP NEAREST / FINAL SOURCE" not in terminal

    assert trace.log_path is not None
    log_text = Path(trace.log_path).read_text(encoding="utf-8")
    assert "QUESTION ANALYSIS" in log_text
    assert "CHUNK STAGE — BM25" in log_text
    assert "ANSWER OPTION — ROUTER" in log_text
    assert "ANSWER OPTION — QWEN" in log_text
    assert "TOP NEAREST / FINAL SOURCE" in log_text
    assert "CANDIDATE ANSWERS — RETRIEVED EVIDENCE" in log_text
    assert "REQUEST SUMMARY" in log_text


def test_compact_candidate_terminal_is_limited_but_log_retains_debug_top_k(
    tmp_path,
    capsys,
) -> None:
    trace = TerminalChatTrace.create(_settings(tmp_path))
    trace.start(role_scope="admin", intent="policy", question="Policy question")
    candidates = [
        {
            "retrieval_score": 0.90 - (index * 0.01),
            "answer_fit": 0.80 - (index * 0.01),
            "source": f"Policy {index + 1}.docx",
            "section": "Rule",
            "page": 1,
            "chunk": f"{index + 1}/10",
            "possible_answer": f"Possible answer {index + 1}",
        }
        for index in range(5)
    ]
    trace.answer_candidates(candidates)
    trace.answer("FINAL CHAT ANSWER", "Final answer")
    trace.finish("qwen-answer")

    terminal = capsys.readouterr().err
    assert "#01 [BEST]" in terminal
    assert "#02 Answer Score" in terminal
    assert "#03 Answer Score" in terminal
    assert "#04 Answer Score" not in terminal

    assert trace.log_path is not None
    log_text = Path(trace.log_path).read_text(encoding="utf-8")
    assert "Candidate #05" in log_text
    assert "Possible answer 5" in log_text


def test_v88220_version_marker_and_previous_checkpoint_are_present() -> None:
    settings = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    env = (ROOT / ".env").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert 'app_version: str = "0.8.8.220"' in settings
    assert '# Immediate base checkpoint: app_version: str = "0.8.8.219"' in settings
    assert "APP_VERSION=0.8.8.220" in env
    assert "APP_VERSION=0.8.8.220" in env_example
