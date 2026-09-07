"""Local, company-scoped AI enhancement for both portal chat assistants.

Architecture:
- Existing deterministic assistants remain authoritative for live HR records.
- Published policy sections and portal help text are retrieved through hybrid
  BM25 + optional Chroma vector search.
- Optional CrossEncoder reranking improves the final candidate order.
- Ollama performs only grounded answer synthesis.
- Every dependency is lazy-loaded so the portal keeps working when the local
  AI runtime or index dependencies are not installed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import logging
import math
import os
import re
import socket
import time
from typing import Iterable
from urllib import request, error
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from authentication.current_user import AuthenticatedUser
from config.chat_assistant_settings import get_chat_assistant_settings
from config.settings import get_settings
from modules.hr_assistant.hr_assistant import HRAssistantResponse
from modules.smart_ai.terminal_trace import TerminalChatTrace
from modules.smart_ai.prompts.hr_assistant_prompt import (
    NOT_FOUND_ANSWER,
    OUT_OF_SCOPE_ANSWER,
    UNDETERMINED_ANSWER,
    build_hr_assistant_prompt,
)
from models.announcement import Announcement
from models.attendance_record import AttendanceRecord
from models.company import Company
from models.company_form import CompanyForm
from models.company_form_submission import CompanyFormSubmission
from models.employee import Employee
from models.employee_training import EmployeeTraining
from models.event_reminder import EventReminder
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.overtime_request import OvertimeRequest
from models.user import User
from repositories.policy_section_repository import PolicySectionRepository
from services.policy_violation_service import PolicyViolationService
from services.company_form_knowledge_service import CompanyFormKnowledgeExtractor
from services.runtime_connection_service import (
    RuntimeServiceModelUnavailableError,
    RuntimeServiceResponseError,
    RuntimeServiceTimeoutError,
    RuntimeServiceUnavailableError,
    classify_runtime_connection_issue,
    log_runtime_connection_issue,
)


def _disable_chroma_product_telemetry() -> None:
    """Disable Chroma product telemetry without disabling vector search."""

    # Pydantic loading this value from .env does not export it to os.environ,
    # which is the process configuration read by Chroma during initialization.
    os.environ["ANONYMIZED_TELEMETRY"] = "False"

    # Older Chroma builds may still instantiate PostHog when telemetry is off.
    # Disable only that component's logger so its incompatible capture call
    # cannot flood the terminal; retrieval errors remain visible elsewhere.
    logging.getLogger("chromadb.telemetry.product.posthog").disabled = True


_disable_chroma_product_telemetry()


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """One role-safe portal or policy knowledge unit."""

    document_id: str
    text: str
    title: str
    source_type: str
    company_id: int
    role_scope: str
    metadata: dict[str, str | int | None]


@dataclass(frozen=True, slots=True)
class RetrievedDocument:
    """One hybrid-search result."""

    document: KnowledgeDocument
    score: float


_PORTAL_GUIDES = {
    "shared": [
        ("Navigation and privacy", "The HR Assistant answers only from the authenticated company portal. It cannot use outside knowledge, expose another company, or reveal passwords, reset tokens, secret keys, SMTP credentials, or private authentication data."),
        ("Company policies and violations", "Published company policies are available in Company Policies. Active company violation/offense rules and their disciplinary actions are available in Violations & Disciplinary Actions. Answers must use only published/effective policy files and active/effective violation rules from the authenticated company. Administrators manage policy upload/versions/Bin and the separate violation master list."),
        ("Announcements and reminders", "Announcements show published company notices. Independent event reminders are planning records for future events and activities. Reminder notifications are sent to administrators at one month, two weeks, and one week before an event."),
        ("Leave workflow", "Employees may file Whole Day, AM Only, or PM Only leave in Leave Management using a coded standard reason and an Others explanation only when 0 - OTHERS is selected. Overlapping active leave for the same owner is blocked. Leaders and Managers may file for direct reports, but approval always follows the leave owner hierarchy and filing is never automatic approval. Paid credits are reserved after final approval and used on approved dates."),
        ("Attendance and DTR", "Attendance supports multiple non-overlapping WFO and WFH work sessions per day. Mixed locations become Hybrid. Actual punches remain in audit history while payroll Time In rounds up and Time Out rounds down to 15-minute boundaries. Approved AM/PM leave supplies four leave hours on an eight-hour day and only the remaining work portion is checked for undertime; leave, gaps, and lunch never become overtime."),
        ("Overtime requests", "The employee Attendance/DTR page contains one collapsible Overtime Request section combining DTR-prefilled filing and My Overtime Requests. Employee ID, name, and the original DTR reference are read-only. Date Rendered, OT Start/End, and Estimated Hours are prefilled but editable. The employee selects OT Type and enters Purpose, optional Travel Fare and required Route, and Dinner Break. Company OT rules can deduct dinner-break hours from payable OT, pair qualifying smaller OT blocks within one cut-off as Shifting Credits, and grant additional Vacation Leave for a qualifying single long OT request. Shifting-credit eligibility uses the company exclusion list rather than guessing a senior-position hierarchy. Approved requests populate the full OT report row; a DTR-only row leaves unsupported fields blank."),
        ("Company forms and documents", "Company Form/Documents contains company templates. Administrators upload and manage templates and review employee submissions. Employees may view, download, fill, and submit forms when the selected template permits employee submission."),
        ("App-wide answer boundary", "The assistant may answer from authorized live HR records, published company policies, company announcements, configured leave rules, and actual workflows available in this HR application. If the information is not present in those company or application sources, it must say that the information was not found and must not use outside knowledge."),
    ],
    "employee": [
        ("Employee portal scope", "The employee assistant may show the signed-in employee's own profile, leave credits, personal leave requests, published company policies, active company violation and disciplinary-action rules, the signed-in employee's own issued disciplinary records when portal visibility is enabled, announcements, reminders visible to employees, and instructions for available employee portal pages. It must never disclose another employee's disciplinary history or private record."),
        ("Employee records", "Employees can ask for their employee number, department, manager, leader, job title, work email, employment status, hire date, and other fields stored in their own employee profile."),
        ("Employee documents", "Company Form/Documents contains available company forms and documents. Its My Documents tab contains only the signed-in employee's own completed form submissions, review status, administrator notes, previews, and downloads. The assistant must not invent a document that is not present."),
        ("Employee navigation", "Dashboard contains the employee's Time In/Time Out and Announcements workspaces. Attendance Hub contains the employee's monthly DTR, attendance editor, and overtime request workflow. Reports generates one employee-scoped Excel workbook containing DTR Logs, Overtime File, and Leave File. Leave Management contains leave overview, filing, My Requests, and authorized leader or manager views. Company Form/Documents contains View, Download, Fill / Submit, and My Documents. Onboarding contains Overview, Checklist, and the permanent Benefits workspace. Company Policies, HR Contacts, and FAQ retain their corresponding approved or default information."),
    ],
    "admin": [
        ("Administrator portal scope", "The administrator assistant may summarize authorized company-wide employees, departments, user accounts, leave requests, leave credits, policies, announcements, reminders, integrations, and company settings. Results must remain restricted to the authenticated company."),
        ("Employee management", "Administrators manage employee records, account linkage, departments, manager and leader assignments, job titles, employment status, hire date, demographics, training checklist, account information, onboarding progress, onboarding checklist setup, and company benefits in Employees."),
        ("Security restrictions", "Passwords, password hashes, reset tokens, cookie secrets, SMTP passwords, and equivalent credentials can never be displayed by the assistant. The assistant may explain where settings are managed without exposing secret values."),
        ("Administrator navigation", "Admin Dashboard contains company metrics and Attendance/DTR/OT. Employees contains employee list, add, edit, and Violations / Disciplinary Records workspaces for actual employee cases. Policies contains library, upload, management, Violations & Disciplinary Actions, and Bin; the violation workspace is the single source of truth for master offense definitions and penalty guidance. Leave Management contains overview, employee leave accounts, leave requests, and rules. Announcements contains overview, create, manage, reminders, and archive. Company Form/Documents contains overview, upload, management, employee submissions, and Bin. Reports includes disciplinary reporting alongside existing reports, and Integrations contains the implemented integration workspaces."),
    ],
}


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_model_answer(value: str) -> str:
    """Normalize model output without destroying Markdown list structure.

    Prompt/history normalization intentionally collapses whitespace, but final
    assistant output must preserve line breaks so bullets and numbered steps
    remain readable in Streamlit Markdown.
    """

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines: list[str] = []
    previous_blank = False

    for raw_line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if cleaned_lines and not previous_blank:
                cleaned_lines.append("")
            previous_blank = True
            continue
        cleaned_lines.append(line)
        previous_blank = False

    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()

    answer = "\n".join(cleaned_lines).strip()
    answer = re.sub(
        r"^(?:final answer|answer|response)\s*:\s*",
        "",
        answer,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    return answer


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").casefold())


def _organize_answer(value: str) -> str:
    """Keep simple answers concise and normalize multi-item responses."""

    text = (value or "").strip()
    if not text:
        return text
    lines = [line.rstrip() for line in text.splitlines()]
    meaningful = [line for line in lines if line.strip()]
    if len(meaningful) <= 2:
        return "\n".join(meaningful)

    # Preserve existing Markdown lists and numbered procedures.
    if any(re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", line) for line in meaningful):
        return "\n".join(lines).strip()

    # Convert short, label-like multi-line answers into readable bullets.
    if all(len(line.strip()) <= 180 for line in meaningful[1:]):
        return meaningful[0] + "\n\n" + "\n".join(
            f"- {line.strip()}" for line in meaningful[1:]
        )
    return "\n".join(lines).strip()


_DOCUMENT_CHUNK_SOURCE_TYPES = frozenset({"policy", "company_form_content"})


def _word_count(value: str) -> int:
    """Return a stable local chunk-sizing unit without external tokenizers."""

    return len(re.findall(r"\S+", value or ""))


def _sentence_units(value: str) -> list[str]:
    """Split text on paragraph/sentence boundaries while preserving rows/lists."""

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    units: list[str] = []
    for raw_block in re.split(r"\n\s*\n+", text):
        block = re.sub(r"[ \t]+", " ", raw_block).strip()
        if not block:
            continue
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        for line in lines:
            # Table/list rows are logical units and should not be broken mid-row.
            if " | " in line or re.match(r"^(?:[-*•]|\d+[.)])\s+", line):
                units.append(line)
                continue
            sentences = [
                item.strip()
                for item in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", line)
                if item.strip()
            ]
            units.extend(sentences or [line])
    return units


_EVIDENCE_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but",
    "by", "can", "could", "did", "do", "does", "for", "from", "had",
    "has", "have", "how", "i", "if", "in", "is", "it", "may", "me",
    "my", "of", "on", "or", "should", "that", "the", "their", "this",
    "to", "was", "were", "what", "when", "where", "which", "who",
    "why", "will", "with", "would", "you", "your",
}


def _meaningful_evidence_tokens(value: str) -> list[str]:
    """Return stable lexical terms used only for local evidence ranking."""

    return [
        token
        for token in _tokenize(value)
        if len(token) >= 2 and token not in _EVIDENCE_STOPWORDS
    ]


def _normalized_phrase_text(value: str) -> str:
    """Normalize punctuation/hyphens so policy wording variants still match."""

    return " ".join(_tokenize(value))


def _question_evidence_profile(question: str) -> str:
    """Classify the evidence shape needed by a user question."""

    clean = _clean_text(question).casefold()
    if re.search(r"\b(compare|comparison|difference|versus|vs\.?)\b", clean):
        return "comparison"
    if re.search(r"^\s*what\s+(?:benefits|requirements|reasons|documents|conditions|options)\b", clean):
        return "list"
    if re.search(r"^\s*how\s+much\b|\b(amount|cost|price|allowance|reimbursement|cash award)\b", clean):
        return "amount"
    if re.search(r"^\s*how\s+(?:many|long)\b", clean):
        return "duration_or_count"
    if re.search(r"^\s*when\b|\bwhat time\b|\bwhat date\b", clean):
        return "date_or_time"
    if re.search(r"\bwhat happens\b|\bpenalt(?:y|ies)\b|\bconsequence\b|\bdisciplin", clean):
        return "consequence"
    if re.search(r"\b(eligible|eligibility|qualify|qualified|entitled|covered|allowed|prohibited)\b", clean):
        return "eligibility"
    if re.search(r"^\s*(?:what should|how (?:do|does|can|should|to)|what do)\b|\bprocedure\b|\bprocess\b", clean):
        return "procedure"
    if re.search(r"^\s*(?:list|show|give me|what are|which are)\b", clean):
        return "list"
    if re.search(r"^\s*(?:can|could|may|should|will|do|does|is|are|has|have)\b", clean):
        return "yes_no"
    return "standard"


def _answerability_cue_bonus(question: str, text: str) -> float:
    """Boost evidence that contains the kind of fact the question asks for."""

    profile = _question_evidence_profile(question)
    clean = _normalized_phrase_text(text)
    raw = str(text or "").casefold()

    if profile == "amount":
        if re.search(r"(?:₱|\$|¥|€)\s*\d|\b\d[\d,]*(?:\.\d+)?\s*(?:peso|pesos|php|yen|dollar|dollars)\b", raw):
            return 1.0
        if re.search(r"\b(amount|allowance|reimbursement|cash|pay|rate|cost|award)\b", clean):
            return 0.55
    elif profile == "duration_or_count":
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:day|days|week|weeks|month|months|year|years|hour|hours|minute|minutes|person|persons|dependent|dependents|credit|credits)\b", raw):
            return 1.0
        if re.search(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|twenty five)\s+(?:day|days|week|weeks|month|months|year|years|hour|hours)\b", clean):
            return 0.9
    elif profile == "date_or_time":
        if re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", raw):
            return 1.0
        if re.search(r"\b(?:before|after|within|effective|date|time|month|year|day)\b", clean):
            return 0.5
    elif profile == "consequence":
        if re.search(r"\b(?:disqualif|absent|penalt|sanction|suspend|dismiss|forfeit|deduct|warning|violation|terminate|termination)\w*\b", clean):
            return 1.0
        if re.search(r"\b(?:shall|will|must|required)\b", clean):
            return 0.45
    elif profile in {"eligibility", "yes_no"}:
        if re.search(r"\b(?:eligible|qualif|entitled|covered|allowed|prohibit|required|shall|may|must|not)\w*\b", clean):
            return 0.8
    elif profile == "procedure":
        if re.search(r"\b(?:submit|notify|inform|request|approval|approve|form|report|contact|must|shall|within|before|after)\w*\b", clean):
            return 0.75
    elif profile in {"comparison", "list"}:
        if " | " in text or re.search(r"(?:^|\n)\s*(?:[-*•]|\d+[.)])\s+", text):
            return 0.65
    return 0.0


def _evidence_fit_bonus(question: str, document: KnowledgeDocument) -> float:
    """Return a bounded relevance bonus on top of BM25/vector RRF ranking."""

    query_terms = _meaningful_evidence_tokens(question)
    if not query_terms:
        return 0.0

    evidence_text = f"{document.title} {document.text}"
    evidence_tokens = _meaningful_evidence_tokens(evidence_text)
    if not evidence_tokens:
        return 0.0

    query_unique = set(query_terms)
    evidence_unique = set(evidence_tokens)
    overlap = query_unique.intersection(evidence_unique)
    coverage = len(overlap) / max(1, len(query_unique))

    # Reward a concise passage that covers the question terms without allowing
    # a very long policy to win simply because the same words occur many times.
    density = min(1.0, len(overlap) / max(1.0, math.sqrt(len(evidence_unique))))

    normalized_evidence = _normalized_phrase_text(evidence_text)
    phrase_hits = 0
    for size in (3, 2):
        for index in range(0, max(0, len(query_terms) - size + 1)):
            phrase = " ".join(query_terms[index:index + size])
            if phrase and phrase in normalized_evidence:
                phrase_hits += 1
    phrase_bonus = min(1.0, phrase_hits / 3.0)

    title_terms = set(_meaningful_evidence_tokens(document.title))
    title_overlap = len(query_unique.intersection(title_terms)) / max(1, len(query_unique))
    cue_bonus = _answerability_cue_bonus(question, evidence_text)

    return (
        (coverage * 0.48)
        + (density * 0.12)
        + (phrase_bonus * 0.18)
        + (title_overlap * 0.10)
        + (cue_bonus * 0.12)
    )


def _focused_evidence_excerpt(query: str, text: str, max_chars: int) -> str:
    """Keep the most question-relevant sentence/row plus nearby context."""

    clean = str(text or "").strip()
    limit = max(320, int(max_chars))
    if len(clean) <= limit:
        return clean

    units = _sentence_units(clean)
    if not units:
        return clean[:limit].rstrip()

    query_terms = set(_meaningful_evidence_tokens(query))
    normalized_query = _normalized_phrase_text(query)

    def unit_score(unit: str) -> float:
        unit_terms = set(_meaningful_evidence_tokens(unit))
        lexical = len(query_terms.intersection(unit_terms))
        cue = _answerability_cue_bonus(query, unit)
        phrase = 0.0
        normalized_unit = _normalized_phrase_text(unit)
        if normalized_query and len(normalized_query) <= 120 and normalized_query in normalized_unit:
            phrase = 2.0
        information = 0.0
        if re.search(r"(?:₱|\$|¥|€)\s*\d|\b\d+(?:[.,]\d+)?\b", unit):
            information += 0.55
        if re.search(
            r"\b(?:shall|must|required|eligible|entitled|allowance|reimbursement|"
            r"disqualif|absent|penalt|sanction|deadline|within|before|after)\w*\b",
            normalized_unit,
        ):
            information += 0.35
        return (lexical * 2.0) + cue + phrase + information

    best_index = max(range(len(units)), key=lambda index: unit_score(units[index]))
    chosen: list[int] = [best_index]
    radius = 1
    while radius < len(units):
        added = False
        for candidate in (best_index - radius, best_index + radius):
            if candidate < 0 or candidate >= len(units) or candidate in chosen:
                continue
            prospective = sorted(chosen + [candidate])
            rendered = " ".join(units[index] for index in prospective)
            if len(rendered) > limit:
                continue
            chosen.append(candidate)
            added = True
        if not added and len(" ".join(units[index] for index in sorted(chosen))) >= int(limit * 0.72):
            break
        radius += 1

    excerpt = " ".join(units[index] for index in sorted(chosen)).strip()
    if not excerpt:
        excerpt = units[best_index].strip()
    return excerpt[:limit].rstrip()


def _split_oversized_unit(value: str, chunk_size: int) -> list[str]:
    words = value.split()
    if len(words) <= chunk_size:
        return [value]
    return [
        " ".join(words[index:index + chunk_size])
        for index in range(0, len(words), chunk_size)
        if words[index:index + chunk_size]
    ]


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Sentence/row-aware bounded chunks with deterministic overlap.

    ``chunk_size`` and ``overlap`` are word budgets.  This deliberately avoids
    an optional tokenizer dependency so every installation chunks documents in
    the same way.  It also fixes the former empty ``SentenceSplitter`` call
    that always fell back to blind fixed-word windows.
    """

    raw = str(text or "").strip()
    if not raw:
        return []
    chunk_size = max(80, int(chunk_size))
    overlap = max(0, min(int(overlap), chunk_size // 3))

    units: list[str] = []
    for unit in _sentence_units(raw):
        units.extend(_split_oversized_unit(unit, chunk_size))
    if not units:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    def emit() -> None:
        nonlocal current, current_words
        if not current:
            return
        chunk = " ".join(current).strip()
        if chunk:
            chunks.append(chunk)
        if not overlap:
            current = []
            current_words = 0
            return
        tail: list[str] = []
        tail_words = 0
        for item in reversed(current):
            count = _word_count(item)
            if tail and tail_words + count > overlap:
                break
            tail.insert(0, item)
            tail_words += count
            if tail_words >= overlap:
                break
        current = tail
        current_words = tail_words

    for unit in units:
        unit_words = max(1, _word_count(unit))
        if current and current_words + unit_words > chunk_size:
            emit()
        # A near-maximal logical unit may not fit beside the retained overlap.
        # Prefer the intact unit over forcing an oversized chunk.
        if current and current_words + unit_words > chunk_size:
            current = []
            current_words = 0
        current.append(unit)
        current_words += unit_words
    if current:
        chunk = " ".join(current).strip()
        if chunk and (not chunks or chunk != chunks[-1]):
            chunks.append(chunk)
    return chunks


def _document_sections(text: str) -> list[tuple[str, str]]:
    """Return logical sections/pages from one extracted company document."""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return []

    sections: list[tuple[str, str]] = []
    heading = "Document"
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        content = "\n".join(body).strip()
        if content:
            sections.append((heading, content))
        body = []

    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            if body and body[-1] != "":
                body.append("")
            continue
        page_match = re.match(r"^Page\s+(\d+)\s*:\s*(.*)$", line, re.I)
        if page_match:
            flush()
            heading = f"Page {page_match.group(1)}"
            remainder = page_match.group(2).strip()
            if remainder:
                body.append(remainder)
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+)$", line)
        if heading_match:
            flush()
            heading = heading_match.group(1).strip() or "Document"
            continue
        if re.match(r"^(?:Sheet\s*:|Table\s+\d+\s*$)", line, re.I):
            flush()
            heading = line
            continue
        body.append(line)
    flush()
    return sections or [("Document", normalized.strip())]


def _prepare_document_chunks(
    sections: list[tuple[str, str, int | None]],
    *,
    chunk_size: int,
    overlap: int,
) -> list[tuple[str, str, int | None]]:
    """Create robust bounded chunks from ordered sections of one file.

    Reliable semantic boundaries are kept when useful, while adjacent tiny
    sections are merged before final splitting so headings do not fragment the
    evidence into low-context micro-chunks. If a document has no dependable
    structure, callers pass a single file-level section and the same bounded
    chunker operates over the whole file.
    """

    normalized: list[tuple[str, str, int | None]] = []
    for label, text, page_number in sections:
        clean = str(text or "").strip()
        if clean:
            normalized.append((str(label or "Document").strip() or "Document", clean, page_number))
    if not normalized:
        return []

    chunk_size = max(80, int(chunk_size))
    overlap = max(0, int(overlap))
    micro_limit = max(48, min(96, chunk_size // 3))

    merged: list[tuple[str, str, int | None]] = []
    pending_label = ""
    pending_text = ""
    pending_page: int | None = None

    def flush_pending() -> None:
        nonlocal pending_label, pending_text, pending_page
        if pending_text.strip():
            merged.append((pending_label or "Document", pending_text.strip(), pending_page))
        pending_label = ""
        pending_text = ""
        pending_page = None

    for label, text, page_number in normalized:
        words = _word_count(text)
        if not pending_text:
            pending_label, pending_text, pending_page = label, text, page_number
            continue

        pending_words = _word_count(pending_text)
        same_page = pending_page == page_number or pending_page is None or page_number is None
        combined_words = pending_words + words
        should_merge = (
            same_page
            and combined_words <= chunk_size
            and (pending_words < micro_limit or words < micro_limit)
        )
        if should_merge:
            if label.casefold() not in pending_label.casefold():
                pending_label = f"{pending_label} / {label}"[:250]
            pending_text = f"{pending_text}\n\n{text}".strip()
            if pending_page != page_number:
                pending_page = None
            continue

        flush_pending()
        pending_label, pending_text, pending_page = label, text, page_number

    flush_pending()

    prepared: list[tuple[str, str, int | None]] = []
    for label, text, page_number in merged:
        for chunk in _split_text(text, chunk_size, overlap):
            prepared.append((label, chunk, page_number))
    return prepared


def _file_key(document: KnowledgeDocument) -> str | None:
    if document.source_type not in _DOCUMENT_CHUNK_SOURCE_TYPES:
        return None
    value = document.metadata.get("file_key")
    return str(value) if value else None


class PortalKnowledgeBuilder:
    """Build role-safe knowledge from published policies and portal workflows."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_chat_assistant_settings()
        self.company_form_extractor = CompanyFormKnowledgeExtractor()

    @staticmethod
    def _add_document(
        documents: list[KnowledgeDocument],
        *,
        document_id: str,
        text: str,
        title: str,
        source_type: str,
        company_id: int,
        role_scope: str,
        metadata: dict[str, str | int | None] | None = None,
    ) -> None:
        """Append one normalized, role-safe live knowledge record."""

        clean = _clean_text(text)
        if not clean:
            return
        documents.append(KnowledgeDocument(
            document_id=document_id,
            text=clean,
            title=title,
            source_type=source_type,
            company_id=company_id,
            role_scope=role_scope,
            metadata=metadata or {"title": title},
        ))

    def _add_live_company_records(
        self,
        documents: list[KnowledgeDocument],
        *,
        current_user: AuthenticatedUser,
        role_scope: str,
    ) -> None:
        """Add authorized live records without authentication secrets.

        Administrators receive company-wide records from their own tenant.
        Employees receive only their own private HR records plus company-wide
        information already available in the employee portal.
        """

        company_id = current_user.company_id
        is_admin = role_scope == "admin"
        employee_id = current_user.employee_id
        live_scope = "admin" if is_admin else "employee"

        company = self.session.scalar(
            select(Company).where(Company.id == company_id)
        )
        if company is not None:
            workdays = [
                label
                for label, enabled in (
                    ("Monday", company.work_monday),
                    ("Tuesday", company.work_tuesday),
                    ("Wednesday", company.work_wednesday),
                    ("Thursday", company.work_thursday),
                    ("Friday", company.work_friday),
                    ("Saturday", company.work_saturday),
                    ("Sunday", company.work_sunday),
                )
                if enabled
            ]
            try:
                excluded_positions = json.loads(
                    company.shifting_credit_excluded_positions_json or "[]"
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                excluded_positions = []
            if not isinstance(excluded_positions, list):
                excluded_positions = []
            excluded_positions_text = ", ".join(
                str(value) for value in excluded_positions if str(value).strip()
            ) or "None"

            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:company",
                title="Live company profile and attendance schedule",
                source_type="live_company",
                company_id=company_id,
                role_scope=live_scope,
                text=(
                    f"Company name: {company.name}. Company code: {company.code}. "
                    f"Company active: {'Yes' if company.is_active else 'No'}. "
                    f"Regular workdays: {', '.join(workdays) or 'None configured'}. "
                    f"Regular hours per workday: {company.attendance_regular_hours}. "
                    f"Lunch break: {company.attendance_lunch_minutes} minutes. "
                    f"OT dinner-break deduction: {company.ot_dinner_break_deduction_hours} hours. "
                    f"Shifting Credits enabled: {'Yes' if company.shifting_credits_enabled else 'No'}. "
                    f"Shifting-credit block: {company.shifting_credit_block_hours} hours; "
                    f"required blocks per cut-off: {company.shifting_credit_required_blocks}; "
                    f"first cut-off end day: {company.shifting_credit_cutoff_day}; "
                    f"availability delay: {company.shifting_credit_availability_cutoffs} completed cut-offs; "
                    f"expiration basis: {company.shifting_credit_expiration_mode}; "
                    f"custom expiration date: {company.shifting_credit_expiration_month}/"
                    f"{company.shifting_credit_expiration_day}. "
                    f"Additional VL qualifying OT: "
                    f"{company.shifting_credit_additional_vl_threshold_hours} hours; "
                    f"additional VL: {company.shifting_credit_additional_vl_days} days; "
                    f"straight-OT VL also remains OT payable: "
                    f"{'Yes' if company.shifting_credit_additional_vl_also_payable else 'No'}. "
                    f"Shifting-credit excluded positions: "
                    f"{excluded_positions_text}."
                ),
            )

        employee_query = select(Employee).where(Employee.company_id == company_id)
        if not is_admin:
            if employee_id is None:
                employee_query = employee_query.where(Employee.id == -1)
            else:
                employee_query = employee_query.where(Employee.id == employee_id)
        employees = self.session.scalars(
            employee_query.order_by(Employee.employee_number).limit(1000)
        ).unique().all()
        for employee in employees:
            department = employee.department.name if employee.department else "Not assigned"
            manager = employee.manager.full_name if employee.manager else "Not assigned"
            leader = employee.leader.full_name if employee.leader else "Not assigned"
            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:employee:{employee.id}",
                title=f"Live employee record — {employee.full_name}",
                source_type="live_employee",
                company_id=company_id,
                role_scope=live_scope,
                text=(
                    f"Employee: {employee.full_name}. Employee number: {employee.employee_number}. "
                    f"Department: {department}. Job title: {employee.job_title or 'Not specified'}. "
                    f"Manager: {manager}. Leader: {leader}. Work email: {employee.work_email or 'Not specified'}. "
                    f"Employment status: {employee.employment_status}. "
                    f"Hire date: {employee.hire_date.isoformat() if employee.hire_date else 'Not specified'}."
                ),
                metadata={
                    "employee_id": employee.id,
                    "employee_number": employee.employee_number,
                    "title": employee.full_name,
                },
            )

        account_query = select(User).where(User.company_id == company_id)
        if not is_admin:
            account_query = account_query.where(User.id == current_user.user_id)
        accounts = self.session.scalars(
            account_query.order_by(User.username).limit(1000)
        ).unique().all()
        for account in accounts:
            linked_employee = account.employee
            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:account:{account.id}",
                title=f"Live user account — {account.username}",
                source_type="live_account",
                company_id=company_id,
                role_scope=live_scope,
                text=(
                    f"Username: {account.username}. Account email: {account.email}. "
                    f"Access: {'Admin' if int(account.clearance) == 1 else 'User'}. "
                    f"Account active: {'Yes' if account.is_active else 'No'}. "
                    f"Linked employee: {linked_employee.full_name if linked_employee else 'Not linked'}."
                ),
                metadata={"user_id": account.id, "title": account.username},
            )

        balance_query = select(LeaveBalance).where(LeaveBalance.company_id == company_id)
        if not is_admin:
            balance_query = balance_query.where(LeaveBalance.employee_id == (employee_id or -1))
        balances = self.session.scalars(
            balance_query.order_by(LeaveBalance.year.desc(), LeaveBalance.id.desc()).limit(1000)
        ).unique().all()
        for balance in balances:
            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:leave-balance:{balance.id}",
                title=f"Live leave credits — {balance.employee.full_name} — {balance.leave_type.name} {balance.year}",
                source_type="live_leave_balance",
                company_id=company_id,
                role_scope=live_scope,
                text=(
                    f"Employee: {balance.employee.full_name}. Employee number: {balance.employee.employee_number}. "
                    f"Leave type: {balance.leave_type.name} ({balance.leave_type.code}). Year: {balance.year}. "
                    f"Beginning credit: {balance.beginning_credit_days} days. Credit: {balance.credit_days} days. "
                    f"Adjustment: {balance.adjustment_days} days. Used: {balance.used_days} days. "
                    f"Reserved: {balance.reserved_days} days. Converted to cash: {balance.converted_to_cash_days} days. "
                    f"Available credits: {balance.available_credits} days."
                ),
                metadata={
                    "employee_id": balance.employee_id,
                    "leave_type": balance.leave_type.name,
                    "year": balance.year,
                },
            )

        request_query = select(LeaveRequest).where(LeaveRequest.company_id == company_id)
        if not is_admin:
            request_query = request_query.where(LeaveRequest.employee_id == (employee_id or -1))
        leave_requests = self.session.scalars(
            request_query.order_by(LeaveRequest.submitted_at.desc(), LeaveRequest.id.desc()).limit(500)
        ).unique().all()
        for leave_request in leave_requests:
            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:leave-request:{leave_request.id}",
                title=f"Live leave request — {leave_request.public_id or leave_request.id}",
                source_type="live_leave_request",
                company_id=company_id,
                role_scope=live_scope,
                text=(
                    f"Leave request ID: {leave_request.public_id or leave_request.id}. "
                    f"Employee: {leave_request.employee.full_name}. Leave type: {leave_request.leave_type.name}. "
                    f"Start date: {leave_request.start_date.isoformat()}. End date: {leave_request.end_date.isoformat()}. "
                    f"Requested days: {leave_request.requested_days}. Status: {leave_request.status}. "
                    f"Duration code: {leave_request.duration_code}. Reason code: {leave_request.reason_code}. "
                    f"Reason for Leave Others: {leave_request.reason_other or 'Not applicable'}. "
                    f"Filed by: {leave_request.filed_by_employee.full_name if leave_request.filed_by_employee else leave_request.employee.full_name}. "
                    f"Approval stage: {leave_request.approval_stage}. "
                    f"Cancellation status: {leave_request.cancellation_status}."
                ),
                metadata={
                    "leave_request_id": leave_request.id,
                    "public_id": leave_request.public_id,
                    "employee_id": leave_request.employee_id,
                },
            )

        attendance_query = select(AttendanceRecord).where(AttendanceRecord.company_id == company_id)
        if not is_admin:
            attendance_query = attendance_query.where(AttendanceRecord.employee_id == (employee_id or -1))
        attendance_records = self.session.scalars(
            attendance_query.order_by(AttendanceRecord.attendance_date.desc(), AttendanceRecord.id.desc()).limit(500)
        ).unique().all()
        for record in attendance_records:
            session_summary = "; ".join(
                f"{item.work_status} actual {item.actual_time_in.isoformat()} to "
                f"{item.actual_time_out.isoformat() if item.actual_time_out else 'OPEN'}, "
                f"rounded {item.rounded_time_in.isoformat()} to "
                f"{item.rounded_time_out.isoformat() if item.rounded_time_out else 'OPEN'}"
                for item in record.sessions
            ) or "No work sessions"
            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:attendance:{record.id}",
                title=f"Live attendance — {record.employee.full_name} — {record.attendance_date.isoformat()}",
                source_type="live_attendance",
                company_id=company_id,
                role_scope=live_scope,
                text=(
                    f"Employee: {record.employee.full_name}. Attendance date: {record.attendance_date.isoformat()}. "
                    f"Work status: {record.work_status or 'Not set'}. "
                    f"Time In: {record.time_in.isoformat() if record.time_in else 'Not set'}. "
                    f"Time Out: {record.time_out.isoformat() if record.time_out else 'Not set'}. "
                    f"Total hours: {record.total_hours}. Overtime hours: {record.ot_hours}. "
                    f"Leave duration code: {record.leave_duration_code or 'None'}. "
                    f"Leave hours: {record.leave_hours}. Undertime hours: {record.undertime_hours}. "
                    f"Sessions: {session_summary}. "
                    f"Status source: {record.status_source}."
                ),
                metadata={
                    "employee_id": record.employee_id,
                    "attendance_date": record.attendance_date.isoformat(),
                },
            )

        overtime_query = select(OvertimeRequest).where(
            OvertimeRequest.company_id == company_id
        )
        if not is_admin:
            overtime_query = overtime_query.where(
                OvertimeRequest.employee_id == (employee_id or -1)
            )
        overtime_requests = self.session.scalars(
            overtime_query.order_by(
                OvertimeRequest.submitted_at.desc(),
                OvertimeRequest.id.desc(),
            ).limit(500)
        ).unique().all()
        for overtime_request in overtime_requests:
            self._add_document(
                documents,
                document_id=(
                    f"company:{company_id}:live:overtime-request:"
                    f"{overtime_request.id}"
                ),
                title=f"Live overtime request — {overtime_request.public_id}",
                source_type="live_overtime_request",
                company_id=company_id,
                role_scope=live_scope,
                text=(
                    f"Overtime request ID: {overtime_request.public_id}. "
                    f"Employee: {overtime_request.employee.full_name}. "
                    f"Date rendered: {overtime_request.date_rendered.isoformat()}. "
                    f"OT type: {overtime_request.ot_type}. Purpose: "
                    f"{overtime_request.ot_purpose}. Submitted estimated hours: "
                    f"{overtime_request.estimated_hours}. DTR detected hours: "
                    f"{overtime_request.dtr_estimated_hours}. DTR mismatch: "
                    f"{'Yes' if overtime_request.has_dtr_mismatch else 'No'}. "
                    f"Travel fare: {overtime_request.travel_fare or 'None'}. "
                    f"Travel route: {overtime_request.travel_route or 'None'}. "
                    f"Dinner break: "
                    f"{'Yes' if overtime_request.dinner_break_flag else 'No'}. "
                    f"Status: {overtime_request.status}. Reviewer comment: "
                    f"{overtime_request.reviewer_comment or 'None'}."
                ),
                metadata={
                    "overtime_request_id": overtime_request.id,
                    "public_id": overtime_request.public_id,
                    "employee_id": overtime_request.employee_id,
                    "date_rendered": overtime_request.date_rendered.isoformat(),
                },
            )

        now = datetime.now(timezone.utc)
        announcement_query = select(Announcement).where(Announcement.company_id == company_id)
        if not is_admin:
            announcement_query = announcement_query.where(
                Announcement.status == "published",
                or_(Announcement.publish_at.is_(None), Announcement.publish_at <= now),
                or_(Announcement.expires_at.is_(None), Announcement.expires_at >= now),
            )
        announcements = self.session.scalars(
            announcement_query.order_by(Announcement.publish_at.desc(), Announcement.id.desc()).limit(250)
        ).all()
        for announcement in announcements:
            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:announcement:{announcement.id}",
                title=f"Live announcement — {announcement.title}",
                source_type="live_announcement",
                company_id=company_id,
                role_scope="admin" if is_admin else "shared",
                text=(
                    f"Announcement ID: {announcement.public_id or announcement.id}. Title: {announcement.title}. "
                    f"Category: {announcement.category}. Summary: {announcement.summary}. "
                    f"Description: {announcement.content}. Status: {announcement.status}. "
                    f"Publish date: {announcement.publish_at.isoformat() if announcement.publish_at else 'Not specified'}. "
                    f"Expiry: {announcement.expires_at.isoformat() if announcement.expires_at else 'No expiry'}."
                ),
                metadata={"announcement_id": announcement.id, "title": announcement.title},
            )

        form_query = select(CompanyForm).where(CompanyForm.company_id == company_id)
        if not is_admin:
            form_query = form_query.where(
                CompanyForm.status == "active",
                CompanyForm.trashed_at.is_(None),
            )
        forms = self.session.scalars(
            form_query.order_by(CompanyForm.title).limit(250)
        ).all()
        for form in forms:
            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:company-form:{form.id}",
                title=f"Live company form — {form.title}",
                source_type="live_company_form",
                company_id=company_id,
                role_scope="admin" if is_admin else "shared",
                text=(
                    f"Company form ID: {form.public_id}. Title: {form.title}. Category: {form.category}. "
                    f"Description: {form.description or 'No description'}. Status: {form.status}. "
                    f"Filename: {form.original_filename}. Employee submission allowed: "
                    f"{'Yes' if form.allow_employee_submission else 'No'}."
                ),
                metadata={"company_form_id": form.id, "title": form.title},
            )

            # Active Company Form/Documents files contribute their actual
            # readable content to company knowledge. This lets a natural
            # question search the document body, not only title/filename
            # metadata. Unsupported/old binary formats remain metadata-only.
            if form.status == "active" and form.trashed_at is None:
                extracted_form_text = self.company_form_extractor.extract(form)
                if extracted_form_text:
                    file_key = f"company-form:{form.id}"
                    raw_sections = [
                        (section_label, section_text, None)
                        for section_label, section_text in _document_sections(extracted_form_text)
                    ]
                    prepared_chunks = _prepare_document_chunks(
                        raw_sections,
                        chunk_size=int(self.settings.company_document_chunk_size),
                        overlap=int(self.settings.company_document_chunk_overlap),
                    )
                    total_chunks = len(prepared_chunks)
                    for chunk_index, (section_label, chunk, section_page) in enumerate(
                        prepared_chunks, start=1
                    ):
                        contextual_chunk = (
                            f"Document: {form.title}. File: {form.original_filename}. "
                            f"Section: {section_label}. {chunk}"
                        )
                        self._add_document(
                            documents,
                            document_id=(
                                f"company:{company_id}:company-form-content:"
                                f"{form.id}:{chunk_index}"
                            ),
                            title=f"{form.title} — {section_label}",
                            source_type="company_form_content",
                            company_id=company_id,
                            role_scope="admin" if is_admin else "shared",
                            text=contextual_chunk,
                            metadata={
                                "company_form_id": form.id,
                                "file_key": file_key,
                                "title": form.title,
                                "filename": form.original_filename,
                                "section": section_label,
                                "page_number": (
                                    section_page
                                    if section_page is not None
                                    else (
                                        int(page_match.group(1))
                                        if (
                                            page_match := re.match(
                                                r"^Page\s+(\d+)(?:\s+[—-]\s+.*)?$",
                                                section_label,
                                                re.I,
                                            )
                                        )
                                        else None
                                    )
                                ),
                                "chunk_index": chunk_index,
                                "total_chunks": total_chunks,
                            },
                        )

        submission_query = select(CompanyFormSubmission).where(
            CompanyFormSubmission.company_id == company_id
        )
        if not is_admin:
            submission_query = submission_query.where(
                CompanyFormSubmission.employee_id == (employee_id or -1)
            )
        submissions = self.session.scalars(
            submission_query.order_by(
                CompanyFormSubmission.created_at.desc(),
                CompanyFormSubmission.id.desc(),
            ).limit(500)
        ).unique().all()
        for submission in submissions:
            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:form-submission:{submission.id}",
                title=f"Live form submission — {submission.public_id}",
                source_type="live_company_form_submission",
                company_id=company_id,
                role_scope=live_scope,
                text=(
                    f"Submission ID: {submission.public_id}. Form: {submission.form.title}. "
                    f"Employee: {submission.employee.full_name}. Status: {submission.status}. "
                    f"Submitted filename: {submission.original_filename}. "
                    f"Employee notes: {submission.notes or 'None'}. "
                    f"Admin note: {submission.admin_note or 'None'}. "
                    f"Reviewed at: {submission.reviewed_at.isoformat() if submission.reviewed_at else 'Not reviewed'}."
                ),
                metadata={
                    "submission_id": submission.id,
                    "employee_id": submission.employee_id,
                    "company_form_id": submission.form_id,
                },
            )

        training_query = select(EmployeeTraining).where(
            EmployeeTraining.company_id == company_id
        )
        if not is_admin:
            training_query = training_query.where(
                EmployeeTraining.employee_id == (employee_id or -1)
            )
        trainings = self.session.scalars(
            training_query.order_by(
                EmployeeTraining.employee_id,
                EmployeeTraining.display_order,
                EmployeeTraining.id,
            ).limit(1000)
        ).unique().all()
        for training in trainings:
            self._add_document(
                documents,
                document_id=f"company:{company_id}:live:training:{training.id}",
                title=f"Live employee training — {training.employee.full_name} — {training.title}",
                source_type="live_employee_training",
                company_id=company_id,
                role_scope=live_scope,
                text=(
                    f"Employee: {training.employee.full_name}. Training: {training.title}. "
                    f"Completed: {'Yes' if training.is_completed else 'No'}."
                ),
                metadata={
                    "employee_id": training.employee_id,
                    "training_id": training.id,
                    "title": training.title,
                },
            )

        if is_admin:
            reminders = self.session.scalars(
                select(EventReminder).where(
                    EventReminder.company_id == company_id
                ).order_by(
                    EventReminder.event_start_at.desc(),
                    EventReminder.id.desc(),
                ).limit(250)
            ).all()
            for reminder in reminders:
                self._add_document(
                    documents,
                    document_id=f"company:{company_id}:live:event-reminder:{reminder.id}",
                    title=f"Live event reminder — {reminder.title}",
                    source_type="live_event_reminder",
                    company_id=company_id,
                    role_scope="admin",
                    text=(
                        f"Reminder ID: {reminder.public_id or reminder.id}. Title: {reminder.title}. "
                        f"Category: {reminder.category}. Notes: {reminder.notes or 'None'}. "
                        f"Event starts: {reminder.event_start_at.isoformat()}. "
                        f"Event ends: {reminder.event_end_at.isoformat() if reminder.event_end_at else 'Not specified'}. "
                        f"Status: {reminder.status}."
                    ),
                    metadata={"reminder_id": reminder.id, "title": reminder.title},
                )

    def build(
        self,
        *,
        current_user: AuthenticatedUser,
        role_scope: str,
    ) -> list[KnowledgeDocument]:
        company_id = current_user.company_id
        documents: list[KnowledgeDocument] = []
        guide_groups = ["shared", role_scope]
        for group in guide_groups:
            for index, (title, text) in enumerate(_PORTAL_GUIDES[group], start=1):
                documents.append(KnowledgeDocument(
                    document_id=f"company:{company_id}:portal:{group}:{index}",
                    text=text,
                    title=title,
                    source_type="portal_guide",
                    company_id=company_id,
                    role_scope=group,
                    metadata={"title": title, "group": group},
                ))

        self._add_live_company_records(
            documents,
            current_user=current_user,
            role_scope=role_scope,
        )

        violation_service = PolicyViolationService(self.session)
        violation_date = datetime.now(
            ZoneInfo(get_settings().display_timezone)
        ).date()
        for violation in violation_service.list_employee_visible(
            company_id=company_id,
            as_of_date=violation_date,
        ):
            related_policy = violation_service.related_policy_label(
                company_id=company_id,
                violation=violation,
            )
            self._add_document(
                documents,
                document_id=(
                    f"company:{company_id}:policy-violation:{violation.id}"
                ),
                title=(
                    f"{violation.violation_code} — {violation.offense_title}"
                ),
                source_type="policy_violation",
                company_id=company_id,
                role_scope="shared",
                text=(
                    f"Violation code: {violation.violation_code}. "
                    f"Violation / offense: {violation.offense_title}. "
                    f"Category: {violation.category}. Severity: {violation.severity}. "
                    f"Description: {violation.description}. "
                    f"1st offense action: {violation.first_offense_action}. "
                    f"2nd offense action: {violation.second_offense_action}. "
                    f"3rd offense action: {violation.third_offense_action}. "
                    f"Final / maximum action: {violation.final_action}. "
                    f"Related policy: {related_policy}. "
                    f"Effective date: "
                    f"{violation.effective_date.isoformat() if violation.effective_date else 'Immediate'}."
                ),
                metadata={
                    "violation_id": violation.id,
                    "violation_code": violation.violation_code,
                    "severity": violation.severity,
                    "category": violation.category,
                    "related_policy_id": violation.related_policy_id,
                },
            )

        rows = PolicySectionRepository(self.session).list_searchable(
            company_id=company_id,
            as_of_date=datetime.now(
                ZoneInfo(get_settings().display_timezone)
            ).date(),
        )
        policy_files: dict[
            tuple[int, int],
            list[tuple[object, object, object]],
        ] = defaultdict(list)
        for policy, document, section in rows:
            policy_files[(int(policy.id), int(document.id))].append(
                (policy, document, section)
            )

        for grouped_rows in policy_files.values():
            policy = grouped_rows[0][0]
            document = grouped_rows[0][1]
            file_key = f"policy:{policy.id}:document:{document.id}"
            prepared_chunks = _prepare_document_chunks(
                [
                    (
                        str(section.heading or "Policy Details"),
                        str(section.text or ""),
                        section.page_number,
                    )
                    for _policy, _document, section in grouped_rows
                ],
                chunk_size=int(self.settings.policy_chunk_size),
                overlap=int(self.settings.policy_chunk_overlap),
            )
            total_chunks = len(prepared_chunks)
            for chunk_index, (section_label, chunk, page_number) in enumerate(
                prepared_chunks, start=1
            ):
                contextual_chunk = (
                    f"Policy: {policy.title}. Version: {policy.version}. "
                    f"Section: {section_label}. {chunk}"
                )
                documents.append(KnowledgeDocument(
                    document_id=(
                        f"company:{company_id}:policy:{policy.id}:"
                        f"{document.id}:{chunk_index}"
                    ),
                    text=contextual_chunk,
                    title=f"{policy.title} — {section_label}",
                    source_type="policy",
                    company_id=company_id,
                    role_scope="shared",
                    metadata={
                        "policy_id": policy.id,
                        "policy_document_id": document.id,
                        "file_key": file_key,
                        "title": policy.title,
                        "section": section_label,
                        "version": policy.version,
                        "filename": document.original_filename,
                        "page_number": page_number,
                        "chunk_index": chunk_index,
                        "total_chunks": total_chunks,
                    },
                ))
        return documents


class BM25Retriever:
    """Small dependency-free BM25 implementation used by every installation."""

    def search(self, query: str, documents: list[KnowledgeDocument], top_k: int) -> list[RetrievedDocument]:
        if not documents:
            return []
        query_terms = _tokenize(query)
        if not query_terms:
            return []
        tokenized = [_tokenize(doc.text + " " + doc.title) for doc in documents]
        n = len(tokenized)
        avgdl = sum(len(tokens) for tokens in tokenized) / max(n, 1)
        df: dict[str, int] = {}
        for tokens in tokenized:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1
        k1, b = 1.5, 0.75
        scored: list[RetrievedDocument] = []
        for doc, tokens in zip(documents, tokenized):
            frequencies: dict[str, int] = {}
            for token in tokens:
                frequencies[token] = frequencies.get(token, 0) + 1
            score = 0.0
            dl = len(tokens)
            for term in query_terms:
                tf = frequencies.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
                score += idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(avgdl, 1))))
            if score > 0:
                scored.append(RetrievedDocument(doc, score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]


class ChromaRetriever:
    """Optional Chroma + lightweight multilingual-e5 vector retrieval.

    Each query is restricted to the exact authorized document-set signature
    that was indexed for the current request.  This prevents stale vectors from
    another company/role/session snapshot from consuming result slots.
    """

    _indexed_signatures: set[str] = set()

    def __init__(self, *, collection_suffix: str = "") -> None:
        self.settings = get_chat_assistant_settings()
        self.collection_suffix = collection_suffix
        self._embedding_model = None

    def _model(self):
        if self._embedding_model is None:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer(self.settings.embedding_model)
        return self._embedding_model

    @staticmethod
    def _signature(documents: list[KnowledgeDocument]) -> str:
        payload = "|".join(
            f"{doc.document_id}:{hashlib.sha1(doc.text.encode('utf-8')).hexdigest()}"
            for doc in documents
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def search(
        self,
        query: str,
        documents: list[KnowledgeDocument],
        top_k: int,
        *,
        access_partition: str | None = None,
    ) -> list[RetrievedDocument]:
        _disable_chroma_product_telemetry()
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except Exception:
            return []
        if not documents:
            return []
        try:
            client = chromadb.PersistentClient(
                path=self.settings.chroma_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            collection = client.get_or_create_collection(
                name=f"{self.settings.chroma_collection}{self.collection_suffix}",
                metadata={"hnsw:space": "cosine"},
            )
            model = self._model()
            signature = self._signature(documents)
            if access_partition is None:
                company = documents[0].company_id
                roles = ",".join(sorted({doc.role_scope for doc in documents}))
                access_partition = f"company:{company}:roles:{roles}"
            partition_hash = hashlib.sha1(
                access_partition.encode("utf-8")
            ).hexdigest()[:16]
            retrieval_scope = f"{partition_hash}:{signature}"
            vector_ids = [
                f"{partition_hash}:{doc.document_id}" for doc in documents
            ]
            cache_key = f"{collection.name}:{retrieval_scope}"
            if cache_key not in self._indexed_signatures:
                texts = [f"passage: {doc.text}" for doc in documents]
                embeddings = model.encode(texts, normalize_embeddings=True).tolist()
                metadatas = [
                    {
                        "company_id": doc.company_id,
                        "role_scope": doc.role_scope,
                        "title": doc.title,
                        "source_type": doc.source_type,
                        "retrieval_signature": signature,
                        "retrieval_scope": retrieval_scope,
                        "payload": json.dumps(doc.metadata, default=str),
                    }
                    for doc in documents
                ]
                collection.upsert(
                    ids=vector_ids,
                    documents=[doc.text for doc in documents],
                    embeddings=embeddings,
                    metadatas=metadatas,
                )
                self._indexed_signatures.add(cache_key)
            query_embedding = model.encode(
                [f"query: {query}"], normalize_embeddings=True
            ).tolist()
            result = collection.query(
                query_embeddings=query_embedding,
                n_results=min(max(1, int(top_k)), len(documents)),
                where={"retrieval_scope": retrieval_scope},
            )
            lookup = {
                vector_id: doc
                for vector_id, doc in zip(vector_ids, documents)
            }
            output: list[RetrievedDocument] = []
            result_ids = result.get("ids") or [[]]
            result_distances = result.get("distances") or [[]]
            for doc_id, distance in zip(result_ids[0], result_distances[0]):
                doc = lookup.get(doc_id)
                if doc is not None:
                    output.append(
                        RetrievedDocument(doc, max(0.0, 1.0 - float(distance)))
                    )
            return output
        except Exception:
            return []


class HybridRetriever:
    """Company/role-safe, file-aware hybrid retrieval.

    Long policy and Company Form/Documents content is retrieved hierarchically:
    first rank the most relevant source files, then rank chunks only inside
    those files alongside live structured HR records.  Final seed diversity
    prevents one large file from monopolizing the context, and adjacent chunks
    from the same section can be added when a rule crosses a chunk boundary.
    """

    def __init__(self) -> None:
        self.settings = get_chat_assistant_settings()
        self.bm25 = BM25Retriever()
        self.vector = ChromaRetriever()
        self.file_vector = ChromaRetriever(collection_suffix="_files")

    def _merge_rrf(
        self,
        bm25: list[RetrievedDocument],
        vector: list[RetrievedDocument],
    ) -> list[RetrievedDocument]:
        merged: dict[str, tuple[KnowledgeDocument, float]] = {}
        rrf_k = int(self.settings.reciprocal_rank_constant)
        for rank, item in enumerate(bm25, start=1):
            previous = merged.get(item.document.document_id, (item.document, 0.0))[1]
            merged[item.document.document_id] = (
                item.document,
                previous + 1.0 / (rrf_k + rank),
            )
        for rank, item in enumerate(vector, start=1):
            previous = merged.get(item.document.document_id, (item.document, 0.0))[1]
            merged[item.document.document_id] = (
                item.document,
                previous + 1.0 / (rrf_k + rank),
            )
        output = [RetrievedDocument(doc, score) for doc, score in merged.values()]
        output.sort(key=lambda item: item.score, reverse=True)
        return output

    @staticmethod
    def _rerank_for_answerability(
        query: str,
        candidates: list[RetrievedDocument],
    ) -> list[RetrievedDocument]:
        """Favor concise evidence that can answer the requested fact type.

        RRF remains the primary rank.  This bounded lexical/answer-shape bonus
        only resolves close candidates and is dependency-free, so the same
        behavior is available even when Chroma/reranker packages are absent.
        """

        adjusted = [
            RetrievedDocument(
                item.document,
                item.score + (0.012 * _evidence_fit_bonus(query, item.document)),
            )
            for item in candidates
        ]
        adjusted.sort(key=lambda item: item.score, reverse=True)
        return adjusted

    def _selected_file_representatives(
        self,
        query: str,
        selected_chunks: list[KnowledgeDocument],
    ) -> list[RetrievedDocument]:
        """Keep a small number of strong representatives from selected files.

        The second-stage global BM25 list can be monopolized by a long file that
        repeats the user's terms many times.  File-stage selection may still have
        correctly identified another concise policy, but without a representative
        from that file none of its evidence can reach the final diversification
        step.  Preserve only the strongest answer-shaped chunk from the best few
        selected files; this is intentionally small so weak files do not crowd out
        the main evidence.
        """

        limit = max(0, int(self.settings.evidence_file_representatives))
        if limit <= 0 or not selected_chunks:
            return []

        grouped: dict[str, list[KnowledgeDocument]] = defaultdict(list)
        for document in selected_chunks:
            key = _file_key(document)
            if key:
                grouped[key].append(document)

        representatives: list[tuple[float, KnowledgeDocument]] = []
        for file_documents in grouped.values():
            best = max(
                file_documents,
                key=lambda document: _evidence_fit_bonus(query, document),
            )
            fit = _evidence_fit_bonus(query, best)
            representatives.append((fit, best))

        representatives.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievedDocument(document, 0.014 + (0.012 * fit))
            for fit, document in representatives[:limit]
        ]

    @staticmethod
    def _scope_documents(
        documents: list[KnowledgeDocument],
        *,
        company_id: int | None,
        role_scope: str | None,
    ) -> list[KnowledgeDocument]:
        """Fail closed to the current tenant/role when caller supplies scope."""

        allowed_roles = {"shared"}
        if role_scope:
            allowed_roles.add(role_scope)
        return [
            doc
            for doc in documents
            if (company_id is None or int(doc.company_id) == int(company_id))
            and (role_scope is None or doc.role_scope in allowed_roles)
        ]

    def _select_file_keys(
        self,
        query: str,
        file_chunks: list[KnowledgeDocument],
        *,
        access_partition: str,
        trace: TerminalChatTrace | None = None,
    ) -> tuple[set[str], dict[str, list[KnowledgeDocument]]]:
        """Rank whole files by aggregating their strongest chunk evidence.

        Scoring all chunks at this first stage means a rule near the end of a
        long file can still make that file relevant; the second stage then
        searches only the selected files in detail.
        """

        grouped: dict[str, list[KnowledgeDocument]] = defaultdict(list)
        for doc in file_chunks:
            key = _file_key(doc)
            if key:
                grouped[key].append(doc)
        if trace is not None:
            trace.counts(files_searched=len(grouped))
        if not grouped:
            return set(), grouped

        pre_k = min(
            len(file_chunks),
            max(
                int(self.settings.file_candidate_k) * 4,
                int(self.settings.file_top_k)
                * int(self.settings.max_chunks_per_file)
                * 4,
            ),
        )
        bm25 = self.bm25.search(query, file_chunks, pre_k)
        vector = self.file_vector.search(
            query,
            file_chunks,
            pre_k,
            access_partition=f"{access_partition}:file-stage",
        )
        if trace is not None:
            trace.candidates(
                "FILE STAGE — BM25", bm25, score_label="bm25", show_excerpt=False
            )
            trace.candidates(
                "FILE STAGE — VECTOR NEAREST (cosine similarity)",
                vector,
                score_label="cosine",
                show_excerpt=False,
            )
        ranked_chunks = self._rerank_for_answerability(
            query, self._merge_rrf(bm25, vector)
        )
        if trace is not None:
            trace.candidates(
                "FILE STAGE — HYBRID RRF + ANSWER FIT",
                ranked_chunks,
                score_label="hybrid",
                show_excerpt=False,
            )
        if not ranked_chunks:
            selected_all = set(grouped)
            if trace is not None:
                trace.selected_files(selected_all, grouped)
            return selected_all, grouped

        per_file_evidence = max(1, int(self.settings.max_chunks_per_file))
        file_evidence: dict[str, list[float]] = defaultdict(list)
        for rank, item in enumerate(ranked_chunks, start=1):
            key = _file_key(item.document)
            if not key or len(file_evidence[key]) >= per_file_evidence:
                continue
            # RRF already includes rank information; keep that signal intact
            # instead of adding another rank term that can over-reward a file
            # simply for producing many nearby candidates.
            file_evidence[key].append(item.score)

        # The strongest matching chunk should decide most of a file's rank.
        # Extra supporting chunks help, but with diminishing weight so a very
        # long document cannot beat a concise exact-match file merely because
        # it produced more medium-strength hits.
        support_weights = (1.0, 0.005, 0.002)
        file_scores = {
            key: sum(
                score * (support_weights[index] if index < len(support_weights) else 0.001)
                for index, score in enumerate(scores)
            )
            for key, scores in file_evidence.items()
        }

        selected = {
            key
            for key, _score in sorted(
                file_scores.items(), key=lambda item: item[1], reverse=True
            )[:int(self.settings.file_top_k)]
        }
        selected = selected or set(grouped)
        if trace is not None:
            matched_chunk_counts: dict[str, int] = defaultdict(int)
            best_chunks: dict[str, str] = {}
            for item in ranked_chunks:
                key = _file_key(item.document)
                if key:
                    matched_chunk_counts[key] += 1
                    if key not in best_chunks:
                        metadata = item.document.metadata or {}
                        best_chunks[key] = (
                            f"{metadata.get('chunk_index') or '-'}/"
                            f"{metadata.get('total_chunks') or '-'}"
                        )
            trace.file_ranking(
                file_scores=file_scores,
                grouped=grouped,
                selected_keys=selected,
                matched_chunk_counts=matched_chunk_counts,
                best_chunks=best_chunks,
            )
            trace.selected_files(selected, grouped)
        return selected, grouped

    def _diversify_seeds(
        self,
        candidates: list[RetrievedDocument],
        *,
        limit: int | None = None,
    ) -> list[RetrievedDocument]:
        """Select the strongest balanced evidence without forcing file variety.

        A previous diversity-first pass could inject several weaker policies just
        because they came from different files.  Cross-file recall is now handled
        explicitly by ``_selected_file_representatives``; this step therefore
        respects score order and only caps how many chunks one file can consume.
        """

        target = max(1, int(limit or self.settings.final_top_k))
        per_file = max(1, int(self.settings.max_chunks_per_file))
        file_counts: dict[str, int] = defaultdict(int)
        selected: list[RetrievedDocument] = []

        for item in candidates:
            key = _file_key(item.document)
            if key and file_counts[key] >= per_file:
                continue
            selected.append(item)
            if key:
                file_counts[key] += 1
            if len(selected) >= target:
                break
        return selected

    def _expand_neighbors(
        self,
        seeds: list[RetrievedDocument],
        grouped: dict[str, list[KnowledgeDocument]],
        *,
        fallback_candidates: list[RetrievedDocument] | None = None,
    ) -> list[RetrievedDocument]:
        window = max(0, int(self.settings.neighbor_chunk_window))
        output: list[RetrievedDocument] = list(seeds)
        seen = {item.document.document_id for item in output}
        max_results = max(1, int(self.settings.final_top_k))

        if window and seeds and len(output) < max_results:
            for seed in seeds:
                key = _file_key(seed.document)
                if not key or key not in grouped:
                    continue
                seed_index = int(seed.document.metadata.get("chunk_index") or 0)
                seed_section = str(seed.document.metadata.get("section") or "")
                for distance in range(1, window + 1):
                    for target_index in (seed_index - distance, seed_index + distance):
                        for neighbor in grouped[key]:
                            if neighbor.document_id in seen:
                                continue
                            if int(neighbor.metadata.get("chunk_index") or 0) != target_index:
                                continue
                            neighbor_section = str(neighbor.metadata.get("section") or "")
                            if (
                                seed_section
                                and neighbor_section
                                and neighbor_section != seed_section
                            ):
                                continue
                            output.append(
                                RetrievedDocument(
                                    neighbor,
                                    max(0.0, seed.score - (distance * 0.0001)),
                                )
                            )
                            seen.add(neighbor.document_id)
                            break
                        if len(output) >= max_results:
                            return output

        # If no useful adjacent chunk exists, do not waste the reserved slot.
        # Fill it with the next strong independent candidate instead.
        for item in fallback_candidates or []:
            if item.document.document_id in seen:
                continue
            output.append(item)
            seen.add(item.document.document_id)
            if len(output) >= max_results:
                break
        return output[:max_results]

    def search(
        self,
        query: str,
        documents: list[KnowledgeDocument],
        *,
        company_id: int | None = None,
        role_scope: str | None = None,
        access_partition: str | None = None,
        trace: TerminalChatTrace | None = None,
    ) -> list[RetrievedDocument]:
        scoped = self._scope_documents(
            documents,
            company_id=company_id,
            role_scope=role_scope,
        )
        if trace is not None:
            trace.counts(
                authorized_documents=len(scoped),
                total_built_documents=len(documents),
            )
        if not scoped:
            if trace is not None:
                trace.line("RETRIEVAL", "No authorized knowledge documents available.")
            return []

        if access_partition is None:
            role_label = role_scope or "unspecified"
            access_partition = f"company:{company_id or 'unknown'}:role:{role_label}"

        file_chunks = [doc for doc in scoped if _file_key(doc)]
        structured = [doc for doc in scoped if not _file_key(doc)]
        if trace is not None:
            trace.counts(
                file_chunks=len(file_chunks),
                structured_records=len(structured),
            )
        selected_file_keys, grouped = self._select_file_keys(
            query,
            file_chunks,
            access_partition=access_partition,
            trace=trace,
        )
        selected_chunks = [
            doc for doc in file_chunks if _file_key(doc) in selected_file_keys
        ]
        search_space = structured + selected_chunks
        if trace is not None:
            trace.counts(
                selected_file_chunks=len(selected_chunks),
                chunk_stage_search_space=len(search_space),
            )
        if not search_space:
            if trace is not None:
                trace.line("RETRIEVAL", "Selected search space is empty.")
            return []

        bm25 = self.bm25.search(
            query, search_space, int(self.settings.bm25_top_k)
        )
        # Keep the semantic index on the stable authorized document snapshot
        # rather than re-indexing a query-specific subset on every question.
        vector_pool = self.vector.search(
            query,
            scoped,
            min(
                len(scoped),
                max(int(self.settings.vector_top_k) * 4, 24),
            ),
            access_partition=f"{access_partition}:all-stage",
        )
        allowed_ids = {doc.document_id for doc in search_space}
        vector = [
            item for item in vector_pool
            if item.document.document_id in allowed_ids
        ][:int(self.settings.vector_top_k)]
        if trace is not None:
            trace.candidates(
                "CHUNK STAGE — BM25", bm25, score_label="bm25"
            )
            trace.candidates(
                "CHUNK STAGE — VECTOR NEAREST (cosine similarity)",
                vector,
                score_label="cosine",
            )
        candidates = self._rerank_for_answerability(
            query, self._merge_rrf(bm25, vector)
        )
        if trace is not None:
            trace.candidates(
                "CHUNK STAGE — HYBRID RRF + ANSWER FIT",
                candidates,
                score_label="hybrid",
            )

        # Preserve a tiny cross-file evidence floor.  This prevents a long file
        # with many lexical hits from eliminating a second directly relevant
        # policy that the file stage already identified.
        representative_candidates = self._selected_file_representatives(
            query, selected_chunks
        )
        if representative_candidates:
            by_id = {item.document.document_id: item for item in candidates}
            for item in representative_candidates:
                existing = by_id.get(item.document.document_id)
                if existing is None or item.score > existing.score:
                    by_id[item.document.document_id] = item
            candidates = sorted(
                by_id.values(), key=lambda item: item.score, reverse=True
            )

        candidates = candidates[:max(
            int(self.settings.final_top_k) * int(self.settings.candidate_multiplier),
            int(self.settings.candidate_minimum),
        )]
        ambiguous = (
            len(candidates) >= int(self.settings.ambiguity_min_candidates)
            and (
                candidates[0].score
                - candidates[min(2, len(candidates) - 1)].score
            ) < float(self.settings.ambiguity_score_gap)
        )
        complex_query = len(_tokenize(query)) >= int(self.settings.complex_query_min_tokens) or bool(
            re.search(
                r"\b(compare|comparison|difference|explain|why|how|paano|bakit|pagkakaiba)\b",
                query,
                re.I,
            )
        )
        if self.settings.reranker_enabled and candidates and ambiguous and complex_query:
            try:
                from sentence_transformers import CrossEncoder
                model = CrossEncoder(self.settings.reranker_model)
                scores = model.predict([
                    (query, item.document.text) for item in candidates
                ])
                candidates = [
                    RetrievedDocument(item.document, float(score))
                    for item, score in zip(candidates, scores)
                ]
                candidates.sort(key=lambda item: item.score, reverse=True)
                if trace is not None:
                    trace.candidates(
                        "CROSS-ENCODER RERANK",
                        candidates,
                        score_label="reranker",
                    )
            except Exception as exc:
                if trace is not None:
                    trace.line(
                        "CROSS-ENCODER RERANK",
                        f"Unavailable/failed; hybrid order retained ({type(exc).__name__}).",
                    )
        elif trace is not None:
            trace.line(
                "CROSS-ENCODER RERANK",
                "Not used for this request (disabled or query not ambiguous/complex).",
            )

        # Keep final evidence focused.  Earlier versions maximized file
        # diversity even when the extra files were much weaker, which could
        # send unrelated policy text to Qwen and dilute an otherwise exact
        # answer.  Preserve only candidates reasonably close to the best
        # evidence score; directly relevant second policies still survive via
        # the selected-file representative floor above.
        evidence_candidates = candidates
        if candidates:
            ratio = min(1.0, max(0.0, float(self.settings.evidence_min_score_ratio)))
            top_score = float(candidates[0].score)
            if top_score > 0:
                score_floor = top_score * ratio
            else:
                score_floor = top_score - max(0.05, abs(top_score) * (1.0 - ratio))
            evidence_candidates = [
                item for item in candidates if float(item.score) >= score_floor
            ] or candidates[:1]

        reserve = 0
        if grouped and int(self.settings.neighbor_chunk_window) > 0:
            reserve = min(
                max(0, int(self.settings.evidence_neighbor_reserve)),
                max(0, int(self.settings.final_top_k) - 1),
            )
        seed_limit = max(1, int(self.settings.final_top_k) - reserve)
        seeds = self._diversify_seeds(evidence_candidates, limit=seed_limit)
        if trace is not None:
            trace.candidates(
                "SELECTED EVIDENCE SEEDS", seeds, score_label="selection"
            )
        final_results = self._expand_neighbors(
            seeds,
            grouped,
            fallback_candidates=evidence_candidates,
        )
        if trace is not None:
            trace.candidates(
                "FINAL EVIDENCE TO QWEN", final_results, score_label="final"
            )
            trace.retrieval_matches(
                candidates=candidates,
                final_results=final_results,
            )
        return final_results


class OllamaClient:
    """Minimal local Ollama chat client with no Python SDK dependency."""

    _availability_cache: dict[str, float] = {}
    _availability_cache_seconds = 30.0

    def __init__(self) -> None:
        self.settings = get_chat_assistant_settings()

    @staticmethod
    def _is_timeout_error(exc: BaseException) -> bool:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return True
        if isinstance(exc, error.URLError):
            reason = getattr(exc, "reason", None)
            return isinstance(reason, (TimeoutError, socket.timeout))
        return False

    @staticmethod
    def _model_key(value: str) -> str:
        return (value or "").strip().casefold()

    @classmethod
    def _model_is_available(cls, configured: str, available: set[str]) -> bool:
        wanted = cls._model_key(configured)
        if not wanted:
            return True
        if wanted in available:
            return True
        # Ollama may display an explicit :latest tag for an untagged model.
        if ":" not in wanted and f"{wanted}:latest" in available:
            return True
        return False

    def check_available(self) -> None:
        """Verify Ollama is reachable and the configured primary model exists."""

        base_url = self.settings.ollama_base_url.rstrip("/")
        configured = str(self.settings.ollama_model)
        cache_key = f"{base_url}|{self._model_key(configured)}"
        cached_until = self._availability_cache.get(cache_key, 0.0)
        if cached_until > time.monotonic():
            return

        url = base_url + "/api/tags"
        req = request.Request(url, method="GET")
        timeout = float(self.settings.ollama_health_timeout_seconds)
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read(2_000_000).decode("utf-8", errors="replace")
            data = json.loads(raw or "{}")
            models = data.get("models") if isinstance(data, dict) else None
            available: set[str] = set()
            for item in models or []:
                if not isinstance(item, dict):
                    continue
                for key in ("name", "model"):
                    value = self._model_key(str(item.get(key) or ""))
                    if value:
                        available.add(value)
            if not self._model_is_available(configured, available):
                raise RuntimeServiceModelUnavailableError(
                    "ollama",
                    model=configured,
                )
            self._availability_cache[cache_key] = (
                time.monotonic() + self._availability_cache_seconds
            )
        except RuntimeServiceModelUnavailableError:
            raise
        except error.HTTPError as exc:
            detail = str(getattr(exc, "reason", "") or "")
            raise RuntimeServiceResponseError(
                "ollama",
                status_code=int(exc.code),
                detail=detail,
                cause=exc,
            ) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeServiceResponseError(
                "ollama",
                detail="Ollama returned an invalid model-list response.",
                cause=exc,
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            if self._is_timeout_error(exc):
                raise RuntimeServiceTimeoutError(
                    "ollama",
                    operation="health_check",
                    timeout_seconds=timeout,
                    cause=exc,
                ) from exc
            raise RuntimeServiceUnavailableError("ollama", cause=exc) from exc

    def generate(
        self,
        prompt: str,
        *,
        quality: bool = False,
        timeout_seconds: float | None = None,
    ) -> str | None:
        url = self.settings.ollama_base_url.rstrip("/") + "/api/generate"
        model = (
            self.settings.quality_ollama_model
            if quality
            else self.settings.ollama_model
        )
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.settings.keep_alive,
            "options": {
                "temperature": float(self.settings.temperature),
                "num_predict": (
                    int(self.settings.quality_max_tokens)
                    if quality
                    else int(self.settings.standard_max_tokens)
                ),
                "num_ctx": int(self.settings.context_window),
            },
        }).encode("utf-8")
        req = request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else self.settings.ollama_timeout_seconds
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            value = _clean_model_answer(str(data.get("response", "")))
            return value or None
        except error.HTTPError as exc:
            detail = ""
            try:
                raw_detail = exc.read(4096).decode("utf-8", errors="replace")
                parsed_detail = json.loads(raw_detail)
                detail = (
                    str(parsed_detail.get("error") or raw_detail)
                    if isinstance(parsed_detail, dict)
                    else raw_detail
                )
            except Exception:
                detail = str(getattr(exc, "reason", "") or "")
            lowered = detail.casefold()
            if "model" in lowered and any(
                term in lowered
                for term in ("not found", "not available", "does not exist", "pull model")
            ):
                raise RuntimeServiceModelUnavailableError(
                    "ollama",
                    model=str(model),
                    cause=exc,
                ) from exc
            raise RuntimeServiceResponseError(
                "ollama",
                status_code=int(exc.code),
                detail=detail,
                cause=exc,
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            if self._is_timeout_error(exc):
                raise RuntimeServiceTimeoutError(
                    "ollama",
                    operation="generation",
                    timeout_seconds=timeout,
                    cause=exc,
                ) from exc
            raise RuntimeServiceUnavailableError("ollama", cause=exc) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeServiceResponseError(
                "ollama",
                detail="Ollama returned an invalid JSON response.",
                cause=exc,
            ) from exc



class SmartPortalAssistant:
    """Enhance deterministic portal answers without weakening access control."""

    _NEVER_ENHANCE_INTENTS = {"sensitive_security", "empty", "leave_carryover", "live_report", "policy_violation", "disciplinary_records", "employee_hierarchy", "employee_aggregate"}
    _RAG_INTENTS = {
        "policy", "policy_question", "policy_fallback", "benefits_policy",
        "leave_type_details", "leave_request_status", "onboarding", "faq", "not_found",
        "employee_summary", "account_summary", "leave_summary",
        "announcement_summary", "attendance", "company_forms",
        "company_profile", "integrations", "audit_logs", "reports",
    }

    # These answers contain authoritative live portal values. They must never
    # be rewritten by an LLM because exact counts, balances, statuses, dates,
    # and employee records are already produced by secured HR services.
    _DIRECT_LIVE_INTENTS = {
        "employee_lookup", "leave_balance", "leave_status",
        "employee_profile", "personal_employee", "policy_summary", "dashboard",
    }


    _YES_NO_PATTERN = re.compile(
        r"^\s*(?:"
        r"can|could|may|might|should|would|will|do|does|did|"
        r"is|are|was|were|has|have|had|am|"
        r"pwede\s+ba|puwede\s+ba|maaari\s+ba"
        r")\b",
        re.I,
    )
    _NON_BINARY_REQUEST_PATTERN = re.compile(
        r"^\s*(?:"
        r"(?:who|what|when|where|why|how|which|show|list|tell|give|display|find|summarize|explain)\b"
        r"|(?:can|could|would|will)\s+you\s+"
        r"(?:show|list|tell|give|display|find|summarize|explain|help|open|check)"
        r"|(?:can|could|may)\s+i\s+"
        r"(?:see|view|show|list|check|know)"
        r")",
        re.I,
    )
    _FOLLOW_UP_PATTERNS = (
        r"\bhow about\b",
        r"\bwhat about\b",
        r"\babout it\b",
        r"\babout that\b",
        r"\bapprove(?:s)? it\b",
        r"\bwho (?:needs to )?approve(?:s)?\b",
        r"\bthat request\b",
        r"\bthis request\b",
        r"\bthe same request\b",
        r"\bwhat happens next\b",
        r"\band (?:vl|sl|el)\b",
        r"\bilan na lang\b",
        r"\bilan nalang\b",
        r"\bpaano naman\b",
        r"\byun\b",
        r"\bito\b",
    )
    _SCOPE_STOPWORDS = {
        "a", "an", "and", "ang", "ano", "are", "ba", "can", "could", "do",
        "does", "for", "from", "how", "i", "in", "is", "it", "ko", "may",
        "my", "ng", "of", "on", "or", "si", "sino", "the", "to", "what",
        "when", "where", "which", "who", "why", "with", "would", "you", "your",
    }
    _IN_SCOPE_TERMS = {
        "hr", "employee", "employees", "company", "work", "office", "manager",
        "leader", "leave", "vacation", "sick", "emergency", "lwop", "attendance",
        "dtr", "overtime", "policy", "policies", "benefit", "benefits", "onboarding",
        "announcement", "announcements", "form", "forms", "document", "documents",
        "report", "reports", "department", "job", "salary", "payroll", "schedule",
        "shift", "holiday", "holidays", "dress", "uniform", "attire", "parking",
        "park", "reimbursement", "travel", "fare", "meal", "break", "remote",
        "wfh", "wfo", "credit", "credits", "request", "requests", "approval",
        "approve", "approver", "contact", "contacts", "faq", "training",
    }
    _STRONG_IN_SCOPE_TERMS = {
        "hr", "employee", "employees", "company", "manager", "leader", "leave",
        "vacation", "sick", "emergency", "lwop", "attendance", "dtr", "overtime",
        "policy", "policies", "benefit", "benefits", "onboarding", "payroll",
        "department", "wfh", "wfo", "approval", "approver", "training",
    }
    _OBVIOUS_EXTERNAL_TERMS = {
        "batman", "superman", "marvel", "dc comics", "celebrity", "celebrities",
        "movie", "movies", "actor", "actress", "singer", "music", "song", "songs",
        "basketball", "football", "nba", "nfl", "sports", "score", "scores",
        "election", "politics", "politician", "president", "senator", "mayor",
        "python programming", "javascript", "programming", "source code", "coding",
        "recipe", "recipes", "weather", "horoscope", "astrology",
    }

    # Retrieval relevance is a second fail-closed layer after the existing
    # company/HR scope check. Generic domain words must not make an unrelated
    # nearest chunk look answerable (for example, ``Laptop policy`` matching a
    # Leave Policy only because both contain the word ``policy``).
    _RELEVANCE_GUARD_INTENTS = {
        "policy", "policy_question", "policy_fallback", "benefits_policy", "not_found",
    }
    _RELEVANCE_GENERIC_TERMS = {
        "company", "detail", "details", "employee", "employees", "hr",
        "information", "policy", "policies", "rule", "rules", "work",
    }

    @classmethod
    def _is_yes_no_question(cls, question: str) -> bool:
        clean = _clean_text(question)
        if cls._NON_BINARY_REQUEST_PATTERN.search(clean):
            return False
        return bool(
            cls._YES_NO_PATTERN.search(clean)
            or re.search(r"\byes\s+or\s+no\b", clean, re.I)
        )

    @classmethod
    def _is_follow_up_question(
        cls,
        question: str,
        history: list[dict] | None,
    ) -> bool:
        if not history:
            return False
        clean = _clean_text(question).casefold()
        if any(re.search(pattern, clean, re.I) for pattern in cls._FOLLOW_UP_PATTERNS):
            return True
        # Very short reference-only questions are also follow-ups, but clear
        # standalone module/topic names are deliberately excluded.
        tokens = _tokenize(clean)
        standalone_topics = {
            "policy", "policies", "documents", "attendance", "overtime",
            "onboarding", "benefits", "announcements", "faq", "reports",
        }
        return (
            0 < len(tokens) <= 4
            and not standalone_topics.intersection(tokens)
            and bool(re.search(r"\b(it|that|those|this|these|them|same)\b", clean))
        )

    @staticmethod
    def _last_user_question(history: list[dict] | None) -> str | None:
        for message in reversed(history or []):
            if message.get("role") != "user":
                continue
            value = _clean_text(str(message.get("content", "")))
            if value:
                return value
        return None

    @classmethod
    def _contextual_search_query(
        cls,
        question: str,
        history: list[dict] | None,
    ) -> str:
        if not cls._is_follow_up_question(question, history):
            return question
        previous = cls._last_user_question(history)
        return f"{previous} {question}".strip() if previous else question

    @classmethod
    def _scope_terms(cls, value: str) -> set[str]:
        terms: set[str] = set()
        for token in _tokenize(value):
            if token in cls._SCOPE_STOPWORDS or len(token) <= 2:
                continue
            stem = token
            for suffix in ("ingly", "edly", "ing", "ed", "es", "s"):
                if stem.endswith(suffix) and len(stem) - len(suffix) >= 4:
                    stem = stem[:-len(suffix)]
                    break
            terms.add(stem)
        return terms

    @classmethod
    def _retrieval_has_lexical_support(
        cls,
        query: str,
        retrieved: list[RetrievedDocument],
    ) -> bool:
        query_terms = cls._scope_terms(query)
        if not query_terms:
            return False
        for item in retrieved:
            document_terms = cls._scope_terms(
                f"{item.document.title} {item.document.text}"
            )
            if query_terms.intersection(document_terms):
                return True
        return False

    @classmethod
    def _relevance_anchor_terms(cls, query: str) -> set[str]:
        """Return specific topic terms, excluding generic company/policy words."""

        return cls._scope_terms(query).difference(cls._RELEVANCE_GENERIC_TERMS)

    @classmethod
    def _retrieval_relevance_snapshot(
        cls,
        *,
        query: str,
        retrieved: list[RetrievedDocument],
    ) -> dict[str, object]:
        """Measure whether retrieved evidence actually covers the user's topic.

        This deliberately favors lexical topic anchors over raw nearest-neighbor
        rank. A vector result can be the mathematically nearest chunk while still
        being unrelated to the requested subject. The guard is fail-closed only
        for fallback/policy-style requests; exact live HR routes remain unchanged.
        """

        anchors = cls._relevance_anchor_terms(query)
        if not retrieved:
            return {
                "accepted": False,
                "anchors": anchors,
                "matched": set(),
                "coverage": 0.0,
                "answer_fit": 0.0,
                "source": "-",
                "reason": "No authorized evidence was retrieved.",
            }

        # If the wording contains only generic company/policy words, do not let
        # this guard invent a topic. The existing deterministic router remains
        # authoritative for those generic requests.
        if not anchors:
            return {
                "accepted": True,
                "anchors": anchors,
                "matched": set(),
                "coverage": 1.0,
                "answer_fit": 0.0,
                "source": "-",
                "reason": "No specific topic anchor; retain existing router behavior.",
            }

        best: dict[str, object] | None = None
        for item in retrieved[: max(1, min(5, len(retrieved)))]:
            document = item.document
            document_terms = cls._scope_terms(
                f"{document.title} {document.text}"
            )
            matched = anchors.intersection(document_terms)
            coverage = len(matched) / max(1, len(anchors))
            fit = _evidence_fit_bonus(query, document)
            metadata = document.metadata or {}
            source = str(
                metadata.get("filename")
                or metadata.get("title")
                or document.title
                or document.document_id
            ).strip()
            candidate = {
                "anchors": anchors,
                "matched": matched,
                "coverage": coverage,
                "answer_fit": fit,
                "source": source,
            }
            if best is None or (coverage, fit) > (
                float(best["coverage"]),
                float(best["answer_fit"]),
            ):
                best = candidate

        assert best is not None
        matched_count = len(best["matched"])
        anchor_count = len(anchors)
        coverage = float(best["coverage"])
        fit = float(best["answer_fit"])

        # Short subject phrases are strict: both terms in ``emergency loan``
        # must be supported, so an ``Emergency Leave`` chunk cannot pass merely
        # on the shared word ``emergency``. Longer natural questions allow half
        # of the specific anchors as long as at least two are supported.
        if anchor_count == 1:
            accepted = matched_count == 1
        elif anchor_count == 2:
            accepted = matched_count == 2
        else:
            accepted = matched_count >= 2 and coverage >= 0.50

        # A strong answer-shape fit can confirm a borderline long question, but
        # never rescues evidence with fewer than two supported topic anchors.
        if (
            not accepted
            and anchor_count >= 4
            and matched_count >= 2
            and coverage >= 0.40
            and fit >= 0.45
        ):
            accepted = True

        best["accepted"] = accepted
        best["reason"] = (
            "Retrieved evidence covers the specific topic anchors."
            if accepted
            else "Nearest evidence does not sufficiently cover the requested topic."
        )
        return best

    @staticmethod
    def _top_display_sources(
        sources: list,
        retrieved: list[RetrievedDocument],
    ) -> list:
        """Return one best policy source for the clean Streamlit source display."""

        if not sources:
            return []

        for item in retrieved:
            metadata = item.document.metadata or {}
            filename = str(metadata.get("filename") or "").strip().casefold()
            policy_id = metadata.get("policy_id")
            section = str(metadata.get("section") or "").strip().casefold()
            for source in sources:
                source_filename = str(getattr(source, "filename", "") or "").strip().casefold()
                source_section = str(
                    getattr(source, "section_heading", "") or ""
                ).strip().casefold()
                source_policy_id = getattr(source, "policy_id", None)
                file_matches = bool(filename and source_filename == filename)
                policy_matches = bool(
                    policy_id is not None and source_policy_id == policy_id
                )
                if not (file_matches or policy_matches):
                    continue
                if section and source_section and section != source_section:
                    # Prefer the exact best section when available, but the file
                    # itself remains the primary source if section labels differ.
                    continue
                return [source]

        # Deterministic policy search is already score ordered. Limiting to one
        # here also protects direct/fallback paths when a retriever match cannot
        # be mapped back to the policy source object.
        return [sources[0]]

    @staticmethod
    def _contains_scope_term(value: str, term: str) -> bool:
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])",
                value,
                re.I,
            )
        )

    @classmethod
    def _is_out_of_scope_question(
        cls,
        *,
        question: str,
        history: list[dict] | None,
        deterministic_intent: str,
        retrieved: list[RetrievedDocument],
    ) -> bool:
        # Recognized HR/application routes are already inside the product scope.
        if deterministic_intent not in {"policy_fallback", "not_found"}:
            return False
        if cls._is_follow_up_question(question, history):
            return False
        if cls._is_yes_no_question(question):
            # A yes/no workplace rule may be phrased without an explicit HR
            # keyword; allow retrieval/prompt grounding to decide it safely.
            return False

        normalized = _clean_text(question).casefold()
        has_strong_scope = any(
            cls._contains_scope_term(normalized, term)
            for term in cls._STRONG_IN_SCOPE_TERMS
        )
        has_external = any(
            cls._contains_scope_term(normalized, term)
            for term in cls._OBVIOUS_EXTERNAL_TERMS
        )
        if has_external and not has_strong_scope:
            return True
        if any(
            cls._contains_scope_term(normalized, term)
            for term in cls._IN_SCOPE_TERMS
        ):
            return False
        if cls._retrieval_has_lexical_support(question, retrieved):
            return False

        # Unknown wording with no authorized HR/company support is kept away
        # from the general-purpose knowledge of the local model.
        return True

    @staticmethod
    def _normalize_standard_answer(answer: str) -> str:
        """Remove an accidental binary prefix from non-binary answers.

        Local models occasionally start an ordinary Who/What/Show/List answer
        with ``YES.`` or ``NO.`` even when the question is not binary. Keep the
        useful grounded remainder but never present that misleading prefix.
        """

        clean = _clean_model_answer(answer)
        match = re.match(
            r"^\s*(?:\*\*)?(?:yes|no)\s*[.!,:;-]\s*(?:\*\*)?\s*(.+)$",
            clean,
            re.I | re.S,
        )
        if match:
            clean = match.group(1).strip()
        return _organize_answer(clean)

    @staticmethod
    def _normalize_yes_no_answer(answer: str) -> str:
        clean = _clean_model_answer(answer)
        if not clean:
            return UNDETERMINED_ANSWER
        if clean.casefold().startswith(UNDETERMINED_ANSWER.casefold()):
            return UNDETERMINED_ANSWER
        if clean.casefold().startswith(NOT_FOUND_ANSWER.casefold()):
            return UNDETERMINED_ANSWER
        match = re.match(
            r"^\s*(?:\*\*)?(yes|no)\s*[.!,:;-]?\s*(?:\*\*)?\s*(.*)$",
            clean,
            re.I | re.S,
        )
        if not match:
            # Do not infer a binary conclusion from prose. If the model did not
            # provide a grounded YES/NO, fail closed instead of guessing.
            return UNDETERMINED_ANSWER
        prefix = f"**{match.group(1).upper()}.**"
        remainder = match.group(2).strip()
        return f"{prefix} {remainder}".strip()

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_chat_assistant_settings()
        self.retriever = HybridRetriever()
        self.ollama = OllamaClient()


    def preflight_connection_issue(
        self,
        *,
        role_scope: str,
    ):
        """Return a safe Ollama warning without blocking deterministic HR answers."""

        if not self.settings.enabled:
            return None
        try:
            self.ollama.check_available()
            return None
        except (
            RuntimeServiceModelUnavailableError,
            RuntimeServiceResponseError,
            RuntimeServiceTimeoutError,
            RuntimeServiceUnavailableError,
        ) as exc:
            issue = classify_runtime_connection_issue(exc, service_hint="ollama")
            if issue is None:
                raise
            log_runtime_connection_issue(
                exc,
                issue,
                context=f"chat_preflight:{role_scope}",
            )
            return issue

    def _history_text(self, history: list[dict] | None) -> str:
        lines = []
        for message in (history or [])[-max(1, int(self.settings.history_messages)):]:
            role = str(message.get("role", "user")).title()
            content = _clean_text(str(message.get("content", "")))
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _truncate_prompt_text(
        value: str,
        limit: int,
        *,
        suffix: str = "\n[Additional authorized context omitted for safe model input size.]",
    ) -> str:
        """Bound one prompt section without changing authoritative source data."""

        clean = str(value or "").strip()
        if limit <= 0 or len(clean) <= limit:
            return clean
        usable = max(0, limit - len(suffix))
        return clean[:usable].rstrip() + suffix

    def _build_evidence_context(
        self,
        *,
        query: str,
        retrieved: list[RetrievedDocument],
    ) -> str:
        """Build compact, source-labeled evidence blocks for the local model.

        The retriever may return several 260-300 word chunks, but Qwen's 4096
        context window cannot safely receive all of them verbatim alongside the
        grounding rules and router answer.  Keep the most question-relevant
        sentences/rows from every selected chunk so multiple applicable policy
        rules survive the prompt budget instead of the first chunk consuming it.
        """

        if not retrieved:
            return "No additional approved portal context was retrieved."

        blocks: list[str] = []
        excerpt_limit = max(320, int(self.settings.evidence_excerpt_chars))
        for index, item in enumerate(retrieved, start=1):
            metadata = item.document.metadata or {}
            source_name = str(
                metadata.get("filename")
                or metadata.get("title")
                or item.document.title
                or "Authorized company source"
            ).strip()
            section = str(metadata.get("section") or "").strip()
            page_number = metadata.get("page_number")
            labels = [f"Source: {source_name}"]
            if section:
                labels.append(f"Section: {section}")
            if page_number:
                labels.append(f"Page: {page_number}")
            excerpt = _focused_evidence_excerpt(
                query,
                item.document.text,
                excerpt_limit,
            )
            blocks.append(
                f"[Evidence {index} | {' | '.join(labels)}]\n{excerpt}"
            )
        return "\n\n".join(blocks)

    def _budget_prompt_sections(
        self,
        *,
        history_text: str,
        router_answer: str,
        context: str,
        rag_priority: bool = False,
        compact: bool = False,
    ) -> tuple[str, str, str]:
        """Keep prompt sections safe while preserving multi-source RAG evidence."""

        context_window = max(2048, int(self.settings.context_window))
        if rag_priority:
            variable_budget = max(4600, min(9800, int(context_window * 1.9)))
        else:
            # Preserve the established non-RAG prompt budget so structured/live
            # answers do not lose the router-first behavior while policy/document
            # questions can use the larger evidence budget above.
            variable_budget = max(4200, min(8200, int(context_window * 1.6)))
        if compact:
            variable_budget = max(3200, int(variable_budget * 0.58))

        if rag_priority:
            # Policy/document questions need more evidence than router prose.
            # The router remains authoritative when exact, but it may be a
            # focused extract; allocate enough space to preserve distinct
            # clauses, exceptions, and cross-policy rules.
            context_limit = int(variable_budget * 0.62)
            router_limit = int(variable_budget * 0.24)
        else:
            router_limit = int(variable_budget * 0.54)
            context_limit = int(variable_budget * 0.34)
        history_limit = max(420, variable_budget - router_limit - context_limit)

        return (
            self._truncate_prompt_text(history_text, history_limit),
            self._truncate_prompt_text(
                router_answer,
                router_limit,
                suffix=(
                    "\n[Additional verified router rows omitted from AI rewriting; "
                    "the verified portal result remains authoritative.]"
                ),
            ),
            self._truncate_prompt_text(context, context_limit),
        )

    def enhance(
        self,
        *,
        current_user: AuthenticatedUser,
        role_scope: str,
        question: str,
        history: list[dict] | None,
        deterministic_response: HRAssistantResponse,
    ) -> HRAssistantResponse:
        trace = TerminalChatTrace.create(self.settings)
        trace.start(
            role_scope=role_scope,
            intent=deterministic_response.intent,
            question=question,
        )
        trace.answer("DETERMINISTIC / ROUTER ANSWER", deterministic_response.answer)

        def complete(
            response: HRAssistantResponse,
            *,
            status: str = "complete",
        ) -> HRAssistantResponse:
            if response.runtime_warning_code:
                trace.runtime_issue(
                    code=response.runtime_warning_code,
                    title=response.runtime_warning_title or "Runtime warning",
                    message=response.runtime_warning or "",
                )
            selected_answer = (
                "qwen" if status == "qwen-answer" else "deterministic/router"
            )
            trace.answer_selection(selected=selected_answer, reason=status)
            trace.answer("FINAL CHAT ANSWER", response.answer)
            trace.finish(status)
            return response

        if not self.settings.enabled:
            trace.line("AI PATH", "Smart AI enhancement is disabled; deterministic answer retained.")
            return complete(deterministic_response, status="smart-ai-disabled")
        if deterministic_response.intent in self._NEVER_ENHANCE_INTENTS:
            trace.line("AI PATH", "Intent is excluded from AI enhancement; no retrieval performed.")
            return complete(deterministic_response, status="never-enhance-intent")

        is_yes_no = self._is_yes_no_question(question)
        is_follow_up = self._is_follow_up_question(question, history)

        # Exact live answers stay deterministic unless the user explicitly
        # asked a binary question or an incomplete follow-up needs resolution.
        if (
            deterministic_response.intent in self._DIRECT_LIVE_INTENTS
            and not is_yes_no
            and not is_follow_up
        ):
            trace.line("AI PATH", "Exact live HR answer retained; RAG/Qwen enhancement not needed.")
            return complete(
                HRAssistantResponse(
                    answer=_organize_answer(deterministic_response.answer),
                    intent=deterministic_response.intent,
                    actions=deterministic_response.actions,
                    sources=deterministic_response.sources,
                ),
                status="direct-live-answer",
            )

        question_tokens = _tokenize(question)
        # "How many" is a count request, not a request for an AI explanation.
        # Only route genuine explanation/how-to wording to the LLM.
        asks_for_explanation = bool(re.search(
            r"\b(explain|compare|comparison|difference|why|paano|bakit|pagkakaiba|summarize)\b"
            r"|\bhow\s+(?:do|does|did|is|are|can|should|to)\b",
            question,
            re.I,
        ))
        needs_ai = (
            deterministic_response.intent in self._RAG_INTENTS
            or asks_for_explanation
            or is_yes_no
            or is_follow_up
            or len(question_tokens) >= int(self.settings.min_question_tokens)
        )
        evidence_profile = _question_evidence_profile(question)
        if not needs_ai:
            trace.question_analysis(
                yes_no=is_yes_no,
                follow_up=is_follow_up,
                explanation=asks_for_explanation,
                needs_ai=False,
                token_count=len(question_tokens),
                evidence_profile=evidence_profile,
            )
            trace.line("AI PATH", "Question does not require RAG/Qwen enhancement.")
            return complete(
                HRAssistantResponse(
                    answer=_organize_answer(deterministic_response.answer),
                    intent=deterministic_response.intent,
                    actions=deterministic_response.actions,
                    sources=deterministic_response.sources,
                ),
                status="deterministic-answer",
            )

        retrieval_query = self._contextual_search_query(question, history)
        trace.question_analysis(
            yes_no=is_yes_no,
            follow_up=is_follow_up,
            explanation=asks_for_explanation,
            needs_ai=True,
            token_count=len(question_tokens),
            evidence_profile=evidence_profile,
            retrieval_query=retrieval_query,
        )
        documents = PortalKnowledgeBuilder(self.session).build(
            current_user=current_user,
            role_scope=role_scope,
        )
        retrieved = self.retriever.search(
            retrieval_query,
            documents,
            company_id=current_user.company_id,
            role_scope=role_scope,
            access_partition=(
                f"company:{current_user.company_id}:role:{role_scope}:"
                f"user:{current_user.user_id}"
            ),
            trace=trace,
        )
        trace.retrieval_summary()

        if self._is_out_of_scope_question(
            question=question,
            history=history,
            deterministic_intent=deterministic_response.intent,
            retrieved=retrieved,
        ):
            trace.line("SCOPE CHECK", "Question classified as outside authorized company HR scope.")
            trace.top_source(retrieved[0] if retrieved else None)
            return complete(
                HRAssistantResponse(
                    answer=OUT_OF_SCOPE_ANSWER,
                    intent="out_of_scope",
                    actions=[],
                    sources=[],
                ),
                status="out-of-scope",
            )

        if deterministic_response.intent in self._RELEVANCE_GUARD_INTENTS:
            relevance = self._retrieval_relevance_snapshot(
                query=retrieval_query,
                retrieved=retrieved,
            )
            trace.relevance_guard(
                anchors=relevance["anchors"],
                matched_anchors=relevance["matched"],
                coverage=float(relevance["coverage"]),
                answer_fit=float(relevance["answer_fit"]),
                source=str(relevance["source"]),
                decision="ACCEPT" if relevance["accepted"] else "REJECT",
                reason=str(relevance["reason"]),
            )
            if not bool(relevance["accepted"]):
                trace.top_source(retrieved[0] if retrieved else None)
                guard_answer = (
                    UNDETERMINED_ANSWER if is_yes_no else NOT_FOUND_ANSWER
                )
                return complete(
                    HRAssistantResponse(
                        answer=guard_answer,
                        intent=deterministic_response.intent,
                        actions=deterministic_response.actions,
                        sources=[],
                        report=deterministic_response.report,
                    ),
                    status="relevance-guard-no-match",
                )

        display_sources = self._top_display_sources(
            deterministic_response.sources,
            retrieved,
        )
        trace.top_source(retrieved[0] if retrieved else None)

        if trace.enabled:
            candidate_answer_limit = max(
                320,
                int(getattr(self.settings, "terminal_debug_candidate_answer_chars", 760)),
            )
            candidate_answers = []
            for item in retrieved[: trace.top_k]:
                metadata = item.document.metadata or {}
                chunk_index = metadata.get("chunk_index") or "-"
                total_chunks = metadata.get("total_chunks") or "-"
                candidate_answers.append(
                    {
                        "retrieval_score": float(item.score),
                        "answer_fit": _evidence_fit_bonus(
                            retrieval_query, item.document
                        ),
                        "source": (
                            metadata.get("filename")
                            or metadata.get("title")
                            or item.document.title
                            or item.document.document_id
                        ),
                        "section": metadata.get("section") or "-",
                        "page": metadata.get("page_number") or "-",
                        "chunk": f"{chunk_index}/{total_chunks}",
                        "possible_answer": _focused_evidence_excerpt(
                            retrieval_query,
                            item.document.text,
                            candidate_answer_limit,
                        ),
                    }
                )
            trace.answer_candidates(candidate_answers)

        context = self._build_evidence_context(
            query=retrieval_query,
            retrieved=retrieved,
        )
        trace.line(
            "EVIDENCE CONTEXT",
            f"retrieved_chunks={len(retrieved)}; context_chars={len(context)}",
        )

        role_rule = (
            "You may use authorized company-wide records provided in the deterministic answer."
            if role_scope == "admin"
            else "You may use only the signed-in employee's own private records and company-wide published information."
        )
        rag_priority = deterministic_response.intent in self._RAG_INTENTS
        full_history_text = self._history_text(history)
        full_router_answer = deterministic_response.answer
        full_context = context
        history_text, router_answer, context = self._budget_prompt_sections(
            history_text=full_history_text,
            router_answer=full_router_answer,
            context=full_context,
            rag_priority=rag_priority,
        )
        prompt = build_hr_assistant_prompt(
            role_rule=role_rule,
            history_text=history_text,
            question=question,
            router_answer=router_answer,
            context=context,
            question_mode="yes_no" if is_yes_no else "standard",
            evidence_profile=_question_evidence_profile(question),
            follow_up=is_follow_up,
            current_datetime_text=datetime.now(
                ZoneInfo(get_settings().display_timezone)
            ).strftime("%Y/%m/%d %I:%M %p %Z"),
        )
        use_quality_model = asks_for_explanation and (
            len(question_tokens) >= int(self.settings.quality_min_question_tokens)
            or len(retrieved) >= int(self.settings.quality_min_retrieved_documents)
        )
        primary_model = (
            getattr(self.settings, "quality_ollama_model", "quality-model")
            if use_quality_model
            else getattr(self.settings, "ollama_model", "configured-model")
        )
        primary_timeout = getattr(self.settings, "ollama_timeout_seconds", 180)
        trace.line(
            "OLLAMA REQUEST",
            (
                f"model={primary_model}; quality={use_quality_model}; "
                f"prompt_chars={len(prompt)}; timeout={primary_timeout}s"
            ),
        )
        started = time.monotonic()
        try:
            generated = self.ollama.generate(prompt, quality=use_quality_model)
            trace.line(
                "OLLAMA RESULT",
                f"primary completed in {time.monotonic() - started:.2f}s",
            )
        except RuntimeServiceTimeoutError as first_timeout:
            trace.line(
                "OLLAMA TIMEOUT",
                f"primary timed out after {time.monotonic() - started:.2f}s",
            )
            if bool(self.settings.ollama_timeout_retry_enabled):
                retry_issue = classify_runtime_connection_issue(
                    first_timeout, service_hint="ollama"
                )
                if retry_issue is None:
                    raise
                log_runtime_connection_issue(
                    first_timeout,
                    retry_issue,
                    context=f"chat_enhancement_timeout_retry:{role_scope}",
                )
                retry_history, retry_router, retry_context = self._budget_prompt_sections(
                    history_text=full_history_text,
                    router_answer=full_router_answer,
                    context=full_context,
                    rag_priority=rag_priority,
                    compact=True,
                )
                retry_prompt = build_hr_assistant_prompt(
                    role_rule=role_rule,
                    history_text=retry_history,
                    question=question,
                    router_answer=retry_router,
                    context=retry_context,
                    question_mode="yes_no" if is_yes_no else "standard",
                    evidence_profile=_question_evidence_profile(question),
                    follow_up=is_follow_up,
                    current_datetime_text=datetime.now(
                        ZoneInfo(get_settings().display_timezone)
                    ).strftime("%Y/%m/%d %I:%M %p %Z"),
                )
                trace.line(
                    "OLLAMA RETRY",
                    (
                        f"model={getattr(self.settings, 'ollama_model', 'configured-model')}; quality=False; "
                        f"prompt_chars={len(retry_prompt)}; "
                        f"timeout={self.settings.ollama_retry_timeout_seconds}s"
                    ),
                )
                retry_started = time.monotonic()
                try:
                    # One internal retry only: smaller prompt + shorter standard
                    # output budget.  This does not resubmit the user's request
                    # or create a second chat message.
                    generated = self.ollama.generate(
                        retry_prompt,
                        quality=False,
                        timeout_seconds=float(
                            self.settings.ollama_retry_timeout_seconds
                        ),
                    )
                    trace.line(
                        "OLLAMA RESULT",
                        f"retry completed in {time.monotonic() - retry_started:.2f}s",
                    )
                except (
                    RuntimeServiceModelUnavailableError,
                    RuntimeServiceResponseError,
                    RuntimeServiceTimeoutError,
                    RuntimeServiceUnavailableError,
                ) as exc:
                    issue = classify_runtime_connection_issue(
                        exc, service_hint="ollama"
                    )
                    if issue is None:
                        raise
                    log_runtime_connection_issue(
                        exc,
                        issue,
                        context=f"chat_enhancement_retry_failed:{role_scope}",
                    )
                    fallback_answer = _organize_answer(
                        deterministic_response.answer
                    )
                    return complete(
                        HRAssistantResponse(
                            answer=fallback_answer,
                            intent=deterministic_response.intent,
                            actions=deterministic_response.actions,
                            sources=display_sources,
                            report=deterministic_response.report,
                            runtime_warning=issue.message,
                            runtime_warning_title=issue.title,
                            runtime_warning_code=issue.code,
                        ),
                        status="ollama-retry-fallback",
                    )
            else:
                issue = classify_runtime_connection_issue(
                    first_timeout, service_hint="ollama"
                )
                if issue is None:
                    raise
                log_runtime_connection_issue(
                    first_timeout,
                    issue,
                    context=f"chat_enhancement:{role_scope}",
                )
                fallback_answer = _organize_answer(deterministic_response.answer)
                return complete(
                    HRAssistantResponse(
                        answer=fallback_answer,
                        intent=deterministic_response.intent,
                        actions=deterministic_response.actions,
                        sources=display_sources,
                        report=deterministic_response.report,
                        runtime_warning=issue.message,
                        runtime_warning_title=issue.title,
                        runtime_warning_code=issue.code,
                    ),
                    status="ollama-timeout-fallback",
                )
        except (
            RuntimeServiceModelUnavailableError,
            RuntimeServiceResponseError,
            RuntimeServiceUnavailableError,
        ) as exc:
            issue = classify_runtime_connection_issue(exc, service_hint="ollama")
            if issue is None:
                raise
            log_runtime_connection_issue(
                exc,
                issue,
                context=f"chat_enhancement:{role_scope}",
            )
            fallback_answer = _organize_answer(deterministic_response.answer)
            return complete(
                HRAssistantResponse(
                    answer=fallback_answer,
                    intent=deterministic_response.intent,
                    actions=deterministic_response.actions,
                    sources=display_sources,
                    report=deterministic_response.report,
                    runtime_warning=issue.message,
                    runtime_warning_title=issue.title,
                    runtime_warning_code=issue.code,
                ),
                status="ollama-error-fallback",
            )
        if not generated:
            trace.line("OLLAMA RESULT", "No model text returned; deterministic answer retained.")
            fallback_answer = _organize_answer(deterministic_response.answer)
            return complete(
                HRAssistantResponse(
                    answer=fallback_answer,
                    intent=deterministic_response.intent,
                    actions=deterministic_response.actions,
                    sources=display_sources,
                    report=deterministic_response.report,
                ),
                status="empty-model-fallback",
            )
        trace.answer("ANSWER OPTION — ROUTER", deterministic_response.answer)
        trace.answer("ANSWER OPTION — QWEN", generated)
        trace.answer("QWEN RAW ANSWER", generated)
        final_answer = (
            self._normalize_yes_no_answer(generated)
            if is_yes_no
            else self._normalize_standard_answer(generated)
        )
        return complete(
            HRAssistantResponse(
                answer=final_answer,
                intent=deterministic_response.intent,
                actions=deterministic_response.actions,
                sources=display_sources,
            ),
            status="qwen-answer",
        )
