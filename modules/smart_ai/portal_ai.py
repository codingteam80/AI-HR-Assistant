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

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import logging
import math
import os
import re
from typing import Iterable
from urllib import request, error
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from authentication.current_user import AuthenticatedUser
from config.chat_assistant_settings import get_chat_assistant_settings
from config.settings import get_settings
from modules.hr_assistant.hr_assistant import HRAssistantResponse
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


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Use LlamaIndex SentenceSplitter when installed; otherwise safe fallback."""

    clean = _clean_text(text)
    if not clean:
        return []
    try:
        from llama_index.core.node_parser import SentenceSplitter
        splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
        chunks = [item.text.strip() for item in splitter.get_nodes_from_documents([])]
        if chunks:
            return chunks
    except Exception:
        pass

    words = clean.split()
    if len(words) <= chunk_size:
        return [clean]
    step = max(1, chunk_size - overlap)
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), step) if words[i:i + chunk_size]]


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
                    f"first cut-off end day: {company.shifting_credit_cutoff_day}. "
                    f"Additional VL qualifying OT: "
                    f"{company.shifting_credit_additional_vl_threshold_hours} hours; "
                    f"additional VL: {company.shifting_credit_additional_vl_days} days. "
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
                    for chunk_index, chunk in enumerate(
                        _split_text(
                            extracted_form_text,
                            int(self.settings.chunk_size),
                            int(self.settings.chunk_overlap),
                        ),
                        start=1,
                    ):
                        self._add_document(
                            documents,
                            document_id=(
                                f"company:{company_id}:company-form-content:"
                                f"{form.id}:{chunk_index}"
                            ),
                            title=f"{form.title} — {form.original_filename}",
                            source_type="company_form_content",
                            company_id=company_id,
                            role_scope="admin" if is_admin else "shared",
                            text=chunk,
                            metadata={
                                "company_form_id": form.id,
                                "title": form.title,
                                "filename": form.original_filename,
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
        chunk_size = int(self.settings.chunk_size)
        overlap = int(self.settings.chunk_overlap)
        for policy, document, section in rows:
            combined = f"Policy: {policy.title}. Section: {section.heading}. {section.text}"
            for chunk_index, chunk in enumerate(_split_text(combined, chunk_size, overlap), start=1):
                documents.append(KnowledgeDocument(
                    document_id=f"company:{company_id}:policy:{policy.id}:{section.id}:{chunk_index}",
                    text=chunk,
                    title=f"{policy.title} — {section.heading}",
                    source_type="policy",
                    company_id=company_id,
                    role_scope="shared",
                    metadata={
                        "policy_id": policy.id,
                        "title": policy.title,
                        "section": section.heading,
                        "version": policy.version,
                        "filename": document.original_filename,
                        "page_number": section.page_number,
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
    """Optional Chroma + lightweight multilingual-e5 vector retrieval."""

    _indexed_signatures: set[str] = set()

    def __init__(self) -> None:
        self.settings = get_chat_assistant_settings()
        self._embedding_model = None

    def _model(self):
        if self._embedding_model is None:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer(self.settings.embedding_model)
        return self._embedding_model

    def search(self, query: str, documents: list[KnowledgeDocument], top_k: int) -> list[RetrievedDocument]:
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
                name=self.settings.chroma_collection,
                metadata={"hnsw:space": "cosine"},
            )
            model = self._model()
            ids = [doc.document_id for doc in documents]
            signature = hashlib.sha256(
                "|".join(f"{doc.document_id}:{hashlib.sha1(doc.text.encode('utf-8')).hexdigest()}" for doc in documents).encode("utf-8")
            ).hexdigest()
            cache_key = f"{collection.name}:{signature}"
            if cache_key not in self._indexed_signatures:
                texts = [f"passage: {doc.text}" for doc in documents]
                embeddings = model.encode(texts, normalize_embeddings=True).tolist()
                metadatas = [
                    {
                        "company_id": doc.company_id,
                        "role_scope": doc.role_scope,
                        "title": doc.title,
                        "source_type": doc.source_type,
                        "payload": json.dumps(doc.metadata, default=str),
                    }
                    for doc in documents
                ]
                collection.upsert(
                    ids=ids,
                    documents=[doc.text for doc in documents],
                    embeddings=embeddings,
                    metadatas=metadatas,
                )
                self._indexed_signatures.add(cache_key)
            query_embedding = model.encode([f"query: {query}"], normalize_embeddings=True).tolist()
            result = collection.query(query_embeddings=query_embedding, n_results=min(top_k, len(documents)))
            lookup = {doc.document_id: doc for doc in documents}
            output: list[RetrievedDocument] = []
            result_ids = result.get("ids") or [[]]
            result_distances = result.get("distances") or [[]]
            for doc_id, distance in zip(result_ids[0], result_distances[0]):
                doc = lookup.get(doc_id)
                if doc is not None:
                    output.append(RetrievedDocument(doc, max(0.0, 1.0 - float(distance))))
            return output
        except Exception:
            return []


class HybridRetriever:
    """Merge BM25 and vector results, then optionally cross-encode rerank."""

    def __init__(self) -> None:
        self.settings = get_chat_assistant_settings()
        self.bm25 = BM25Retriever()
        self.vector = ChromaRetriever()

    def search(self, query: str, documents: list[KnowledgeDocument]) -> list[RetrievedDocument]:
        bm25 = self.bm25.search(query, documents, int(self.settings.bm25_top_k))
        vector = self.vector.search(query, documents, int(self.settings.vector_top_k))
        merged: dict[str, tuple[KnowledgeDocument, float]] = {}
        for rank, item in enumerate(bm25, start=1):
            merged[item.document.document_id] = (item.document, merged.get(item.document.document_id, (item.document, 0.0))[1] + 1.0 / (int(self.settings.reciprocal_rank_constant) + rank))
        for rank, item in enumerate(vector, start=1):
            merged[item.document.document_id] = (item.document, merged.get(item.document.document_id, (item.document, 0.0))[1] + 1.0 / (int(self.settings.reciprocal_rank_constant) + rank))
        candidates = [RetrievedDocument(doc, score) for doc, score in merged.values()]
        candidates.sort(key=lambda item: item.score, reverse=True)
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
            re.search(r"\b(compare|comparison|difference|explain|why|how|paano|bakit|pagkakaiba)\b", query, re.I)
        )
        if self.settings.reranker_enabled and candidates and ambiguous and complex_query:
            try:
                from sentence_transformers import CrossEncoder
                model = CrossEncoder(self.settings.reranker_model)
                scores = model.predict([(query, item.document.text) for item in candidates])
                candidates = [RetrievedDocument(item.document, float(score)) for item, score in zip(candidates, scores)]
                candidates.sort(key=lambda item: item.score, reverse=True)
            except Exception:
                pass
        return candidates[:int(self.settings.final_top_k)]


class OllamaClient:
    """Minimal local Ollama chat client with no Python SDK dependency."""

    def __init__(self) -> None:
        self.settings = get_chat_assistant_settings()


    def check_available(self) -> None:
        """Fast local health check used before each submitted chat question."""

        url = self.settings.ollama_base_url.rstrip("/") + "/api/tags"
        req = request.Request(url, method="GET")
        try:
            with request.urlopen(
                req,
                timeout=float(self.settings.ollama_health_timeout_seconds),
            ) as response:
                response.read(1)
        except (error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeServiceUnavailableError("ollama", cause=exc) from exc

    def generate(self, prompt: str, *, quality: bool = False) -> str | None:
        url = self.settings.ollama_base_url.rstrip("/") + "/api/generate"
        payload = json.dumps({
            "model": (
                self.settings.quality_ollama_model
                if quality
                else self.settings.ollama_model
            ),
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
        req = request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with request.urlopen(req, timeout=float(self.settings.ollama_timeout_seconds)) as response:
                data = json.loads(response.read().decode("utf-8"))
            value = _clean_model_answer(str(data.get("response", "")))
            return value or None
        except (error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeServiceUnavailableError("ollama", cause=exc) from exc
        except ValueError as exc:
            raise RuntimeServiceUnavailableError("ollama", cause=exc) from exc


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
        except RuntimeServiceUnavailableError as exc:
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

    def enhance(
        self,
        *,
        current_user: AuthenticatedUser,
        role_scope: str,
        question: str,
        history: list[dict] | None,
        deterministic_response: HRAssistantResponse,
    ) -> HRAssistantResponse:
        if not self.settings.enabled:
            return deterministic_response
        if deterministic_response.intent in self._NEVER_ENHANCE_INTENTS:
            return deterministic_response

        is_yes_no = self._is_yes_no_question(question)
        is_follow_up = self._is_follow_up_question(question, history)

        # Exact live answers stay deterministic unless the user explicitly
        # asked a binary question or an incomplete follow-up needs resolution.
        if (
            deterministic_response.intent in self._DIRECT_LIVE_INTENTS
            and not is_yes_no
            and not is_follow_up
        ):
            return HRAssistantResponse(
                answer=_organize_answer(deterministic_response.answer),
                intent=deterministic_response.intent,
                actions=deterministic_response.actions,
                sources=deterministic_response.sources,
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
        if not needs_ai:
            return HRAssistantResponse(
                answer=_organize_answer(deterministic_response.answer),
                intent=deterministic_response.intent,
                actions=deterministic_response.actions,
                sources=deterministic_response.sources,
            )

        documents = PortalKnowledgeBuilder(self.session).build(
            current_user=current_user,
            role_scope=role_scope,
        )
        retrieval_query = self._contextual_search_query(question, history)
        retrieved = self.retriever.search(retrieval_query, documents)

        if self._is_out_of_scope_question(
            question=question,
            history=history,
            deterministic_intent=deterministic_response.intent,
            retrieved=retrieved,
        ):
            return HRAssistantResponse(
                answer=OUT_OF_SCOPE_ANSWER,
                intent="out_of_scope",
                actions=[],
                sources=[],
            )

        context = "\n\n".join(
            f"[{index}] {item.document.title}\n{item.document.text}"
            for index, item in enumerate(retrieved, start=1)
        ) or "No additional approved portal context was retrieved."

        role_rule = (
            "You may use authorized company-wide records provided in the deterministic answer."
            if role_scope == "admin"
            else "You may use only the signed-in employee's own private records and company-wide published information."
        )
        prompt = build_hr_assistant_prompt(
            role_rule=role_rule,
            history_text=self._history_text(history),
            question=question,
            router_answer=deterministic_response.answer,
            context=context,
            question_mode="yes_no" if is_yes_no else "standard",
            follow_up=is_follow_up,
            current_datetime_text=datetime.now(
                ZoneInfo(get_settings().display_timezone)
            ).strftime("%Y/%m/%d %I:%M %p %Z"),
        )
        use_quality_model = asks_for_explanation and (
            len(question_tokens) >= int(self.settings.quality_min_question_tokens)
            or len(retrieved) >= int(self.settings.quality_min_retrieved_documents)
        )
        try:
            generated = self.ollama.generate(prompt, quality=use_quality_model)
        except RuntimeServiceUnavailableError as exc:
            issue = classify_runtime_connection_issue(exc, service_hint="ollama")
            if issue is None:
                raise
            log_runtime_connection_issue(
                exc,
                issue,
                context=f"chat_enhancement:{role_scope}",
            )
            fallback_answer = (
                UNDETERMINED_ANSWER
                if is_yes_no
                else _organize_answer(deterministic_response.answer)
            )
            return HRAssistantResponse(
                answer=fallback_answer,
                intent=deterministic_response.intent,
                actions=deterministic_response.actions,
                sources=deterministic_response.sources,
                report=deterministic_response.report,
                runtime_warning=issue.message,
                runtime_warning_title=issue.title,
                runtime_warning_code=issue.code,
            )
        if not generated:
            fallback_answer = (
                UNDETERMINED_ANSWER
                if is_yes_no
                else _organize_answer(deterministic_response.answer)
            )
            return HRAssistantResponse(
                answer=fallback_answer,
                intent=deterministic_response.intent,
                actions=deterministic_response.actions,
                sources=deterministic_response.sources,
                report=deterministic_response.report,
            )
        final_answer = (
            self._normalize_yes_no_answer(generated)
            if is_yes_no
            else self._normalize_standard_answer(generated)
        )
        return HRAssistantResponse(
            answer=final_answer,
            intent=deterministic_response.intent,
            actions=deterministic_response.actions,
            sources=deterministic_response.sources,
        )
