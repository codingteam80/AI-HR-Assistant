"""Terminal-only Chat Assistant diagnostics with compact live output + full logs.

Runtime behavior:
- The live terminal stays intentionally compact when the request-local evidence
  log is available.  It shows only the question, retrieval totals, top source
  scores, candidate-answer scores, final answer/source, and runtime status.
- The request-local ``.log`` keeps the full forensic trace (all retrieval stages,
  chunk excerpts, relevance decisions, router/Qwen options, and summaries).
- If the evidence log cannot be created, the terminal automatically falls back
  to the verbose trace so diagnostic evidence is not silently lost.

The module intentionally has no Streamlit dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
import sys
import time
from typing import Iterable, Mapping, TextIO
from uuid import uuid4


_RULE = "=" * 88
_SUBRULE = "-" * 88
_COMPACT_RULE = "-" * 80


def _clean_inline(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _bounded(value: object, limit: int) -> str:
    text = _clean_inline(value)
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _multiline(value: object, limit: int) -> str:
    """Return readable bounded text without collapsing intentional paragraphs."""

    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    if limit > 0 and len(raw) > limit:
        raw = raw[: max(0, limit - 1)].rstrip() + "…"
    return raw


def _float_from_text(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class TerminalChatTrace:
    """One request-local trace with compact terminal + full evidence log."""

    enabled: bool
    trace_id: str
    top_k: int = 10
    excerpt_chars: int = 520
    answer_chars: int = 1800
    candidate_answer_chars: int = 760
    log_enabled: bool = True
    log_dir: str = "logs/chat_assistant"
    log_path: str | None = None
    _started_monotonic: float = field(default_factory=time.monotonic)
    _counts: dict[str, object] = field(default_factory=dict)
    _log_failed: bool = False
    _section_number: int = 0
    _log_stream: TextIO | None = field(default=None, repr=False)
    _source_rows: list[dict[str, object]] = field(default_factory=list)
    _top_source_summary: dict[str, object] = field(default_factory=dict)
    _final_answer: str = ""
    _selected_answer: str = ""
    _selection_reason: str = ""
    _runtime: dict[str, object] = field(default_factory=dict)
    _runtime_issue_summary: str = ""

    @classmethod
    def create(cls, settings) -> "TerminalChatTrace":
        enabled = bool(getattr(settings, "terminal_debug_enabled", False))
        log_enabled = bool(getattr(settings, "terminal_debug_log_enabled", False))
        trace = cls(
            enabled=enabled,
            trace_id=uuid4().hex[:8].upper(),
            top_k=max(1, int(getattr(settings, "terminal_debug_top_k", 10))),
            excerpt_chars=max(
                120, int(getattr(settings, "terminal_debug_excerpt_chars", 520))
            ),
            answer_chars=max(
                240, int(getattr(settings, "terminal_debug_answer_chars", 1800))
            ),
            candidate_answer_chars=max(
                240,
                int(getattr(settings, "terminal_debug_candidate_answer_chars", 760)),
            ),
            log_enabled=log_enabled,
            log_dir=str(
                getattr(settings, "terminal_debug_log_dir", "logs/chat_assistant")
                or "logs/chat_assistant"
            ),
        )
        if enabled and log_enabled:
            trace._prepare_log_path()
        return trace

    @property
    def _compact_terminal(self) -> bool:
        """Compact mode is safe only while the full evidence log is available."""

        return bool(
            self.enabled
            and self.log_enabled
            and self._log_stream is not None
            and not self._log_failed
        )

    def _prepare_log_path(self) -> None:
        try:
            directory = Path(self.log_dir)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
            path = directory / f"chat_trace_{stamp}_{self.trace_id}.log"
            self._log_stream = path.open("w", encoding="utf-8", newline="\n")
            self.log_path = str(path)
        except OSError:
            # Debug evidence must never make the chat path fail.
            self.log_path = None
            self._log_stream = None
            self._log_failed = True

    def _write_log(self, line: str) -> None:
        if not self.log_enabled or self._log_stream is None or self._log_failed:
            return
        try:
            self._log_stream.write(line + "\n")
            # Keep evidence current even if the local Streamlit process is later
            # interrupted during generation/debugging.
            self._log_stream.flush()
        except OSError:
            self._log_failed = True
            self._close_log()

    def _close_log(self) -> None:
        stream = self._log_stream
        self._log_stream = None
        if stream is None:
            return
        try:
            stream.close()
        except OSError:
            self._log_failed = True

    def _emit(
        self,
        message: str = "",
        *,
        terminal: bool = True,
        log: bool = True,
    ) -> None:
        if not self.enabled:
            return
        if terminal:
            print(message, file=sys.stderr, flush=True)
        if log:
            self._write_log(message)

    def _section(
        self,
        title: str,
        *,
        terminal: bool = True,
        log: bool = True,
    ) -> None:
        """Verbose numbered section used by the full forensic trace."""

        if not self.enabled:
            return
        self._section_number += 1
        self._emit("", terminal=terminal, log=log)
        self._emit(
            f"[{self._section_number}] {title}", terminal=terminal, log=log
        )
        self._emit(_SUBRULE, terminal=terminal, log=log)

    def _compact_emit(self, message: str = "") -> None:
        """Write live compact output without duplicating it into the full log."""

        self._emit(message, terminal=True, log=False)

    def _compact_section(self, title: str) -> None:
        if not self.enabled:
            return
        self._compact_emit("")
        self._compact_emit(title)
        self._compact_emit(_COMPACT_RULE)

    def _verbose_terminal_allowed(self) -> bool:
        # If a full request log cannot be preserved, keep the old verbose
        # terminal behavior so debugging evidence is not lost.
        return not self._compact_terminal

    def start(self, *, role_scope: str, intent: str, question: str) -> None:
        if not self.enabled:
            return
        self._started_monotonic = time.monotonic()
        self._section_number = 0
        self._emit("")
        self._emit(_RULE)
        self._emit("AI HR ASSISTANT — RETRIEVAL DEBUG")
        self._emit(_RULE)
        self._emit(f"Trace ID : {self.trace_id}")
        self._emit(f"Portal   : {_clean_inline(role_scope) or '-'}")
        # Intent/timestamp stay in the full log during compact live output.
        verbose_terminal = self._verbose_terminal_allowed()
        self._emit(
            f"Intent   : {_clean_inline(intent) or '-'}",
            terminal=verbose_terminal,
        )
        self._emit(
            "Started  : "
            + datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            terminal=verbose_terminal,
        )
        if self.log_path:
            self._emit(f"Log File : {self.log_path}")
        elif self.log_enabled:
            self._emit("Log File : unavailable — verbose terminal fallback enabled")
        self._section("QUESTION", terminal=verbose_terminal)
        question_text = _multiline(question, self.answer_chars)
        if self._compact_terminal:
            self._emit(question_text or "(empty question)", terminal=False)
            self._compact_section("QUESTION")
            self._compact_emit(question_text or "(empty question)")
        else:
            self._emit(question_text or "(empty question)")

    def _log_request_summary(self, status: str, elapsed: float) -> None:
        self._section("REQUEST SUMMARY", terminal=False)
        preferred = (
            "files_searched",
            "authorized_documents",
            "file_chunks",
            "structured_records",
            "selected_files",
            "selected_file_chunks",
            "chunk_stage_search_space",
            "matched_files",
            "matched_chunks",
            "final_evidence_chunks",
        )
        emitted: set[str] = set()
        for key in preferred:
            if key in self._counts:
                self._emit(
                    f"{key.replace('_', ' ').title():24}: {self._counts[key]}",
                    terminal=False,
                )
                emitted.add(key)
        for key, value in self._counts.items():
            if key in emitted or key == "total_built_documents":
                continue
            self._emit(
                f"{key.replace('_', ' ').title():24}: {value}",
                terminal=False,
            )
        self._emit(
            f"Total Request Time      : {elapsed:.2f} sec", terminal=False
        )
        self._emit(
            f"Result                  : {_clean_inline(status).upper() or 'COMPLETE'}",
            terminal=False,
        )
        self._emit(_RULE, terminal=False)

    def _terminal_final(self, status: str, elapsed: float) -> None:
        self._compact_section("FINAL")
        if self._final_answer:
            self._compact_emit("Answer:")
            for line in _multiline(self._final_answer, self.answer_chars).splitlines():
                self._compact_emit(f"  {line}")
        else:
            self._compact_emit("Answer: (no final answer text recorded)")

        if self._top_source_summary and status not in {
            "out-of-scope",
            "relevance-guard-no-match",
        }:
            source = _bounded(self._top_source_summary.get("source") or "-", 260)
            chunk = _clean_inline(self._top_source_summary.get("chunk") or "-")
            score = float(self._top_source_summary.get("score") or 0.0)
            self._compact_emit(f"Source      : {source}")
            self._compact_emit(f"Chunk       : {chunk}")
            self._compact_emit(f"Final Score : {score:.6f}")

        self._compact_section("RUNTIME")
        primary_status = str(self._runtime.get("primary_status") or "").upper()
        if not primary_status:
            if status == "qwen-answer":
                primary_status = "SUCCESS"
            elif status.startswith("ollama-"):
                primary_status = "FALLBACK"
            else:
                primary_status = "NOT USED"
        retry_used = bool(self._runtime.get("retry_used", False))
        retry_status = str(self._runtime.get("retry_status") or "").upper()
        model = _clean_inline(self._runtime.get("model") or "")

        if model:
            self._compact_emit(f"Model       : {model}")
        self._compact_emit(f"Ollama      : {primary_status}")
        if retry_used:
            self._compact_emit(f"Retry       : YES ({retry_status or 'ATTEMPTED'})")
        else:
            self._compact_emit("Retry       : NO")
        if self._runtime_issue_summary:
            self._compact_emit(f"Issue       : {_bounded(self._runtime_issue_summary, 320)}")
        self._compact_emit(f"Total Time  : {elapsed:.2f} sec")
        self._compact_emit(f"Result      : {_clean_inline(status).upper() or 'COMPLETE'}")
        if self.log_path:
            self._compact_emit(f"Full Log    : {self.log_path}")
        elif self.log_enabled:
            self._compact_emit("Full Log    : unavailable; verbose terminal fallback was used")
        self._compact_emit(_RULE)
        self._compact_emit("")

    def finish(self, status: str = "complete") -> None:
        if not self.enabled:
            return
        elapsed = max(0.0, time.monotonic() - self._started_monotonic)
        if self._compact_terminal:
            self._log_request_summary(status, elapsed)
            self._terminal_final(status, elapsed)
        else:
            self._section("REQUEST SUMMARY")
            preferred = (
                "files_searched",
                "authorized_documents",
                "file_chunks",
                "structured_records",
                "selected_files",
                "selected_file_chunks",
                "chunk_stage_search_space",
                "matched_files",
                "matched_chunks",
                "final_evidence_chunks",
            )
            emitted: set[str] = set()
            for key in preferred:
                if key in self._counts:
                    self._emit(
                        f"{key.replace('_', ' ').title():24}: {self._counts[key]}"
                    )
                    emitted.add(key)
            for key, value in self._counts.items():
                if key in emitted or key == "total_built_documents":
                    continue
                self._emit(f"{key.replace('_', ' ').title():24}: {value}")
            self._emit(f"Total Request Time      : {elapsed:.2f} sec")
            self._emit(
                f"Result                  : {_clean_inline(status).upper() or 'COMPLETE'}"
            )
            self._emit(_RULE)
            self._emit("")
        self._close_log()

    def _record_runtime_line(self, label: str, text: str) -> None:
        normalized = label.upper()
        if normalized == "OLLAMA REQUEST":
            model_match = re.search(r"\bmodel=([^;]+)", text, re.I)
            if model_match:
                self._runtime["model"] = model_match.group(1).strip()
            self._runtime.setdefault("primary_status", "STARTED")
        elif normalized == "OLLAMA RESULT":
            if "retry completed" in text.lower():
                self._runtime["retry_used"] = True
                self._runtime["retry_status"] = "SUCCESS"
                duration = _float_from_text(text, r"completed\s+in\s+([0-9.]+)s")
                if duration is not None:
                    self._runtime["retry_duration"] = duration
            elif "primary completed" in text.lower():
                self._runtime["primary_status"] = "SUCCESS"
                duration = _float_from_text(text, r"completed\s+in\s+([0-9.]+)s")
                if duration is not None:
                    self._runtime["primary_duration"] = duration
            elif "no model text" in text.lower():
                self._runtime["primary_status"] = "EMPTY RESPONSE"
        elif normalized == "OLLAMA TIMEOUT":
            self._runtime["primary_status"] = "TIMEOUT"
            duration = _float_from_text(text, r"after\s+([0-9.]+)s")
            if duration is not None:
                self._runtime["primary_duration"] = duration
        elif normalized == "OLLAMA RETRY":
            self._runtime["retry_used"] = True
            self._runtime["retry_status"] = "STARTED"
            model_match = re.search(r"\bmodel=([^;]+)", text, re.I)
            if model_match and not self._runtime.get("model"):
                self._runtime["model"] = model_match.group(1).strip()

    def line(self, label: str, value: object = "") -> None:
        if not self.enabled:
            return
        clean_label = _clean_inline(label) or "INFO"
        text = _multiline(value, self.answer_chars)
        self._record_runtime_line(clean_label, text)
        verbose_terminal = self._verbose_terminal_allowed()
        self._section(clean_label, terminal=verbose_terminal)
        if text:
            self._emit(text, terminal=verbose_terminal)

    def answer(self, label: str, value: object) -> None:
        if not self.enabled:
            return
        text = _multiline(value, self.answer_chars)
        if _clean_inline(label).upper() == "FINAL CHAT ANSWER":
            self._final_answer = text
        # Router/Qwen/raw/final options remain available in the full log.  In
        # compact mode the final answer is rendered once in ``finish``.
        self.line(label, text)

    def question_analysis(
        self,
        *,
        yes_no: bool,
        follow_up: bool,
        explanation: bool,
        needs_ai: bool,
        token_count: int,
        evidence_profile: str,
        retrieval_query: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        verbose_terminal = self._verbose_terminal_allowed()
        self._section("QUESTION ANALYSIS", terminal=verbose_terminal)
        self._emit(
            f"Answer Type     : {_clean_inline(evidence_profile) or 'standard'}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"YES / NO       : {'YES' if yes_no else 'NO'}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Follow-up      : {'YES' if follow_up else 'NO'}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Explanation    : {'YES' if explanation else 'NO'}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Needs AI/RAG   : {'YES' if needs_ai else 'NO'}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Question Tokens: {int(token_count)}", terminal=verbose_terminal
        )
        if retrieval_query:
            self._emit(
                f"Retrieval Query: {_bounded(retrieval_query, self.answer_chars)}",
                terminal=verbose_terminal,
            )

    def counts(self, **values: object) -> None:
        if not self.enabled:
            return
        self._counts.update(values)

    def retrieval_summary(self) -> None:
        """Render compact totals live while preserving the full count set in log."""

        if not self.enabled:
            return
        if self._compact_terminal:
            # Full count detail first, log only.
            self._section("RETRIEVAL SUMMARY", terminal=False)
            fields = (
                ("Files searched", "files_searched"),
                ("Authorized knowledge entries", "authorized_documents"),
                ("Document/file chunks", "file_chunks"),
                ("Structured HR records", "structured_records"),
                ("Selected files", "selected_files"),
                ("Selected file chunks", "selected_file_chunks"),
                ("Chunk-stage search space", "chunk_stage_search_space"),
                ("Matched files", "matched_files"),
                ("Matched chunks", "matched_chunks"),
                ("Final evidence chunks", "final_evidence_chunks"),
            )
            for label, key in fields:
                if key in self._counts:
                    self._emit(
                        f"{label:26}: {self._counts[key]}", terminal=False
                    )

            self._compact_section("RETRIEVAL")
            self._compact_emit(
                f"Files Searched    : {self._counts.get('files_searched', 0)}"
            )
            self._compact_emit(
                f"Chunks Searched   : {self._counts.get('chunk_stage_search_space', self._counts.get('file_chunks', 0))}"
            )
            self._compact_emit(
                f"Matched Chunks    : {self._counts.get('matched_chunks', 0)}"
            )
            self._compact_emit(
                f"Final Chunks Used : {self._counts.get('final_evidence_chunks', 0)}"
            )
            self._compact_emit(
                f"Matched Files     : {self._counts.get('matched_files', 0)}"
            )

            self._compact_section("TOP SOURCES")
            if not self._source_rows:
                self._compact_emit("(no file-level source matches)")
            else:
                for row in self._source_rows[: min(5, self.top_k)]:
                    rank = int(row.get("rank") or 0)
                    label = _bounded(row.get("label") or "-", 46)
                    score = float(row.get("score") or 0.0)
                    matched = int(row.get("matched") or 0)
                    total = int(row.get("total") or 0)
                    best_chunk = _clean_inline(row.get("best_chunk") or "-")
                    self._compact_emit(f"#{rank:02d} {label}")
                    self._compact_emit(
                        f"    Source Score : {score:.6f} | Chunks: {matched}/{total} matched | Best: {best_chunk}"
                    )
            return

        self._section("RETRIEVAL SUMMARY")
        fields = (
            ("Files searched", "files_searched"),
            ("Authorized knowledge entries", "authorized_documents"),
            ("Document/file chunks", "file_chunks"),
            ("Structured HR records", "structured_records"),
            ("Selected files", "selected_files"),
            ("Selected file chunks", "selected_file_chunks"),
            ("Chunk-stage search space", "chunk_stage_search_space"),
            ("Matched files", "matched_files"),
            ("Matched chunks", "matched_chunks"),
            ("Final evidence chunks", "final_evidence_chunks"),
        )
        for label, key in fields:
            if key in self._counts:
                self._emit(f"{label:26}: {self._counts[key]}")

    @staticmethod
    def _source_label(document) -> str:
        metadata = getattr(document, "metadata", {}) or {}
        return _clean_inline(
            metadata.get("filename")
            or metadata.get("title")
            or getattr(document, "title", "")
            or getattr(document, "document_id", "")
        )

    def candidates(
        self,
        title: str,
        items: Iterable,
        *,
        score_label: str,
        show_excerpt: bool = True,
    ) -> None:
        if not self.enabled:
            return
        values = list(items)
        verbose_terminal = self._verbose_terminal_allowed()
        self._section(title, terminal=verbose_terminal)
        self._emit(
            f"Results: {len(values)} | Showing: {min(len(values), self.top_k)}",
            terminal=verbose_terminal,
        )
        if not values:
            self._emit("(no results)", terminal=verbose_terminal)
            return
        for rank, item in enumerate(values[: self.top_k], start=1):
            document = getattr(item, "document", None)
            if document is None:
                continue
            metadata = getattr(document, "metadata", {}) or {}
            section = _clean_inline(metadata.get("section")) or "-"
            page = metadata.get("page_number") or "-"
            chunk_index = metadata.get("chunk_index") or "-"
            total_chunks = metadata.get("total_chunks") or "-"
            source_type = _clean_inline(getattr(document, "source_type", "")) or "-"
            score = float(getattr(item, "score", 0.0))
            self._emit("", terminal=verbose_terminal)
            self._emit(
                f"#{rank:02d}  {score_label.upper():12}: {score:.6f}",
                terminal=verbose_terminal,
            )
            self._emit(
                f"     Source       : {self._source_label(document)}",
                terminal=verbose_terminal,
            )
            self._emit(f"     Type         : {source_type}", terminal=verbose_terminal)
            self._emit(f"     Section      : {section}", terminal=verbose_terminal)
            self._emit(f"     Page         : {page}", terminal=verbose_terminal)
            self._emit(
                f"     Chunk        : {chunk_index}/{total_chunks}",
                terminal=verbose_terminal,
            )
            if show_excerpt:
                excerpt = _multiline(
                    getattr(document, "text", ""), self.excerpt_chars
                )
                if excerpt:
                    self._emit("     Evidence     :", terminal=verbose_terminal)
                    for line in excerpt.splitlines() or [excerpt]:
                        self._emit(f"       {line}", terminal=verbose_terminal)

    def selected_files(
        self,
        selected_keys: Iterable[str],
        grouped: Mapping[str, list],
    ) -> None:
        if not self.enabled:
            return
        keys = list(selected_keys)
        self._counts["selected_files"] = len(keys)
        verbose_terminal = self._verbose_terminal_allowed()
        self._section("SELECTED FILES", terminal=verbose_terminal)
        self._emit(
            f"Selected file count: {len(keys)}", terminal=verbose_terminal
        )
        for rank, key in enumerate(keys[: self.top_k], start=1):
            docs = grouped.get(key) or []
            label = self._source_label(docs[0]) if docs else _clean_inline(key)
            self._emit(
                f"#{rank:02d} {label} | total_chunks={len(docs)} | "
                f"file_key={_bounded(key, 220)}",
                terminal=verbose_terminal,
            )

    def file_ranking(
        self,
        *,
        file_scores: Mapping[str, float],
        grouped: Mapping[str, list],
        selected_keys: Iterable[str],
        matched_chunk_counts: Mapping[str, int] | None = None,
        best_chunks: Mapping[str, str] | None = None,
    ) -> None:
        if not self.enabled:
            return
        selected = set(selected_keys)
        matched_chunk_counts = matched_chunk_counts or {}
        best_chunks = best_chunks or {}
        ranked = sorted(
            file_scores.items(), key=lambda item: float(item[1]), reverse=True
        )
        self._source_rows = []
        for rank, (key, score) in enumerate(ranked, start=1):
            if key not in selected:
                continue
            docs = grouped.get(key) or []
            label = self._source_label(docs[0]) if docs else _clean_inline(key)
            self._source_rows.append(
                {
                    "rank": len(self._source_rows) + 1,
                    "label": label,
                    "score": float(score),
                    "matched": int(matched_chunk_counts.get(key, 0)),
                    "total": len(docs),
                    "best_chunk": best_chunks.get(key, "-"),
                }
            )

        verbose_terminal = self._verbose_terminal_allowed()
        self._section("MATCHED FILES — FILE-LEVEL RANKING", terminal=verbose_terminal)
        self._emit(
            "Rank  File                                      Total  Matched  Score      Status",
            terminal=verbose_terminal,
        )
        self._emit(
            "----  ----------------------------------------  -----  -------  ---------  --------",
            terminal=verbose_terminal,
        )
        for rank, (key, score) in enumerate(ranked[: self.top_k], start=1):
            docs = grouped.get(key) or []
            label = self._source_label(docs[0]) if docs else _clean_inline(key)
            status = "SELECTED" if key in selected else "REJECTED"
            self._emit(
                f"{rank:>4}  {_bounded(label, 40):<40}  {len(docs):>5}  "
                f"{int(matched_chunk_counts.get(key, 0)):>7}  {float(score):>9.6f}  {status}",
                terminal=verbose_terminal,
            )
        if not ranked:
            self._emit("(no file-level matches)", terminal=verbose_terminal)

    def retrieval_matches(
        self,
        *,
        candidates: Iterable,
        final_results: Iterable,
    ) -> None:
        if not self.enabled:
            return
        candidate_values = list(candidates)
        final_values = list(final_results)
        candidate_files = {
            self._source_label(item.document)
            for item in candidate_values
            if getattr(item, "document", None) is not None
        }
        self._counts["matched_chunks"] = len(candidate_values)
        self._counts["matched_files"] = len(candidate_files)
        self._counts["final_evidence_chunks"] = len(final_values)

        by_file: dict[str, int] = {}
        for item in final_values:
            document = getattr(item, "document", None)
            if document is None:
                continue
            label = self._source_label(document)
            by_file[label] = by_file.get(label, 0) + 1
        verbose_terminal = self._verbose_terminal_allowed()
        self._section("FINAL EVIDENCE CHUNKS BY FILE", terminal=verbose_terminal)
        if not by_file:
            self._emit("(no final evidence chunks)", terminal=verbose_terminal)
        else:
            for rank, (label, count) in enumerate(
                sorted(by_file.items(), key=lambda item: (-item[1], item[0].casefold())),
                start=1,
            ):
                self._emit(
                    f"#{rank:02d} {_bounded(label, 58):<58} chunks={count}",
                    terminal=verbose_terminal,
                )

    def answer_candidates(self, candidates: Iterable[Mapping[str, object]]) -> None:
        """Show candidate answer scores live; keep full metadata/excerpts in log."""

        if not self.enabled:
            return
        values = list(candidates)
        verbose_terminal = self._verbose_terminal_allowed()
        self._section(
            "CANDIDATE ANSWERS — RETRIEVED EVIDENCE",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Candidates: {len(values)} | Showing: {min(len(values), self.top_k)}",
            terminal=verbose_terminal,
        )
        if not values:
            self._emit("(no candidate answers)", terminal=verbose_terminal)
            if self._compact_terminal:
                self._compact_section("CANDIDATE ANSWERS")
                self._compact_emit("(no candidate answers)")
            return

        # Full forensic candidate block.
        for rank, candidate in enumerate(values[: self.top_k], start=1):
            retrieval_score = float(candidate.get("retrieval_score") or 0.0)
            answer_fit = float(candidate.get("answer_fit") or 0.0)
            source = _bounded(candidate.get("source") or "-", 220)
            section = _bounded(candidate.get("section") or "-", 260)
            page = _clean_inline(candidate.get("page") or "-")
            chunk = _clean_inline(candidate.get("chunk") or "-")
            marker = "  << BEST MATCH" if rank == 1 else ""
            self._emit("", terminal=verbose_terminal)
            self._emit(
                f"Candidate #{rank:02d}{marker}", terminal=verbose_terminal
            )
            self._emit(
                f"  Retrieval Score : {retrieval_score:.6f}",
                terminal=verbose_terminal,
            )
            self._emit(
                f"  Answer Fit      : {answer_fit:.6f}",
                terminal=verbose_terminal,
            )
            self._emit(f"  Source          : {source}", terminal=verbose_terminal)
            self._emit(f"  Section         : {section}", terminal=verbose_terminal)
            self._emit(f"  Page            : {page}", terminal=verbose_terminal)
            self._emit(f"  Chunk           : {chunk}", terminal=verbose_terminal)
            possible_answer = _multiline(
                candidate.get("possible_answer") or "",
                self.candidate_answer_chars,
            )
            if possible_answer:
                self._emit("  Possible Answer :", terminal=verbose_terminal)
                for line in possible_answer.splitlines() or [possible_answer]:
                    self._emit(f"    {line}", terminal=verbose_terminal)

        if self._compact_terminal:
            self._compact_section("CANDIDATE ANSWERS")
            # Three candidates are normally enough for quick live diagnosis;
            # the request log still contains up to terminal_debug_top_k.
            for rank, candidate in enumerate(values[:3], start=1):
                answer_score = float(candidate.get("answer_fit") or 0.0)
                retrieval_score = float(candidate.get("retrieval_score") or 0.0)
                source = _bounded(candidate.get("source") or "-", 48)
                chunk = _clean_inline(candidate.get("chunk") or "-")
                marker = " [BEST]" if rank == 1 else ""
                self._compact_emit(
                    f"#{rank:02d}{marker} Answer Score: {answer_score:.6f} | Retrieval: {retrieval_score:.6f}"
                )
                self._compact_emit(f"    Source: {source} | Chunk: {chunk}")
                possible_answer = _multiline(
                    candidate.get("possible_answer") or "",
                    min(420, self.candidate_answer_chars),
                )
                if possible_answer:
                    self._compact_emit("    Answer:")
                    for line in possible_answer.splitlines() or [possible_answer]:
                        self._compact_emit(f"      {line}")

    def relevance_guard(
        self,
        *,
        anchors: Iterable[str],
        matched_anchors: Iterable[str],
        coverage: float,
        answer_fit: float,
        source: str,
        decision: str,
        reason: str,
    ) -> None:
        if not self.enabled:
            return
        anchor_list = sorted(set(anchors))
        matched_list = sorted(set(matched_anchors))
        verbose_terminal = self._verbose_terminal_allowed()
        self._section("RELEVANCE / NO-MATCH GUARD", terminal=verbose_terminal)
        self._emit(
            f"Topic Anchors    : {', '.join(anchor_list) or '(none)'}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Matched Anchors  : {', '.join(matched_list) or '(none)'}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Anchor Coverage  : {float(coverage):.3f}", terminal=verbose_terminal
        )
        self._emit(
            f"Answer Fit       : {float(answer_fit):.3f}", terminal=verbose_terminal
        )
        self._emit(
            f"Best Source      : {_bounded(source or '-', 260)}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Decision         : {_clean_inline(decision).upper()}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Reason           : {_bounded(reason, 520)}", terminal=verbose_terminal
        )
        if self._compact_terminal and _clean_inline(decision).upper() == "REJECT":
            self._compact_section("RELEVANCE GUARD")
            self._compact_emit("Decision : REJECT")
            self._compact_emit(f"Reason   : {_bounded(reason, 300)}")

    def top_source(self, item) -> None:
        if not self.enabled:
            return
        verbose_terminal = self._verbose_terminal_allowed()
        self._section("TOP NEAREST / FINAL SOURCE", terminal=verbose_terminal)
        if item is None or getattr(item, "document", None) is None:
            self._top_source_summary = {}
            self._emit("No accepted top source.", terminal=verbose_terminal)
            return
        document = item.document
        metadata = getattr(document, "metadata", {}) or {}
        chunk = (
            f"{metadata.get('chunk_index') or '-'}/"
            f"{metadata.get('total_chunks') or '-'}"
        )
        score = float(getattr(item, "score", 0.0))
        source = self._source_label(document)
        self._top_source_summary = {
            "source": source,
            "section": _clean_inline(metadata.get("section")) or "-",
            "page": metadata.get("page_number") or "-",
            "chunk": chunk,
            "score": score,
        }
        self._emit(f"File       : {source}", terminal=verbose_terminal)
        self._emit(
            f"Section    : {_clean_inline(metadata.get('section')) or '-'}",
            terminal=verbose_terminal,
        )
        self._emit(
            f"Page       : {metadata.get('page_number') or '-'}",
            terminal=verbose_terminal,
        )
        self._emit(f"Chunk      : {chunk}", terminal=verbose_terminal)
        self._emit(f"Score      : {score:.6f}", terminal=verbose_terminal)
        self._emit("UI Display : TOP SOURCE ONLY", terminal=verbose_terminal)

    def answer_selection(self, *, selected: str, reason: str) -> None:
        if not self.enabled:
            return
        self._selected_answer = _clean_inline(selected)
        self._selection_reason = _bounded(reason, 420)
        verbose_terminal = self._verbose_terminal_allowed()
        self._section("FINAL ANSWER SELECTION", terminal=verbose_terminal)
        self._emit(
            f"Selected : {self._selected_answer or '-'}", terminal=verbose_terminal
        )
        self._emit(
            f"Reason   : {self._selection_reason}", terminal=verbose_terminal
        )

    def runtime_issue(self, *, code: str, title: str, message: str) -> None:
        if not self.enabled:
            return
        self._runtime_issue_summary = (
            f"{_clean_inline(title) or _clean_inline(code) or 'Runtime issue'}: "
            f"{_bounded(message, 260)}"
        ).strip()
        if self._runtime.get("primary_status") in {None, "", "STARTED"}:
            self._runtime["primary_status"] = "ERROR / FALLBACK"
        verbose_terminal = self._verbose_terminal_allowed()
        self._section("RUNTIME ISSUE", terminal=verbose_terminal)
        self._emit(
            f"Code    : {_clean_inline(code) or '-'}", terminal=verbose_terminal
        )
        self._emit(
            f"Title   : {_clean_inline(title) or '-'}", terminal=verbose_terminal
        )
        self._emit(
            f"Message : {_bounded(message, self.answer_chars)}",
            terminal=verbose_terminal,
        )
