"""Permission-aware live report/query support for the portal Chat Assistant.

The service interprets explicit dates/months/years/ranges and report/chart
requests, then reads only authorized company-scoped HR records. Qwen never
creates or changes report numbers; every metric comes from these deterministic
queries.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import calendar
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from authentication.current_user import AuthenticatedUser
from config.settings import get_settings
from models.attendance_record import AttendanceRecord
from models.employee import Employee
from models.leave_request import LeaveRequest
from services.attendance_service import AttendanceService


_MONTHS = {
    name.casefold(): index
    for index, name in enumerate(calendar.month_name)
    if name
}
_MONTHS.update({
    name.casefold(): index
    for index, name in enumerate(calendar.month_abbr)
    if name
})
_ACTIVE_LEAVE_STATUSES = {
    "scheduled", "approved", "in_progress", "completed", "partially_cancelled",
}
_PENDING_LEAVE_STATUSES = {"pending_leader_approval", "pending_manager_approval"}


@dataclass(frozen=True, slots=True)
class DateWindow:
    start: date
    end: date
    label: str
    explicit: bool = True


@dataclass(frozen=True, slots=True)
class ChatReportResult:
    answer: str
    report: dict[str, Any] | None = None


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + offset
    return absolute // 12, absolute % 12 + 1


def _month_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%B %Y")


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _local_date(value: datetime | None, tz: ZoneInfo) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz).date()


class ChatDateRangeParser:
    """Resolve natural date/month/year wording against the configured timezone."""

    def __init__(self, *, today: date) -> None:
        self.today = today

    @staticmethod
    def _parse_named_date(value: str, *, default_year: int) -> date | None:
        clean = re.sub(r"\s+", " ", value.strip().replace(",", " "))
        patterns = (
            r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})\s+(?P<year>\d{4})",
            r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})",
            r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})",
            r"(?P<year>\d{4})[-/]\s*(?P<month>\d{1,2})[-/]\s*(?P<day>\d{1,2})",
            # Day-first numeric format is the project-friendly local form.
            r"(?P<day>\d{1,2})[-/]\s*(?P<month>\d{1,2})[-/]\s*(?P<year>\d{4})",
        )
        for pattern in patterns:
            match = re.fullmatch(pattern, clean, re.I)
            if not match:
                continue
            try:
                month_text = match.group("month")
                month = int(month_text) if month_text.isdigit() else _MONTHS[month_text.casefold()]
                year_text = match.groupdict().get("year")
                year = int(year_text) if year_text else default_year
                return date(year, month, int(match.group("day")))
            except (KeyError, TypeError, ValueError):
                return None
        return None

    def parse(self, question: str, *, default_when_report: bool = False) -> DateWindow | None:
        q = re.sub(r"\s+", " ", question.casefold()).strip()
        today = self.today

        # Explicit day ranges: from August 1, 2026 to August 15, 2026.
        range_match = re.search(
            r"\b(?:from|between)\s+"
            r"(?P<start>[a-z]+\s+\d{1,2}(?:,?\s+\d{4})?|\d{1,2}\s+[a-z]+\s+\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})"
            r"\s+(?:to|and|through|until|-)\s+"
            r"(?P<end>[a-z]+\s+\d{1,2}(?:,?\s+\d{4})?|\d{1,2}\s+[a-z]+\s+\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})\b",
            q,
            re.I,
        )
        if range_match:
            start = self._parse_named_date(range_match.group("start"), default_year=today.year)
            end = self._parse_named_date(range_match.group("end"), default_year=(start.year if start else today.year))
            if start and end:
                if end < start:
                    start, end = end, start
                return DateWindow(start, end, f"{start:%B %d, %Y} to {end:%B %d, %Y}")

        # Month-to-month range: January to August 2026.
        month_range = re.search(
            r"\b(?:from\s+)?(?P<m1>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")"
            r"\s+(?:to|through|until|-)\s+"
            r"(?P<m2>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")"
            r"(?:\s+(?P<year>20\d{2}|19\d{2}))?\b",
            q,
            re.I,
        )
        if month_range:
            year = int(month_range.group("year") or today.year)
            m1 = _MONTHS[month_range.group("m1").casefold()]
            m2 = _MONTHS[month_range.group("m2").casefold()]
            start = date(year, m1, 1)
            end_year = year + (1 if m2 < m1 else 0)
            end = _month_end(end_year, m2)
            return DateWindow(start, end, f"{_month_label(year, m1)} to {_month_label(end_year, m2)}")

        # Last N periods.
        relative_count = re.search(r"\blast\s+(\d{1,2})\s+(day|days|week|weeks|month|months|year|years)\b", q)
        if relative_count:
            count = max(1, int(relative_count.group(1)))
            unit = relative_count.group(2)
            if unit.startswith("day"):
                return DateWindow(today - timedelta(days=count - 1), today, f"Last {count} days")
            if unit.startswith("week"):
                return DateWindow(today - timedelta(days=count * 7 - 1), today, f"Last {count} weeks")
            if unit.startswith("month"):
                start_y, start_m = _shift_month(today.year, today.month, -(count - 1))
                return DateWindow(date(start_y, start_m, 1), today, f"Last {count} months")
            start = date(today.year - count + 1, 1, 1)
            return DateWindow(start, today, f"Last {count} years")

        if "today" in q:
            return DateWindow(today, today, today.strftime("%B %d, %Y"))
        if "yesterday" in q:
            target = today - timedelta(days=1)
            return DateWindow(target, target, target.strftime("%B %d, %Y"))
        if "tomorrow" in q:
            target = today + timedelta(days=1)
            return DateWindow(target, target, target.strftime("%B %d, %Y"))

        if "this week" in q:
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            return DateWindow(start, end, f"This week ({start:%b %d}–{end:%b %d, %Y})")
        if "last week" in q:
            end = today - timedelta(days=today.weekday() + 1)
            start = end - timedelta(days=6)
            return DateWindow(start, end, f"Last week ({start:%b %d}–{end:%b %d, %Y})")
        if "this month" in q:
            return DateWindow(date(today.year, today.month, 1), _month_end(today.year, today.month), _month_label(today.year, today.month))
        if "last month" in q:
            year, month = _shift_month(today.year, today.month, -1)
            return DateWindow(date(year, month, 1), _month_end(year, month), _month_label(year, month))
        if "this year" in q:
            return DateWindow(date(today.year, 1, 1), date(today.year, 12, 31), str(today.year))
        if "last year" in q:
            year = today.year - 1
            return DateWindow(date(year, 1, 1), date(year, 12, 31), str(year))

        # Quarter range wording: Q1 to Q2 2026.
        quarter_range = re.search(
            r"\bq([1-4])\s+(?:to|through|until|-)\s+q([1-4])(?:\s+(20\d{2}|19\d{2}))?\b",
            q,
            re.I,
        )
        if quarter_range:
            q1 = int(quarter_range.group(1))
            q2 = int(quarter_range.group(2))
            year = int(quarter_range.group(3) or today.year)
            start_month = 1 + (q1 - 1) * 3
            end_year = year + (1 if q2 < q1 else 0)
            end_month = 1 + (q2 - 1) * 3 + 2
            return DateWindow(
                date(year, start_month, 1),
                _month_end(end_year, end_month),
                f"Q{q1} {year} to Q{q2} {end_year}",
            )

        # Quarter wording.
        quarter_match = re.search(r"\bq([1-4])(?:\s+(20\d{2}|19\d{2}))?\b", q, re.I)
        if quarter_match:
            quarter = int(quarter_match.group(1))
            year = int(quarter_match.group(2) or today.year)
            month = 1 + (quarter - 1) * 3
            return DateWindow(date(year, month, 1), _month_end(year, month + 2), f"Q{quarter} {year}")

        # Specific full date anywhere in the question.
        date_match = re.search(
            r"\b(?P<date>(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\s+\d{1,2}(?:,?\s+(?:20\d{2}|19\d{2}))?|\d{1,2}\s+(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\s+(?:20\d{2}|19\d{2})|(?:20\d{2}|19\d{2})[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/](?:20\d{2}|19\d{2}))\b",
            q,
            re.I,
        )
        if date_match:
            target = self._parse_named_date(date_match.group("date"), default_year=today.year)
            if target:
                return DateWindow(target, target, target.strftime("%B %d, %Y"))

        # "this August" / "August 2026" / bare named month.
        month_match = re.search(
            r"\b(?:(?P<this>this)\s+)?(?P<month>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")(?:\s+(?P<year>20\d{2}|19\d{2}))?\b",
            q,
            re.I,
        )
        if month_match:
            month_token = month_match.group("month").casefold()
            # "may" is also a common modal verb ("May I ..."). Treat it as
            # the month only when the surrounding wording is date-like.
            if month_token == "may" and not month_match.group("this") and not month_match.group("year"):
                before = q[max(0, month_match.start() - 12):month_match.start()]
                if not re.search(r"\b(?:in|for|during|from|to|through)\s*$", before):
                    month_match = None
            if month_match is not None:
                month = _MONTHS[month_token]
                year = int(month_match.group("year") or today.year)
                return DateWindow(date(year, month, 1), _month_end(year, month), _month_label(year, month))

        # Bare explicit year. Ignore the current-year number if it appears only
        # in a non-date identifier by requiring a time/report preposition nearby.
        year_match = re.search(r"\b(?:in|for|during|year)\s+(20\d{2}|19\d{2})\b", q)
        if year_match:
            year = int(year_match.group(1))
            return DateWindow(date(year, 1, 1), date(year, 12, 31), str(year))

        if default_when_report:
            return DateWindow(date(today.year, today.month, 1), _month_end(today.year, today.month), _month_label(today.year, today.month), explicit=False)
        return None


class ChatReportService:
    """Answer temporal HR questions and build report artifacts from live data."""

    _REPORT_TERMS = re.compile(r"\b(report|chart|graph|trend|breakdown|visual|plot|compare|comparison|pie|donut|bar chart|line chart|highest|top|ranking|rank|monthly|per month|by month|per department|by department|per employee|by employee|versus|vs)\b", re.I)
    _TEMPORAL_TERMS = re.compile(
        r"\b(today|yesterday|tomorrow|this week|last week|this month|last month|this year|last year|last\s+\d+\s+(?:days?|weeks?|months?|years?)|q[1-4]|from|between|20\d{2}|19\d{2}|"
        + "|".join(sorted(_MONTHS, key=len, reverse=True))
        + r")\b",
        re.I,
    )
    _DATA_QUERY_TERMS = re.compile(
        r"\b(how many|count|list|show|display|view|see|who|which|what|records?|requests?|hours?|status|on leave|attendance|dtr|overtime|absent|absence)\b",
        re.I,
    )
    _NON_REPORT_EXPLANATION_TERMS = re.compile(
        r"\b(policy|policies|rule|rules|requirement|requirements|procedure|process|eligible|eligibility|allowed|carry over|how do|how can|how to|can i|may i|should i|pwede ba|paano)\b",
        re.I,
    )

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.timezone = ZoneInfo(self.settings.display_timezone)
        self.now = datetime.now(self.timezone)
        self.parser = ChatDateRangeParser(today=self.now.date())

    @staticmethod
    def _domain(question: str) -> str | None:
        q = question.casefold()
        if (
            any(term in q for term in ("overtime", "ot hours", "ot hour"))
            or re.search(r"\bot\b", q)
        ):
            return "overtime"
        if any(term in q for term in (
            "attendance", "dtr", "wfo", "wfh", "work status", "undertime",
            "time in", "time out", "absent", "absence",
        )):
            return "attendance"
        if (
            any(term in q for term in ("leave", "vacation", "sick", "emergency"))
            or re.search(r"\b(?:vl|sl|el|lwop)\b", q)
        ):
            return "leave"
        return None

    @staticmethod
    def _narrow_named_employees(employees: list[Employee], question: str) -> list[Employee]:
        """Narrow only when an authorized employee name/number is explicitly written."""

        q = re.sub(r"\s+", " ", question.casefold()).strip()
        matches = []
        for employee in employees:
            name = re.sub(r"\s+", " ", employee.full_name.casefold()).strip()
            number = str(employee.employee_number or "").strip().casefold()
            if (name and name in q) or (number and re.search(rf"(?<![a-z0-9]){re.escape(number)}(?![a-z0-9])", q)):
                matches.append(employee)
        return matches or employees

    def _authorized_employees(self, current_user: AuthenticatedUser, role_scope: str, question: str) -> list[Employee]:
        company_id = current_user.company_id
        if role_scope == "admin":
            employees = self.session.scalars(
                select(Employee)
                .where(Employee.company_id == company_id, Employee.archived_at.is_(None))
                .order_by(Employee.employee_number)
            ).unique().all()
            return self._narrow_named_employees(employees, question)

        employee_id = current_user.employee_id
        if employee_id is None:
            return []
        q = question.casefold()
        personal = bool(re.search(r"\b(my|mine|me|ako|akin|ko)\b", q))
        if personal:
            employee = self.session.get(Employee, employee_id)
            return [employee] if employee and employee.company_id == company_id else []

        team_only = bool(re.search(r"\b(team|members?|direct reports?|subordinates?)\b", q))
        if team_only:
            employees = self.session.scalars(
                select(Employee)
                .where(
                    Employee.company_id == company_id,
                    Employee.archived_at.is_(None),
                    or_(
                        Employee.manager_id == employee_id,
                        Employee.leader_id == employee_id,
                    ),
                )
                .order_by(Employee.employee_number)
            ).unique().all()
            return self._narrow_named_employees(employees, question)

        # Leaders/managers may already view their assigned members in the portal.
        # Report scope mirrors that authorization and never expands beyond direct
        # manager/leader relationships plus the signed-in employee.
        employees = self.session.scalars(
            select(Employee)
            .where(
                Employee.company_id == company_id,
                Employee.archived_at.is_(None),
                or_(
                    Employee.id == employee_id,
                    Employee.manager_id == employee_id,
                    Employee.leader_id == employee_id,
                ),
            )
            .order_by(Employee.employee_number)
        ).unique().all()
        return self._narrow_named_employees(employees, question)

    @staticmethod
    def _leave_type_filter(question: str, request: LeaveRequest) -> bool:
        """Honor explicit leave-type names/codes without treating generic leave as a type."""

        q = question.casefold()
        groups = {
            "vacation": (r"\bvl\b", r"\bvacation(?: leave)?\b"),
            "sick": (r"\bsl\b", r"\bsick(?: leave)?\b"),
            "emergency": (r"\bel\b", r"\bemergency(?: leave)?\b"),
            "lwop": (r"\blwop\b", r"\bleave without pay\b", r"\bunpaid leave\b"),
        }
        requested = {
            name for name, patterns in groups.items()
            if any(re.search(pattern, q, re.I) for pattern in patterns)
        }
        leave_type = request.leave_type
        type_text = f"{getattr(leave_type, 'code', '')} {getattr(leave_type, 'name', '')}".casefold()

        # Also recognize an exact configured type name/code when the user writes it.
        configured_name = str(getattr(leave_type, "name", "") or "").strip().casefold()
        configured_code = str(getattr(leave_type, "code", "") or "").strip().casefold()
        if configured_name and configured_name in q and configured_name not in {"leave"}:
            return True
        if configured_code and re.search(rf"(?<![a-z0-9]){re.escape(configured_code)}(?![a-z0-9])", q):
            return True

        if not requested:
            return True
        matches = {
            "vacation": "vacation" in type_text or re.search(r"(?<![a-z])vl(?![a-z])", type_text),
            "sick": "sick" in type_text or re.search(r"(?<![a-z])sl(?![a-z])", type_text),
            "emergency": "emergency" in type_text or re.search(r"(?<![a-z])el(?![a-z])", type_text),
            "lwop": "without pay" in type_text or "unpaid" in type_text or "lwop" in type_text,
        }
        return any(bool(matches.get(name)) for name in requested)

    @staticmethod
    def _status_filter(question: str, request: LeaveRequest) -> bool:
        q = question.casefold()
        status = request.status
        if "pending" in q:
            return status in _PENDING_LEAVE_STATUSES
        if "rejected" in q:
            return status == "rejected"
        if "cancelled" in q or "canceled" in q:
            return status in {"cancelled", "partially_cancelled"}
        if "approved" in q:
            return status in _ACTIVE_LEAVE_STATUSES
        if "on leave" in q:
            return status in _ACTIVE_LEAVE_STATUSES
        return True

    def _leave_rows(self, current_user: AuthenticatedUser, role_scope: str, question: str, window: DateWindow) -> list[dict[str, Any]]:
        employees = self._authorized_employees(current_user, role_scope, question)
        ids = {item.id for item in employees}
        if not ids:
            return []
        requests = self.session.scalars(
            select(LeaveRequest)
            .where(LeaveRequest.company_id == current_user.company_id, LeaveRequest.employee_id.in_(ids))
            .order_by(LeaveRequest.start_date, LeaveRequest.id)
        ).unique().all()
        filed_mode = bool(re.search(r"\b(filed|submitted|created)\b", question, re.I))
        rows: list[dict[str, Any]] = []
        for request in requests:
            if not self._status_filter(question, request):
                continue
            if not self._leave_type_filter(question, request):
                continue
            if filed_mode:
                submitted = _local_date(request.submitted_at, self.timezone)
                if submitted is None or not (window.start <= submitted <= window.end):
                    continue
            elif request.end_date < window.start or request.start_date > window.end:
                continue
            employee = request.employee
            rows.append({
                "Employee": employee.full_name if employee else f"Employee ID {request.employee_id}",
                "Employee Number": employee.employee_number if employee else "—",
                "Department": employee.department.name if employee and employee.department else "Not assigned",
                "Leave Type": request.leave_type.name if request.leave_type else "Leave",
                "Start Date": request.start_date.isoformat(),
                "End Date": request.end_date.isoformat(),
                "Days": float(request.requested_days),
                "Status": request.status.replace("_", " ").title(),
                "Submitted Date": (_local_date(request.submitted_at, self.timezone) or request.start_date).isoformat(),
                "_employee_id": request.employee_id,
                "_start": request.start_date,
                "_end": request.end_date,
                "_status_raw": request.status,
            })
        return rows

    def _attendance_rows(self, current_user: AuthenticatedUser, role_scope: str, question: str, window: DateWindow, *, overtime_only: bool = False) -> list[dict[str, Any]]:
        employees = self._authorized_employees(current_user, role_scope, question)
        ids = {item.id for item in employees}
        if not ids:
            return []
        records = self.session.scalars(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.company_id == current_user.company_id,
                AttendanceRecord.employee_id.in_(ids),
                AttendanceRecord.attendance_date.between(window.start, window.end),
            )
            .order_by(AttendanceRecord.attendance_date, AttendanceRecord.employee_id)
        ).unique().all()
        rows: list[dict[str, Any]] = []
        q = question.casefold()
        for record in records:
            if overtime_only and float(record.ot_hours or 0) <= 0:
                continue
            status = str(record.work_status or "Not set").upper()
            if "wfo" in q and "wfh" not in q and status != "WFO":
                continue
            if "wfh" in q and "wfo" not in q and status != "WFH":
                continue
            employee = record.employee
            rows.append({
                "Employee": employee.full_name if employee else f"Employee ID {record.employee_id}",
                "Employee Number": employee.employee_number if employee else "—",
                "Department": employee.department.name if employee and employee.department else "Not assigned",
                "Date": record.attendance_date.isoformat(),
                "Work Status": status,
                "Work Hours": float(record.total_hours or 0),
                "Leave Hours": float(record.leave_hours or 0),
                "Undertime Hours": float(record.undertime_hours or 0),
                "OT Hours": float(record.ot_hours or 0),
                "_employee_id": record.employee_id,
                "_date": record.attendance_date,
            })
        return rows

    def _absence_rows(
        self,
        current_user: AuthenticatedUser,
        role_scope: str,
        question: str,
        window: DateWindow,
    ) -> list[dict[str, Any]]:
        """Return scheduled past/current workdays with neither attendance nor leave."""

        employees = [
            item for item in self._authorized_employees(current_user, role_scope, question)
            if str(item.employment_status or "").casefold() == "employed"
        ]
        if not employees:
            return []
        start = window.start
        end = min(window.end, self.now.date())
        if end < start:
            return []
        employee_ids = {item.id for item in employees}
        records = self.session.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.company_id == current_user.company_id,
                AttendanceRecord.employee_id.in_(employee_ids),
                AttendanceRecord.attendance_date.between(start, end),
            )
        ).unique().all()
        attendance_keys = {(row.employee_id, row.attendance_date) for row in records}
        leave_requests = self.session.scalars(
            select(LeaveRequest).where(
                LeaveRequest.company_id == current_user.company_id,
                LeaveRequest.employee_id.in_(employee_ids),
                LeaveRequest.end_date >= start,
                LeaveRequest.start_date <= end,
            )
        ).unique().all()
        leave_days: set[tuple[int, date]] = set()
        for request in leave_requests:
            if request.status not in _ACTIVE_LEAVE_STATUSES:
                continue
            day = max(start, request.start_date)
            last = min(end, request.end_date)
            while day <= last:
                leave_days.add((request.employee_id, day))
                day += timedelta(days=1)

        workdays = AttendanceService(self.session).workday_map(
            company_id=current_user.company_id,
            start_date=start,
            end_date=end,
        )
        rows: list[dict[str, Any]] = []
        for employee in employees:
            day = start
            while day <= end:
                if employee.hire_date and day < employee.hire_date:
                    day += timedelta(days=1)
                    continue
                if (
                    workdays.get(day, day.weekday() < 5)
                    and (employee.id, day) not in attendance_keys
                    and (employee.id, day) not in leave_days
                ):
                    rows.append({
                        "Employee": employee.full_name,
                        "Employee Number": employee.employee_number,
                        "Department": employee.department.name if employee.department else "Not assigned",
                        "Date": day.isoformat(),
                        "Work Status": "ABSENT",
                        "Work Hours": 0.0,
                        "Leave Hours": 0.0,
                        "Undertime Hours": 0.0,
                        "OT Hours": 0.0,
                        "_employee_id": employee.id,
                        "_date": day,
                    })
                day += timedelta(days=1)
        return rows

    @staticmethod
    def _month_buckets(window: DateWindow) -> list[tuple[int, int]]:
        result = []
        year, month = window.start.year, window.start.month
        while (year, month) <= (window.end.year, window.end.month):
            result.append((year, month))
            year, month = _shift_month(year, month, 1)
        return result

    def _chart_for_leave(self, rows: list[dict[str, Any]], question: str, window: DateWindow) -> dict[str, Any] | None:
        if not rows:
            return None
        q = question.casefold()
        chart_type = "line" if any(term in q for term in ("line chart", "trend", "monthly", "per month", "by month")) else "bar"
        if any(term in q for term in ("pie", "donut", "breakdown")):
            chart_type = "donut" if "pie" not in q else "pie"

        if chart_type == "line" or "per month" in q or "by month" in q:
            data = []
            employee_metric = "employee" in q or "on leave" in q
            day_metric = "days" in q and not employee_metric
            for year, month in self._month_buckets(window):
                bucket_start = date(year, month, 1)
                bucket_end = _month_end(year, month)
                bucket_rows = [
                    row for row in rows
                    if row["_end"] >= bucket_start and row["_start"] <= bucket_end
                ]
                if employee_metric:
                    value = len({
                        row["_employee_id"] for row in bucket_rows
                        if row["_status_raw"] in _ACTIVE_LEAVE_STATUSES
                    })
                elif day_metric:
                    value = round(sum(float(row["Days"]) for row in bucket_rows), 2)
                else:
                    value = len(bucket_rows)
                data.append({
                    "label": date(year, month, 1).strftime("%b %Y"),
                    "value": value,
                })
            if employee_metric:
                title, value_label = "Employees on leave by month", "Employees"
            elif day_metric:
                title, value_label = "Requested leave days by month", "Leave days"
            else:
                title, value_label = "Leave requests by month", "Requests"
            return {
                "type": "line",
                "title": title,
                "category_label": "Month",
                "value_label": value_label,
                "data": data,
            }

        group_key = "Leave Type"
        title = "Leave requests by type"
        if "department" in q:
            group_key, title = "Department", "Leave requests by department"
        elif "status" in q:
            group_key, title = "Status", "Leave requests by status"
        counts: dict[str, float] = defaultdict(float)
        for row in rows:
            counts[str(row[group_key])] += 1
        data = [{"label": label, "value": value} for label, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
        return {"type": chart_type, "title": title, "category_label": group_key, "value_label": "Requests", "data": data}

    def _chart_for_attendance(self, rows: list[dict[str, Any]], question: str, window: DateWindow, *, overtime: bool) -> dict[str, Any] | None:
        if not rows:
            return None
        q = question.casefold()
        if overtime:
            value_key = "OT Hours"
            value_label = "OT hours"
            default_title = "Overtime hours"
        else:
            value_key = "Work Hours"
            value_label = "Work hours"
            default_title = "Attendance work hours"

        chart_type = "line" if any(term in q for term in ("line chart", "trend", "monthly", "per month", "by month")) else "bar"
        if any(term in q for term in ("pie", "donut", "breakdown", "wfo vs wfh", "wfh vs wfo")):
            chart_type = "donut" if "pie" not in q else "pie"

        quarter_compare = re.search(
            r"\bq([1-4])\s+(?:to|vs|versus|through|-)\s+q([1-4])(?:\s+(20\d{2}|19\d{2}))?\b",
            q,
            re.I,
        )
        if quarter_compare:
            q1 = int(quarter_compare.group(1))
            q2 = int(quarter_compare.group(2))
            base_year = int(quarter_compare.group(3) or window.start.year)
            period_totals: dict[str, float] = {}
            for quarter, year in ((q1, base_year), (q2, base_year + (1 if q2 < q1 else 0))):
                start_month = 1 + (quarter - 1) * 3
                quarter_start = date(year, start_month, 1)
                quarter_end = _month_end(year, start_month + 2)
                value = sum(
                    float(row[value_key])
                    for row in rows
                    if quarter_start <= row["_date"] <= quarter_end
                )
                period_totals[f"Q{quarter} {year}"] = round(value, 2)
            return {
                "type": "bar",
                "title": f"{default_title} by quarter",
                "category_label": "Quarter",
                "value_label": value_label,
                "data": [
                    {"label": label, "value": value}
                    for label, value in period_totals.items()
                ],
            }

        if chart_type == "line" or "per month" in q or "by month" in q:
            totals: dict[tuple[int, int], float] = defaultdict(float)
            for row in rows:
                work_date = row["_date"]
                totals[(work_date.year, work_date.month)] += float(row[value_key])
            data = [
                {"label": date(year, month, 1).strftime("%b %Y"), "value": round(totals.get((year, month), 0.0), 2)}
                for year, month in self._month_buckets(window)
            ]
            return {"type": "line", "title": f"{default_title} by month", "category_label": "Month", "value_label": value_label, "data": data}

        if "department" in q:
            group_key = "Department"
        elif any(term in q for term in ("employee", "highest", "top")) and overtime:
            group_key = "Employee"
        elif not overtime and any(term in q for term in ("wfo", "wfh", "status", "breakdown", "pie", "donut")):
            group_key = "Work Status"
            value_key = "_record_count"
            value_label = "Records"
        else:
            group_key = "Employee" if overtime else "Work Status"
            if not overtime:
                value_key = "_record_count"
                value_label = "Records"

        totals: dict[str, float] = defaultdict(float)
        if value_key == "_record_count" and "employee" in q:
            employees_by_group: dict[str, set[int]] = defaultdict(set)
            for row in rows:
                employees_by_group[str(row[group_key])].add(int(row["_employee_id"]))
            totals = {label: float(len(ids)) for label, ids in employees_by_group.items()}
            value_label = "Employees"
        else:
            for row in rows:
                totals[str(row[group_key])] += 1.0 if value_key == "_record_count" else float(row[value_key])
        data = [{"label": label, "value": round(value, 2)} for label, value in sorted(totals.items(), key=lambda item: (-item[1], item[0]))]
        return {"type": chart_type, "title": f"{default_title} by {group_key.casefold()}", "category_label": group_key, "value_label": value_label, "data": data}

    @staticmethod
    def _public_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in rows
        ]

    def _artifact(self, *, title: str, window: DateWindow, rows: list[dict[str, Any]], summary: list[str], chart: dict[str, Any] | None, domain: str) -> dict[str, Any]:
        public_rows = self._public_rows(rows)
        columns = list(public_rows[0]) if public_rows else []
        return {
            "title": title,
            "period": window.label,
            "start_date": window.start.isoformat(),
            "end_date": window.end.isoformat(),
            "generated_at": self.now.isoformat(),
            "timezone": self.settings.display_timezone,
            "summary": summary,
            "columns": columns,
            "rows": public_rows,
            "chart": chart,
            "domain": domain,
        }

    @staticmethod
    def _leave_list_answer(rows: list[dict[str, Any]], window: DateWindow) -> str:
        if not rows:
            return f"No matching leave records were found for **{window.label}**."
        lines = [f"Matching leave records for **{window.label}**:"]
        for row in rows:
            lines.append(
                f"- **{row['Employee']}** — {row['Leave Type']} — "
                f"{row['Start Date']} to {row['End Date']} — {row['Status']}"
            )
        return "\n".join(lines)

    def _leave_result(self, current_user: AuthenticatedUser, role_scope: str, question: str, window: DateWindow, wants_report: bool) -> ChatReportResult:
        rows = self._leave_rows(current_user, role_scope, question, window)
        q = question.casefold()
        asks_employee_count = bool(re.search(r"how many\s+(?:authorized\s+)?employees?", q)) or "employee count" in q
        asks_list = bool(re.search(r"\b(list|show|who|which employees?)\b", q))
        asks_binary_leave_status = bool(
            re.match(r"\s*(?:is|are|was|were)\b", q) and "on leave" in q
        )

        if not wants_report and asks_binary_leave_status:
            if not rows:
                return ChatReportResult(
                    f"**NO.** No authorized employee matching the question is on leave for **{window.label}**."
                )
            employees = sorted({row["Employee"] for row in rows})
            detail = ", ".join(employees)
            return ChatReportResult(
                f"**YES.** {detail} {'is' if len(employees) == 1 else 'are'} on leave for **{window.label}**."
            )

        if not wants_report and asks_employee_count:
            employee_count = len({row["_employee_id"] for row in rows})
            return ChatReportResult(f"**{employee_count}** authorized employee(s) match the leave criteria for **{window.label}**.")
        if not wants_report and asks_list:
            if "employee" in q or "who" in q:
                if not rows:
                    return ChatReportResult(
                        f"No matching employees were found on leave for **{window.label}**."
                    )
                grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
                for row in rows:
                    grouped[int(row["_employee_id"])].append(row)
                lines = [f"Employees matching the leave criteria for **{window.label}**:"]
                for employee_rows in grouped.values():
                    first = employee_rows[0]
                    details = "; ".join(
                        f"{item['Leave Type']} {item['Start Date']} to {item['End Date']}"
                        for item in employee_rows
                    )
                    lines.append(f"- **{first['Employee']}** — {details}")
                return ChatReportResult("\n".join(lines))
            return ChatReportResult(self._leave_list_answer(rows, window))
        if not wants_report and "how many" in q:
            return ChatReportResult(f"**{len(rows)}** leave request(s) match the criteria for **{window.label}**.")

        employee_count = len({row["_employee_id"] for row in rows})
        total_days = sum(float(row["Days"]) for row in rows)
        summary = [
            f"Leave requests: {len(rows)}",
            f"Employees represented: {employee_count}",
            f"Requested leave days: {_format_number(total_days)}",
        ]
        chart = self._chart_for_leave(rows, question, window)
        artifact = self._artifact(
            title=f"Leave Report — {window.label}",
            window=window,
            rows=rows,
            summary=summary,
            chart=chart,
            domain="leave",
        )
        answer = (
            f"**Leave Report — {window.label}**\n\n"
            + "\n".join(f"- {item}" for item in summary)
        )
        return ChatReportResult(answer, artifact)

    def _attendance_result(self, current_user: AuthenticatedUser, role_scope: str, question: str, window: DateWindow, wants_report: bool, *, overtime: bool) -> ChatReportResult:
        q = question.casefold()
        rows = (
            self._absence_rows(current_user, role_scope, question, window)
            if (not overtime and any(term in q for term in ("absent", "absence")))
            else self._attendance_rows(
                current_user, role_scope, question, window, overtime_only=overtime
            )
        )
        if not wants_report and "how many" in q:
            if "employees" in q:
                count = len({row["_employee_id"] for row in rows})
                label = "employee(s)"
            else:
                count = len(rows)
                label = "attendance record(s)"
            return ChatReportResult(f"**{count}** {label} match the criteria for **{window.label}**.")
        if not wants_report and re.search(r"\b(list|show|who)\b", q):
            if not rows:
                return ChatReportResult(f"No matching {'overtime' if overtime else 'attendance'} records were found for **{window.label}**.")
            lines = [f"Matching {'overtime' if overtime else 'attendance'} records for **{window.label}**:"]
            for row in rows:
                detail = f"OT { _format_number(float(row['OT Hours'])) } h" if overtime else f"{row['Work Status']} — {_format_number(float(row['Work Hours']))} h"
                lines.append(f"- **{row['Employee']}** — {row['Date']} — {detail}")
            return ChatReportResult("\n".join(lines))

        total_work = sum(float(row["Work Hours"]) for row in rows)
        total_ot = sum(float(row["OT Hours"]) for row in rows)
        employee_count = len({row["_employee_id"] for row in rows})
        summary = [
            f"Records: {len(rows)}",
            f"Employees represented: {employee_count}",
            f"Total work hours: {_format_number(total_work)}",
            f"Total OT hours: {_format_number(total_ot)}",
        ]
        title = f"{'Overtime' if overtime else 'Attendance'} Report — {window.label}"
        chart = self._chart_for_attendance(rows, question, window, overtime=overtime)
        artifact = self._artifact(title=title, window=window, rows=rows, summary=summary, chart=chart, domain="overtime" if overtime else "attendance")
        return ChatReportResult(
            f"**{title}**\n\n" + "\n".join(f"- {item}" for item in summary),
            artifact,
        )

    @staticmethod
    def _last_assistant_intent(history: list[dict] | None) -> str | None:
        for message in reversed(history or []):
            if message.get("role") != "assistant":
                continue
            intent = str(message.get("intent", "")).strip()
            if intent:
                return intent
        return None

    def _contextual_question(
        self,
        question: str,
        history: list[dict] | None,
    ) -> str:
        """Carry report domain/filter context into short follow-up questions."""

        cleaned = re.sub(r"\s+", " ", question or "").strip()
        if not cleaned or self._domain(cleaned) is not None:
            return cleaned
        if self._last_assistant_intent(history) != "live_report":
            return cleaned

        follow_up = bool(
            re.search(
                r"\b(?:what about|how about|how many|count|list|show|who|which|names?|them|those|same|next|previous|last|this)\b",
                cleaned,
                re.I,
            )
            or self._TEMPORAL_TERMS.search(cleaned)
            or re.fullmatch(r"(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")(?:\s+(?:20\d{2}|19\d{2}))?[?.!]*", cleaned, re.I)
        )
        if not follow_up:
            return cleaned

        previous = None
        for message in reversed(history or []):
            if message.get("role") != "user":
                continue
            candidate = str(message.get("content", "")).strip()
            if candidate and self._domain(candidate) is not None:
                previous = candidate
                break
        if previous is None:
            return cleaned

        # Put the new wording first: when the follow-up changes the month/year,
        # the parser sees that new period before the old period while retaining
        # the previous domain/status/type filters later in the string.
        return f"{cleaned} {previous}"

    def try_answer(
        self,
        *,
        current_user: AuthenticatedUser,
        role_scope: str,
        question: str,
        history: list[dict] | None = None,
    ) -> ChatReportResult | None:
        """Return a deterministic temporal/report answer when the query qualifies."""

        cleaned = self._contextual_question(question, history)
        if not cleaned:
            return None
        domain = self._domain(cleaned)
        if domain is None:
            return None
        wants_report = bool(self._REPORT_TERMS.search(cleaned))
        has_temporal = bool(self._TEMPORAL_TERMS.search(cleaned))
        if (
            not wants_report
            and (
                not self._DATA_QUERY_TERMS.search(cleaned)
                or self._NON_REPORT_EXPLANATION_TERMS.search(cleaned)
            )
        ):
            return None
        # Preserve the established exact "on leave today" route unless the user
        # explicitly asks for a report/chart; v8.8.174 behavior stays intact.
        if not wants_report and re.search(r"\bon leave today\b", cleaned, re.I):
            return None
        if not wants_report and not has_temporal:
            return None

        window = self.parser.parse(cleaned, default_when_report=wants_report)
        if window is None:
            return None
        if domain == "leave":
            return self._leave_result(current_user, role_scope, cleaned, window, wants_report)
        if domain == "overtime":
            return self._attendance_result(current_user, role_scope, cleaned, window, wants_report, overtime=True)
        return self._attendance_result(current_user, role_scope, cleaned, window, wants_report, overtime=False)
