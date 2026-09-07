"""DTR-grounded employee overtime filing, approval, and reconciliation."""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import get_settings
from models.attendance_record import AttendanceRecord
from models.company import Company
from models.employee import Employee
from models.overtime_request import OvertimeRequest
from models.shifting_credit import ShiftingCredit
from models.user import User
from repositories.attendance_repository import AttendanceRepository
from repositories.overtime_repository import OvertimeRequestRepository
from schemas.overtime_schema import OvertimeRequestInput, OvertimeReviewInput
from services.leave_service import LeaveService
from services.notification_service import NotificationService


@dataclass(slots=True)
class OvertimeDTRReference:
    """Read-only DTR values used to prefill an OT request."""

    record_id: int
    date_rendered: date
    time_in: datetime | None
    time_out: datetime | None
    ot_start: datetime | None
    ot_end: datetime | None
    estimated_hours: Decimal


@dataclass(slots=True, frozen=True)
class OvertimeRuleSnapshot:
    """Detached company OT/shifting settings safe for UI calculations."""

    dinner_break_deduction_hours: Decimal
    shifting_credits_enabled: bool
    shifting_credit_block_hours: Decimal
    shifting_credit_required_blocks: int
    shifting_credit_cutoff_day: int
    additional_vl_threshold_hours: Decimal
    additional_vl_days: Decimal
    additional_vl_also_payable: bool
    excluded_positions: tuple[str, ...]
    availability_cutoffs: int
    expiration_mode: str
    expiration_month: int
    expiration_day: int


class OvertimeService:
    """Enforce ownership, DTR grounding, routing, and OT decisions."""

    ACTIVE_STATUSES = {"pending_approval", "approved"}

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = OvertimeRequestRepository(session)
        self.attendance_repository = AttendanceRepository(session)
        self.timezone = ZoneInfo(get_settings().display_timezone)

    def _company(self, company_id: int) -> Company:
        company = self.session.get(Company, company_id)
        if company is None:
            raise ValueError("The company record was not found.")
        return company

    @staticmethod
    def _normalized_position(value: str | None) -> str:
        return " ".join((value or "").strip().casefold().split())

    @classmethod
    def _position_tokens(cls, value: str | None) -> set[str]:
        """Return exact and DE1/DE2 alias tokens for exclusion matching."""

        token = cls._normalized_position(value)
        tokens = {token} if token else set()
        aliases = {
            "de1": "design engineer i",
            "design engineer 1": "design engineer i",
            "design engineer i": "de1",
            "de2": "design engineer ii",
            "design engineer 2": "design engineer ii",
            "design engineer ii": "de2",
        }
        alias = aliases.get(token)
        if alias:
            tokens.add(alias)
        return tokens

    @staticmethod
    def _excluded_positions(company: Company) -> tuple[str, ...]:
        raw = company.shifting_credit_excluded_positions_json or "[]"
        try:
            values = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        if not isinstance(values, list):
            values = []
        cleaned = []
        seen = set()
        for raw_value in values:
            value = " ".join(str(raw_value or "").strip().split())
            token = value.casefold()
            if value and token not in seen:
                seen.add(token)
                cleaned.append(value)
        return tuple(cleaned)

    def rule_snapshot(self, company_id: int) -> OvertimeRuleSnapshot:
        company = self._company(company_id)
        return OvertimeRuleSnapshot(
            dinner_break_deduction_hours=Decimal(
                company.ot_dinner_break_deduction_hours
            ),
            shifting_credits_enabled=bool(company.shifting_credits_enabled),
            shifting_credit_block_hours=Decimal(company.shifting_credit_block_hours),
            shifting_credit_required_blocks=int(company.shifting_credit_required_blocks),
            shifting_credit_cutoff_day=int(company.shifting_credit_cutoff_day),
            additional_vl_threshold_hours=Decimal(
                company.shifting_credit_additional_vl_threshold_hours
            ),
            additional_vl_days=Decimal(company.shifting_credit_additional_vl_days),
            additional_vl_also_payable=bool(
                company.shifting_credit_additional_vl_also_payable
            ),
            excluded_positions=self._excluded_positions(company),
            availability_cutoffs=int(company.shifting_credit_availability_cutoffs),
            expiration_mode=str(company.shifting_credit_expiration_mode or "follow_leave_reset"),
            expiration_month=int(company.shifting_credit_expiration_month),
            expiration_day=int(company.shifting_credit_expiration_day),
        )

    def shifting_eligibility(
        self, *, company_id: int, employee_id: int
    ) -> tuple[bool, str | None]:
        rules = self.rule_snapshot(company_id)
        employee = self._employee(company_id, employee_id)
        return self._is_shifting_eligible(employee, rules), employee.job_title

    @staticmethod
    def payable_hours_before_shifting(
        gross_hours: Decimal,
        *,
        dinner_break_flag: bool,
        dinner_break_deduction_hours: Decimal,
    ) -> Decimal:
        deduction = dinner_break_deduction_hours if dinner_break_flag else Decimal("0")
        return max(Decimal("0.00"), Decimal(gross_hours) - deduction).quantize(
            Decimal("0.01")
        )

    @classmethod
    def _is_shifting_eligible(
        cls, employee: Employee, rules: OvertimeRuleSnapshot
    ) -> bool:
        employee_tokens = cls._position_tokens(employee.job_title)
        if not employee_tokens:
            return True
        excluded_tokens: set[str] = set()
        for position in rules.excluded_positions:
            excluded_tokens.update(cls._position_tokens(position))
        return employee_tokens.isdisjoint(excluded_tokens)

    @staticmethod
    def _cutoff_range(work_date: date, cutoff_day: int) -> tuple[date, date]:
        last_day = calendar.monthrange(work_date.year, work_date.month)[1]
        split = min(max(int(cutoff_day), 1), last_day - 1)
        if work_date.day <= split:
            return date(work_date.year, work_date.month, 1), date(
                work_date.year, work_date.month, split
            )
        return date(work_date.year, work_date.month, split + 1), date(
            work_date.year, work_date.month, last_day
        )

    @staticmethod
    def _safe_annual_date(year: int, month: int, day: int) -> date:
        maximum = calendar.monthrange(year, month)[1]
        return date(year, month, min(day, maximum))

    @classmethod
    def _availability_after_cutoffs(
        cls, cutoff_end: date, *, cutoff_day: int, completed_cutoffs: int
    ) -> date:
        cursor = cutoff_end + timedelta(days=1)
        for _ in range(max(0, int(completed_cutoffs))):
            _start, end = cls._cutoff_range(cursor, cutoff_day)
            cursor = end + timedelta(days=1)
        return cursor

    def _credit_expiration_date(
        self, *, company_id: int, availability_date: date, rules: OvertimeRuleSnapshot
    ) -> date:
        if rules.expiration_mode == "custom_date":
            candidate = self._safe_annual_date(
                availability_date.year, rules.expiration_month, rules.expiration_day
            )
            if candidate < availability_date:
                candidate = self._safe_annual_date(
                    availability_date.year + 1,
                    rules.expiration_month,
                    rules.expiration_day,
                )
            return candidate

        leave_service = LeaveService(self.session)
        cycle_year = leave_service.leave_cycle_year(company_id, availability_date)
        return leave_service.leave_cycle_end(company_id, cycle_year)

    def _ensure_shifting_credit_records(self, *, company_id: int) -> None:
        """Backfill lifecycle rows for already-approved paired OT from older checkpoints."""

        rules = self.rule_snapshot(company_id)
        requests = list(
            self.session.scalars(
                select(OvertimeRequest)
                .where(
                    OvertimeRequest.company_id == company_id,
                    OvertimeRequest.status == "approved",
                    OvertimeRequest.shifting_credit_group.is_not(None),
                    OvertimeRequest.shifting_credit_hours > Decimal("0.00"),
                )
                .order_by(OvertimeRequest.date_rendered, OvertimeRequest.id)
            ).all()
        )
        grouped: dict[str, list[OvertimeRequest]] = {}
        for request in requests:
            if request.shifting_credit_group:
                grouped.setdefault(request.shifting_credit_group, []).append(request)
        if not grouped:
            return

        existing_groups = set(
            self.session.scalars(
                select(ShiftingCredit.group_key).where(
                    ShiftingCredit.company_id == company_id,
                    ShiftingCredit.group_key.in_(list(grouped)),
                )
            ).all()
        )
        for group_key, items in grouped.items():
            if group_key in existing_groups:
                continue
            first = min(items, key=lambda item: (item.date_rendered, item.id))
            cutoff_start, cutoff_end = self._cutoff_range(
                first.date_rendered, rules.shifting_credit_cutoff_day
            )
            availability_date = self._availability_after_cutoffs(
                cutoff_end,
                cutoff_day=rules.shifting_credit_cutoff_day,
                completed_cutoffs=rules.availability_cutoffs,
            )
            expiration_date = self._credit_expiration_date(
                company_id=company_id,
                availability_date=availability_date,
                rules=rules,
            )
            qualifying_hours = sum(
                (Decimal(item.shifting_credit_hours or 0) for item in items),
                start=Decimal("0.00"),
            ).quantize(Decimal("0.01"))
            self.session.add(
                ShiftingCredit(
                    company_id=company_id,
                    employee_id=first.employee_id,
                    group_key=group_key,
                    cutoff_start=cutoff_start,
                    cutoff_end=cutoff_end,
                    earned_date=max(item.date_rendered for item in items),
                    availability_date=availability_date,
                    expiration_date=expiration_date,
                    qualifying_hours=qualifying_hours,
                    ob_credit_days=Decimal("1.00"),
                    status=(
                        "available"
                        if datetime.now(self.timezone).date() >= availability_date
                        else "pending"
                    ),
                )
            )
        self.session.flush()

    def refresh_shifting_credit_statuses(
        self, *, company_id: int, as_of: date | None = None
    ) -> list[ShiftingCredit]:
        """Advance pending credits and restore unused expired credits safely."""

        selected_date = as_of or datetime.now(self.timezone).date()
        rules = self.rule_snapshot(company_id)
        self._ensure_shifting_credit_records(company_id=company_id)
        credits = list(
            self.session.scalars(
                select(ShiftingCredit)
                .where(ShiftingCredit.company_id == company_id)
                .order_by(ShiftingCredit.availability_date, ShiftingCredit.id)
            ).all()
        )
        changed = False
        for credit in credits:
            if credit.status == "pending" and selected_date >= credit.availability_date:
                credit.status = "available"
                changed = True
            if credit.status == "available" and selected_date > credit.expiration_date:
                credit.status = "expired"
                source_requests = list(
                    self.session.scalars(
                        select(OvertimeRequest).where(
                            OvertimeRequest.company_id == company_id,
                            OvertimeRequest.employee_id == credit.employee_id,
                            OvertimeRequest.shifting_credit_group == credit.group_key,
                        )
                    ).all()
                )
                restored = Decimal("0.00")
                for request in source_requests:
                    amount = Decimal(request.shifting_credit_hours or 0)
                    request.shifting_credit_restored_hours = amount
                    restored += amount
                    self._recalculate_payable(request, rules)
                credit.restored_regular_ot_hours = restored.quantize(Decimal("0.01"))
                changed = True
        if changed:
            self.session.flush()
        return credits

    def list_shifting_credits(
        self, *, company_id: int, employee_ids: list[int] | None = None, as_of: date | None = None
    ) -> list[ShiftingCredit]:
        self.refresh_shifting_credit_statuses(company_id=company_id, as_of=as_of)
        statement = select(ShiftingCredit).where(ShiftingCredit.company_id == company_id)
        if employee_ids is not None:
            if not employee_ids:
                return []
            statement = statement.where(ShiftingCredit.employee_id.in_(employee_ids))
        return list(
            self.session.scalars(
                statement.order_by(
                    ShiftingCredit.employee_id,
                    ShiftingCredit.cutoff_start,
                    ShiftingCredit.id,
                )
            ).all()
        )

    def available_shifting_credit_count(
        self, *, company_id: int, employee_id: int, as_of: date | None = None
    ) -> int:
        today = datetime.now(self.timezone).date()
        selected_date = as_of or today
        credits = self.list_shifting_credits(
            company_id=company_id, employee_ids=[employee_id], as_of=today
        )
        return sum(
            1
            for credit in credits
            if credit.status == "available"
            and credit.availability_date <= selected_date <= credit.expiration_date
        )

    def reserve_shifting_credit_for_leave(
        self,
        *,
        company_id: int,
        employee_id: int,
        usage_date: date,
        leave_request_id: int,
    ) -> ShiftingCredit:
        """Reserve one currently available whole-day OB for Leave Management."""

        today = datetime.now(self.timezone).date()
        self.refresh_shifting_credit_statuses(company_id=company_id, as_of=today)
        existing = self.session.scalar(
            select(ShiftingCredit).where(
                ShiftingCredit.company_id == company_id,
                ShiftingCredit.leave_request_id == leave_request_id,
            )
        )
        if existing is not None:
            return existing

        credit = self.session.scalar(
            select(ShiftingCredit)
            .where(
                ShiftingCredit.company_id == company_id,
                ShiftingCredit.employee_id == employee_id,
                ShiftingCredit.status == "available",
                ShiftingCredit.availability_date <= today,
                ShiftingCredit.availability_date <= usage_date,
                ShiftingCredit.expiration_date >= usage_date,
            )
            .order_by(ShiftingCredit.expiration_date, ShiftingCredit.id)
            .limit(1)
        )
        if credit is None:
            raise ValueError(
                "No available Official Business (OB) credit can cover the selected date."
            )
        credit.status = "reserved"
        credit.usage_date = usage_date
        credit.leave_request_id = leave_request_id
        credit.usage_attendance_record_id = None
        credit.restored_regular_ot_hours = Decimal("0.00")
        self.session.flush()
        return credit

    def confirm_shifting_credit_leave_usage(
        self, *, company_id: int, leave_request_id: int
    ) -> ShiftingCredit:
        """Convert one Leave Management OB reservation into a used credit."""

        credit = self.session.scalar(
            select(ShiftingCredit).where(
                ShiftingCredit.company_id == company_id,
                ShiftingCredit.leave_request_id == leave_request_id,
            )
        )
        if credit is None:
            raise ValueError("The reserved Official Business (OB) credit is unavailable.")
        if credit.status == "used":
            return credit
        if credit.status != "reserved":
            raise ValueError("The Official Business (OB) credit is no longer reserved.")
        credit.status = "used"
        credit.restored_regular_ot_hours = Decimal("0.00")
        self.session.flush()
        return credit

    def release_shifting_credit_leave_reservation(
        self, *, company_id: int, leave_request_id: int
    ) -> ShiftingCredit | None:
        """Release a rejected/cancelled OB request without duplicating the credit."""

        credit = self.session.scalar(
            select(ShiftingCredit).where(
                ShiftingCredit.company_id == company_id,
                ShiftingCredit.leave_request_id == leave_request_id,
            )
        )
        if credit is None:
            return None
        credit.leave_request_id = None
        credit.usage_date = None
        credit.usage_attendance_record_id = None
        today = datetime.now(self.timezone).date()
        credit.status = "pending" if today < credit.availability_date else "available"
        self.session.flush()
        self.refresh_shifting_credit_statuses(company_id=company_id, as_of=today)
        return credit

    def use_shifting_credit(
        self,
        *,
        company_id: int,
        employee_id: int,
        usage_date: date,
        attendance_record_id: int | None = None,
    ) -> ShiftingCredit:
        """Consume one available whole-day OB credit for an attendance date."""

        today = datetime.now(self.timezone).date()
        self.refresh_shifting_credit_statuses(company_id=company_id, as_of=today)
        existing = self.session.scalar(
            select(ShiftingCredit).where(
                ShiftingCredit.company_id == company_id,
                ShiftingCredit.employee_id == employee_id,
                ShiftingCredit.status == "used",
                ShiftingCredit.usage_date == usage_date,
                ShiftingCredit.leave_request_id.is_(None),
            )
        )
        if existing is not None:
            if attendance_record_id is not None:
                existing.usage_attendance_record_id = attendance_record_id
            return existing

        credit = self.session.scalar(
            select(ShiftingCredit)
            .where(
                ShiftingCredit.company_id == company_id,
                ShiftingCredit.employee_id == employee_id,
                ShiftingCredit.status == "available",
                ShiftingCredit.leave_request_id.is_(None),
                ShiftingCredit.availability_date <= usage_date,
                ShiftingCredit.expiration_date >= usage_date,
            )
            .order_by(ShiftingCredit.expiration_date, ShiftingCredit.id)
            .limit(1)
        )
        if credit is None:
            raise ValueError(
                "No available Shifting/OB credit can be used for the selected date."
            )
        credit.status = "used"
        credit.usage_date = usage_date
        credit.usage_attendance_record_id = attendance_record_id
        credit.restored_regular_ot_hours = Decimal("0.00")
        self.session.flush()
        return credit

    def release_shifting_credit_usage(
        self, *, company_id: int, employee_id: int, usage_date: date
    ) -> ShiftingCredit | None:
        """Release a credit when an OB attendance status is changed back."""

        credit = self.session.scalar(
            select(ShiftingCredit).where(
                ShiftingCredit.company_id == company_id,
                ShiftingCredit.employee_id == employee_id,
                ShiftingCredit.status == "used",
                ShiftingCredit.usage_date == usage_date,
                ShiftingCredit.leave_request_id.is_(None),
            )
        )
        if credit is None:
            return None
        credit.usage_date = None
        credit.usage_attendance_record_id = None
        today = datetime.now(self.timezone).date()
        credit.status = "pending" if today < credit.availability_date else "available"
        self.session.flush()
        self.refresh_shifting_credit_statuses(company_id=company_id, as_of=today)
        return credit

    def _recalculate_payable(
        self, request: OvertimeRequest, rules: OvertimeRuleSnapshot
    ) -> None:
        dinner_deduction = (
            rules.dinner_break_deduction_hours
            if request.dinner_break_flag
            else Decimal("0")
        )
        request.payable_hours = max(
            Decimal("0.00"),
            Decimal(request.estimated_hours)
            - dinner_deduction
            - Decimal(request.shifting_credit_hours or 0)
            + Decimal(request.shifting_credit_restored_hours or 0),
        ).quantize(Decimal("0.01"))

    def _apply_shifting_credit_rules(
        self, request: OvertimeRequest, *, reviewed_by_user_id: int
    ) -> None:
        """Apply dinner deduction, 4-hour pairing, and automatic VL credit."""

        company = self._company(request.company_id)
        rules = self.rule_snapshot(request.company_id)
        employee = self._employee(request.company_id, request.employee_id)

        request.shifting_credit_hours = Decimal("0.00")
        request.shifting_credit_restored_hours = Decimal("0.00")
        request.shifting_credit_group = None
        request.additional_vl_days = Decimal("0.00")
        request.straight_vl_also_payable = False
        self._recalculate_payable(request, rules)

        if not rules.shifting_credits_enabled or not self._is_shifting_eligible(
            employee, rules
        ):
            return

        gross_hours = Decimal(request.estimated_hours)
        if gross_hours >= rules.additional_vl_threshold_hours:
            if rules.additional_vl_days > 0:
                LeaveService(self.session).grant_overtime_additional_vl(
                    company_id=request.company_id,
                    employee_id=request.employee_id,
                    overtime_public_id=request.public_id,
                    overtime_date=request.date_rendered,
                    days=rules.additional_vl_days,
                    created_by_user_id=reviewed_by_user_id,
                )
                request.additional_vl_days = rules.additional_vl_days
                request.straight_vl_also_payable = rules.additional_vl_also_payable
                if not rules.additional_vl_also_payable:
                    request.payable_hours = max(
                        Decimal("0.00"),
                        Decimal(request.payable_hours)
                        - rules.additional_vl_threshold_hours,
                    ).quantize(Decimal("0.01"))
            return

        if gross_hours < rules.shifting_credit_block_hours:
            return

        cutoff_start, cutoff_end = self._cutoff_range(
            request.date_rendered, rules.shifting_credit_cutoff_day
        )
        needed_previous = rules.shifting_credit_required_blocks - 1
        previous = list(
            self.session.scalars(
                select(OvertimeRequest)
                .where(
                    OvertimeRequest.company_id == request.company_id,
                    OvertimeRequest.employee_id == request.employee_id,
                    OvertimeRequest.id != request.id,
                    OvertimeRequest.status == "approved",
                    OvertimeRequest.date_rendered >= cutoff_start,
                    OvertimeRequest.date_rendered <= cutoff_end,
                    OvertimeRequest.estimated_hours >= rules.shifting_credit_block_hours,
                    OvertimeRequest.estimated_hours < rules.additional_vl_threshold_hours,
                    OvertimeRequest.shifting_credit_hours == Decimal("0.00"),
                )
                .order_by(
                    OvertimeRequest.date_rendered.asc(), OvertimeRequest.id.asc()
                )
                .limit(needed_previous)
            ).all()
        )
        if len(previous) < needed_previous:
            return

        group_key = (
            f"SC_{request.company_id}_{request.employee_id}_"
            f"{cutoff_start:%Y%m%d}_{cutoff_end:%Y%m%d}_{request.id}"
        )
        paired_requests = [*previous, request]
        for item in paired_requests:
            item.shifting_credit_hours = rules.shifting_credit_block_hours
            item.shifting_credit_restored_hours = Decimal("0.00")
            item.shifting_credit_group = group_key
            self._recalculate_payable(item, rules)

        qualifying_hours = (
            rules.shifting_credit_block_hours * rules.shifting_credit_required_blocks
        ).quantize(Decimal("0.01"))
        availability_date = self._availability_after_cutoffs(
            cutoff_end,
            cutoff_day=rules.shifting_credit_cutoff_day,
            completed_cutoffs=rules.availability_cutoffs,
        )
        expiration_date = self._credit_expiration_date(
            company_id=request.company_id,
            availability_date=availability_date,
            rules=rules,
        )
        if expiration_date < availability_date:
            raise ValueError(
                "Shifting Credit expiration cannot be earlier than its availability date."
            )
        credit = self.session.scalar(
            select(ShiftingCredit).where(
                ShiftingCredit.company_id == request.company_id,
                ShiftingCredit.group_key == group_key,
            )
        )
        if credit is None:
            credit = ShiftingCredit(
                company_id=request.company_id,
                employee_id=request.employee_id,
                group_key=group_key,
                cutoff_start=cutoff_start,
                cutoff_end=cutoff_end,
                earned_date=max(item.date_rendered for item in paired_requests),
                availability_date=availability_date,
                expiration_date=expiration_date,
                qualifying_hours=qualifying_hours,
                ob_credit_days=Decimal("1.00"),
                status=(
                    "available"
                    if datetime.now(self.timezone).date() >= availability_date
                    else "pending"
                ),
            )
            self.session.add(credit)
            self.session.flush()

    def _employee(self, company_id: int, employee_id: int) -> Employee:
        employee = self.session.scalar(
            select(Employee).where(
                Employee.company_id == company_id,
                Employee.id == employee_id,
            )
        )
        if employee is None:
            raise ValueError("The employee record was not found.")
        return employee

    def _require_owner(self, *, company_id: int, employee_id: int, user_id: int) -> Employee:
        employee = self._employee(company_id, employee_id)
        if employee.user_id != user_id:
            raise ValueError("You can file overtime only for your own employee account.")
        return employee

    def _to_local(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(self.timezone)

    def _to_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=self.timezone)
        return value.astimezone(timezone.utc)

    def dtr_reference(
        self, *, company_id: int, employee_id: int, date_rendered: date
    ) -> OvertimeDTRReference | None:
        record = self.attendance_repository.get_daily(
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=date_rendered,
        )
        if record is None:
            return None
        local_in = self._to_local(record.time_in)
        local_out = self._to_local(record.time_out)
        hours = Decimal(record.ot_hours or 0).quantize(Decimal("0.01"))
        rounded_session_ends: list[datetime] = []
        for item in list(getattr(record, "sessions", ()) or ()):
            if item.rounded_time_out is None:
                continue
            local_end = self._to_local(item.rounded_time_out)
            if local_end is not None:
                rounded_session_ends.append(local_end)
        payroll_out = max(rounded_session_ends) if rounded_session_ends else local_out
        ot_end = payroll_out if hours > 0 else None
        ot_start = (
            payroll_out - timedelta(hours=float(hours))
            if payroll_out is not None and hours > 0
            else None
        )
        return OvertimeDTRReference(
            record_id=record.id,
            date_rendered=date_rendered,
            time_in=local_in,
            time_out=local_out,
            ot_start=ot_start,
            ot_end=ot_end,
            estimated_hours=hours,
        )

    def list_own(self, *, company_id: int, employee_id: int) -> list[OvertimeRequest]:
        return self.repository.list_employee(
            company_id=company_id, employee_id=employee_id
        )

    def list_pending(
        self, *, company_id: int, reviewer_employee_id: int | None, clearance: int
    ) -> list[OvertimeRequest]:
        return self.repository.list_pending_for_approver(
            company_id=company_id,
            employee_id=reviewer_employee_id,
            include_all=clearance == 1,
        )

    def list_company_range(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
        employee_ids: list[int] | None = None,
    ) -> list[OvertimeRequest]:
        return self.repository.list_company_range(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
            employee_ids=employee_ids,
        )

    def _next_public_id(self) -> str:
        next_id = int(self.session.scalar(select(func.max(OvertimeRequest.id))) or 0) + 1
        return f"OTR_{next_id:06d}"

    def submit(self, values: OvertimeRequestInput) -> OvertimeRequest:
        employee = self._require_owner(
            company_id=values.company_id,
            employee_id=values.employee_id,
            user_id=values.requested_by_user_id,
        )
        reference = self.dtr_reference(
            company_id=values.company_id,
            employee_id=values.employee_id,
            date_rendered=values.date_rendered,
        )
        if reference is None:
            raise ValueError("No DTR record is available for the selected date.")
        if reference.time_out is None:
            raise ValueError("Complete the DTR Time Out before filing overtime.")
        if reference.estimated_hours <= 0:
            raise ValueError("The selected DTR date has no detected overtime.")

        start_utc = self._to_utc(values.ot_time_start)
        end_utc = self._to_utc(values.ot_time_end)
        if values.ot_time_start.date() != values.date_rendered:
            raise ValueError("OT Start Time must begin on the selected Date Rendered.")

        overlapping = self.session.scalar(
            select(OvertimeRequest.id).where(
                OvertimeRequest.company_id == values.company_id,
                OvertimeRequest.employee_id == values.employee_id,
                OvertimeRequest.status.in_(self.ACTIVE_STATUSES),
                OvertimeRequest.ot_time_start < end_utc,
                OvertimeRequest.ot_time_end > start_utc,
            ).limit(1)
        )
        if overlapping is not None:
            raise ValueError("This OT time overlaps an existing active overtime request.")

        detected_start_utc = self._to_utc(reference.ot_start) if reference.ot_start else None
        detected_end_utc = self._to_utc(reference.ot_end) if reference.ot_end else None
        tolerance = Decimal("0.01")
        has_mismatch = (
            detected_start_utc != start_utc
            or detected_end_utc != end_utc
            or abs(Decimal(values.estimated_hours) - reference.estimated_hours) > tolerance
        )
        approver_id = employee.leader_id or employee.manager_id
        rules = self.rule_snapshot(values.company_id)
        payable_hours = self.payable_hours_before_shifting(
            Decimal(values.estimated_hours),
            dinner_break_flag=values.dinner_break_flag,
            dinner_break_deduction_hours=rules.dinner_break_deduction_hours,
        )
        request = OvertimeRequest(
            public_id=self._next_public_id(),
            company_id=values.company_id,
            employee_id=values.employee_id,
            attendance_record_id=reference.record_id,
            filed_by_user_id=values.requested_by_user_id,
            current_approver_employee_id=approver_id,
            date_rendered=values.date_rendered,
            dtr_time_in=self._to_utc(reference.time_in) if reference.time_in else None,
            dtr_time_out=self._to_utc(reference.time_out) if reference.time_out else None,
            dtr_ot_start=detected_start_utc,
            dtr_ot_end=detected_end_utc,
            dtr_estimated_hours=reference.estimated_hours,
            ot_time_start=start_utc,
            ot_time_end=end_utc,
            estimated_hours=values.estimated_hours,
            payable_hours=payable_hours,
            shifting_credit_hours=Decimal("0.00"),
            additional_vl_days=Decimal("0.00"),
            ot_type=values.ot_type,
            ot_purpose=values.ot_purpose,
            travel_fare=values.travel_fare,
            travel_route=values.travel_route,
            dinner_break_flag=values.dinner_break_flag,
            has_dtr_mismatch=has_mismatch,
            status="pending_approval",
        )
        self.session.add(request)
        self.session.flush()

        if approver_id is not None:
            approver = self._employee(values.company_id, approver_id)
            if approver.user_id is not None:
                NotificationService(self.session).create(
                    company_id=values.company_id,
                    user_id=approver.user_id,
                    event_type="overtime_request_filed",
                    title="Overtime · Request filed",
                    message=(
                        f"{employee.full_name} filed {values.estimated_hours} hour(s) "
                        f"of OT for {values.date_rendered:%b %d, %Y}."
                    ),
                    related_entity_type="overtime_request",
                    related_entity_id=request.id,
                )
        self.session.commit()
        self.session.refresh(request)
        return request

    def cancel_own(
        self, *, company_id: int, request_id: int, employee_id: int, user_id: int
    ) -> OvertimeRequest:
        self._require_owner(
            company_id=company_id, employee_id=employee_id, user_id=user_id
        )
        request = self.repository.get_by_id(request_id, company_id)
        if request is None or request.employee_id != employee_id:
            raise ValueError("The overtime request was not found.")
        if request.status != "pending_approval":
            raise ValueError("Only a pending overtime request may be cancelled.")
        request.status = "cancelled"
        self.session.commit()
        self.session.refresh(request)
        return request

    def review(self, values: OvertimeReviewInput) -> OvertimeRequest:
        request = self.repository.get_by_id(
            values.overtime_request_id, values.company_id
        )
        if request is None:
            raise ValueError("The overtime request was not found.")
        if request.status != "pending_approval":
            raise ValueError("This overtime request is no longer pending.")
        is_admin = values.clearance == 1
        is_assigned = (
            values.reviewer_employee_id is not None
            and request.current_approver_employee_id == values.reviewer_employee_id
        )
        if not (is_admin or is_assigned):
            raise ValueError("You are not the assigned overtime approver.")

        request.status = values.decision
        request.reviewer_comment = values.comment
        request.reviewed_by_user_id = values.reviewed_by_user_id
        request.reviewed_at = datetime.now(timezone.utc)
        if values.decision == "approved":
            self._apply_shifting_credit_rules(
                request, reviewed_by_user_id=values.reviewed_by_user_id
            )
        owner = self._employee(values.company_id, request.employee_id)
        if owner.user_id is not None:
            NotificationService(self.session).create(
                company_id=values.company_id,
                user_id=owner.user_id,
                event_type=f"overtime_request_{values.decision}",
                title=f"Overtime · Request {values.decision}",
                message=(
                    f"{request.public_id} for {request.date_rendered:%b %d, %Y} "
                    f"was {values.decision}."
                    + (
                        f" Payable OT: {Decimal(request.payable_hours):.2f} hour(s)."
                        if values.decision == "approved"
                        else ""
                    )
                ),
                related_entity_type="overtime_request",
                related_entity_id=request.id,
            )
        self.session.commit()
        self.session.refresh(request)
        return request
