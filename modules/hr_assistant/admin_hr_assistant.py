"""Company-scoped, context-aware HR Assistant for administrators.

The administrator assistant uses live records from the authenticated company,
approved company policies, and existing admin modules. It never exposes
password hashes, reset tokens, SMTP secrets, or data from another company.
"""

from collections import Counter
from datetime import date
from decimal import Decimal
import re

from sqlalchemy.orm import Session

from authentication.current_user import AuthenticatedUser
from modules.hr_assistant.hr_assistant import (
    HRAssistant,
    HRAssistantAction,
    HRAssistantResponse,
)
from modules.policy_qa.policy_assistant import PolicyAssistant
from repositories.employee_repository import EmployeeRepository
from repositories.user_repository import UserRepository
from services.announcement_service import AnnouncementService
from services.leave_service import LeaveService
from services.policy_service import PolicyService


class AdminHRAssistant:
    """Answer administrator HR questions using tenant-scoped live data."""

    _FOLLOW_UP_MARKERS = {
        "and those",
        "how about",
        "how many",
        "ilan",
        "paano naman",
        "show details",
        "sino",
        "those",
        "what about",
        "which ones",
        "yun",
    }

    _PERSONAL_MARKERS = {
        "ako",
        "akin",
        "ko",
        "my",
        "mine",
        "personal",
    }

    _SENSITIVE_TERMS = {
        "password",
        "password hash",
        "reset token",
        "secret key",
        "smtp password",
        "cookie secret",
        "show credentials",
    }

    def __init__(self, session: Session) -> None:
        self.session = session
        self.employee_repository = EmployeeRepository(session)
        self.user_repository = UserRepository(session)
        self.leave_service = LeaveService(session)
        self.policy_service = PolicyService(session)
        self.policy_assistant = PolicyAssistant(session)
        self.announcement_service = AnnouncementService(session)
        self.employee_assistant = HRAssistant(session)

    @staticmethod
    def _format_days(value) -> str:
        """Format Decimal day values without unnecessary zeros."""

        return f"{Decimal(value):.2f}".rstrip("0").rstrip(".")

    @classmethod
    def normalize_query(cls, value: str) -> str:
        """Reuse employee shorthand and query normalization."""

        return HRAssistant.normalize_query(value)

    @staticmethod
    def _contains_any(value: str, terms: set[str]) -> bool:
        return any(term in value for term in terms)

    @staticmethod
    def _history_last_user_question(history: list[dict] | None) -> str | None:
        if not history:
            return None

        for message in reversed(history):
            if message.get("role") == "user":
                value = str(message.get("content", "")).strip()
                if value:
                    return value

        return None

    @staticmethod
    def _history_last_intent(history: list[dict] | None) -> str | None:
        if not history:
            return None

        for message in reversed(history):
            if message.get("role") != "assistant":
                continue
            intent = str(message.get("intent", "")).strip()
            if intent and intent != "welcome":
                return intent

        return None

    @classmethod
    def _is_explicit_follow_up(cls, query: str) -> bool:
        return bool(query) and any(
            marker in query
            for marker in cls._FOLLOW_UP_MARKERS
        )

    @classmethod
    def _is_personal_employee_question(cls, query: str) -> bool:
        """Detect questions about the signed-in administrator as employee."""

        personal = any(
            re.search(rf"\b{re.escape(marker)}\b", query)
            for marker in cls._PERSONAL_MARKERS
        )
        employee_topic = any(
            term in query
            for term in (
                "leave",
                "vacation",
                "sick",
                "emergency",
                "manager",
                "department",
                "employee number",
                "job title",
                "work email",
            )
        )

        return personal and employee_topic

    @classmethod
    def _standalone_intent(cls, query: str) -> str:
        """Classify a complete administrator question without history."""

        if cls._contains_any(query, cls._SENSITIVE_TERMS):
            return "sensitive_security"

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

        if cls._is_personal_employee_question(query):
            return "personal_employee"

        if cls._contains_any(
            query,
            {
                "file leave",
                "apply leave",
                "apply for leave",
                "mag file ng leave",
                "magfile ng leave",
            },
        ):
            return "personal_employee"

        if cls._contains_any(
            query,
            {
                "attendance",
                "dtr",
                "time in",
                "time out",
                "overtime",
                "work status",
            },
        ):
            return "attendance"

        if cls._contains_any(
            query,
            {
                "company form",
                "company forms",
                "form document",
                "employee submission",
                "submitted form",
                "upload form",
            },
        ):
            return "company_forms"

        if cls._contains_any(
            query,
            {
                "add employee",
                "create employee",
                "new employee",
                "employee onboarding account",
            },
        ):
            return "employee_howto"

        if cls._contains_any(
            query,
            {
                "find employee",
                "lookup employee",
                "employee details",
                "who is employee",
                "show employee",
            },
        ):
            return "employee_lookup"

        if cls._contains_any(
            query,
            {
                "employee count",
                "employees count",
                "how many employees",
                "headcount",
                "employed employees",
                "resigned employees",
                "employee summary",
                "departments count",
                "department summary",
                "employees",
            },
        ):
            return "employee_summary"

        if cls._contains_any(
            query,
            {
                "user account",
                "user accounts",
                "login account",
                "login accounts",
                "active account",
                "inactive account",
                "admin users",
                "account summary",
            },
        ):
            return "account_summary"

        if cls._contains_any(
            query,
            {
                "set leave credit",
                "leave allocation",
                "credit management",
                "configure leave type",
                "leave rules",
            },
        ):
            return "leave_howto"

        if cls._contains_any(
            query,
            {
                "pending leave",
                "leave requests",
                "leave request",
                "on leave today",
                "low leave credit",
                "leave summary",
                "leave overview",
                "leave status",
                "leave",
            },
        ):
            return "leave_summary"

        if cls._contains_any(
            query,
            {
                "upload policy",
                "add policy",
                "publish policy",
                "manage policy",
                "delete policy",
                "archive policy",
            },
        ):
            return "policy_howto"

        if cls._contains_any(
            query,
            {
                "how many policies",
                "published policies",
                "policy count",
                "policy summary",
                "policy bin",
                "policies",
                "policy",
            },
        ):
            # Generic policy wording opens management. Specific questions
            # are handled as policy Q&A below.
            if cls._contains_any(
                query,
                {
                    "what is the policy",
                    "what does the policy",
                    "policy about",
                    "policy on",
                    "according to policy",
                },
            ):
                return "policy_question"
            return "policy_summary"

        if cls._contains_any(
            query,
            {
                "create announcement",
                "add announcement",
                "publish announcement",
                "post announcement",
            },
        ):
            return "announcement_howto"

        if cls._contains_any(
            query,
            {
                "announcement count",
                "announcement summary",
                "published announcement",
                "scheduled announcement",
                "draft announcement",
                "archived announcement",
                "announcements",
                "announcement",
            },
        ):
            return "announcement_summary"

        if cls._contains_any(
            query,
            {
                "smtp",
                "email integration",
                "email settings",
                "integration",
                "integrations",
            },
        ):
            return "integrations"

        if cls._contains_any(
            query,
            {
                "company profile",
                "company color",
                "theme color",
                "company name",
                "company settings",
            },
        ):
            return "company_profile"

        if cls._contains_any(query, {"audit log", "audit logs", "audit"}):
            return "audit_logs"

        if cls._contains_any(query, {"report", "reports"}):
            return "reports"

        if cls._contains_any(query, {"dashboard", "admin dashboard"}):
            return "dashboard"

        # Questions with formal policy language can still be answered from
        # approved company policies even without the word "policy".
        if cls._contains_any(
            query,
            {
                "guideline",
                "procedure",
                "company rule",
                "requirement",
                "allowed",
                "entitled",
                "eligibility",
            },
        ):
            return "policy_question"

        return "not_found"

    @classmethod
    def classify_intent(
        cls,
        question: str,
        *,
        history: list[dict] | None = None,
    ) -> str:
        """Prioritize a new admin topic; use context only when incomplete."""

        current = cls.normalize_query(question)
        standalone = cls._standalone_intent(current)

        if standalone != "not_found":
            return standalone

        if not cls._is_explicit_follow_up(current):
            return standalone

        previous_question = cls._history_last_user_question(history)
        previous_intent = cls._history_last_intent(history)

        if not previous_question or not previous_intent:
            return standalone

        combined = cls.normalize_query(
            f"{previous_question} {current}"
        )
        contextual = cls._standalone_intent(combined)

        return contextual if contextual != "not_found" else previous_intent

    @staticmethod
    def _admin_action(
        label: str,
        page: str,
        *,
        query_params: dict[str, str] | None = None,
    ) -> HRAssistantAction:
        default_views = {
            "Employees": {"employee_view": "list"},
            "Policies": {"policy_view": "library"},
            "Leave Management": {"leave_view": "overview"},
            "Announcements": {"announcement_view": "overview"},
            "Company Form/Documents": {"form_view": "overview"},
        }
        return HRAssistantAction(
            label=label,
            page=page,
            portal_mode="admin",
            query_params=(
                dict(query_params)
                if query_params is not None
                else dict(default_views.get(page, {}))
            ),
        )

    def _leave_credit_ranking(
        self,
        current_user: AuthenticatedUser,
        normalized_question: str,
    ) -> HRAssistantResponse:
        """Rank live employee leave credits for a comparative admin question."""

        year = date.today().year
        balances = self.leave_service.list_company_balances(
            current_user.company_id,
            year,
        )
        paid_balances = [
            balance
            for balance in balances
            if bool(balance.leave_type.is_paid)
        ]

        requested_type = None
        for balance in paid_balances:
            aliases = {
                self.normalize_query(balance.leave_type.name),
                self.normalize_query(balance.leave_type.code),
            }
            if any(alias and alias in normalized_question for alias in aliases):
                requested_type = balance.leave_type_id
                break

        if requested_type is not None:
            paid_balances = [
                balance
                for balance in paid_balances
                if balance.leave_type_id == requested_type
            ]

        totals: dict[int, Decimal] = {}
        employees: dict[int, object] = {}
        for balance in paid_balances:
            totals[balance.employee_id] = (
                totals.get(balance.employee_id, Decimal("0.00"))
                + Decimal(balance.remaining_days)
            )
            employees[balance.employee_id] = balance.employee

        if not totals:
            return HRAssistantResponse(
                answer=f"No paid leave-credit balances are available for {year}.",
                intent="leave_summary",
                actions=[
                    self._admin_action(
                        "Open Employee Leave Accounts",
                        "Leave Management",
                        query_params={"leave_view": "accounts"},
                    )
                ],
            )

        ascending = self._contains_any(
            normalized_question,
            {"lowest", "least", "low", "mababa", "pinakamababa"},
        )
        ranked = sorted(
            totals.items(),
            key=lambda item: (item[1], employees[item[0]].full_name.casefold()),
            reverse=not ascending,
        )[:5]

        leave_label = "paid leave"
        if requested_type is not None:
            selected_balance = next(
                balance
                for balance in paid_balances
                if balance.leave_type_id == requested_type
            )
            leave_label = selected_balance.leave_type.name

        direction = "Lowest" if ascending else "Highest"
        lines = [
            f"{direction} available {leave_label} credits for **{year}**:"
        ]
        for index, (employee_id, total) in enumerate(ranked, start=1):
            employee = employees[employee_id]
            lines.append(
                f"{index}. **{employee.employee_number} — {employee.full_name}:** "
                f"{self._format_days(total)} day(s) available"
            )

        return HRAssistantResponse(
            answer="\n".join(lines),
            intent="leave_summary",
            actions=[
                self._admin_action(
                    "Open Employee Leave Accounts",
                    "Leave Management",
                    query_params={"leave_view": "accounts"},
                )
            ],
        )

    def _employees(self, company_id: int):
        return self.employee_repository.list_with_details(company_id)

    def _users(self, company_id: int):
        return self.user_repository.list_with_details(company_id)

    def _match_employees(self, company_id: int, query: str):
        """Match employee number or full name inside an admin question."""

        normalized = self.normalize_query(query)
        matches = []

        for employee in self._employees(company_id):
            employee_number = self.normalize_query(employee.employee_number)
            full_name = self.normalize_query(employee.full_name)

            if employee_number and employee_number in normalized:
                matches.append(employee)
                continue

            if (
                len(full_name.split()) >= 2
                and full_name in normalized
            ):
                matches.append(employee)

        return matches

    def _employee_summary(self, current_user: AuthenticatedUser) -> HRAssistantResponse:
        employees = self._employees(current_user.company_id)
        employed = [item for item in employees if item.employment_status == "employed"]
        resigned = [item for item in employees if item.employment_status == "resigned"]
        with_account = [item for item in employees if item.user is not None]
        active_accounts = [
            item
            for item in employees
            if item.user is not None and item.user.is_active
        ]
        departments = {
            item.department.name
            for item in employees
            if item.department is not None
        }
        managers = {
            item.manager_id
            for item in employees
            if item.manager_id is not None
        }

        answer = (
            "Current employee summary:\n"
            f"- **Total employees:** {len(employees)}\n"
            f"- **Employed:** {len(employed)}\n"
            f"- **Resigned:** {len(resigned)}\n"
            f"- **Linked login accounts:** {len(with_account)}\n"
            f"- **Active linked accounts:** {len(active_accounts)}\n"
            f"- **Departments represented:** {len(departments)}\n"
            f"- **Assigned managers:** {len(managers)}"
        )

        return HRAssistantResponse(
            answer=answer,
            intent="employee_summary",
            actions=[self._admin_action("Open Employees", "Employees")],
        )

    def _employee_lookup(
        self,
        current_user: AuthenticatedUser,
        question: str,
    ) -> HRAssistantResponse:
        matches = self._match_employees(
            current_user.company_id,
            question,
        )

        if not matches:
            return HRAssistantResponse(
                answer=(
                    "Include the employee number or complete employee name. "
                    "Example: **Show employee ADMIN-001**."
                ),
                intent="employee_lookup",
                actions=[self._admin_action("Open Employees", "Employees")],
            )

        if len(matches) > 1:
            lines = ["Multiple employees matched:"]
            for employee in matches[:10]:
                lines.append(
                    f"- **{employee.employee_number}** — {employee.full_name}"
                )
            lines.append("\nUse the employee number for an exact result.")
            return HRAssistantResponse(
                answer="\n".join(lines),
                intent="employee_lookup",
                actions=[self._admin_action("Open Employees", "Employees")],
            )

        employee = matches[0]
        manager = employee.manager.full_name if employee.manager else "Not assigned"
        department = employee.department.name if employee.department else "Not assigned"
        account_status = (
            "Active"
            if employee.user is not None and employee.user.is_active
            else "Inactive / No active account"
        )
        clearance = (
            "Admin"
            if employee.user is not None and int(employee.user.clearance) == 1
            else "User"
        )

        answer = (
            f"Employee record for **{employee.full_name}**:\n"
            f"- **Employee Number:** {employee.employee_number}\n"
            f"- **Department:** {department}\n"
            f"- **Job Title:** {employee.job_title or 'Not specified'}\n"
            f"- **Manager:** {manager}\n"
            f"- **Work Email:** {employee.work_email or 'Not specified'}\n"
            f"- **Employment Status:** {employee.employment_status.title()}\n"
            f"- **Account Status:** {account_status}\n"
            f"- **Clearance:** {clearance}"
        )

        return HRAssistantResponse(
            answer=answer,
            intent="employee_lookup",
            actions=[self._admin_action("Open Employees", "Employees")],
        )

    def _account_summary(self, current_user: AuthenticatedUser) -> HRAssistantResponse:
        users = self._users(current_user.company_id)
        active = [item for item in users if item.is_active]
        inactive = [item for item in users if not item.is_active]
        admins = [item for item in users if int(item.clearance) == 1]
        standard = [item for item in users if int(item.clearance) == 2]
        must_change = [item for item in users if item.must_change_password]

        answer = (
            "Current account summary:\n"
            f"- **Total user accounts:** {len(users)}\n"
            f"- **Active:** {len(active)}\n"
            f"- **Inactive:** {len(inactive)}\n"
            f"- **Admin clearance:** {len(admins)}\n"
            f"- **User clearance:** {len(standard)}\n"
            f"- **Must change password:** {len(must_change)}\n\n"
            "Passwords and password hashes are never displayed. Admins may "
            "reset an account through the protected employee/account workflow."
        )

        return HRAssistantResponse(
            answer=answer,
            intent="account_summary",
            actions=[self._admin_action("Open Employees", "Employees")],
        )

    def _leave_summary(
        self,
        current_user: AuthenticatedUser,
        question: str,
    ) -> HRAssistantResponse:
        matches = self._match_employees(
            current_user.company_id,
            question,
        )
        normalized = self.normalize_query(question)

        comparative_credit_question = (
            self._contains_any(normalized, {"credit", "credits"})
            and self._contains_any(
                normalized,
                {
                    "highest",
                    "most",
                    "top",
                    "mataas",
                    "pinakamataas",
                    "lowest",
                    "least",
                    "low",
                    "mababa",
                    "pinakamababa",
                    "sino",
                    "who",
                },
            )
        )
        if comparative_credit_question and not matches:
            return self._leave_credit_ranking(current_user, normalized)

        if matches and any(
            term in normalized
            for term in ("balance", "credit", "credits", "remaining", "left", "ilan")
        ):
            employee = matches[0]
            balances = self.leave_service.list_employee_balances(
                current_user.company_id,
                employee.id,
                date.today().year,
            )
            lines = [
                f"Leave credits for **{employee.employee_number} — {employee.full_name}**:"
            ]
            if not balances:
                lines.append("- No leave balances are configured for the current year.")
            else:
                for balance in balances:
                    lines.append(
                        f"- **{balance.leave_type.code} — {balance.leave_type.name}:** "
                        f"{self._format_days(balance.remaining_days)} available | "
                        f"{self._format_days(balance.reserved_days)} reserved | "
                        f"{self._format_days(balance.used_days)} used"
                    )
            return HRAssistantResponse(
                answer="\n".join(lines),
                intent="leave_summary",
                actions=[
                    self._admin_action(
                        "Open Employee Leave Accounts",
                        "Leave Management",
                        query_params={"leave_view": "accounts"},
                    )
                ],
            )

        self.leave_service.reconcile_approved_leave(
            company_id=current_user.company_id
        )
        overview = self.leave_service.overview(
            current_user.company_id,
            date.today().year,
        )
        requests = self.leave_service.list_company_requests(
            current_user.company_id,
            date.today().year,
        )
        statuses = Counter(request.status for request in requests)

        answer = (
            f"Leave overview for **{date.today().year}**:\n"
            f"- **Total requests:** {overview.get('total_requests', 0)}\n"
            f"- **Requests this month:** {overview.get('requests_this_month', 0)}\n"
            f"- **Employees on leave today:** {overview.get('employees_on_leave_today', 0)}\n"
            f"- **Employees with low credits:** {overview.get('employees_with_low_credits', 0)}\n"
            f"- **Pending manager approval:** {statuses.get('pending_manager_approval', 0)}\n"
            f"- **Approved / scheduled:** "
            f"{statuses.get('scheduled', 0) + statuses.get('approved', 0)}\n"
            f"- **In progress:** {statuses.get('in_progress', 0)}\n"
            f"- **Completed:** {statuses.get('completed', 0)}\n"
            f"- **Rejected:** {statuses.get('rejected', 0)}"
        )

        return HRAssistantResponse(
            answer=answer,
            intent="leave_summary",
            actions=[
                self._admin_action(
                    "Open Leave Overview",
                    "Leave Management",
                    query_params={"leave_view": "overview"},
                )
            ],
        )

    def _policy_summary(self, current_user: AuthenticatedUser) -> HRAssistantResponse:
        active = self.policy_service.list_for_admin(current_user.company_id)
        published = self.policy_service.list_published(current_user.company_id)
        in_bin = self.policy_service.list_bin(current_user.company_id)
        categories = Counter(policy.category for policy in active)
        category_text = ", ".join(
            f"{name}: {count}"
            for name, count in categories.most_common(5)
        ) or "None"

        answer = (
            "Current policy library summary:\n"
            f"- **Active policy versions:** {len(active)}\n"
            f"- **Published and currently effective:** {len(published)}\n"
            f"- **In Bin:** {len(in_bin)}\n"
            f"- **Top categories:** {category_text}"
        )

        return HRAssistantResponse(
            answer=answer,
            intent="policy_summary",
            actions=[self._admin_action("Open Policies", "Policies")],
        )

    def _policy_question(
        self,
        current_user: AuthenticatedUser,
        question: str,
    ) -> HRAssistantResponse:
        result = self.policy_assistant.answer(
            company_id=current_user.company_id,
            question=question,
        )

        if not result.matched:
            return HRAssistantResponse(
                answer="Information not found in approved company policies.",
                intent="policy_question",
                actions=[self._admin_action("Open Policies", "Policies")],
            )

        return HRAssistantResponse(
            answer=result.answer,
            intent="policy_question",
            sources=result.sources,
            actions=[self._admin_action("Open Policies", "Policies")],
        )

    def _announcement_summary(self, current_user: AuthenticatedUser) -> HRAssistantResponse:
        announcements = self.announcement_service.list_for_admin(
            current_user.company_id
        )
        labels = Counter(
            self.announcement_service.display_status(item)
            for item in announcements
        )
        pinned = sum(1 for item in announcements if item.is_pinned)

        answer = (
            "Current announcement summary:\n"
            f"- **Total records:** {len(announcements)}\n"
            f"- **Published:** {labels.get('Published', 0)}\n"
            f"- **Scheduled:** {labels.get('Scheduled', 0)}\n"
            f"- **Draft:** {labels.get('Draft', 0)}\n"
            f"- **Expired:** {labels.get('Expired', 0)}\n"
            f"- **Archived:** {labels.get('Archived', 0)}\n"
            f"- **Pinned:** {pinned}"
        )

        return HRAssistantResponse(
            answer=answer,
            intent="announcement_summary",
            actions=[self._admin_action("Open Announcements", "Announcements")],
        )

    @classmethod
    def _help_response(cls) -> HRAssistantResponse:
        return HRAssistantResponse(
            answer=(
                "I can help administrators with:\n"
                "- Company employee and account summaries\n"
                "- Employee lookup by employee number or full name\n"
                "- Company leave requests, on-leave totals, and credit summaries\n"
                "- Published policy summaries and approved-policy questions\n"
                "- Announcement status summaries\n"
                "- Attendance / DTR / OT and Company Form/Documents workflows\n"
                "- Navigation and basic workflows for Employees, Policies, "
                "Leave Management, Announcements, Company Profile, Reports, "
                "and Integrations\n"
                "- Personal employee questions such as your own leave balance\n\n"
                "Passwords, hashes, reset tokens, and secret configuration values "
                "are never shown."
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
        """Answer one administrator question using live company data."""

        cleaned = (question or "").strip()
        if not cleaned:
            return HRAssistantResponse(
                answer="Please enter an administrator HR question.",
                intent="empty",
            )

        normalized = self.normalize_query(cleaned)
        intent = self.classify_intent(cleaned, history=history)

        if intent == "sensitive_security":
            return HRAssistantResponse(
                answer=(
                    "Passwords, password hashes, reset tokens, SMTP secrets, "
                    "and cookie secrets cannot be viewed. Use the protected "
                    "reset or configuration workflow instead."
                ),
                intent=intent,
                actions=[
                    self._admin_action("Open Employees", "Employees"),
                    self._admin_action("Open Integrations", "Integrations"),
                ],
            )

        if intent == "help":
            return self._help_response()

        if intent == "personal_employee":
            return self.employee_assistant.answer(
                current_user=current_user,
                question=cleaned,
                history=history,
            )

        if intent == "employee_summary":
            return self._employee_summary(current_user)

        if intent == "employee_lookup":
            return self._employee_lookup(current_user, cleaned)

        if intent == "account_summary":
            return self._account_summary(current_user)

        if intent == "leave_summary":
            return self._leave_summary(current_user, cleaned)

        if intent == "policy_summary":
            return self._policy_summary(current_user)

        if intent == "policy_question":
            return self._policy_question(current_user, cleaned)

        if intent == "announcement_summary":
            return self._announcement_summary(current_user)

        direct_answers = {
            "employee_howto": (
                "Open **Employees**, then use Add Employee. Enter the employee "
                "master record, department, manager, employment status, and "
                "optional login-account information.",
                "Open Employees",
                "Employees",
            ),
            "leave_howto": (
                "Open **Leave Management**. Use Employee Leave Accounts for "
                "balances, Leave Rules for configuration, and Leave "
                "Requests for company monitoring. Manager approval remains in "
                "the manager workflow.",
                "Open Leave Management",
                "Leave Management",
            ),
            "policy_howto": (
                "Open **Policies** to upload PDF, DOCX, TXT, or Markdown files. "
                "Review the extracted content, publish the version, manage "
                "metadata, or move a policy to the Bin.",
                "Open Policies",
                "Policies",
            ),
            "announcement_howto": (
                "Open **Announcements**, select Create Announcement, enter the "
                "title, category, summary, full content, optional image, publish "
                "date, expiry, and pinned status, then publish or save as draft.",
                "Create Announcement",
                "Announcements",
            ),
            "integrations": (
                "Open **Integrations** for email and SMTP-related configuration. "
                "Secret values are never displayed by the assistant.",
                "Open Integrations",
                "Integrations",
            ),
            "company_profile": (
                "Open **Company Profile** to manage company name and the shared "
                "primary accent color used by login, Admin Portal, and Employee Portal.",
                "Open Company Profile",
                "Company Profile",
            ),
            "audit_logs": (
                "Open **Audit Logs**. The current page may remain a placeholder "
                "until the audit module is implemented.",
                "Open Audit Logs",
                "Audit Logs",
            ),
            "reports": (
                "Open **Reports**. Available reports depend on the currently "
                "implemented reporting modules.",
                "Open Reports",
                "Reports",
            ),
            "dashboard": (
                "Open **Admin Dashboard** for company-scoped employee and account metrics.",
                "Open Admin Dashboard",
                "Admin Dashboard",
            ),
            "attendance": (
                "Open **Admin Dashboard** and use **Attendance / DTR / OT** to "
                "review monthly attendance, time records, work status, overtime, "
                "employee edit history, and authorized corrections.",
                "Open Attendance / DTR / OT",
                "Admin Dashboard",
            ),
            "company_forms": (
                "Open **Company Form/Documents** to upload or manage company "
                "templates and review employee form submissions.",
                "Open Company Form/Documents",
                "Company Form/Documents",
            ),
        }

        if intent in direct_answers:
            answer, label, page = direct_answers[intent]
            exact_params = {
                "employee_howto": {"employee_view": "add"},
                "leave_howto": {"leave_view": "accounts"},
                "policy_howto": {"policy_view": "upload"},
                "announcement_howto": {"announcement_view": "create"},
                "company_forms": {"form_view": "overview"},
            }.get(intent)
            return HRAssistantResponse(
                answer=answer,
                intent=intent,
                actions=[
                    self._admin_action(
                        label,
                        page,
                        query_params=exact_params,
                    )
                ],
            )

        # Final approved-policy fallback for a natural HR question.
        policy_result = self.policy_assistant.answer(
            company_id=current_user.company_id,
            question=cleaned,
        )
        if policy_result.matched:
            return HRAssistantResponse(
                answer=policy_result.answer,
                intent="policy_fallback",
                sources=policy_result.sources,
                actions=[self._admin_action("Open Policies", "Policies")],
            )

        return HRAssistantResponse(
            answer=(
                "I could not match that question to live admin data or approved "
                "company policies. Try asking about employees, accounts, leave, "
                "policies, announcements, integrations, reports, or company settings."
            ),
            intent="not_found",
            actions=[self._admin_action("Open Admin Dashboard", "Admin Dashboard")],
        )
