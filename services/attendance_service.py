"""Company-scoped attendance, DTR, leave synchronization, and OT service."""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from config.settings import get_settings
from models.attendance_correction import AttendanceCorrection
from models.attendance_record import AttendanceRecord
from models.attendance_session import AttendanceSession
from models.company import Company
from models.employee import Employee
from models.leave_request import LeaveRequest
from models.user import User
from repositories.attendance_repository import AttendanceRepository
from repositories.company_workday_repository import CompanyWorkdayRepository
from schemas.attendance_schema import (
    CompanyAttendanceCalendarInput,
    CompanyOvertimeRulesInput,
    AttendanceCorrectionInput,
    AttendancePunchInput,
    AttendanceSessionInput,
    AttendanceSelfEditInput,
    AttendanceStatusInput,
)
from services.attendance_calculations import (
    calculate_attendance_hours,
    calculate_session_hours,
    calculate_work_rate,
    round_time_in_up,
    round_time_out_down,
)


ATTENDANCE_COLORS = {
    "WFO": "#FFCC99",
    "WFH": "#92D050",
    "VL": "#FFCCFF",
    "SL": "#FFCCFF",
    "EL": "#FFCCFF",
    "HYBRID": "#D9EAD3",
}
WEEKEND_COLOR = "#BFBFBF"
APPROVED_LEAVE_STATUSES = {
    "scheduled",
    "approved",
    "in_progress",
    "completed",
    "partially_cancelled",
}


@dataclass(slots=True)
class AttendanceMatrix:
    """Detached monthly DTR values ready for presentation."""

    employees: list[Employee]
    dates: list[date]
    records: dict[tuple[int, date], AttendanceRecord]
    scheduled_workdays: dict[date, bool] = field(default_factory=dict)


@dataclass(slots=True)
class EmployeeAttendanceSummary:
    """Selected employee totals for one monthly dashboard period."""

    leave_count: int
    overtime_hours_day: Decimal
    total_overtime_hours: Decimal
    total_hours: Decimal
    total_working_days: int
    work_rate: Decimal


@dataclass(slots=True)
class AttendanceHistoryEntry:
    """Detached attendance edit-history row for the admin dashboard."""

    employee_name: str
    attendance_date: date
    edited_by: str
    changed_at: str
    change_type: str
    reason: str
    previous_time_in: str
    new_time_in: str
    previous_time_out: str
    new_time_out: str
    previous_status: str
    new_status: str


class AttendanceService:
    """Apply tenant, ownership, hierarchy, leave, and schedule rules."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AttendanceRepository(session)
        self.workday_repository = CompanyWorkdayRepository(session)
        self.timezone = ZoneInfo(get_settings().display_timezone)

    def _company(self, company_id: int) -> Company:
        company = self.session.get(Company, company_id)
        if company is None:
            raise ValueError("The company record was not found.")
        return company

    def get_company(self, company_id: int) -> Company:
        """Return company attendance settings for an authorized UI scope."""

        return self._company(company_id)

    @staticmethod
    def overtime_excluded_positions(company: Company) -> list[str]:
        """Return the normalized company-configured shifting exclusions."""

        raw = company.shifting_credit_excluded_positions_json or "[]"
        try:
            values = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        if not isinstance(values, list):
            values = []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values:
            value = " ".join(str(item or "").strip().split())
            token = value.casefold()
            if value and token not in seen:
                seen.add(token)
                cleaned.append(value)
        return cleaned

    def save_overtime_rules(self, values: CompanyOvertimeRulesInput) -> Company:
        """Persist company OT/shifting rules without changing the DTR calendar."""

        company = self._company(values.company_id)
        company.ot_dinner_break_deduction_hours = values.dinner_break_deduction_hours
        company.shifting_credits_enabled = values.shifting_credits_enabled
        company.shifting_credit_block_hours = values.shifting_credit_block_hours
        company.shifting_credit_required_blocks = values.shifting_credit_required_blocks
        company.shifting_credit_cutoff_day = values.shifting_credit_cutoff_day
        company.shifting_credit_additional_vl_threshold_hours = (
            values.additional_vl_threshold_hours
        )
        company.shifting_credit_additional_vl_days = values.additional_vl_days
        company.shifting_credit_excluded_positions_json = json.dumps(
            values.excluded_positions, ensure_ascii=False
        )
        self.session.commit()
        self.session.refresh(company)
        return company

    def _employee(self, company_id: int, employee_id: int) -> Employee:
        employee = self.session.scalar(
            select(Employee).where(
                Employee.id == employee_id,
                Employee.company_id == company_id,
            )
        )
        if employee is None:
            raise ValueError("The employee record was not found.")
        return employee

    def _require_employee_owner(
        self, company_id: int, employee_id: int, user_id: int
    ) -> Employee:
        employee = self._employee(company_id, employee_id)
        if employee.user_id != user_id:
            raise ValueError("You can record attendance only for your own account.")
        return employee

    def _new_record(
        self,
        *,
        company: Company,
        employee_id: int,
        attendance_date: date,
        work_status: str | None = None,
    ) -> AttendanceRecord:
        return AttendanceRecord(
            company_id=company.id,
            employee_id=employee_id,
            attendance_date=attendance_date,
            work_status=work_status,
            status_source="manual",
            scheduled_workday=self.is_company_workday(
                company.id,
                attendance_date,
            ),
            regular_hours_target=company.attendance_regular_hours,
            lunch_break_minutes=company.attendance_lunch_minutes,
        )

    def _get_or_create(
        self, company: Company, employee_id: int, attendance_date: date
    ) -> AttendanceRecord:
        record = self.repository.get_daily(
            company_id=company.id,
            employee_id=employee_id,
            attendance_date=attendance_date,
        )
        if record is None:
            record = self._new_record(
                company=company,
                employee_id=employee_id,
                attendance_date=attendance_date,
            )
            self.session.add(record)
            self.session.flush()
        return record

    def _localize_input(self, value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=self.timezone)
        return value.astimezone(timezone.utc)

    def to_local(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(self.timezone)

    def _recalculate(self, record: AttendanceRecord) -> None:
        sessions = list(getattr(record, "sessions", ()) or ())
        if sessions:
            total, ot, undertime = calculate_session_hours(
                sessions,
                scheduled_workday=record.scheduled_workday,
                regular_hours=record.regular_hours_target,
                lunch_break_minutes=record.lunch_break_minutes,
                leave_hours=record.leave_hours,
            )
            completed = [item for item in sessions if item.actual_time_out is not None]
            if len(completed) != len(sessions):
                # An open session means the workday is still in progress. Do
                # not label the employee undertime before their final logout.
                undertime = Decimal("0.00")
            record.time_in = min(
                sessions,
                key=self._session_sort_key,
            ).actual_time_in
            record.time_out = (
                max(
                    completed,
                    key=lambda item: (
                        item.actual_time_out.replace(tzinfo=timezone.utc)
                        if item.actual_time_out.tzinfo is None
                        else item.actual_time_out
                    ),
                ).actual_time_out
                if completed and len(completed) == len(sessions)
                else None
            )
            locations = {item.work_status for item in sessions}
            record.work_status = (
                "HYBRID" if len(locations) > 1 else next(iter(locations))
            )
        else:
            total, ot = calculate_attendance_hours(
                record.time_in,
                record.time_out,
                scheduled_workday=record.scheduled_workday,
                regular_hours=max(
                    Decimal("0.00"),
                    Decimal(record.regular_hours_target) - Decimal(record.leave_hours),
                ),
                lunch_break_minutes=record.lunch_break_minutes,
            )
            undertime = (
                max(
                    Decimal("0.00"),
                    Decimal(record.regular_hours_target)
                    - Decimal(record.leave_hours)
                    - Decimal(total),
                )
                if record.scheduled_workday and record.time_in is not None
                else Decimal("0.00")
            )
        record.total_hours = total
        record.ot_hours = ot
        record.undertime_hours = undertime

    @staticmethod
    def _session_sort_key(session: AttendanceSession) -> datetime:
        value = session.actual_time_in
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    def _replace_sessions(
        self,
        *,
        record: AttendanceRecord,
        inputs: list[AttendanceSessionInput],
        source: str,
        corrected_by_user_id: int,
        correction_reason: str,
    ) -> None:
        """Replace editable sessions after validating actual non-overlap."""

        localized = sorted(
            (
                (
                    item,
                    self._localize_input(item.time_in),
                    self._localize_input(item.time_out) if item.time_out else None,
                )
                for item in inputs
            ),
            key=lambda values: values[1],
        )
        for previous, current in zip(localized, localized[1:]):
            if previous[2] is None or current[1] < previous[2]:
                raise ValueError("Attendance sessions cannot overlap.")
        record.sessions.clear()
        record.time_in = None
        record.time_out = None
        for sequence, (item, actual_in, actual_out) in enumerate(localized, start=1):
            record.sessions.append(
                AttendanceSession(
                    company_id=record.company_id,
                    sequence_number=sequence,
                    work_status=item.work_status,
                    actual_time_in=actual_in,
                    actual_time_out=actual_out,
                    rounded_time_in=round_time_in_up(actual_in),
                    rounded_time_out=(
                        round_time_out_down(actual_out) if actual_out else None
                    ),
                    source=source,
                    corrected_by_user_id=corrected_by_user_id,
                    correction_reason=correction_reason,
                )
            )

    def workday_map(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
    ) -> dict[date, bool]:
        """Return saved calendar choices with Mon–Fri defaults."""

        if end_date < start_date:
            return {}
        saved = {
            row.work_date: bool(row.is_workday)
            for row in self.workday_repository.list_range(
                company_id=company_id,
                start_date=start_date,
                end_date=end_date,
            )
        }
        day = start_date
        result: dict[date, bool] = {}
        while day <= end_date:
            result[day] = saved.get(day, day.weekday() < 5)
            day += timedelta(days=1)
        return result

    def monthly_workday_map(
        self,
        *,
        company_id: int,
        year: int,
        month: int,
    ) -> dict[date, bool]:
        """Return every selected/rest-day state for one calendar month."""

        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        return self.workday_map(
            company_id=company_id,
            start_date=first,
            end_date=last,
        )

    def is_company_workday(
        self,
        company_id: int,
        work_date: date,
    ) -> bool:
        """Return the saved daily choice or the default weekday state."""

        return self.workday_map(
            company_id=company_id,
            start_date=work_date,
            end_date=work_date,
        )[work_date]

    def save_attendance_calendar(
        self,
        values: CompanyAttendanceCalendarInput,
    ) -> None:
        """Save one month and recalculate its existing attendance records."""

        company = self._company(values.company_id)
        first = date(values.year, values.month, 1)
        last = date(
            values.year,
            values.month,
            calendar.monthrange(values.year, values.month)[1],
        )
        selected = set(values.work_dates)
        day = first
        calendar_values: dict[date, bool] = {}
        while day <= last:
            calendar_values[day] = day in selected
            day += timedelta(days=1)

        company.attendance_regular_hours = values.regular_hours
        company.attendance_lunch_minutes = values.lunch_break_minutes
        self.workday_repository.replace_range(
            company_id=values.company_id,
            start_date=first,
            end_date=last,
            workday_values=calendar_values,
        )

        # Existing rows retain an audit snapshot of their prior values, while
        # the current DTR/OT result follows the newly saved monthly schedule.
        for record in self.repository.list_range(
            company_id=values.company_id,
            start_date=first,
            end_date=last,
        ):
            record.scheduled_workday = calendar_values[record.attendance_date]
            record.regular_hours_target = values.regular_hours
            record.lunch_break_minutes = values.lunch_break_minutes
            self._recalculate(record)

        self.session.commit()

    def get_daily(
        self, *, company_id: int, employee_id: int, attendance_date: date
    ) -> AttendanceRecord | None:
        self.sync_approved_leaves(company_id, attendance_date, attendance_date)
        return self.repository.get_daily(
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=attendance_date,
        )

    def set_daily_status(self, values: AttendanceStatusInput) -> AttendanceRecord:
        self._require_employee_owner(values.company_id, values.employee_id, values.user_id)
        self.sync_approved_leaves(
            values.company_id, values.attendance_date, values.attendance_date
        )
        company = self._company(values.company_id)
        record = self._get_or_create(company, values.employee_id, values.attendance_date)
        if record.status_source == "approved_leave":
            raise ValueError("Approved Leave Management status controls this date.")
        record.work_status = values.work_status
        record.status_source = "manual"
        self.session.commit()
        self.session.refresh(record)
        return record

    def edit_own_work_status(
        self,
        values: AttendanceStatusInput,
    ) -> AttendanceRecord:
        """Edit only Work Status without changing any attendance punch."""

        self._require_employee_owner(
            values.company_id,
            values.employee_id,
            values.user_id,
        )
        self.sync_approved_leaves(
            values.company_id,
            values.attendance_date,
            values.attendance_date,
        )
        company = self._company(values.company_id)
        record = self._get_or_create(
            company,
            values.employee_id,
            values.attendance_date,
        )
        before = self._snapshot(record)
        record.work_status = values.work_status
        record.status_source = "employee_status_edit"
        record.corrected_by_user_id = values.user_id
        record.corrected_at = datetime.now(timezone.utc)
        record.correction_reason = "Employee Work Status-only edit"
        self.session.flush()
        self.session.add(
            AttendanceCorrection(
                company_id=values.company_id,
                attendance_record_id=record.id,
                employee_id=values.employee_id,
                corrected_by_user_id=values.user_id,
                reason="Employee Work Status-only edit",
                previous_values_json=json.dumps(before, sort_keys=True),
                new_values_json=json.dumps(self._snapshot(record), sort_keys=True),
            )
        )
        self.session.commit()
        self.session.refresh(record)
        return record

    def clock_in(self, values: AttendancePunchInput) -> AttendanceRecord:
        self._require_employee_owner(values.company_id, values.employee_id, values.user_id)
        self.sync_approved_leaves(
            values.company_id, values.attendance_date, values.attendance_date
        )
        company = self._company(values.company_id)
        record = self._get_or_create(company, values.employee_id, values.attendance_date)
        if values.work_status not in {"WFO", "WFH"}:
            raise ValueError("Login work location must be WFO or WFH.")
        if any(item.actual_time_out is None for item in record.sessions):
            raise ValueError("Logout the current attendance session before logging in again.")
        actual_in = self._localize_input(values.occurred_at)
        if record.sessions:
            previous = max(record.sessions, key=self._session_sort_key)
            if previous.actual_time_out is not None:
                previous_out = previous.actual_time_out
                if previous_out.tzinfo is None:
                    previous_out = previous_out.replace(tzinfo=timezone.utc)
                if actual_in < previous_out:
                    raise ValueError("A new attendance session cannot overlap the previous session.")
        record.sessions.append(
            AttendanceSession(
                company_id=record.company_id,
                sequence_number=len(record.sessions) + 1,
                work_status=values.work_status,
                actual_time_in=actual_in,
                rounded_time_in=round_time_in_up(actual_in),
                source="employee_punch",
            )
        )
        record.status_source = "employee_punch"
        self._recalculate(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def clock_out(self, values: AttendancePunchInput) -> AttendanceRecord:
        self._require_employee_owner(values.company_id, values.employee_id, values.user_id)
        record = self.repository.get_daily(
            company_id=values.company_id,
            employee_id=values.employee_id,
            attendance_date=values.attendance_date,
        )
        if record is None:
            raise ValueError("Record Login before recording Logout.")
        open_sessions = [item for item in record.sessions if item.actual_time_out is None]
        if not open_sessions:
            raise ValueError("Record Login before recording Logout.")
        session = max(open_sessions, key=self._session_sort_key)
        occurred_at = self._localize_input(values.occurred_at)
        time_in = session.actual_time_in
        if time_in.tzinfo is None:
            time_in = time_in.replace(tzinfo=timezone.utc)
        if occurred_at <= time_in:
            raise ValueError("Logout must be later than Login.")
        session.actual_time_out = occurred_at
        session.rounded_time_out = round_time_out_down(occurred_at)
        self._recalculate(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def edit_own_daily_attendance(
        self,
        values: AttendanceSelfEditInput,
    ) -> AttendanceRecord:
        """Allow an employee to edit their own selected daily record.

        Approved leave supplies the initial VL, SL, or EL status but the
        employee may replace that default. Every edit receives an immutable
        before/after audit snapshot.
        """

        self._require_employee_owner(
            values.company_id,
            values.employee_id,
            values.user_id,
        )
        self.sync_approved_leaves(
            values.company_id,
            values.attendance_date,
            values.attendance_date,
        )
        company = self._company(values.company_id)
        record = self._get_or_create(
            company,
            values.employee_id,
            values.attendance_date,
        )
        before = self._snapshot(record)
        preserved_work_status = record.work_status
        time_in = (
            self._localize_input(values.time_in)
            if values.time_in is not None
            else None
        )
        time_out = (
            self._localize_input(values.time_out)
            if values.time_out is not None
            else None
        )
        if time_out is not None and time_in is None:
            raise ValueError("Time In is required when Time Out is provided.")
        if time_in is not None and time_out is not None and time_out <= time_in:
            raise ValueError("Time Out must be later than Time In.")

        session_inputs = list(values.sessions)
        if not session_inputs and time_in is not None:
            session_inputs = [
                AttendanceSessionInput(
                    work_status=(
                        values.work_status
                        if values.work_status in {"WFO", "WFH"}
                        else "WFO"
                    ),
                    time_in=values.time_in,
                    time_out=values.time_out,
                )
            ]
        self._replace_sessions(
            record=record,
            inputs=session_inputs,
            source="employee_edit",
            corrected_by_user_id=values.user_id,
            correction_reason="Employee self-service edit",
        )
        if not session_inputs:
            record.work_status = values.work_status
            record.time_in = None
            record.time_out = None
        record.status_source = "employee_edit"
        record.corrected_by_user_id = values.user_id
        record.corrected_at = datetime.now(timezone.utc)
        record.correction_reason = "Employee self-service edit"
        self._recalculate(record)
        # Session/timestamp maintenance must not silently replace a Work
        # Status that the employee selected separately. New records still
        # receive the normal session-derived location.
        if preserved_work_status is not None:
            record.work_status = preserved_work_status
        self.session.flush()
        self.session.add(
            AttendanceCorrection(
                company_id=values.company_id,
                attendance_record_id=record.id,
                employee_id=values.employee_id,
                corrected_by_user_id=values.user_id,
                reason="Employee self-service edit",
                previous_values_json=json.dumps(before, sort_keys=True),
                new_values_json=json.dumps(self._snapshot(record), sort_keys=True),
            )
        )
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_correction_history(
        self,
        *,
        company_id: int,
        limit: int = 200,
    ) -> list[AttendanceHistoryEntry]:
        """Return company-scoped admin and employee attendance edits."""

        statement = (
            select(
                AttendanceCorrection,
                AttendanceRecord,
                Employee,
                User,
            )
            .join(
                AttendanceRecord,
                AttendanceRecord.id
                == AttendanceCorrection.attendance_record_id,
            )
            .join(
                Employee,
                Employee.id == AttendanceCorrection.employee_id,
            )
            .join(
                User,
                User.id == AttendanceCorrection.corrected_by_user_id,
            )
            .where(
                AttendanceCorrection.company_id == company_id,
                AttendanceRecord.company_id == company_id,
                Employee.company_id == company_id,
                User.company_id == company_id,
            )
            .order_by(
                AttendanceCorrection.created_at.desc(),
                AttendanceCorrection.id.desc(),
            )
            .limit(max(1, min(int(limit), 1000)))
        )

        history: list[AttendanceHistoryEntry] = []
        for correction, record, employee, actor in self.session.execute(statement):
            try:
                previous = json.loads(correction.previous_values_json or "{}")
            except (TypeError, json.JSONDecodeError):
                previous = {}
            try:
                current = json.loads(correction.new_values_json or "{}")
            except (TypeError, json.JSONDecodeError):
                current = {}

            changed_at = correction.created_at
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=timezone.utc)
            changed_at_text = changed_at.astimezone(self.timezone).strftime(
                "%Y/%m/%d %H:%M"
            )

            history.append(
                AttendanceHistoryEntry(
                    employee_name=employee.full_name,
                    attendance_date=record.attendance_date,
                    edited_by=actor.username,
                    changed_at=changed_at_text,
                    change_type=(
                        "Employee Edit"
                        if correction.reason == "Employee self-service edit"
                        else "Admin Correction"
                    ),
                    reason=correction.reason,
                    previous_time_in=self._snapshot_local_time(
                        previous.get("time_in")
                    ),
                    new_time_in=self._snapshot_local_time(
                        current.get("time_in")
                    ),
                    previous_time_out=self._snapshot_local_time(
                        previous.get("time_out")
                    ),
                    new_time_out=self._snapshot_local_time(
                        current.get("time_out")
                    ),
                    previous_status=str(previous.get("work_status") or "—"),
                    new_status=str(current.get("work_status") or "—"),
                )
            )
        return history

    def _snapshot_local_time(self, value: object) -> str:
        """Format an ISO audit value in the configured display timezone."""

        if not value:
            return "—"
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return "—"
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(self.timezone).strftime("%H:%M")

    @staticmethod
    def _leave_code(request: LeaveRequest) -> str:
        label = f"{request.leave_type.code} {request.leave_type.name}".upper()
        if "SICK" in label or label.strip().startswith("SL"):
            return "SL"
        if "EMERGENCY" in label or label.strip().startswith("EL"):
            return "EL"
        return "VL"

    def sync_approved_leaves(
        self, company_id: int, start_date: date, end_date: date
    ) -> None:
        company = self._company(company_id)
        requests = list(
            self.session.scalars(
                select(LeaveRequest)
                .options(joinedload(LeaveRequest.leave_type))
                .where(
                    LeaveRequest.company_id == company_id,
                    LeaveRequest.status.in_(APPROVED_LEAVE_STATUSES),
                    LeaveRequest.start_date <= end_date,
                    LeaveRequest.end_date >= start_date,
                )
            ).unique().all()
        )
        workdays = self.workday_map(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
        )
        expected: dict[tuple[int, date], LeaveRequest] = {}
        for request in requests:
            day = max(request.start_date, start_date)
            last = min(request.end_date, end_date)
            while day <= last:
                cancellation_cutoff = (
                    request.cancellation_effective_date
                    if request.cancellation_status == "approved"
                    else None
                )
                if workdays[day] and (
                    cancellation_cutoff is None or day < cancellation_cutoff
                ):
                    expected[(request.employee_id, day)] = request
                day += timedelta(days=1)

        for record in self.repository.list_leave_linked_range(
            company_id=company_id, start_date=start_date, end_date=end_date
        ):
            if (record.employee_id, record.attendance_date) not in expected:
                if record.status_source == "approved_leave":
                    record.work_status = None
                    record.status_source = "manual"
                record.leave_request_id = None
                record.leave_duration_code = None
                record.leave_hours = Decimal("0.00")
                self._recalculate(record)

        for (employee_id, day), request in expected.items():
            record = self._get_or_create(company, employee_id, day)
            previous_leave_request_id = record.leave_request_id
            duration_code = request.duration_code or "90503"
            record.leave_duration_code = duration_code
            record.leave_hours = (
                Decimal(record.regular_hours_target) / Decimal("2")
                if duration_code in {"90501", "90502"}
                else Decimal(record.regular_hours_target)
            )
            record.leave_request_id = request.id
            # Once an employee or administrator has explicitly replaced the
            # approved-leave default, later synchronization must preserve that
            # decision. A manual entry created before approval has no matching
            # leave link, so the newly approved VL/SL/EL still becomes default.
            if (
                previous_leave_request_id == request.id
                and record.status_source in {
                    "employee_edit",
                    "employee_status_edit",
                    "admin_correction",
                }
            ):
                self._recalculate(record)
                continue
            if not record.sessions:
                record.work_status = self._leave_code(request)
                record.status_source = "approved_leave"
            self._recalculate(record)
        self.session.commit()

    def visible_employees(
        self,
        *,
        company_id: int,
        user_id: int,
        employee_id: int | None,
        clearance: int,
    ) -> list[Employee]:
        statement = select(Employee).where(
            Employee.company_id == company_id,
            Employee.employment_status == "employed",
        )
        if clearance != 1:
            if employee_id is None:
                return []
            statement = statement.where(
                or_(
                    Employee.id == employee_id,
                    Employee.manager_id == employee_id,
                    Employee.leader_id == employee_id,
                )
            )
        statement = statement.order_by(Employee.last_name, Employee.first_name)
        return list(self.session.scalars(statement).all())

    def monthly_matrix(
        self,
        *,
        company_id: int,
        year: int,
        month: int,
        user_id: int,
        employee_id: int | None,
        clearance: int,
    ) -> AttendanceMatrix:
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        employees = self.visible_employees(
            company_id=company_id,
            user_id=user_id,
            employee_id=employee_id,
            clearance=clearance,
        )
        self.sync_approved_leaves(company_id, first, last)
        ids = [employee.id for employee in employees]
        rows = self.repository.list_range(
            company_id=company_id,
            start_date=first,
            end_date=last,
            employee_ids=ids,
        )
        dates = [first + timedelta(days=index) for index in range((last - first).days + 1)]
        scheduled_workdays = self.workday_map(
            company_id=company_id,
            start_date=first,
            end_date=last,
        )
        return AttendanceMatrix(
            employees=employees,
            dates=dates,
            records={(row.employee_id, row.attendance_date): row for row in rows},
            scheduled_workdays=scheduled_workdays,
        )

    def employee_month_summary(
        self,
        *,
        company_id: int,
        employee_id: int,
        matrix: AttendanceMatrix,
        today: date,
    ) -> EmployeeAttendanceSummary:
        """Calculate the requested employee dashboard metrics."""

        company = self._company(company_id)
        employee_records = [
            record
            for (record_employee_id, _), record in matrix.records.items()
            if record_employee_id == employee_id
        ]
        leave_count = sum(
            Decimal("0.50")
            if record.leave_duration_code in {"90501", "90502"}
            else Decimal("1.00")
            for record in employee_records
            if Decimal(record.leave_hours or Decimal("0.00")) > Decimal("0.00")
        )
        total_hours = sum(
            (Decimal(str(record.total_hours)) for record in employee_records),
            Decimal("0.00"),
        )
        total_overtime = sum(
            (Decimal(str(record.ot_hours)) for record in employee_records),
            Decimal("0.00"),
        )
        today_record = matrix.records.get((employee_id, today))
        overtime_day = (
            Decimal(str(today_record.ot_hours))
            if today_record is not None
            else Decimal("0.00")
        )
        total_working_days = sum(
            1
            for day in matrix.dates
            if matrix.scheduled_workdays.get(day, day.weekday() < 5)
        )
        # The denominator follows the complete saved monthly Regular Workdays
        # calendar. Total Hours already excludes unpaid lunch, includes OT,
        # and intentionally receives no automatic paid-leave-hour credit.
        work_rate = calculate_work_rate(
            total_hours=total_hours,
            total_workdays=total_working_days,
            regular_paid_hours_per_day=company.attendance_regular_hours,
        )
        return EmployeeAttendanceSummary(
            leave_count=leave_count,
            overtime_hours_day=overtime_day,
            total_overtime_hours=total_overtime,
            total_hours=total_hours,
            total_working_days=total_working_days,
            work_rate=work_rate,
        )

    def list_report_records(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
        employee_ids: list[int] | None = None,
    ) -> list[AttendanceRecord]:
        self.sync_approved_leaves(company_id, start_date, end_date)
        return self.repository.list_range(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
            employee_ids=employee_ids,
        )

    @staticmethod
    def _snapshot(record: AttendanceRecord) -> dict[str, object]:
        return {
            "time_in": record.time_in.isoformat() if record.time_in else None,
            "time_out": record.time_out.isoformat() if record.time_out else None,
            "work_status": record.work_status,
            "total_hours": str(record.total_hours),
            "ot_hours": str(record.ot_hours),
            "leave_duration_code": record.leave_duration_code,
            "leave_hours": str(record.leave_hours),
            "undertime_hours": str(record.undertime_hours),
            "sessions": [
                {
                    "sequence": item.sequence_number,
                    "status": item.work_status,
                    "actual_time_in": item.actual_time_in.isoformat(),
                    "actual_time_out": (
                        item.actual_time_out.isoformat() if item.actual_time_out else None
                    ),
                    "rounded_time_in": item.rounded_time_in.isoformat(),
                    "rounded_time_out": (
                        item.rounded_time_out.isoformat() if item.rounded_time_out else None
                    ),
                }
                for item in record.sessions
            ],
        }

    def correct_attendance(self, values: AttendanceCorrectionInput) -> AttendanceRecord:
        actor = self.session.scalar(
            select(User).where(
                User.id == values.corrected_by_user_id,
                User.company_id == values.company_id,
                User.clearance == 1,
            )
        )
        if actor is None:
            raise ValueError("Administrator access is required.")
        self._employee(values.company_id, values.employee_id)
        company = self._company(values.company_id)
        record = self._get_or_create(company, values.employee_id, values.attendance_date)
        before = self._snapshot(record)
        session_inputs = list(values.sessions)
        if not session_inputs and values.time_in is not None:
            session_inputs = [
                AttendanceSessionInput(
                    work_status=(
                        values.work_status
                        if values.work_status in {"WFO", "WFH"}
                        else "WFO"
                    ),
                    time_in=values.time_in,
                    time_out=values.time_out,
                )
            ]
        self._replace_sessions(
            record=record,
            inputs=session_inputs,
            source="admin_correction",
            corrected_by_user_id=values.corrected_by_user_id,
            correction_reason=values.reason,
        )
        if not session_inputs:
            record.work_status = values.work_status
            record.time_in = None
            record.time_out = None
        record.status_source = "admin_correction"
        record.corrected_by_user_id = values.corrected_by_user_id
        record.corrected_at = datetime.now(timezone.utc)
        record.correction_reason = values.reason
        self._recalculate(record)
        self.session.flush()
        self.session.add(
            AttendanceCorrection(
                company_id=values.company_id,
                attendance_record_id=record.id,
                employee_id=values.employee_id,
                corrected_by_user_id=values.corrected_by_user_id,
                reason=values.reason,
                previous_values_json=json.dumps(before, sort_keys=True),
                new_values_json=json.dumps(self._snapshot(record), sort_keys=True),
            )
        )
        self.session.commit()
        self.session.refresh(record)
        return record
