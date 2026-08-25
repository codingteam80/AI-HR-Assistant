"""Context-aware employee HR Assistant.

The assistant uses only:
- The signed-in employee's company-scoped records
- Live leave credits, leave requests, and configured leave types
- Approved company policies
- Existing HR application modules and routes

It does not use outside knowledge or invent unavailable company information.
"""

from dataclasses import dataclass, field
from decimal import Decimal
import re
import unicodedata

from sqlalchemy.orm import Session

from authentication.current_user import AuthenticatedUser
from models.leave_type import LeaveType
from modules.policy_qa.policy_assistant import PolicyAssistant
from repositories.employee_repository import EmployeeRepository
from services.employee_hierarchy_service import EmployeeHierarchyService
from services.leave_service import LeaveService
from services.chat_report_service import ChatReportService
from services.disciplinary_record_service import DisciplinaryRecordService
from services.policy_service import PolicySource
from services.policy_violation_service import PolicyViolationService


@dataclass(frozen=True, slots=True)
class HRAssistantAction:
    """One safe in-app navigation action shown below an answer."""

    label: str
    page: str
    portal_mode: str = "employee"
    query_params: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class HRAssistantResponse:
    """Assistant answer, sources, intent, and related navigation."""

    answer: str
    intent: str
    actions: list[HRAssistantAction] = field(default_factory=list)
    sources: list[PolicySource] = field(default_factory=list)
    report: dict[str, object] | None = None
    runtime_warning: str | None = None
    runtime_warning_title: str | None = None
    runtime_warning_code: str | None = None


class HRAssistant:
    """Route employee HR questions using keywords and conversation context."""

    _COMMON_LEAVE_ALIASES = {
        "vac leave": "vacation leave",
        "unpaid leave": "leave without pay",
        "lwop": "leave without pay",
        "vl": "vacation leave",
        "sl": "sick leave",
        "el": "emergency leave",
    }

    _DISPLAY_CODES = {
        "vacation leave": "VL",
        "sick leave": "SL",
        "emergency leave": "EL",
        "leave without pay": "LWOP",
    }

    _TAGALOG_MARKERS = {
        "ako",
        "akin",
        "ano",
        "ilan",
        "ko",
        "mag",
        "magfile",
        "nalang",
        "natitira",
        "paano",
        "pwede",
        "saan",
        "yung",
        "yun",
    }

    _FOLLOW_UP_MARKERS = {
        "about it",
        "about that",
        "and el",
        "and sl",
        "and vl",
        "approve it",
        "approves it",
        "how about",
        "how many left",
        "ilan nalang",
        "ilan na lang",
        "ito",
        "naman",
        "paano naman",
        "that request",
        "the same request",
        "this request",
        "what about",
        "what happens next",
        "who approves",
        "who needs to approve",
        "yun",
    }

    _BALANCE_TERMS = {
        "available",
        "balance",
        "credit",
        "credits",
        "how many",
        "ilan",
        "left",
        "nalang",
        "natitira",
        "remaining",
    }

    _FILE_LEAVE_TERMS = {
        "apply for leave",
        "apply leave",
        "file a leave",
        "file leave",
        "how to file",
        "mag file",
        "magfile",
        "request leave",
        "submit leave",
    }

    _REQUEST_STATUS_TERMS = {
        "approved",
        "history",
        "pending",
        "rejected",
        "latest leave request",
        "leave request status",
        "request history",
        "request status",
        "requests ko",
        "status",
        "status ng request",
        "track",
    }

    _POLICY_TERMS = {
        "company policy",
        "guideline",
        "policy",
        "policies",
        "procedure",
        "rule",
        "rules",
        "violation",
        "violations",
        "offense",
        "offenses",
        "penalty",
        "penalties",
        "disciplinary",
        "sanction",
        "sanctions",
    }

    def __init__(self, session: Session) -> None:
        self.session = session
        self.leave_service = LeaveService(session)
        self.employee_repository = EmployeeRepository(session)
        self.employee_hierarchy_service = EmployeeHierarchyService(session)
        self.policy_assistant = PolicyAssistant(session)
        self.violation_service = PolicyViolationService(session)
        self.disciplinary_service = DisciplinaryRecordService(session)

    @classmethod
    def normalize_query(cls, value: str) -> str:
        """Normalize casing, punctuation, spacing, and common shorthand."""

        normalized = unicodedata.normalize("NFKC", value or "").casefold()
        normalized = normalized.replace("-", " ")
        normalized = re.sub(r"[^a-z0-9@._\s]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        for alias, expansion in sorted(
            cls._COMMON_LEAVE_ALIASES.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            normalized = re.sub(
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                expansion,
                normalized,
            )

        return re.sub(r"\s+", " ", normalized).strip()

    @classmethod
    def _is_tagalog(cls, value: str) -> bool:
        """Detect common Tagalog wording for same-language direct answers."""

        tokens = set(cls.normalize_query(value).split())
        return bool(tokens & cls._TAGALOG_MARKERS)

    @staticmethod
    def _format_days(value) -> str:
        """Format Decimal leave days without unnecessary trailing zeros."""

        return f"{Decimal(value):.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _status_label(value: str) -> str:
        """Convert leave workflow values into employee-facing labels."""

        labels = {
            "pending_manager_approval": "Pending Manager Approval",
            "scheduled": "Approved / Scheduled",
            "approved": "Approved",
            "in_progress": "In Progress",
            "completed": "Completed",
            "rejected": "Rejected",
        }
        return labels.get(value, value.replace("_", " ").title())

    @staticmethod
    def _history_user_questions(history: list[dict] | None) -> list[str]:
        """Return recent user questions from Streamlit-safe dictionaries."""

        if not history:
            return []

        return [
            str(message.get("content", "")).strip()
            for message in history
            if message.get("role") == "user"
            and str(message.get("content", "")).strip()
        ][-3:]

    @staticmethod
    def _history_last_assistant_intent(
        history: list[dict] | None,
    ) -> str | None:
        """Return the latest assistant intent from this private chat."""

        if not history:
            return None

        for message in reversed(history):
            if message.get("role") != "assistant":
                continue

            intent = str(
                message.get(
                    "intent",
                    "",
                )
            ).strip()

            if intent and intent != "welcome":
                return intent

        return None

    @staticmethod
    def _contains_any(
        value: str,
        terms: set[str],
    ) -> bool:
        """Return True when at least one keyword or phrase is present."""

        return any(
            term in value
            for term in terms
        )

    @classmethod
    def looks_like_employee_hierarchy_query(cls, value: str) -> bool:
        """Recognize varied English/Tagalog member and supervisor questions.

        The actual role is never inferred here.  This method only routes the
        question to the hierarchy handler; Manager/Leader status is determined
        later from live ``manager_id`` / ``leader_id`` assignments.
        """

        query = cls.normalize_query(value)
        if not query:
            return False

        direct_phrases = {
            "my member",
            "my members",
            "member ko",
            "members ko",
            "member ni",
            "members ni",
            "member niya",
            "members niya",
            "member nya",
            "members nya",
            "members of",
            "member of",
            "team member",
            "team members",
            "direct report",
            "direct reports",
            "reports to me",
            "who reports to",
            "who reports",
            "has a member",
            "has member",
            "has members",
            "have a member",
            "have member",
            "have members",
            "may member",
            "may members",
            "may mga member",
            "sino member",
            "sino ang member",
            "sino members",
            "sino ang members",
            "who is under",
            "who are under",
            "who works under",
            "under me",
            "under him",
            "under her",
            "under them",
            "hawak kong member",
            "hawak niyang member",
            "hawak nyang member",
            "leader or manager",
            "leader o manager",
            "manager or leader",
            "manager o leader",
            "my manager",
            "my leader",
            "manager ko",
            "leader ko",
            "manager niya",
            "leader niya",
            "manager nya",
            "leader nya",
            "manager ni",
            "leader ni",
            "manager of",
            "leader of",
            "reports to whom",
            "who manages",
            "who leads",
            "hierarchy role",
            "supervisory role",
            "am i a leader",
            "am i a manager",
            "leader ba",
            "manager ba",
        }
        if any(phrase in query for phrase in direct_phrases):
            return True

        patterns = (
            r"\bmembers?\s+(?:of|ni|ng|kay)\b",
            r"\bmay\s+(?:mga\s+)?members?\b",
            r"\b(?:who|sino)\s+(?:is|are|ang|mga)?\s*(?:under|members?)\b",
            r"\b(?:team|members?|direct reports?|subordinates?)\s+(?:handled|managed|led)\s+by\b",
            r"\b(?:handle|handles|handling|hawak)\b.*\b(?:team|members?|people|employees?)\b",
            r"\b(?:manage|manages|managing|lead|leads|leading)\b.*\b(?:team|members?|people|employees?)\b",
            r"\b(?:is|si)\b.*\b(?:a\s+)?(?:leader|manager)\b",
            r"\b(?:leader|manager)\b.*\b(?:ba|role|members?|team)\b",
            r"\b(?:who|sino)\b.*\b(?:manager|leader)\b",
            r"\b(?:manager|leader)\s+(?:of|ni|ng|kay)\b",
            r"\b(?:who|sino)\b.*\b(?:manages|leads|manager\s+of|leader\s+of)\b",
            r"\b(?:reports?\s+to|nag\s*rereport\s+kay|nagre-report\s+kay)\b",
        )
        return any(re.search(pattern, query) for pattern in patterns)

    @classmethod
    def _has_leave_context(
        cls,
        value: str,
    ) -> bool:
        """Recognize leave wording after shorthand expansion."""

        return any(
            term in value
            for term in (
                "leave",
                "vacation",
                "sick",
                "emergency",
                "lwop",
            )
        )

    @classmethod
    def _classify_normalized_query(
        cls,
        query: str,
    ) -> str:
        """Classify one normalized question without conversation history."""

        leave_context = cls._has_leave_context(
            query
        )

        if cls._contains_any(
            query,
            {
                "what can you do",
                "help me",
                "help",
                "capabilities",
                "anong kaya mo",
            },
        ):
            return "help"

        if (
            leave_context
            and cls._contains_any(
                query,
                {
                    "carry over",
                    "carryover",
                    "carried over",
                    "roll over",
                    "rollover",
                },
            )
        ):
            return "leave_carryover"

        if (
            leave_context
            and cls._contains_any(
                query,
                cls._BALANCE_TERMS,
            )
        ):
            return "leave_balance"

        if (
            leave_context
            and cls._contains_any(
                query,
                cls._FILE_LEAVE_TERMS,
            )
        ):
            return "file_leave"

        if (
            leave_context
            and cls._contains_any(
                query,
                cls._REQUEST_STATUS_TERMS,
            )
        ):
            return "leave_request_status"

        if (
            leave_context
            and cls._contains_any(
                query,
                {
                    "annual allocation",
                    "handover",
                    "meaning",
                    "minimum notice",
                    "paid",
                    "requirement",
                    "what is",
                    "ano ang",
                    "ano ibig sabihin",
                },
            )
        ):
            return "leave_type_details"

        if cls.looks_like_employee_hierarchy_query(query):
            return "employee_hierarchy"

        if cls._contains_any(
            query,
            {
                "my manager",
                "manager ko",
                "my department",
                "department ko",
                "my profile",
                "my employee info",
                "my employee information",
                "employee number",
                "job title",
                "hire date",
                "work email",
                "employment status",
                "profile ko",
            },
        ):
            return "employee_profile"

        # Recognizable new topics are evaluated before chat history.
        if cls._contains_any(
            query,
            cls._POLICY_TERMS,
        ):
            return "policy"

        if cls._contains_any(
            query,
            {
                "attendance",
                "dtr",
                "time in",
                "time out",
                "overtime",
                "work status",
                "login attendance",
                "logout attendance",
            },
        ):
            return "attendance"

        if cls._contains_any(
            query,
            {
                "company form",
                "company forms",
                "download form",
                "fill form",
                "submit form",
                "form submission",
            },
        ):
            return "company_forms"

        if cls._contains_any(
            query,
            {
                "certificate of employment",
                "coe",
                "document",
                "documents",
                "my files",
                "payslip",
                "request a file",
                "request file",
            },
        ):
            return "documents"

        if "benefit" in query:
            return "benefits"

        if cls._contains_any(
            query,
            {
                "onboarding",
                "orientation",
                "training",
            },
        ):
            return "onboarding"

        if cls._contains_any(
            query,
            {
                "contact hr",
                "hr contact",
                "raise concern",
                "report concern",
                "complaint",
                "concern",
            },
        ):
            return "hr_contacts"

        if cls._contains_any(
            query,
            {
                "announcement",
                "company update",
                "event",
            },
        ):
            return "announcements"

        if cls._contains_any(
            query,
            {
                "faq",
                "frequently asked",
            },
        ):
            return "faq"

        if leave_context:
            return "leave_overview"

        return "policy_fallback"

    @classmethod
    def _is_explicit_follow_up(
        cls,
        current: str,
    ) -> bool:
        """Allow history only for genuinely incomplete follow-up wording."""

        if not current:
            return False

        return any(
            re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", current)
            for marker in cls._FOLLOW_UP_MARKERS
        )

    @classmethod
    def _contextual_query(
        cls,
        question: str,
        history: list[dict] | None,
    ) -> str:
        """Use prior topic only for an explicit ambiguous follow-up."""

        current = cls.normalize_query(
            question
        )

        standalone_intent = cls._classify_normalized_query(current)
        explicit_follow_up = cls._is_explicit_follow_up(current)

        # A complete recognizable topic normally starts fresh. Safe exceptions
        # are intentionally incomplete follow-ups such as "How about SL?" or
        # "What about the second offense?". Policy follow-ups inherit context
        # only when the previous assistant topic was also policy/violation.
        policy_follow_up = (
            standalone_intent == "policy"
            and explicit_follow_up
        )
        if (
            standalone_intent != "policy_fallback"
            and not (
                standalone_intent == "leave_overview"
                and explicit_follow_up
            )
            and not policy_follow_up
        ):
            return current

        if not explicit_follow_up:
            return current

        previous_questions = (
            cls._history_user_questions(
                history
            )
        )
        previous_intent = (
            cls._history_last_assistant_intent(
                history
            )
        )

        if (
            not previous_questions
            or previous_intent is None
        ):
            return current

        if policy_follow_up and previous_intent not in {
            "policy",
            "policy_fallback",
            "policy_violation",
        }:
            return current

        previous = cls.normalize_query(
            previous_questions[-1]
        )

        return f"{previous} {current}".strip()

    @classmethod
    def classify_intent(
        cls,
        question: str,
        *,
        history: list[dict] | None = None,
    ) -> str:
        """Classify a new topic first, then resolve true follow-ups."""

        current = cls.normalize_query(
            question
        )
        standalone_intent = (
            cls._classify_normalized_query(
                current
            )
        )

        if (
            standalone_intent != "policy_fallback"
            and not (
                standalone_intent == "leave_overview"
                and cls._is_explicit_follow_up(current)
            )
        ):
            return standalone_intent

        contextual = cls._contextual_query(
            question,
            history,
        )

        if contextual == current:
            return standalone_intent

        return cls._classify_normalized_query(
            contextual
        )

    @classmethod
    def _leave_type_aliases(cls, leave_type: LeaveType) -> set[str]:
        """Return normalized dynamic aliases for one configured leave type."""

        name = cls.normalize_query(leave_type.name)
        code = cls.normalize_query(leave_type.code)
        aliases = {name, code}

        for alias, expansion in cls._COMMON_LEAVE_ALIASES.items():
            if expansion == name or expansion in name or name in expansion:
                aliases.add(cls.normalize_query(alias))
                aliases.add(expansion)

        return {value for value in aliases if value}

    @classmethod
    def _display_code(cls, leave_type: LeaveType) -> str:
        """Use familiar shorthand for defaults and configured code otherwise."""

        normalized_name = cls.normalize_query(leave_type.name)
        return cls._DISPLAY_CODES.get(normalized_name, leave_type.code)

    @classmethod
    def _requested_leave_type(
        cls,
        query: str,
        leave_types: list[LeaveType],
    ) -> LeaveType | None:
        """Match shorthand, full name, or configured leave code."""

        normalized = cls.normalize_query(query)
        candidates: list[tuple[int, LeaveType]] = []

        for leave_type in leave_types:
            for alias in cls._leave_type_aliases(leave_type):
                if alias in normalized:
                    candidates.append((len(alias), leave_type))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _employee_record(self, current_user: AuthenticatedUser):
        """Load the signed-in employee with manager and department details."""

        if current_user.employee_id is None:
            return None

        return self.employee_repository.get_with_details(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
        )

    @staticmethod
    def _leave_carryover_answer() -> HRAssistantResponse:
        """Return the implemented annual SL/VL carry-over rule exactly."""

        return HRAssistantResponse(
            answer=(
                "**YES.** Unused annual Sick Leave and Vacation Leave balances "
                "can carry into the next leave-year ledger. Applicable year-end "
                "Vacation Leave utilization/forfeiture and retained cash-conversion "
                "rules are applied before the remaining balance becomes the next "
                "year's beginning credit; other leave types are not part of this "
                "annual SL/VL carry-over rule."
            ),
            intent="leave_carryover",
            actions=[
                HRAssistantAction(
                    label="View Leave Credits",
                    page="Leave Management",
                    query_params={"leave_view": "credits"},
                )
            ],
        )

    def _leave_overview_answer(
        self,
    ) -> HRAssistantResponse:
        """Start a fresh general leave topic without using old context."""

        return HRAssistantResponse(
            answer=(
                "I can help with leave credits, filing a leave request, "
                "request status, and configured leave rules. You may ask "
                "using VL, SL, EL, LWOP, or the complete leave name."
            ),
            intent="leave_overview",
            actions=[
                HRAssistantAction(
                    label="Open Leave Management",
                    page="Leave Management",
                ),
                HRAssistantAction(
                    label="File Leave Request",
                    page="Leave Management",
                    query_params={
                        "leave_view": "file",
                    },
                ),
                HRAssistantAction(
                    label="View Leave Credits",
                    page="Leave Management",
                    query_params={
                        "leave_view": "overview",
                    },
                ),
            ],
        )

    def _leave_balance_answer(
        self,
        *,
        current_user: AuthenticatedUser,
        question: str,
        contextual_query: str,
    ) -> HRAssistantResponse:
        """Return live employee leave-credit data."""

        action = HRAssistantAction(
            label="View Leave Credit Details",
            page="Leave Management",
            query_params={"leave_view": "overview"},
        )

        if current_user.employee_id is None:
            return HRAssistantResponse(
                answer=(
                    "Your login account is not linked to an employee record, "
                    "so leave credits cannot be retrieved."
                ),
                intent="leave_balance",
                actions=[action],
            )

        self.leave_service.reconcile_approved_leave(
            company_id=current_user.company_id
        )
        balances = self.leave_service.list_employee_balances(
            current_user.company_id,
            current_user.employee_id,
        )
        leave_types = [balance.leave_type for balance in balances]
        # Prefer an explicit leave type in the current follow-up (e.g. SL in
        # "How about SL?") before falling back to the combined history query.
        selected_type = (
            self._requested_leave_type(question, leave_types)
            or self._requested_leave_type(contextual_query, leave_types)
        )
        vacation_combined = False
        if selected_type is not None:
            selected_code = selected_type.code.upper()
            if selected_code == "VACATION":
                balances = [
                    balance
                    for balance in balances
                    if balance.leave_type.code.upper()
                    in {"VACATION", "EMERGENCY"}
                ]
                vacation_combined = True
            else:
                balances = [
                    balance
                    for balance in balances
                    if balance.leave_type_id == selected_type.id
                ]

        if not balances:
            return HRAssistantResponse(
                answer="No leave credits are configured for your employee record.",
                intent="leave_balance",
                actions=[action],
            )

        tagalog = self._is_tagalog(question)
        year = balances[0].year
        lines = [
            (
                f"Narito ang leave credit breakdown mo para sa {year}:"
                if tagalog
                else f"Your leave credit breakdown for {year}:"
            )
        ]

        if vacation_combined:
            vacation = next(
                balance
                for balance in balances
                if balance.leave_type.code.upper() == "VACATION"
            )
            emergency = next(
                (
                    balance
                    for balance in balances
                    if balance.leave_type.code.upper() == "EMERGENCY"
                ),
                None,
            )
            emergency_remaining = (
                emergency.remaining_days
                if emergency is not None
                else Decimal("0.00")
            )
            emergency_reserved = (
                emergency.reserved_days
                if emergency is not None
                else Decimal("0.00")
            )
            emergency_used = (
                emergency.used_days
                if emergency is not None
                else Decimal("0.00")
            )
            emergency_allocated = (
                emergency.allocated_days
                if emergency is not None
                else Decimal("0.00")
            )
            lines.append(
                f"- **VL — Vacation Leave:** "
                f"{self._format_days(Decimal(vacation.remaining_days) + Decimal(emergency_remaining))} available"
                f" | {self._format_days(Decimal(vacation.reserved_days) + Decimal(emergency_reserved))} reserved"
                f" | {self._format_days(Decimal(vacation.used_days) + Decimal(emergency_used))} used"
                f" | {self._format_days(Decimal(vacation.allocated_days) + Decimal(emergency_allocated))} annual allocation"
                f" (includes {self._format_days(emergency_allocated)} Emergency Leave)"
            )
        else:
            for balance in balances:
                leave_type = balance.leave_type
                lines.append(
                    f"- **{self._display_code(leave_type)} — {leave_type.name}:** "
                    f"{self._format_days(balance.remaining_days)} available"
                    f" | {self._format_days(balance.reserved_days)} reserved"
                    f" | {self._format_days(balance.used_days)} used"
                    f" | {self._format_days(balance.allocated_days)} annual allocation"
                )

        lines.append(
            (
                "\nAng pending request ay hindi pa binabawas. Kapag approved, "
                "reserved muna ang credits at magiging used sa mismong approved "
                "leave dates."
                if tagalog
                else (
                    "\nPending requests do not reduce credits. Once approved, "
                    "credits are reserved and become used on the approved leave dates."
                )
            )
        )

        return HRAssistantResponse(
            answer="\n".join(lines),
            intent="leave_balance",
            actions=[action],
        )

    def _file_leave_answer(
        self,
        *,
        current_user: AuthenticatedUser,
        question: str,
        contextual_query: str,
    ) -> HRAssistantResponse:
        """Explain the actual leave-request workflow and link to the form."""

        self.leave_service.ensure_default_leave_types(
            current_user.company_id
        )
        leave_types = self.leave_service.list_leave_types(
            current_user.company_id,
            active_only=True,
        )
        selected_type = self._requested_leave_type(contextual_query, leave_types)
        type_label = selected_type.name if selected_type is not None else "leave"
        tagalog = self._is_tagalog(question)

        if tagalog:
            lines = [
                f"Para mag-file ng **{type_label}**:",
                "1. Buksan ang **Leave Management**.",
                "2. Piliin ang **File Leave Request**.",
                "3. Piliin ang leave type at ilagay ang start at end date.",
                "4. Automatic na kakalkulahin ang Monday-to-Friday working days.",
                "5. Ilagay ang reason at handover plan/countermeasure kapag kailangan.",
                "6. I-send ang request sa assigned manager. Automatic ang To at CC recipients.",
                (
                    "\nHindi pa mababawas ang credits habang pending. Kapag approved, "
                    "reserved muna at magiging used sa approved leave dates."
                ),
            ]
        else:
            lines = [
                f"To file **{type_label}**:",
                "1. Open **Leave Management**.",
                "2. Select **File Leave Request**.",
                "3. Choose the leave type and enter the start and end dates.",
                "4. The system automatically calculates Monday-to-Friday working days.",
                "5. Enter the reason and the handover plan/countermeasure when required.",
                "6. Send the request to the assigned manager. To and CC recipients are filled automatically.",
                (
                    "\nCredits are unchanged while the request is pending. After approval, "
                    "credits are reserved and become used on the approved leave dates."
                ),
            ]

        if selected_type is not None:
            rule_credits = Decimal(selected_type.annual_credits)
            rule_note = ""
            if selected_type.code.upper() == "VACATION":
                emergency_type = next(
                    (
                        item
                        for item in leave_types
                        if item.code.upper() == "EMERGENCY"
                    ),
                    None,
                )
                if emergency_type is not None:
                    rule_credits += Decimal(emergency_type.annual_credits)
                    rule_note = (
                        f" including {self._format_days(emergency_type.annual_credits)} "
                        "Emergency Leave"
                    )
            lines.append(
                f"\n**{self._display_code(selected_type)} rule:** "
                f"{self._format_days(rule_credits)} annual credits{rule_note} | "
                f"{selected_type.minimum_notice_days} day(s) minimum notice | "
                f"handover plan {selected_type.handover_plan_requirement}."
            )

        return HRAssistantResponse(
            answer="\n".join(lines),
            intent="file_leave",
            actions=[
                HRAssistantAction(
                    label="File Leave Request",
                    page="Leave Management",
                    query_params={"leave_view": "file"},
                )
            ],
        )

    def _leave_request_status_answer(
        self,
        *,
        current_user: AuthenticatedUser,
        question: str,
    ) -> HRAssistantResponse:
        """Return the signed-in employee's recent leave-request statuses."""

        action = HRAssistantAction(
            label="View My Leave Requests",
            page="Leave Management",
            query_params={"leave_view": "requests"},
        )
        if current_user.employee_id is None:
            return HRAssistantResponse(
                answer=(
                    "Your account is not linked to an employee record, "
                    "so leave requests cannot be retrieved."
                ),
                intent="leave_request_status",
                actions=[action],
            )

        self.leave_service.reconcile_approved_leave(
            company_id=current_user.company_id
        )
        requests = self.leave_service.list_employee_requests(
            current_user.company_id,
            current_user.employee_id,
        )
        tagalog = self._is_tagalog(question)

        if not requests:
            answer = (
                "Wala ka pang na-file na leave request."
                if tagalog
                else "You have not submitted a leave request yet."
            )
        else:
            normalized_question = self.normalize_query(question)
            asks_latest = any(
                term in normalized_question
                for term in ("latest", "most recent", "pinakahuli")
            )
            selected_requests = requests[:1] if asks_latest else requests[:5]
            if asks_latest:
                lines = [
                    "Ito ang latest leave request mo:"
                    if tagalog
                    else "Your latest leave request:"
                ]
            else:
                lines = [
                    "Narito ang latest leave requests mo:"
                    if tagalog
                    else "Here are your latest leave requests:"
                ]
            for request in selected_requests:
                lines.append(
                    f"- **{request.public_id} — {request.leave_type.name}:** "
                    f"{request.start_date.isoformat()} to {request.end_date.isoformat()} | "
                    f"{self._format_days(request.requested_days)} day(s) | "
                    f"{self._status_label(request.status)}"
                )
            answer = "\n".join(lines)

        return HRAssistantResponse(
            answer=answer,
            intent="leave_request_status",
            actions=[action],
        )

    def _leave_type_details_answer(
        self,
        *,
        current_user: AuthenticatedUser,
        contextual_query: str,
    ) -> HRAssistantResponse:
        """Explain configured leave codes and basic operational rules."""

        self.leave_service.ensure_default_leave_types(
            current_user.company_id
        )
        leave_types = self.leave_service.list_leave_types(
            current_user.company_id,
            active_only=True,
        )
        selected_type = self._requested_leave_type(contextual_query, leave_types)
        selected = [selected_type] if selected_type is not None else leave_types

        if not selected:
            return HRAssistantResponse(
                answer="No active leave types are configured.",
                intent="leave_type_details",
            )

        lines = ["Configured leave types and operational rules:"]
        emergency_type = next(
            (
                item
                for item in leave_types
                if item.code.upper() == "EMERGENCY"
            ),
            None,
        )
        for leave_type in selected:
            display_credits = Decimal(leave_type.annual_credits)
            detail_note = ""
            if (
                leave_type.code.upper() == "VACATION"
                and emergency_type is not None
            ):
                display_credits += Decimal(emergency_type.annual_credits)
                detail_note = (
                    f" including {self._format_days(emergency_type.annual_credits)} "
                    "Emergency Leave"
                )
            elif leave_type.code.upper() == "EMERGENCY":
                detail_note = " within the Vacation entitlement"
            elif leave_type.code.upper() == "LWOP":
                detail_note = " and automatic when paid credits are insufficient"

            lines.append(
                f"- **{self._display_code(leave_type)} — {leave_type.name}:** "
                f"{self._format_days(display_credits)} annual credits{detail_note} | "
                f"{'Paid' if leave_type.is_paid else 'Unpaid'} | "
                f"{leave_type.minimum_notice_days} day(s) minimum notice | "
                f"handover plan {leave_type.handover_plan_requirement}"
            )

        lines.append(
            "\nFor eligibility conditions or formal company rules, ask the policy "
            "question directly so the answer can be taken from approved policy files."
        )
        return HRAssistantResponse(
            answer="\n".join(lines),
            intent="leave_type_details",
            actions=[
                HRAssistantAction(label="Open Leave Management", page="Leave Management"),
                HRAssistantAction(label="Open Company Policies", page="Company Policies"),
            ],
        )


    def _employee_hierarchy_answer(
        self,
        *,
        current_user: AuthenticatedUser,
        question: str,
    ) -> HRAssistantResponse:
        """Describe only the signed-in employee's actual assignment hierarchy."""

        employee = self._employee_record(current_user)
        if employee is None:
            return HRAssistantResponse(
                answer="Your login account is not linked to an employee master record.",
                intent="employee_hierarchy",
            )

        normalized = self.normalize_query(question)
        own_number = self.normalize_query(employee.employee_number)
        own_name = self.normalize_query(employee.full_name)
        personal_markers = (
            " my ", " me ", " i ", " ako ", " ko ", " akin ",
        )
        padded = f" {normalized} "
        self_scoped = (
            any(marker in padded for marker in personal_markers)
            or (own_number and own_number in normalized)
            or (own_name and own_name in normalized)
        )
        if not self_scoped:
            return HRAssistantResponse(
                answer=(
                    "You can view only your own Manager/Leader relationships and "
                    "members available to your signed-in employee assignment."
                ),
                intent="employee_hierarchy",
            )

        snapshot = self.employee_hierarchy_service.snapshot(
            company_id=current_user.company_id,
            employee_id=employee.id,
        )
        if snapshot is None:
            return HRAssistantResponse(
                answer="Your employee hierarchy record is no longer available.",
                intent="employee_hierarchy",
            )

        lines = [
            "Your current employee hierarchy is based on actual Manager/Leader selections in Employee Master:",
            f"- **Hierarchy Role:** {snapshot.role_label}",
            f"- **Your Manager:** {snapshot.manager.full_name if snapshot.manager else 'Not assigned'}",
            f"- **Your Leader:** {snapshot.leader.full_name if snapshot.leader else 'Not assigned'}",
            f"- **Manager Direct Reports:** {len(snapshot.manager_reports)}",
            f"- **Leader Team Members:** {len(snapshot.leader_members)}",
        ]
        if snapshot.manager_reports:
            lines.append("- **Assigned as Manager for:** " + ", ".join(
                f"{item.employee_number} — {item.full_name}" for item in snapshot.manager_reports
            ))
        if snapshot.leader_members:
            lines.append("- **Assigned as Leader for:** " + ", ".join(
                f"{item.employee_number} — {item.full_name}" for item in snapshot.leader_members
            ))
        lines.append(
            "- **Basis:** reverse Manager/Leader assignments, not job title. You may report to someone above you while also managing or leading employees below you."
        )

        return HRAssistantResponse(
            answer="\n".join(lines),
            intent="employee_hierarchy",
        )

    def _employee_profile_answer(
        self,
        *,
        current_user: AuthenticatedUser,
    ) -> HRAssistantResponse:
        """Return safe employee master-record information to its owner."""

        employee = self._employee_record(current_user)
        if employee is None:
            return HRAssistantResponse(
                answer="Your login account is not linked to an employee master record.",
                intent="employee_profile",
            )

        snapshot = self.employee_hierarchy_service.snapshot(
            company_id=current_user.company_id,
            employee_id=employee.id,
        )
        if snapshot is None:
            return HRAssistantResponse(
                answer="Your employee record is no longer available.",
                intent="employee_profile",
            )

        lines = [
            "Your employee information:",
            f"- **Employee Number:** {employee.employee_number}",
            f"- **Name:** {employee.full_name}",
            f"- **Job Title:** {employee.job_title or 'Not specified'}",
            (
                f"- **Department:** "
                f"{employee.department.name if employee.department else 'Not assigned'}"
            ),
            (
                f"- **Manager:** "
                f"{snapshot.manager.full_name if snapshot.manager else 'Not assigned'}"
            ),
            (
                f"- **Leader:** "
                f"{snapshot.leader.full_name if snapshot.leader else 'Not assigned'}"
            ),
            f"- **Hierarchy Role:** {snapshot.role_label}",
            f"- **Manager Direct Reports:** {len(snapshot.manager_reports)}",
            f"- **Leader Team Members:** {len(snapshot.leader_members)}",
            f"- **Work Email:** {employee.work_email or current_user.email}",
            f"- **Employment Status:** {employee.employment_status.title()}",
            (
                f"- **Hire Date:** "
                f"{employee.hire_date.isoformat() if employee.hire_date else 'Not specified'}"
            ),
        ]
        return HRAssistantResponse(
            answer="\n".join(lines),
            intent="employee_profile",
        )

    def _policy_response(
        self,
        *,
        current_user: AuthenticatedUser,
        question: str,
        intent: str = "policy",
    ) -> HRAssistantResponse | None:
        """Return an approved-policy answer when a relevant section exists."""

        violation_answer = self.violation_service.answer_question(
            company_id=current_user.company_id,
            question=question,
        )
        if violation_answer is not None:
            return HRAssistantResponse(
                answer=violation_answer,
                intent="policy_violation",
                actions=[
                    HRAssistantAction(
                        label="Open Violations & Disciplinary Actions",
                        page="Company Policies",
                        query_params={"policy_view": "violations"},
                    )
                ],
            )

        result = self.policy_assistant.answer(
            company_id=current_user.company_id,
            question=question,
        )
        if not result.matched:
            return None

        return HRAssistantResponse(
            answer=result.answer,
            intent=intent,
            sources=result.sources,
            actions=[
                HRAssistantAction(
                    label="Open Company Policies",
                    page="Company Policies",
                )
            ],
        )

    @staticmethod
    def _module_response(
        *,
        answer: str,
        intent: str,
        label: str,
        page: str,
        query_params: dict[str, str] | None = None,
    ) -> HRAssistantResponse:
        """Create one direct routing answer for an existing HR module."""

        return HRAssistantResponse(
            answer=answer,
            intent=intent,
            actions=[
                HRAssistantAction(
                    label=label,
                    page=page,
                    query_params=dict(query_params or {}),
                )
            ],
        )

    @classmethod
    def _help_response(cls) -> HRAssistantResponse:
        """Describe grounded assistant capabilities without overpromising."""

        return HRAssistantResponse(
            answer=(
                "I can help with:\n"
                "- Live leave-credit breakdowns, including **VL**, **SL**, **EL**, "
                "and configured leave types\n"
                "- Filing leave and where to open the request form\n"
                "- Recent leave-request status\n"
                "- Your employee number, department, manager, leader, job title, and work email\n"
                "- Your actual Manager/Leader member assignments and direct reports\n"
                "- Approved company HR policies with sources\n"
                "- Active company violations and disciplinary-action rules\n"
                "- Your own issued disciplinary records, when Employee Portal visibility is enabled\n"
                "- Attendance / DTR and Company Form/Documents workflows\n"
                "- Navigation to Company Form/Documents, Onboarding Benefits, "
                "HR Contacts, FAQ, and company announcements\n\n"
                "You may use shorthand or full wording. Example: **'Ilan na lang VL ko?'** "
                "or **'How do I file Vacation Leave?'**"
            ),
            intent="help",
        )

    def answer(
        self,
        *,
        current_user: AuthenticatedUser,
        question: str,
        history: list[dict] | None = None,
    ) -> HRAssistantResponse:
        """Answer one employee HR question using context and live records."""

        cleaned_question = (question or "").strip()
        if not cleaned_question:
            return HRAssistantResponse(answer="Please enter an HR question.", intent="empty")

        report_result = ChatReportService(self.session).try_answer(
            current_user=current_user,
            role_scope="employee",
            question=cleaned_question,
            history=history,
        )
        if report_result is not None:
            return HRAssistantResponse(
                answer=report_result.answer,
                intent="live_report",
                report=report_result.report,
            )

        intent = self.classify_intent(
            cleaned_question,
            history=history,
        )
        contextual_query = (
            self._contextual_query(
                cleaned_question,
                history,
            )
            if intent
            in {
                "leave_balance",
                "file_leave",
                "leave_request_status",
                "leave_type_details",
            }
            else self.normalize_query(
                cleaned_question
            )
        )

        if intent == "help":
            return self._help_response()

        disciplinary_answer = self.disciplinary_service.answer_employee_question(
            company_id=current_user.company_id,
            employee_id=current_user.employee_id,
            requester_user_id=current_user.user_id,
            question=cleaned_question,
        )
        if disciplinary_answer is not None:
            return HRAssistantResponse(
                answer=disciplinary_answer,
                intent="disciplinary_records",
                actions=[
                    HRAssistantAction(
                        label="Open My Disciplinary Records",
                        page="Company Policies",
                        query_params={"policy_view": "disciplinary"},
                    )
                ],
            )

        if intent == "leave_overview":
            return self._leave_overview_answer()

        if intent == "leave_carryover":
            return self._leave_carryover_answer()

        if intent == "leave_balance":
            return self._leave_balance_answer(
                current_user=current_user,
                question=cleaned_question,
                contextual_query=contextual_query,
            )
        if intent == "file_leave":
            return self._file_leave_answer(
                current_user=current_user,
                question=cleaned_question,
                contextual_query=contextual_query,
            )
        if intent == "leave_request_status":
            return self._leave_request_status_answer(
                current_user=current_user,
                question=contextual_query,
            )
        if intent == "leave_type_details":
            return self._leave_type_details_answer(
                current_user=current_user,
                contextual_query=contextual_query,
            )
        if intent == "employee_hierarchy":
            return self._employee_hierarchy_answer(
                current_user=current_user,
                question=cleaned_question,
            )
        if intent == "employee_profile":
            return self._employee_profile_answer(current_user=current_user)

        if intent == "policy":
            normalized_question = self.normalize_query(
                cleaned_question
            )

            if normalized_question in {
                "policy",
                "policies",
                "company policy",
            }:
                return HRAssistantResponse(
                    answer=(
                        "Ask a specific company-policy question, or open "
                        "Company Policies to browse active published files."
                    ),
                    intent="policy",
                    actions=[
                        HRAssistantAction(
                            label="Browse Company Policies",
                            page="Company Policies",
                        )
                    ],
                )

            policy_question = (
                self._contextual_query(cleaned_question, history)
                if self._is_explicit_follow_up(self.normalize_query(cleaned_question))
                else cleaned_question
            )
            policy = self._policy_response(
                current_user=current_user,
                question=policy_question,
            )
            if policy is not None:
                return policy
            return HRAssistantResponse(
                answer="Information not found in approved company policies.",
                intent="policy",
                actions=[
                    HRAssistantAction(
                        label="Browse Company Policies",
                        page="Company Policies",
                    )
                ],
            )

        if intent == "documents":
            return self._module_response(
                answer=(
                    "Open **Company Form/Documents** to view the forms and documents "
                    "available from your company. Your completed submissions and their "
                    "review status are available in its **My Documents** tab. For an "
                    "unavailable document, contact HR."
                ),
                intent="documents",
                label="Open Company Form/Documents",
                page="Company Form/Documents",
                query_params={"form_view": "view"},
            )

        if intent == "attendance":
            return self._module_response(
                answer=(
                    "Open **Dashboard** for your Attendance / DTR. You can view "
                    "your monthly attendance, use Login and Logout for today's "
                    "record, save Work Status, and edit your own authorized "
                    "attendance entries."
                ),
                intent="attendance",
                label="Open Attendance / DTR",
                page="Dashboard",
                query_params={"dashboard_view": "attendance"},
            )

        if intent == "company_forms":
            return self._module_response(
                answer=(
                    "Open **Company Form/Documents** to view or download available "
                    "company forms and submit a completed form when submissions are enabled."
                ),
                intent="company_forms",
                label="Open Company Form/Documents",
                page="Company Form/Documents",
                query_params={"form_view": "view"},
            )

        if intent == "benefits":
            policy = self._policy_response(
                current_user=current_user,
                question=cleaned_question,
                intent="benefits_policy",
            )
            if policy is not None:
                policy.actions.append(
                    HRAssistantAction(
                        label="Open Benefits",
                        page="Onboarding",
                        query_params={"onboarding_view": "benefits"},
                    )
                )
                return policy
            return self._module_response(
                answer=(
                    "Open **Onboarding → Benefits** for company-configured benefit information. "
                    "Formal eligibility rules are answered only when they exist in "
                    "approved company policies."
                ),
                intent="benefits",
                label="Open Benefits",
                page="Onboarding",
                query_params={"onboarding_view": "benefits"},
            )

        if intent == "onboarding":
            return self._module_response(
                answer=(
                    "Open **Onboarding** for your progress overview, checklist, and "
                    "permanent company benefits. Policy-specific requirements are "
                    "taken only from approved policy files."
                ),
                intent="onboarding",
                label="Open Onboarding",
                page="Onboarding",
                query_params={"onboarding_view": "overview"},
            )

        if intent == "hr_contacts":
            return self._module_response(
                answer=(
                    "Open **HR Contacts** to find the appropriate HR contact or raise "
                    "a concern that requires human review."
                ),
                intent="hr_contacts",
                label="Open HR Contacts",
                page="HR Contacts",
            )

        if intent == "announcements":
            return self._module_response(
                answer=(
                    "Current company announcements and activities are available on "
                    "the Employee Dashboard."
                ),
                intent="announcements",
                label="Open Announcements",
                page="Dashboard",
                query_params={"dashboard_view": "announcements"},
            )

        if intent == "faq":
            return self._module_response(
                answer="Open **FAQ** for company-configured frequently asked questions.",
                intent="faq",
                label="Open FAQ",
                page="FAQ",
            )

        fallback_question = (
            self._contextual_query(cleaned_question, history)
            if self._is_explicit_follow_up(self.normalize_query(cleaned_question))
            else cleaned_question
        )
        policy = self._policy_response(
            current_user=current_user,
            question=fallback_question,
            intent="policy_fallback",
        )
        if policy is not None:
            return policy

        return HRAssistantResponse(
            answer=(
                "I could not find that information in your live HR records or approved "
                "company policies. Try asking about leave credits, filing leave, request "
                "status, employee details, documents, benefits, onboarding, or HR contacts."
            ),
            intent="not_found",
            actions=[
                HRAssistantAction(label="Open HR Contacts", page="HR Contacts"),
                HRAssistantAction(label="Open FAQ", page="FAQ"),
            ],
        )
