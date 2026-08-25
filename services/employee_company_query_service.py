"""Deterministic company-wide employee list/query support for Admin Chat.

This service intentionally reads live Employee Master relationships instead of
asking the local LLM to infer people, hierarchy roles, departments, or counts.
It is company-scoped and designed for natural-language aggregate questions and
follow-ups such as "Who are the leaders?", "names of them", "how many?", and
"what departments are they in?".
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from models.employee import Employee


@dataclass(frozen=True, slots=True)
class EmployeeCompanyQueryResult:
    """One deterministic employee aggregate answer and optional chart report."""

    answer: str
    intent: str
    report: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class _EmployeeRow:
    employee: Employee
    role_label: str
    is_manager: bool
    is_leader: bool


class EmployeeCompanyQueryService:
    """Resolve natural company-wide employee aggregate questions for admins."""

    _DOMAIN_BLOCKERS = re.compile(
        r"\b(?:leave|vacation|sick|emergency|lwop|attendance|dtr|overtime|\bot\b|"
        r"violation|disciplinary|offense|policy|form|document|announcement|"
        r"password|secret|credential|smtp|sms|email provider)\b",
        re.I,
    )
    _AGGREGATE_TERMS = re.compile(
        r"\b(?:employees?|staff|people|leaders?|managers?|supervisors?|members?|"
        r"headcount|workforce|direct reports?)\b",
        re.I,
    )
    _LIST_TERMS = re.compile(
        r"\b(?:who|which|list|show|display|names?|sino|mga sino|give me)\b",
        re.I,
    )
    _COUNT_TERMS = re.compile(r"\b(?:how many|count|ilan|number of)\b", re.I)
    _CHART_TERMS = re.compile(
        r"\b(?:chart|graph|plot|visual|bar chart|pie chart|breakdown|compare)\b",
        re.I,
    )
    _DEPARTMENT_OUTPUT_TERMS = re.compile(
        r"\b(?:what|which)\s+departments?\b|\bdepartments?\s+(?:are|do)\b",
        re.I,
    )
    _FOLLOW_UP_ONLY = re.compile(
        r"^\s*(?:names?(?:\s+of\s+(?:them|those|the\s+leaders?|the\s+managers?))?|"
        r"how many(?:\s+are\s+there)?|ilan(?:\s+sila)?|"
        r"what departments?(?:\s+are\s+they\s+in)?|"
        r"which departments?(?:\s+are\s+they\s+in)?|"
        r"graph(?:\s+them)?|chart(?:\s+them)?|show\s+the\s+graph)\s*[?.!]*\s*$",
        re.I,
    )

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _normalize(value: str) -> str:
        value = (value or "").casefold().replace("-", " ")
        value = re.sub(r"[^a-z0-9@._\s]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _history_context(history: list[dict] | None) -> str | None:
        """Find the user query associated with the most recent aggregate answer."""

        if not history:
            return None
        for index in range(len(history) - 1, -1, -1):
            message = history[index]
            if message.get("role") != "assistant":
                continue
            intent = str(message.get("intent", ""))
            if not intent.startswith("employee_aggregate"):
                continue
            for previous in range(index - 1, -1, -1):
                if history[previous].get("role") == "user":
                    content = str(history[previous].get("content", "")).strip()
                    if content:
                        return content
            return None
        return None

    @staticmethod
    def _whole_value_present(query: str, value: str) -> bool:
        normalized = EmployeeCompanyQueryService._normalize(value)
        if not normalized:
            return False
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])",
                query,
            )
        )

    def _rows(self, company_id: int) -> list[_EmployeeRow]:
        employees = self.session.scalars(
            select(Employee)
            .where(
                Employee.company_id == company_id,
                Employee.archived_at.is_(None),
            )
            .order_by(Employee.employee_number)
        ).unique().all()

        employed = [
            employee
            for employee in employees
            if str(employee.employment_status or "").casefold() == "employed"
        ]
        manager_ids = {
            employee.manager_id for employee in employed if employee.manager_id is not None
        }
        leader_ids = {
            employee.leader_id for employee in employed if employee.leader_id is not None
        }

        rows: list[_EmployeeRow] = []
        for employee in employees:
            is_manager = employee.id in manager_ids
            is_leader = employee.id in leader_ids
            if is_manager and is_leader:
                label = "Manager and Leader"
            elif is_manager:
                label = "Manager"
            elif is_leader:
                label = "Leader"
            else:
                label = "No supervisory assignment"
            rows.append(_EmployeeRow(employee, label, is_manager, is_leader))
        return rows

    @staticmethod
    def _explicit_role(query: str) -> str | None:
        both = bool(
            re.search(
                r"\b(?:both\s+)?manager\s+(?:and|&)\s+leader\b|"
                r"\b(?:both\s+)?leader\s+(?:and|&)\s+manager\b|"
                r"\bmanager\s+and\s+leader\b",
                query,
                re.I,
            )
        )
        if both:
            return "both"
        has_leader = bool(re.search(r"\bleaders?\b", query, re.I))
        has_manager = bool(re.search(r"\bmanagers?\b", query, re.I))
        if has_leader and not has_manager:
            return "leader"
        if has_manager and not has_leader:
            return "manager"
        return None

    def _apply_filters(
        self,
        rows: list[_EmployeeRow],
        *,
        query: str,
    ) -> tuple[list[_EmployeeRow], list[str]]:
        normalized = self._normalize(query)
        filters: list[str] = []
        role = self._explicit_role(normalized)
        if role == "leader":
            rows = [row for row in rows if row.is_leader]
            filters.append("Leader")
        elif role == "manager":
            rows = [row for row in rows if row.is_manager]
            filters.append("Manager")
        elif role == "both":
            rows = [row for row in rows if row.is_manager and row.is_leader]
            filters.append("Manager and Leader")

        if re.search(r"\bresigned\b", normalized):
            rows = [
                row for row in rows
                if str(row.employee.employment_status or "").casefold() == "resigned"
            ]
            filters.append("Resigned")
        elif not re.search(r"\b(?:all\s+employees?|including\s+resigned)\b", normalized):
            # Current lists default to active/employed people, matching Employee Master.
            rows = [
                row for row in rows
                if str(row.employee.employment_status or "").casefold() == "employed"
            ]

        departments = sorted(
            {
                row.employee.department.name
                for row in rows
                if row.employee.department is not None
                and str(row.employee.department.name or "").strip()
            },
            key=str.casefold,
        )
        for department in departments:
            if self._whole_value_present(normalized, department):
                rows = [
                    row for row in rows
                    if row.employee.department is not None
                    and self._normalize(row.employee.department.name) == self._normalize(department)
                ]
                filters.append(f"Department: {department}")
                break

        job_titles = sorted(
            {
                str(row.employee.job_title).strip()
                for row in rows
                if str(row.employee.job_title or "").strip()
            },
            key=str.casefold,
        )
        for title in job_titles:
            # Exact whole-value matching avoids false positives such as a short
            # department/job title being found inside an ordinary word.
            if self._whole_value_present(normalized, title):
                rows = [
                    row for row in rows
                    if self._normalize(str(row.employee.job_title or "")) == self._normalize(title)
                ]
                filters.append(f"Job Title: {title}")
                break

        return rows, filters

    @staticmethod
    def _row_label(row: _EmployeeRow) -> str:
        department = row.employee.department.name if row.employee.department else "Not assigned"
        title = row.employee.job_title or "Not specified"
        return (
            f"**{row.employee.employee_number} — {row.employee.full_name}** — "
            f"{department} — {title} — {row.role_label}"
        )

    @staticmethod
    def _public_rows(rows: list[_EmployeeRow]) -> list[dict[str, Any]]:
        return [
            {
                "Employee Number": row.employee.employee_number,
                "Employee": row.employee.full_name,
                "Department": row.employee.department.name if row.employee.department else "Not assigned",
                "Job Title": row.employee.job_title or "Not specified",
                "Hierarchy Role": row.role_label,
                "Employment Status": str(row.employee.employment_status or "").title(),
            }
            for row in rows
        ]

    def _report(
        self,
        *,
        rows: list[_EmployeeRow],
        query: str,
        title: str,
    ) -> dict[str, Any]:
        normalized = self._normalize(query)
        if re.search(r"\b(?:job title|position|positions|title)\b", normalized):
            group_label = "Job Title"
            getter = lambda row: row.employee.job_title or "Not specified"
        elif re.search(r"\b(?:hierarchy|role|leaders?|managers?)\b", normalized) and not re.search(
            r"\bdepartments?\b", normalized
        ):
            group_label = "Hierarchy Role"
            getter = lambda row: row.role_label
        else:
            group_label = "Department"
            getter = lambda row: row.employee.department.name if row.employee.department else "Not assigned"

        counts = Counter(str(getter(row)) for row in rows)
        data = [
            {"label": label, "value": count}
            for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
        ]
        now = datetime.now(ZoneInfo(get_settings().display_timezone))
        public_rows = self._public_rows(rows)
        return {
            "title": title,
            "period": "Current Employee Master",
            "start_date": now.date().isoformat(),
            "end_date": now.date().isoformat(),
            "generated_at": now.isoformat(),
            "timezone": get_settings().display_timezone,
            "summary": [f"Employees represented: {len(rows)}"],
            "columns": list(public_rows[0]) if public_rows else [],
            "rows": public_rows,
            "chart": {
                "type": "bar",
                "title": f"{title} by {group_label.casefold()}",
                "category_label": group_label,
                "value_label": "Employees",
                "data": data,
            },
            "domain": "employees",
        }

    def try_answer(
        self,
        *,
        current_user: AuthenticatedUser,
        question: str,
        history: list[dict] | None = None,
    ) -> EmployeeCompanyQueryResult | None:
        """Answer an authorized company-wide employee aggregate question."""

        # This service is deliberately Admin-only. Employee Chat keeps its
        # established self/direct-report scope and never receives company-wide
        # employee enumeration through this path.
        if int(current_user.clearance) != 1:
            return None

        cleaned = re.sub(r"\s+", " ", question or "").strip()
        if not cleaned:
            return None

        if self._DOMAIN_BLOCKERS.search(cleaned):
            return None

        previous_query = self._history_context(history)
        is_follow_up = bool(previous_query and self._FOLLOW_UP_ONLY.match(cleaned))
        effective_query = f"{previous_query} {cleaned}" if is_follow_up else cleaned
        normalized = self._normalize(effective_query)

        has_aggregate_term = bool(self._AGGREGATE_TERMS.search(effective_query))
        asks_chart = bool(self._CHART_TERMS.search(cleaned))
        asks_count = bool(self._COUNT_TERMS.search(cleaned))
        asks_list = bool(self._LIST_TERMS.search(cleaned))
        asks_departments = bool(self._DEPARTMENT_OUTPUT_TERMS.search(cleaned))

        if not has_aggregate_term and not is_follow_up:
            return None
        if not (asks_chart or asks_count or asks_list or asks_departments or self._explicit_role(normalized)):
            return None

        # Preserve the established richer company headcount summary when the
        # user asks only the unfiltered total employee count.
        plain_headcount = bool(
            re.search(r"\b(?:how many|count)\s+employees?\b", normalized)
            and self._explicit_role(normalized) is None
            and not asks_chart
            and not re.search(r"\b(?:department|job title|position|resigned|leader|manager)\b", normalized)
        )
        if plain_headcount and not is_follow_up:
            return None

        rows, filters = self._apply_filters(self._rows(current_user.company_id), query=effective_query)
        descriptor = ", ".join(filters) if filters else "Employees"

        if asks_count:
            return EmployeeCompanyQueryResult(
                answer=f"**{len(rows)}** employee(s) match **{descriptor}** in the current company records.",
                intent="employee_aggregate",
            )

        if asks_departments and not asks_chart:
            if not rows:
                answer = f"No employees match **{descriptor}** in the current company records."
            else:
                grouped = Counter(
                    row.employee.department.name if row.employee.department else "Not assigned"
                    for row in rows
                )
                lines = [f"Departments represented by **{descriptor}**:"]
                for index, (department, count) in enumerate(
                    sorted(grouped.items(), key=lambda item: item[0].casefold()), start=1
                ):
                    lines.append(f"{index}. **{department}** — {count} employee(s)")
                answer = "\n".join(lines)
            return EmployeeCompanyQueryResult(answer=answer, intent="employee_aggregate")

        title = descriptor if filters else "Employees"
        report = self._report(rows=rows, query=effective_query, title=title) if asks_chart else None
        if not rows:
            answer = f"No employees match **{descriptor}** in the current company records."
        else:
            lines = [f"{descriptor} in the current company records:"]
            for index, row in enumerate(rows, start=1):
                lines.append(f"{index}. {self._row_label(row)}")
            lines.append(f"\n**Total:** {len(rows)}")
            answer = "\n".join(lines)

        return EmployeeCompanyQueryResult(
            answer=answer,
            intent="employee_aggregate",
            report=report,
        )
