"""Leave credits, requests, manager email delivery, and HR monitoring."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import calendar
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from core.leave_codes import (
    LEAVE_DURATION_OPTIONS,
    LEAVE_REASON_OPTIONS,
    duration_label,
    reason_label,
)
from integrations.email.email_sender import (
    EmailAttachment,
    EmailDeliveryError,
    EmailSender,
    OutboundEmail,
    build_email_sender,
)
from models.employee import Employee
from models.company import Company
from models.leave_balance import LeaveBalance
from models.leave_credit_transaction import LeaveCreditTransaction
from models.leave_request import LeaveRequest
from models.leave_type import LeaveType
from models.user import User
from modules.leave.leave_file_storage import LeaveFileStorage
from repositories.employee_repository import EmployeeRepository
from repositories.company_workday_repository import CompanyWorkdayRepository
from repositories.leave_repository import (
    LeaveBalanceRepository,
    LeaveCreditTransactionRepository,
    LeaveRequestRepository,
    LeaveTypeRepository,
)
from repositories.user_repository import UserRepository
from schemas.leave_schema import (
    LeaveCreditAdjustmentInput,
    LeaveCreditBalanceSetInput,
    LeaveCancellationDecisionInput,
    LeaveCancellationRequestInput,
    LeaveDecisionInput,
    LeaveRequestInput,
    LeaveTypeInput,
    CompanyLeavePolicyInput,
)
from services.notification_service import NotificationService


DEFAULT_LEAVE_TYPES = (
    {
        # Vacation and Sick Leave follow the completed-tenure bracket on
        # January 1: 15 / 17 / 20 / 23 / 26 days.
        "code": "VACATION",
        "name": "Vacation Leave",
        "annual_credits": Decimal("15.00"),
        "is_paid": True,
        "carry_over_limit": Decimal("0.00"),
        "requires_attachment": False,
        "minimum_notice_days": 5,
        "handover_plan_requirement": "recommended",
    },
    {
        "code": "SICK",
        "name": "Sick Leave",
        "annual_credits": Decimal("15.00"),
        "is_paid": True,
        "carry_over_limit": Decimal("0.00"),
        "requires_attachment": False,
        "minimum_notice_days": 0,
        "handover_plan_requirement": "optional",
    },
    {
        # Emergency Leave is included in the Vacation Leave entitlement.
        # Phase 2 therefore gives it no separate annual credit. Its protected
        # three-day usage allowance is enforced in the later EL phase.
        "code": "EMERGENCY",
        "name": "Emergency Leave",
        "annual_credits": Decimal("0.00"),
        "is_paid": True,
        "carry_over_limit": Decimal("0.00"),
        "requires_attachment": False,
        "minimum_notice_days": 0,
        "handover_plan_requirement": "optional",
    },
    {
        # Phase 5 grants five days once, after manager approval of the
        # employee's single qualifying Honeymoon Leave request.
        "code": "HONEYMOON",
        "name": "Honeymoon Leave",
        "annual_credits": Decimal("0.00"),
        "is_paid": True,
        "carry_over_limit": Decimal("0.00"),
        "requires_attachment": False,
        "minimum_notice_days": 0,
        "handover_plan_requirement": "recommended",
    },
    {
        # Phase 5 grants 105 days for each manager-approved qualifying event.
        "code": "MATERNITY",
        "name": "Maternity Leave",
        "annual_credits": Decimal("0.00"),
        "is_paid": True,
        "carry_over_limit": Decimal("0.00"),
        "requires_attachment": False,
        "minimum_notice_days": 0,
        "handover_plan_requirement": "recommended",
    },
    {
        # Phase 5 grants seven days for each manager-approved qualifying event.
        "code": "PATERNITY",
        "name": "Paternity Leave",
        "annual_credits": Decimal("0.00"),
        "is_paid": True,
        "carry_over_limit": Decimal("0.00"),
        "requires_attachment": False,
        "minimum_notice_days": 0,
        "handover_plan_requirement": "recommended",
    },
    {
        # Phase 5 grants seven days for each manager-approved qualifying event.
        "code": "BEREAVEMENT",
        "name": "Bereavement Leave",
        "annual_credits": Decimal("0.00"),
        "is_paid": True,
        "carry_over_limit": Decimal("0.00"),
        "requires_attachment": False,
        "minimum_notice_days": 0,
        "handover_plan_requirement": "recommended",
    },
    {
        # LWOP remains an internal fallback and is intentionally excluded
        # from the seven-row employee leave-credit table.
        "code": "LWOP",
        "name": "Leave Without Pay",
        "annual_credits": Decimal("0.00"),
        "is_paid": False,
        "carry_over_limit": Decimal("0.00"),
        "requires_attachment": False,
        "minimum_notice_days": 0,
        "handover_plan_requirement": "recommended",
    },
)

LEAVE_CREDIT_TABLE_CODES = (
    "VACATION",
    "EMERGENCY",
    "SICK",
    "HONEYMOON",
    "MATERNITY",
    "PATERNITY",
    "BEREAVEMENT",
)
LEAVE_CREDIT_TABLE_ORDER = {
    code: index
    for index, code in enumerate(LEAVE_CREDIT_TABLE_CODES)
}

ANNUAL_ACCRUAL_CODES = {"VACATION", "SICK"}
ANNUAL_TENURE_CREDIT_BRACKETS = (
    (21, Decimal("26.00")),
    (16, Decimal("23.00")),
    (11, Decimal("20.00")),
    (6, Decimal("17.00")),
    (0, Decimal("15.00")),
)

# Emergency Leave is a protected annual usage allowance inside Vacation
# Leave. It never creates additional credits; approved EL days consume VL.
EMERGENCY_USAGE_LIMIT = Decimal("3.00")
EMERGENCY_ACTIVE_STATUSES = {
    "scheduled",
    "approved",
    "in_progress",
    "completed",
    "partially_cancelled",
}

# Event-based leave is granted only when a manager approves the related
# request. Each approved request represents one qualifying event. Honeymoon
# Leave is the only lifetime one-time benefit; the other event leave types may
# receive another fixed grant for a later approved qualifying event.
EVENT_LEAVE_ENTITLEMENTS = {
    "HONEYMOON": Decimal("5.00"),
    "MATERNITY": Decimal("105.00"),
    "PATERNITY": Decimal("7.00"),
    "BEREAVEMENT": Decimal("7.00"),
}
EVENT_LEAVE_CODES = set(EVENT_LEAVE_ENTITLEMENTS)
EVENT_LEAVE_GRANT_TRANSACTION = "event_leave_entitlement_grant"

# Maternity and Paternity eligibility follows the employee gender recorded
# in the employee master file. The service layer remains the source of truth
# so direct calls and old pending requests cannot bypass the UI filter.
EVENT_LEAVE_GENDER_REQUIREMENTS = {
    "MATERNITY": "FEMALE",
    "PATERNITY": "MALE",
}

EVENT_LEAVE_NON_REJECTED_STATUSES = {
    "pending_manager_approval",
    "scheduled",
    "approved",
    "in_progress",
    "completed",
    "partially_cancelled",
}

# Fixed balances that may remain usable after the January annual credit.
# Any opening ledger amount above these limits is transferred to the
# Converted to Cash column and is no longer part of available credits.
CASH_CONVERSION_LIMITS = {
    "SICK": Decimal("15.00"),
    "VACATION": Decimal("45.00"),
}
CASH_CONVERSION_TRANSACTION = "january_cash_conversion"
CASH_CONVERSION_LIMIT_ENFORCEMENT_TRANSACTION = (
    "cash_conversion_limit_enforcement"
)

# Vacation Leave utilization is a monitoring target during the year. It does
# not reserve or deduct credits in advance. Only the unmet target is forfeited
# after year end, before the remaining VL is carried into the next ledger.
# The utilization ledger is treated as active from January 1, 2026 so
# existing annual VL usage and the utilization Used value stay aligned.
LEAVE_UTILIZATION_POLICY_START = date(2026, 1, 1)
LEAVE_UTILIZATION_2026_TARGETS = {
    Decimal("15.00"): Decimal("7.50"),
    Decimal("17.00"): Decimal("8.50"),
    Decimal("20.00"): Decimal("10.00"),
    Decimal("23.00"): Decimal("11.50"),
    Decimal("26.00"): Decimal("13.00"),
}
LEAVE_UTILIZATION_YEAR_END_TRANSACTION = "leave_utilization_year_end"
LEAVE_UTILIZATION_REMINDER_DATES = (
    (10, 1, "leave_utilization_reminder_october", "Leave utilization reminder"),
    (11, 1, "leave_utilization_reminder_november", "Leave utilization follow-up"),
    (12, 1, "leave_utilization_reminder_december", "Leave utilization urgent reminder"),
    (12, 15, "leave_utilization_reminder_final", "Final leave utilization reminder"),
)

# Only exact legacy defaults are upgraded automatically. Company-specific
# values that HR already customized remain untouched.
LEGACY_DEFAULT_UPGRADES = {
    "VACATION": {
        "annual_credits": ({Decimal("42.00")}, Decimal("15.00")),
        "carry_over_limit": ({Decimal("5.00")}, Decimal("0.00")),
    },
    "SICK": {
        "annual_credits": ({Decimal("10.00")}, Decimal("15.00")),
    },
    "EMERGENCY": {
        "annual_credits": ({Decimal("3.00")}, Decimal("0.00")),
    },
}



@dataclass(frozen=True, slots=True)
class LeaveCreditBalanceSetResult:
    """Outcome after setting and enforcing one leave-credit value."""

    balance: LeaveBalance
    previous_remaining: Decimal
    requested_remaining: Decimal
    new_remaining: Decimal
    converted_to_cash: Decimal


@dataclass(frozen=True, slots=True)
class LeaveSubmissionResult:
    """Outcome returned after recording and emailing a request."""

    request: LeaveRequest
    email_sent: bool
    message: str


@dataclass(frozen=True, slots=True)
class LeaveAllocationPlan:
    """Paid-credit and automatic LWOP split for one leave request."""

    primary_balance: LeaveBalance | None
    primary_days: Decimal
    fallback_balance: LeaveBalance | None
    fallback_days: Decimal
    lwop_days: Decimal

    @property
    def paid_days(self) -> Decimal:
        return self.primary_days + self.fallback_days


@dataclass(frozen=True, slots=True)
class EmergencyAllowanceSummary:
    """Annual EL usage tracked separately while credits remain in VL."""

    used_days: Decimal
    reserved_days: Decimal
    remaining_days: Decimal
    last_updated: datetime | None = None


@dataclass(frozen=True, slots=True)
class LeaveUtilizationSummary:
    """Derived Vacation Leave utilization for one annual ledger."""

    required_days: Decimal
    used_days: Decimal
    remaining_days: Decimal
    forfeited_days: Decimal = Decimal("0.00")
    is_enabled: bool = True

    @property
    def display_text(self) -> str:
        if not self.is_enabled:
            return "Disabled"
        remaining = LeaveService._display_days(self.remaining_days)
        if self.forfeited_days > 0:
            remaining = f"{remaining} — Forfeited"
        return (
            f"• Required: {LeaveService._display_days(self.required_days)}\n"
            f"• Used: {LeaveService._display_days(self.used_days)}\n"
            f"• Remaining: {remaining}"
        )


@dataclass(frozen=True, slots=True)
class LeaveCreditTableRow:
    """Employee-facing leave ledger row with eligibility display metadata."""

    leave_type: LeaveType
    beginning_credit_days: Decimal
    credit_days: Decimal
    adjustment_days: Decimal
    used_days: Decimal
    reserved_days: Decimal
    available_credits: Decimal
    converted_to_cash_days: Decimal
    updated_at: datetime | None
    is_applicable: bool = True
    leave_utilization: LeaveUtilizationSummary | None = None


class LeaveService:
    """Coordinate all leave-management business rules."""

    def __init__(self, session: Session, *, settings: Settings | None = None, email_sender: EmailSender | None = None, storage: LeaveFileStorage | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.email_sender = email_sender or build_email_sender(self.settings)
        self.storage = storage or LeaveFileStorage(self.settings.leave_attachment_dir)
        self.leave_type_repository = LeaveTypeRepository(session)
        self.balance_repository = LeaveBalanceRepository(session)
        self.request_repository = LeaveRequestRepository(session)
        self.transaction_repository = LeaveCreditTransactionRepository(session)
        self.employee_repository = EmployeeRepository(session)
        self.user_repository = UserRepository(session)
        self.notification_service = NotificationService(session)
        self.workday_repository = CompanyWorkdayRepository(session)

    def _today(self) -> date:
        return datetime.now(ZoneInfo(self.settings.display_timezone)).date()

    def _company(self, company_id: int) -> Company:
        company = self.session.get(Company, company_id)
        if company is None:
            raise ValueError("The company record is unavailable.")
        return company

    @staticmethod
    def _safe_annual_date(year: int, month: int, day: int) -> date:
        """Build an annual policy date, clamping February 29 when needed."""

        maximum = calendar.monthrange(year, month)[1]
        return date(year, month, min(day, maximum))

    def leave_cycle_start(self, company_id: int, cycle_year: int) -> date:
        company = self._company(company_id)
        return self._safe_annual_date(
            cycle_year,
            int(company.leave_reset_month),
            int(company.leave_reset_day),
        )

    def leave_cycle_end(self, company_id: int, cycle_year: int) -> date:
        return self.leave_cycle_start(company_id, cycle_year + 1) - timedelta(days=1)

    def leave_cycle_year(self, company_id: int, target_date: date | None = None) -> int:
        selected = target_date or self._today()
        start = self.leave_cycle_start(company_id, selected.year)
        return selected.year if selected >= start else selected.year - 1

    def save_company_leave_policy(
        self,
        values: CompanyLeavePolicyInput,
    ) -> Company:
        """Persist validated leave-cycle and utilization settings."""

        company = self._company(values.company_id)
        company.leave_reset_month = values.reset_month
        company.leave_reset_day = values.reset_day
        company.leave_utilization_enabled = values.utilization_enabled
        company.leave_utilization_percentage = values.utilization_percentage
        company.manager_vl_retention_limit = values.manager_vl_retention_limit
        self.session.commit()
        self.session.refresh(company)
        return company

    def _employee_is_manager(self, employee: Employee) -> bool:
        """Identify a manager through organization assignment or job title."""

        has_direct_reports = self.session.scalar(
            select(func.count(Employee.id)).where(
                Employee.company_id == employee.company_id,
                Employee.manager_id == employee.id,
                Employee.employment_status == "employed",
            )
        )
        title = " ".join((employee.job_title or "").strip().casefold().split())
        return bool(has_direct_reports) or "manager" in title

    @staticmethod
    def _business_days(start_date: date, end_date: date) -> Decimal:
        days = Decimal("0.00")
        current = start_date
        from datetime import timedelta
        while current <= end_date:
            if current.weekday() < 5:
                days += Decimal("1.00")
            current += timedelta(days=1)
        return days

    @classmethod
    def calculate_working_days(
        cls,
        start_date: date,
        end_date: date,
    ) -> Decimal:
        """Return Monday-to-Friday days for live form preview."""

        if end_date < start_date:
            return Decimal("0.00")

        return cls._business_days(start_date, end_date)

    def company_working_days(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
    ) -> Decimal:
        """Count dates selected as Regular Workdays for this company."""

        if end_date < start_date:
            return Decimal("0.00")
        saved = {
            row.work_date: bool(row.is_workday)
            for row in self.workday_repository.list_range(
                company_id=company_id,
                start_date=start_date,
                end_date=end_date,
            )
        }
        count = Decimal("0.00")
        current = start_date
        while current <= end_date:
            if saved.get(current, current.weekday() < 5):
                count += Decimal("1.00")
            current += timedelta(days=1)
        return count

    @staticmethod
    def _email_for_employee(employee: Employee | None) -> str | None:
        if employee is None:
            return None
        if employee.work_email and employee.work_email.strip():
            return employee.work_email.strip()
        if employee.user and employee.user.email:
            return employee.user.email.strip()
        return None

    @staticmethod
    def completed_service_years(
        hire_date: date | None,
        as_of: date,
    ) -> int:
        """Return completed service years without counting partial years."""

        if hire_date is None or as_of < hire_date:
            return 0

        years = as_of.year - hire_date.year
        if (as_of.month, as_of.day) < (
            hire_date.month,
            hire_date.day,
        ):
            years -= 1
        return max(0, years)

    @staticmethod
    def _round_to_half_day(value: Decimal) -> Decimal:
        """Round a prorated entitlement to the nearest half day."""

        return (
            (value * Decimal("2"))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            / Decimal("2")
        ).quantize(Decimal("0.00"))

    @staticmethod
    def _display_days(value: Decimal) -> str:
        """Format a day value without unnecessary trailing zeroes."""

        normalized = Decimal(value).quantize(Decimal("0.01"))
        return format(normalized, "f").rstrip("0").rstrip(".") or "0"

    def _leave_utilization_required_days(
        self,
        *,
        balance: LeaveBalance,
    ) -> Decimal:
        """Return the approved VL target for the selected leave year."""

        company = self._company(balance.company_id)
        if not company.leave_utilization_enabled:
            return Decimal("0.00")

        annual_credit = Decimal(balance.credit_days).quantize(
            Decimal("0.01")
        )
        employee = self.employee_repository.get_with_details(
            company_id=balance.company_id,
            employee_id=balance.employee_id,
        )
        if employee is not None and self._employee_is_manager(employee):
            return max(
                Decimal("0.00"),
                annual_credit - Decimal(company.manager_vl_retention_limit),
            ).quantize(Decimal("0.00"))

        return self._round_to_half_day(
            annual_credit
            * Decimal(company.leave_utilization_percentage)
            / Decimal("100")
        )

    def _leave_utilization_used_days(
        self,
        *,
        balance: LeaveBalance,
        as_of: date,
    ) -> Decimal:
        """Count annual paid VL usage while excluding Emergency Leave.

        ``LeaveBalance.used_days`` is the official posted annual ledger and
        also covers safe legacy/sample data that predates request-level audit
        rows. Emergency Leave is paid from the VL balance but is not Vacation
        Leave utilization, so its posted usage is removed explicitly.
        """

        period_start = self.leave_cycle_start(balance.company_id, balance.year)
        period_end = self.leave_cycle_end(balance.company_id, balance.year)
        effective_end = min(as_of, period_end)
        if effective_end < period_start:
            return Decimal("0.00")

        emergency_used = self.emergency_allowance_summary(
            company_id=balance.company_id,
            employee_id=balance.employee_id,
            year=balance.year,
        ).used_days
        return max(
            Decimal("0.00"),
            Decimal(balance.used_days) - Decimal(emergency_used),
        ).quantize(Decimal("0.01"))

    def _leave_utilization_year_end_transaction(
        self,
        balance: LeaveBalance,
    ) -> LeaveCreditTransaction | None:
        return self.session.scalar(
            select(LeaveCreditTransaction)
            .where(
                LeaveCreditTransaction.leave_balance_id == balance.id,
                LeaveCreditTransaction.transaction_type
                == LEAVE_UTILIZATION_YEAR_END_TRANSACTION,
            )
            .order_by(LeaveCreditTransaction.id.desc())
        )

    def leave_utilization_summary(
        self,
        *,
        balance: LeaveBalance,
        as_of: date | None = None,
    ) -> LeaveUtilizationSummary | None:
        """Return VL-only utilization without mutating available credits."""

        code = (balance.leave_type.code or "").strip().upper()
        if code != "VACATION":
            return None

        company = self._company(balance.company_id)
        if not company.leave_utilization_enabled:
            return LeaveUtilizationSummary(
                required_days=Decimal("0.00"),
                used_days=Decimal("0.00"),
                remaining_days=Decimal("0.00"),
                is_enabled=False,
            )

        required = self._leave_utilization_required_days(balance=balance)
        used = self._leave_utilization_used_days(
            balance=balance,
            as_of=as_of or self._today(),
        )
        remaining = max(
            Decimal("0.00"),
            required - used,
        ).quantize(Decimal("0.01"))
        marker = self._leave_utilization_year_end_transaction(balance)
        forfeited = (
            abs(Decimal(marker.amount_days))
            if marker is not None and Decimal(marker.amount_days) < 0
            else Decimal("0.00")
        )
        return LeaveUtilizationSummary(
            required_days=required,
            used_days=used,
            remaining_days=remaining,
            forfeited_days=forfeited,
        )

    def _finalize_leave_utilization(
        self,
        *,
        balance: LeaveBalance,
        as_of: date,
    ) -> LeaveUtilizationSummary | None:
        """Forfeit one unmet VL target once the annual period has ended."""

        period_end = self.leave_cycle_end(balance.company_id, balance.year)
        if as_of < period_end:
            return None
        existing = self._leave_utilization_year_end_transaction(balance)
        if existing is not None:
            return self.leave_utilization_summary(
                balance=balance,
                as_of=as_of,
            )

        summary = self.leave_utilization_summary(
            balance=balance,
            as_of=period_end,
        )
        if summary is None:
            return None
        if not summary.is_enabled:
            return summary

        forfeited = min(
            summary.remaining_days,
            Decimal(balance.available_credits),
        ).quantize(Decimal("0.01"))
        if forfeited > 0:
            balance.adjustment_days = (
                Decimal(balance.adjustment_days) - forfeited
            ).quantize(Decimal("0.01"))

        self.session.add(
            LeaveCreditTransaction(
                company_id=balance.company_id,
                employee_id=balance.employee_id,
                leave_type_id=balance.leave_type_id,
                leave_balance_id=balance.id,
                transaction_type=LEAVE_UTILIZATION_YEAR_END_TRANSACTION,
                amount_days=-forfeited,
                note=(
                    f"Vacation Leave utilization year-end {balance.year}: "
                    f"required {summary.required_days} day(s), used "
                    f"{summary.used_days} day(s), forfeited unmet target "
                    f"{forfeited} day(s). The forfeiture is not carried "
                    "over and is not converted to cash."
                ),
            )
        )
        return LeaveUtilizationSummary(
            required_days=summary.required_days,
            used_days=summary.used_days,
            remaining_days=summary.remaining_days,
            forfeited_days=forfeited,
        )

    def _leave_utilization_recipient_ids(
        self,
        *,
        employee: Employee,
    ) -> set[int]:
        """Return employee, direct supervisors, and active administrators."""

        recipients = set(
            self.user_repository.list_active_admin_ids(
                company_id=employee.company_id,
            )
        )
        for related in (employee, employee.leader, employee.manager):
            if (
                related is not None
                and related.user is not None
                and related.user.is_active
            ):
                recipients.add(related.user.id)
        return recipients

    def _send_leave_utilization_notification(
        self,
        *,
        balance: LeaveBalance,
        employee: Employee,
        event_type: str,
        title: str,
        message: str,
    ) -> int:
        """Create one idempotent utilization notification per recipient."""

        created = 0
        for user_id in self._leave_utilization_recipient_ids(
            employee=employee,
        ):
            if self.notification_service.exists_for_entity_event(
                company_id=balance.company_id,
                user_id=user_id,
                event_type=event_type,
                related_entity_type="leave_balance",
                related_entity_id=balance.id,
            ):
                continue
            self.notification_service.create(
                company_id=balance.company_id,
                user_id=user_id,
                event_type=event_type,
                title=title,
                message=message,
                related_entity_type="leave_balance",
                related_entity_id=balance.id,
            )
            created += 1
        return created

    def reconcile_leave_utilization(
        self,
        *,
        company_id: int,
        through_date: date | None = None,
    ) -> int:
        """Finalize due VL targets and emit non-duplicating reminders."""

        selected_date = through_date or self._today()
        if not self._company(company_id).leave_utilization_enabled:
            return 0
        changed = 0
        current_cycle_year = self.leave_cycle_year(company_id, selected_date)
        balances = [
            item
            for item in self.balance_repository.list_company_year(
                company_id,
                current_cycle_year,
            )
            if (item.leave_type.code or "").strip().upper() == "VACATION"
        ]

        # Also finalize any older VL balance that has not yet received its
        # immutable year-end marker. This repairs safe legacy carryover on the
        # next app open without resetting or rewriting historical records.
        for year in range(2026, current_cycle_year):
            balances.extend(
                item
                for item in self.balance_repository.list_company_year(
                    company_id,
                    year,
                )
                if (item.leave_type.code or "").strip().upper() == "VACATION"
            )

        for balance in balances:
            employee = self.employee_repository.get_with_details(
                company_id=company_id,
                employee_id=balance.employee_id,
            )
            if employee is None:
                continue

            period_end = self.leave_cycle_end(company_id, balance.year)
            if selected_date >= period_end:
                was_finalized = (
                    self._leave_utilization_year_end_transaction(balance)
                    is not None
                )
                summary = self._finalize_leave_utilization(
                    balance=balance,
                    as_of=selected_date,
                )
                if summary is None:
                    continue
                if not was_finalized:
                    changed += 1
                if summary.forfeited_days > 0:
                    changed += self._send_leave_utilization_notification(
                        balance=balance,
                        employee=employee,
                        event_type="leave_utilization_forfeited",
                        title="Leave utilization year-end result",
                        message=(
                            f"{employee.full_name} used "
                            f"{self._display_days(summary.used_days)} of "
                            f"{self._display_days(summary.required_days)} "
                            "required Vacation Leave day(s). "
                            f"{self._display_days(summary.forfeited_days)} "
                            "unmet day(s) were forfeited and will not be "
                            "carried over or converted to cash."
                        ),
                    )
                continue

            summary = self.leave_utilization_summary(
                balance=balance,
                as_of=selected_date,
            )
            if summary is None or not summary.is_enabled:
                continue

            if summary.remaining_days <= 0:
                changed += self._send_leave_utilization_notification(
                    balance=balance,
                    employee=employee,
                    event_type="leave_utilization_completed",
                    title="Leave utilization target completed",
                    message=(
                        f"{employee.full_name} has consumed the required "
                        f"{self._display_days(summary.required_days)} "
                        f"Vacation Leave day(s) for {balance.year}."
                    ),
                )
                continue

            reminder_schedule = (
                (92, "leave_utilization_reminder_first", "Leave utilization reminder"),
                (61, "leave_utilization_reminder_followup", "Leave utilization follow-up"),
                (30, "leave_utilization_reminder_urgent", "Leave utilization urgent reminder"),
                (16, "leave_utilization_reminder_final", "Final leave utilization reminder"),
            )
            due_reminders = [
                item for item in reminder_schedule
                if selected_date >= period_end - timedelta(days=item[0])
            ]
            if not due_reminders:
                continue
            _, event_type, title = due_reminders[-1]
            changed += self._send_leave_utilization_notification(
                balance=balance,
                employee=employee,
                event_type=event_type,
                title=title,
                message=(
                    f"{employee.full_name} still needs to consume "
                    f"{self._display_days(summary.remaining_days)} of "
                    f"{self._display_days(summary.required_days)} required "
                    f"Vacation Leave day(s) before {period_end:%B %d, %Y}."
                ),
            )

        if changed:
            self.session.commit()
        return changed

    def _annual_processing_date(self, year: int, company_id: int | None = None) -> date:
        """Return the company-configured yearly SL/VL reset date."""

        return self.leave_cycle_start(company_id, year) if company_id else date(year, 1, 1)

    @staticmethod
    def annual_tenure_credit(completed_service_years: int) -> Decimal:
        """Return the non-cumulative January credit for one tenure bracket."""

        years = max(0, int(completed_service_years))
        return next(
            credit
            for minimum_years, credit in ANNUAL_TENURE_CREDIT_BRACKETS
            if years >= minimum_years
        )

    def _allocation_reference_date(
        self,
        *,
        year: int,
        as_of: date | None = None,
    ) -> date:
        """Return the January processing date for annual entitlement rules.

        ``as_of`` is retained for compatibility with callers and tests, but a
        mid-year service anniversary must not change an already processed
        annual credit. The tenure bracket is evaluated only on January 1.
        """

        return self._annual_processing_date(year)

    def calculate_annual_allocation(
        self,
        *,
        employee: Employee,
        leave_type: LeaveType,
        year: int,
        as_of: date | None = None,
    ) -> Decimal:
        """Compute one employee's January SL/VL credit for a calendar year.

        Rules:
        - Vacation Leave and Sick Leave use the completed-service bracket on
          January 1: 1–5 years = 15, 6–10 = 17, 11–15 = 20,
          16–20 = 23, and 21+ = 26 days.
        - A service anniversary reached after January 1 applies next year.
        - The hire year keeps the accepted prorated entitlement behavior.
        - Other leave types do not receive an annual Phase 2 accrual.
        """

        code = (leave_type.code or "").strip().upper()
        hire_date = employee.hire_date
        processing_date = self._annual_processing_date(year, employee.company_id)

        if code not in ANNUAL_ACCRUAL_CODES:
            return Decimal("0.00")
        if (as_of or self._today()) < processing_date:
            return Decimal("0.00")

        cycle_end = self.leave_cycle_end(employee.company_id, year)
        if hire_date is not None:
            if hire_date > cycle_end:
                return Decimal("0.00")
            if as_of is not None and as_of < hire_date:
                return Decimal("0.00")

        service_years = self.completed_service_years(
            hire_date,
            processing_date,
        )
        allocation = self.annual_tenure_credit(service_years)

        if hire_date is not None and hire_date > processing_date:
            next_processing = self.leave_cycle_start(employee.company_id, year + 1)
            remaining_months = max(
                0,
                (next_processing.year - hire_date.year) * 12
                + next_processing.month
                - hire_date.month,
            )
            allocation = self._round_to_half_day(
                allocation
                * Decimal(min(12, remaining_months))
                / Decimal("12")
            )

        return max(Decimal("0.00"), allocation)

    def entitlement_summary(
        self,
        *,
        employee: Employee,
        year: int,
        as_of: date | None = None,
    ) -> dict[str, Decimal | int | str]:
        """Return the standard combined leave entitlement for UI display."""

        leave_types = {
            item.code.upper(): item
            for item in self.list_leave_types(employee.company_id)
        }
        reference_date = self._annual_processing_date(year, employee.company_id)

        def allocation(code: str) -> Decimal:
            leave_type = leave_types.get(code)
            if leave_type is None:
                return Decimal("0.00")
            return self.calculate_annual_allocation(
                employee=employee,
                leave_type=leave_type,
                year=year,
                as_of=as_of,
            )

        regular_vacation = allocation("VACATION")
        emergency = Decimal("0.00")
        sick = allocation("SICK")
        return {
            "service_years": self.completed_service_years(
                employee.hire_date,
                reference_date,
            ),
            "regular_vacation": regular_vacation,
            "emergency": emergency,
            "vacation_total": regular_vacation,
            "sick": sick,
            "lwop": Decimal("0.00"),
            "basis": (
                "Hire-year prorated"
                if employee.hire_date is not None
                and employee.hire_date > reference_date
                and employee.hire_date
                <= self.leave_cycle_end(employee.company_id, year)
                else f"{reference_date:%B %d} annual accrual"
            ),
            "reset_date": reference_date,
        }

    def ensure_default_leave_types(self, company_id: int) -> list[LeaveType]:
        """Create defaults and safely upgrade untouched legacy allocations."""

        changed = False
        for spec in DEFAULT_LEAVE_TYPES:
            existing = self.leave_type_repository.get_by_code(
                company_id,
                spec["code"],
            )
            if existing is None:
                self.session.add(
                    LeaveType(
                        company_id=company_id,
                        is_active=True,
                        **spec,
                    )
                )
                changed = True
                continue

            upgrades = LEGACY_DEFAULT_UPGRADES.get(
                spec["code"],
                {},
            )
            for field_name, (legacy_values, new_value) in upgrades.items():
                current_value = Decimal(getattr(existing, field_name))
                if current_value in legacy_values:
                    setattr(existing, field_name, new_value)
                    changed = True

        if changed:
            self.session.commit()
        return self.leave_type_repository.list_company(company_id)

    @staticmethod
    def _sync_credit_table_columns(balance: LeaveBalance) -> bool:
        """Mirror the legacy ledger into the Phase 1 table columns.

        Returns True only when at least one persisted value changes. This
        keeps old records accurate without replacing or deleting them.
        """

        expected_beginning = Decimal(balance.carry_over_days)
        # Credit contains only automatic annual accruals or approved
        # event grants. Administrator corrections remain independently
        # visible in Adjustment and must never overwrite the credit source.
        expected_credit = Decimal(balance.allocated_days)
        changed = False

        if Decimal(balance.beginning_credit_days) != expected_beginning:
            balance.beginning_credit_days = expected_beginning
            changed = True

        if Decimal(balance.credit_days) != expected_credit:
            balance.credit_days = expected_credit
            changed = True

        return changed


    def _normalize_event_credit_classification(
        self,
        *,
        balance: LeaveBalance,
        leave_type: LeaveType,
    ) -> bool:
        """Move legacy event grants from Adjustment into Credit.

        Phase 5 originally stored approved event grants in the legacy
        adjustment bucket so they could coexist with annual accrual logic.
        The explicit Adjustment column now requires those immutable grant
        transactions to appear as Credit instead. Only the amount supported
        by event-grant audit transactions is reclassified, so unrelated
        repair adjustments remain untouched.
        """

        code = (leave_type.code or "").strip().upper()
        if code not in EVENT_LEAVE_CODES:
            return False

        grant_total = self.session.scalar(
            select(
                func.coalesce(
                    func.sum(LeaveCreditTransaction.amount_days),
                    Decimal("0.00"),
                )
            ).where(
                LeaveCreditTransaction.leave_balance_id == balance.id,
                LeaveCreditTransaction.transaction_type
                == EVENT_LEAVE_GRANT_TRANSACTION,
            )
        )
        grant_total = max(Decimal("0.00"), Decimal(grant_total or 0))
        allocated = Decimal(balance.allocated_days)
        adjustment = Decimal(balance.adjustment_days)
        amount_to_move = min(
            max(Decimal("0.00"), grant_total - allocated),
            max(Decimal("0.00"), adjustment),
        )
        if amount_to_move <= Decimal("0.00"):
            return False

        balance.allocated_days = allocated + amount_to_move
        balance.adjustment_days = adjustment - amount_to_move
        return True


    def _normalize_emergency_balance(
        self,
        *,
        balance: LeaveBalance,
        leave_type: LeaveType,
    ) -> bool:
        """Remove legacy standalone EL credits without deleting requests.

        Phase 4 treats leave requests as the source of EL usage and Vacation
        Leave as the only paid-credit source. Older standalone EL ledger
        values are therefore cleared once with an audit entry.
        """

        code = (leave_type.code or "").strip().upper()
        if code != "EMERGENCY":
            return False

        tracked_values = (
            Decimal(balance.allocated_days),
            Decimal(balance.carry_over_days),
            Decimal(balance.adjustment_days),
            Decimal(balance.used_days),
            Decimal(balance.reserved_days),
            Decimal(balance.beginning_credit_days),
            Decimal(balance.credit_days),
            Decimal(balance.converted_to_cash_days),
        )
        if all(value == Decimal("0.00") for value in tracked_values):
            return False

        prior_usable = Decimal(balance.available_credits)
        balance.allocated_days = Decimal("0.00")
        balance.carry_over_days = Decimal("0.00")
        balance.adjustment_days = Decimal("0.00")
        balance.used_days = Decimal("0.00")
        balance.reserved_days = Decimal("0.00")
        balance.beginning_credit_days = Decimal("0.00")
        balance.credit_days = Decimal("0.00")
        balance.converted_to_cash_days = Decimal("0.00")

        self.session.add(
            LeaveCreditTransaction(
                company_id=balance.company_id,
                employee_id=balance.employee_id,
                leave_type_id=balance.leave_type_id,
                leave_balance_id=balance.id,
                transaction_type="emergency_credit_normalization",
                amount_days=-prior_usable,
                note=(
                    "Phase 4 normalization: Emergency Leave is a maximum "
                    "three-day annual usage allowance inside Vacation Leave, "
                    "not a separate credit balance. Existing leave requests "
                    "and their history were preserved."
                ),
            )
        )
        return True

    def _repair_negative_balance(
        self,
        balance: LeaveBalance,
    ) -> Decimal:
        """Bring one invalid legacy balance back to zero with an audit entry.

        Older test data may contain more used/reserved days than the recorded
        credits. The history is preserved; only the internal adjustment is
        increased by the exact deficit so the usable balance becomes zero.
        Re-running this method is idempotent.
        """

        raw_available = Decimal(
            balance.calculated_available_credits
        ).quantize(Decimal("0.01"))

        if raw_available >= Decimal("0.00"):
            return Decimal("0.00")

        repair_days = -raw_available
        balance.adjustment_days = (
            Decimal(balance.adjustment_days) + repair_days
        )
        self._sync_credit_table_columns(balance)

        self.session.add(
            LeaveCreditTransaction(
                company_id=balance.company_id,
                employee_id=balance.employee_id,
                leave_type_id=balance.leave_type_id,
                leave_balance_id=balance.id,
                transaction_type="negative_balance_repair",
                amount_days=repair_days,
                note=(
                    "Automatic non-negative balance safeguard: "
                    f"legacy balance {raw_available} day(s) was corrected "
                    "to 0.00 without deleting leave usage or request history."
                ),
            )
        )
        return repair_days

    @staticmethod
    def _validate_nonnegative_balance(balance: LeaveBalance) -> None:
        """Block any write that would persist a negative usable balance."""

        raw_available = Decimal(
            balance.calculated_available_credits
        ).quantize(Decimal("0.01"))
        if raw_available < Decimal("0.00"):
            raise ValueError(
                "Insufficient leave credits. The balance cannot go below "
                "zero; use Leave Without Pay for the uncovered days."
            )

    @staticmethod
    def credit_table_balances(balances) -> list[LeaveBalance]:
        """Return the seven employee-facing leave rows in required order."""

        return sorted(
            (
                balance
                for balance in balances
                if balance.leave_type.code.upper()
                in LEAVE_CREDIT_TABLE_ORDER
            ),
            key=lambda balance: LEAVE_CREDIT_TABLE_ORDER[
                balance.leave_type.code.upper()
            ],
        )

    @staticmethod
    def _emergency_paid_days(request: LeaveRequest) -> Decimal:
        """Return the approved paid EL portion, excluding automatic LWOP."""

        paid = (
            Decimal(request.primary_credit_days or Decimal("0.00"))
            + Decimal(request.fallback_credit_days or Decimal("0.00"))
        )
        return max(Decimal("0.00"), paid)

    @staticmethod
    def event_leave_entitlement(
        leave_type_or_code: LeaveType | str,
    ) -> Decimal:
        """Return the fixed grant for one qualifying event leave request."""

        code = (
            leave_type_or_code.code
            if isinstance(leave_type_or_code, LeaveType)
            else leave_type_or_code
        )
        return EVENT_LEAVE_ENTITLEMENTS.get(
            (code or "").strip().upper(),
            Decimal("0.00"),
        )

    @staticmethod
    def normalized_employee_gender(employee: Employee | None) -> str:
        """Return a stable MALE/FEMALE value for eligibility checks."""

        raw_value = (employee.gender if employee is not None else None)
        normalized = (raw_value or "").strip().upper()
        aliases = {
            "M": "MALE",
            "MALE": "MALE",
            "F": "FEMALE",
            "FEMALE": "FEMALE",
        }
        return aliases.get(normalized, normalized)

    @classmethod
    def event_leave_gender_eligibility(
        cls,
        *,
        employee: Employee | None,
        leave_type_or_code: LeaveType | str,
    ) -> tuple[bool, str | None]:
        """Return whether an employee may use the selected event leave."""

        code = (
            leave_type_or_code.code
            if isinstance(leave_type_or_code, LeaveType)
            else leave_type_or_code
        )
        normalized_code = (code or "").strip().upper()
        required_gender = EVENT_LEAVE_GENDER_REQUIREMENTS.get(
            normalized_code
        )
        if required_gender is None:
            return True, None

        employee_gender = cls.normalized_employee_gender(employee)
        if employee_gender == required_gender:
            return True, None

        leave_name = (
            leave_type_or_code.name
            if isinstance(leave_type_or_code, LeaveType)
            else normalized_code.title()
        )
        required_label = required_gender.title()
        if employee_gender not in {"MALE", "FEMALE"}:
            return (
                False,
                f"{leave_name} requires the employee gender to be recorded "
                f"as {required_label}. Update the employee profile before "
                "filing or approving this request.",
            )

        return (
            False,
            f"{leave_name} is available only to employees recorded as "
            f"{required_label}.",
        )

    @classmethod
    def is_event_leave_gender_eligible(
        cls,
        *,
        employee: Employee | None,
        leave_type_or_code: LeaveType | str,
    ) -> bool:
        """Convenience boolean used by the employee request UI."""

        eligible, _ = cls.event_leave_gender_eligibility(
            employee=employee,
            leave_type_or_code=leave_type_or_code,
        )
        return eligible

    @classmethod
    def _validate_event_leave_gender_eligibility(
        cls,
        *,
        employee: Employee | None,
        leave_type_or_code: LeaveType | str,
    ) -> None:
        """Reject ineligible Maternity/Paternity requests consistently."""

        eligible, message = cls.event_leave_gender_eligibility(
            employee=employee,
            leave_type_or_code=leave_type_or_code,
        )
        if not eligible:
            raise ValueError(message or "The selected leave is unavailable.")

    @staticmethod
    def leave_entitlement_display(leave_type_or_code: LeaveType | str) -> str:
        """Return the policy allowance label for explanatory UI text."""

        code = (
            leave_type_or_code.code
            if isinstance(leave_type_or_code, LeaveType)
            else leave_type_or_code
        )
        normalized_code = (code or "").strip().upper()
        labels = {
            "VACATION": "15 / 17 annually",
            "EMERGENCY": "3 max/year from VL",
            "SICK": "15 / 17 annually",
            "HONEYMOON": "5 one-time",
            "MATERNITY": "105 per event · Female",
            "PATERNITY": "7 per event · Male",
            "BEREAVEMENT": "7 per event",
        }
        return labels.get(normalized_code, "—")

    @staticmethod
    def supports_cash_conversion(
        leave_type_or_code: LeaveType | str,
    ) -> bool:
        """Return True only for leave types allowed to convert to cash."""

        code = (
            leave_type_or_code.code
            if isinstance(leave_type_or_code, LeaveType)
            else leave_type_or_code
        )
        return (code or "").strip().upper() in CASH_CONVERSION_LIMITS

    def _honeymoon_request_exists(
        self,
        *,
        company_id: int,
        employee_id: int,
        exclude_request_id: int | None = None,
    ) -> bool:
        """Return whether the employee already claimed or filed Honeymoon Leave."""

        for request in self.request_repository.list_employee(
            company_id,
            employee_id,
        ):
            code = (
                request.leave_type.code
                if request.leave_type is not None
                else ""
            ).strip().upper()
            if code != "HONEYMOON":
                continue
            if (
                exclude_request_id is not None
                and request.id == exclude_request_id
            ):
                continue
            if request.status in EVENT_LEAVE_NON_REJECTED_STATUSES:
                return True
        return False

    def event_leave_preview_entitlement(
        self,
        *,
        company_id: int,
        employee_id: int,
        leave_type: LeaveType,
    ) -> Decimal:
        """Return the grant expected if a new event request is approved."""

        code = (leave_type.code or "").strip().upper()
        entitlement = self.event_leave_entitlement(code)
        if entitlement <= Decimal("0.00"):
            return Decimal("0.00")

        employee = self.employee_repository.get_with_details(
            company_id=company_id,
            employee_id=employee_id,
        )
        if not self.is_event_leave_gender_eligible(
            employee=employee,
            leave_type_or_code=leave_type,
        ):
            return Decimal("0.00")
        if code == "HONEYMOON" and self._honeymoon_request_exists(
            company_id=company_id,
            employee_id=employee_id,
        ):
            return Decimal("0.00")
        return entitlement

    def _event_grant_already_posted(
        self,
        request: LeaveRequest,
    ) -> bool:
        """Keep one immutable entitlement grant per approved event request."""

        count = self.session.scalar(
            select(func.count(LeaveCreditTransaction.id)).where(
                LeaveCreditTransaction.leave_request_id == request.id,
                LeaveCreditTransaction.transaction_type
                == EVENT_LEAVE_GRANT_TRANSACTION,
            )
        )
        return bool(count)

    def _grant_event_leave_entitlement(
        self,
        *,
        request: LeaveRequest,
        created_by_user_id: int,
    ) -> Decimal:
        """Post the fixed event entitlement before reserving approved days."""

        code = (
            request.leave_type.code
            if request.leave_type is not None
            else ""
        ).strip().upper()
        entitlement = self.event_leave_entitlement(code)
        if entitlement <= Decimal("0.00"):
            return Decimal("0.00")
        if self._event_grant_already_posted(request):
            return Decimal("0.00")

        self._validate_event_leave_gender_eligibility(
            employee=request.employee,
            leave_type_or_code=request.leave_type,
        )

        if code == "HONEYMOON" and self._honeymoon_request_exists(
            company_id=request.company_id,
            employee_id=request.employee_id,
            exclude_request_id=request.id,
        ):
            raise ValueError(
                "Honeymoon Leave is a one-time five-day benefit and has "
                "already been requested or used by this employee."
            )

        balance = self._ensure_balance(
            company_id=request.company_id,
            employee_id=request.employee_id,
            leave_type=request.leave_type,
            year=self.leave_cycle_year(request.company_id, request.start_date),
            employee=request.employee,
            as_of=self._today(),
        )
        balance.allocated_days = (
            Decimal(balance.allocated_days) + entitlement
        )
        self._sync_credit_table_columns(balance)
        self._validate_nonnegative_balance(balance)
        self.session.add(
            LeaveCreditTransaction(
                company_id=request.company_id,
                employee_id=request.employee_id,
                leave_type_id=request.leave_type_id,
                leave_balance_id=balance.id,
                leave_request_id=request.id,
                created_by_user_id=created_by_user_id,
                transaction_type=EVENT_LEAVE_GRANT_TRANSACTION,
                amount_days=entitlement,
                note=(
                    f"Phase 5 qualifying event grant for "
                    f"{request.public_id}: {entitlement} day(s) of "
                    f"{request.leave_type.name}."
                ),
            )
        )
        return entitlement

    def emergency_allowance_summary(
        self,
        *,
        company_id: int,
        employee_id: int,
        year: int,
    ) -> EmergencyAllowanceSummary:
        """Return annual EL used, reserved, and remaining allowance.

        Emergency Leave has no separate credit bucket. Approved EL days are
        funded from Vacation Leave, while this summary independently enforces
        the maximum three-day annual EL classification.
        """

        used = Decimal("0.00")
        reserved = Decimal("0.00")
        last_updated = None

        for request in self.request_repository.list_employee(
            company_id,
            employee_id,
        ):
            code = (
                request.leave_type.code
                if request.leave_type is not None
                else ""
            ).strip().upper()
            if (
                code != "EMERGENCY"
                or self.leave_cycle_year(company_id, request.start_date) != int(year)
                or request.status not in EMERGENCY_ACTIVE_STATUSES
            ):
                continue

            paid_days = min(
                EMERGENCY_USAGE_LIMIT,
                self._emergency_paid_days(request),
            )
            posted_days = min(
                paid_days,
                max(
                    Decimal("0.00"),
                    Decimal(
                        request.posted_working_days
                        or Decimal("0.00")
                    ),
                ),
            )
            used += posted_days
            reserved += max(
                Decimal("0.00"),
                paid_days - posted_days,
            )

            candidate = request.updated_at or request.reviewed_at
            if candidate is not None and (
                last_updated is None or candidate > last_updated
            ):
                last_updated = candidate

        committed = min(
            EMERGENCY_USAGE_LIMIT,
            used + reserved,
        )
        return EmergencyAllowanceSummary(
            used_days=used.quantize(Decimal("0.01")),
            reserved_days=reserved.quantize(Decimal("0.01")),
            remaining_days=max(
                Decimal("0.00"),
                EMERGENCY_USAGE_LIMIT - committed,
            ).quantize(Decimal("0.01")),
            last_updated=last_updated,
        )

    def credit_table_rows(
        self,
        *,
        company_id: int,
        employee_id: int,
        year: int,
        balances=None,
    ) -> list[LeaveCreditTableRow]:
        """Build the seven display rows without double-counting EL credits."""

        selected_balances = list(
            balances
            if balances is not None
            else self.list_employee_balances(
                company_id,
                employee_id,
                year,
            )
        )
        emergency = self.emergency_allowance_summary(
            company_id=company_id,
            employee_id=employee_id,
            year=year,
        )
        employee = self.employee_repository.get_with_details(
            company_id=company_id,
            employee_id=employee_id,
        )
        rows: list[LeaveCreditTableRow] = []

        for balance in self.credit_table_balances(selected_balances):
            code = (balance.leave_type.code or "").strip().upper()
            is_applicable = self.is_event_leave_gender_eligible(
                employee=employee,
                leave_type_or_code=balance.leave_type,
            )
            if code == "EMERGENCY":
                updated_at = emergency.last_updated or balance.updated_at
                rows.append(
                    LeaveCreditTableRow(
                        leave_type=balance.leave_type,
                        beginning_credit_days=Decimal("0.00"),
                        credit_days=Decimal("0.00"),
                        adjustment_days=Decimal("0.00"),
                        used_days=emergency.used_days,
                        reserved_days=emergency.reserved_days,
                        available_credits=emergency.remaining_days,
                        converted_to_cash_days=Decimal("0.00"),
                        updated_at=updated_at,
                        is_applicable=True,
                    )
                )
                continue

            actual_available = Decimal(balance.available_credits)
            display_available = actual_available

            # Event-based rows show their fixed policy allowance directly in
            # Available Credits before a grant exists. Once a grant has an
            # active remaining or reserved balance, the row shows the real
            # ledger remainder. Honeymoon automatically returns zero after
            # its one-time benefit has already been requested or used.
            if code in EVENT_LEAVE_CODES:
                preview_allowance = self.event_leave_preview_entitlement(
                    company_id=company_id,
                    employee_id=employee_id,
                    leave_type=balance.leave_type,
                )
                if (
                    actual_available <= Decimal("0.00")
                    and Decimal(balance.reserved_days)
                    <= Decimal("0.00")
                ):
                    display_available = preview_allowance

            rows.append(
                LeaveCreditTableRow(
                    leave_type=balance.leave_type,
                    beginning_credit_days=Decimal(
                        balance.beginning_credit_days
                    ),
                    credit_days=Decimal(balance.credit_days),
                    adjustment_days=Decimal(balance.adjustment_days),
                    used_days=Decimal(balance.used_days),
                    reserved_days=Decimal(balance.reserved_days),
                    available_credits=display_available,
                    converted_to_cash_days=Decimal(
                        balance.converted_to_cash_days
                    ),
                    updated_at=balance.updated_at,
                    is_applicable=is_applicable,
                    leave_utilization=(
                        self.leave_utilization_summary(
                            balance=balance,
                        )
                        if code == "VACATION" and is_applicable
                        else None
                    ),
                )
            )

        return rows

    @staticmethod
    def _annual_beginning_credit(
        *,
        leave_type: LeaveType,
        previous_balance: LeaveBalance | None,
    ) -> Decimal:
        """Carry only the prior year's post-conversion available balance.

        ``available_credits`` already excludes amounts recorded in
        ``converted_to_cash_days``. This prevents a converted amount from
        returning as Beginning Credit in a later leave year.
        """

        code = (leave_type.code or "").strip().upper()
        if code not in ANNUAL_ACCRUAL_CODES or previous_balance is None:
            return Decimal("0.00")

        return max(
            Decimal("0.00"),
            Decimal(previous_balance.available_credits),
        ).quantize(Decimal("0.00"))

    @staticmethod
    def _cash_conversion_limit(leave_type: LeaveType) -> Decimal | None:
        """Return the fixed retained limit for SL or VL."""

        code = (leave_type.code or "").strip().upper()
        return CASH_CONVERSION_LIMITS.get(code)

    def _cash_conversion_already_processed(
        self,
        balance: LeaveBalance,
    ) -> bool:
        """Return True when this annual ledger already has its cash marker."""

        count = self.session.scalar(
            select(func.count(LeaveCreditTransaction.id)).where(
                LeaveCreditTransaction.leave_balance_id == balance.id,
                LeaveCreditTransaction.transaction_type
                == CASH_CONVERSION_TRANSACTION,
            )
        )
        return bool(count)

    @staticmethod
    def _opening_cash_conversion_amount(
        *,
        balance: LeaveBalance,
        retained_limit: Decimal,
    ) -> Decimal:
        """Calculate the annual excess using the approved ledger formula.

        Total Before Conversion = Beginning Credit + Credit + Adjustment
        Converted to Cash = max(Total Before Conversion - Limit, 0)

        Used and Reserved are intentionally excluded from conversion. They are
        deducted from Available Credits after the fixed excess is identified,
        so later leave usage cannot reverse a completed cash conversion.
        """

        total_before_conversion = (
            Decimal(balance.beginning_credit_days)
            + Decimal(balance.credit_days)
            + Decimal(balance.adjustment_days)
        )
        return max(
            Decimal("0.00"),
            total_before_conversion - Decimal(retained_limit),
        ).quantize(Decimal("0.00"))

    def _apply_january_cash_conversion(
        self,
        *,
        balance: LeaveBalance,
        leave_type: LeaveType,
        year: int,
    ) -> Decimal:
        """Apply one immutable January SL/VL cash-conversion calculation.

        A zero-value marker is also stored. This keeps processing idempotent
        and prevents later leave usage or manual adjustments from rewriting
        the January conversion result.
        """

        retained_limit = self._cash_conversion_limit(leave_type)
        if retained_limit is None:
            balance.converted_to_cash_days = Decimal("0.00")
            return Decimal("0.00")

        if self._cash_conversion_already_processed(balance):
            return Decimal(balance.converted_to_cash_days)

        converted = self._opening_cash_conversion_amount(
            balance=balance,
            retained_limit=retained_limit,
        )
        balance.converted_to_cash_days = converted

        self.session.add(
            LeaveCreditTransaction(
                company_id=balance.company_id,
                employee_id=balance.employee_id,
                leave_type_id=balance.leave_type_id,
                leave_balance_id=balance.id,
                transaction_type=CASH_CONVERSION_TRANSACTION,
                # A conversion removes days from the usable credit ledger.
                amount_days=-converted,
                note=(
                    f"{self._annual_processing_date(year, balance.company_id):%B %d, %Y} "
                    "cash conversion: retained limit "
                    f"{retained_limit} day(s); converted excess "
                    f"{converted} day(s)."
                ),
            )
        )
        return converted

    def _enforce_cash_conversion_limit(
        self,
        *,
        balance: LeaveBalance,
        leave_type: LeaveType,
        created_by_user_id: int | None = None,
        source: str = "automatic balance validation",
    ) -> Decimal:
        """Move any current SL/VL excess out of usable credits.

        January processing performs the scheduled annual conversion. This
        additional invariant protects every later write path, including
        manual administrator updates and legacy records created before Phase
        3. It is naturally idempotent because converted days are immediately
        removed from ``calculated_available_credits``.
        """

        retained_limit = self._cash_conversion_limit(leave_type)
        if retained_limit is None:
            return Decimal("0.00")

        current_available = Decimal(
            balance.calculated_available_credits
        ).quantize(Decimal("0.01"))
        excess = max(
            Decimal("0.00"),
            current_available - retained_limit,
        ).quantize(Decimal("0.01"))

        if excess <= Decimal("0.00"):
            return Decimal("0.00")

        balance.converted_to_cash_days = (
            Decimal(balance.converted_to_cash_days) + excess
        ).quantize(Decimal("0.01"))

        self.session.add(
            LeaveCreditTransaction(
                company_id=balance.company_id,
                employee_id=balance.employee_id,
                leave_type_id=balance.leave_type_id,
                leave_balance_id=balance.id,
                created_by_user_id=created_by_user_id,
                transaction_type=(
                    CASH_CONVERSION_LIMIT_ENFORCEMENT_TRANSACTION
                ),
                amount_days=-excess,
                note=(
                    f"{source}: retained limit {retained_limit} day(s); "
                    f"converted excess {excess} day(s)."
                ),
            )
        )
        return excess

    def _sync_balance_beginning_credit(
        self,
        *,
        balance: LeaveBalance,
        leave_type: LeaveType,
        year: int,
    ) -> None:
        """Synchronize the current annual beginning credit non-destructively."""

        previous = self.balance_repository.get_balance(
            company_id=balance.company_id,
            employee_id=balance.employee_id,
            leave_type_id=balance.leave_type_id,
            year=year - 1,
        )
        expected = self._annual_beginning_credit(
            leave_type=leave_type,
            previous_balance=previous,
        )
        current = Decimal(balance.carry_over_days)
        if current == expected:
            return

        difference = expected - current
        balance.carry_over_days = expected
        balance.beginning_credit_days = expected
        previous_converted = Decimal(balance.converted_to_cash_days)
        if self._cash_conversion_already_processed(balance):
            retained_limit = self._cash_conversion_limit(leave_type)
            if retained_limit is not None:
                corrected_converted = self._opening_cash_conversion_amount(
                    balance=balance,
                    retained_limit=retained_limit,
                )
                if corrected_converted != previous_converted:
                    balance.converted_to_cash_days = corrected_converted
                    self.session.add(
                        LeaveCreditTransaction(
                            company_id=balance.company_id,
                            employee_id=balance.employee_id,
                            leave_type_id=balance.leave_type_id,
                            leave_balance_id=balance.id,
                            transaction_type=(
                                "beginning_credit_conversion_recalculation"
                            ),
                            amount_days=-(
                                corrected_converted - previous_converted
                            ),
                            note=(
                                f"Cash conversion recalculated after "
                                f"Beginning Credit for {year} changed from "
                                f"{current} to {expected} day(s); converted "
                                f"amount changed from {previous_converted} "
                                f"to {corrected_converted} day(s)."
                            ),
                        )
                    )
        self.session.add(
            LeaveCreditTransaction(
                company_id=balance.company_id,
                employee_id=balance.employee_id,
                leave_type_id=balance.leave_type_id,
                leave_balance_id=balance.id,
                transaction_type="january_beginning_credit_update",
                amount_days=difference,
                note=(
                    f"Beginning credit for {year} synchronized from the "
                    f"unused {year - 1} balance; beginning credit is now "
                    f"{expected} day(s)."
                ),
            )
        )

    def _sync_balance_allocation(
        self,
        *,
        balance: LeaveBalance,
        employee: Employee,
        leave_type: LeaveType,
        year: int,
        as_of: date | None = None,
    ) -> None:
        """Synchronize only the automatic allocation portion of a balance."""

        code = (leave_type.code or "").strip().upper()
        if code in EVENT_LEAVE_CODES:
            return

        expected = self.calculate_annual_allocation(
            employee=employee,
            leave_type=leave_type,
            year=year,
            as_of=as_of,
        )
        current = Decimal(balance.allocated_days)
        if expected == current:
            return

        difference = expected - current
        previous_converted = Decimal(balance.converted_to_cash_days)
        balance.allocated_days = expected
        self._sync_credit_table_columns(balance)

        retained_limit = self._cash_conversion_limit(leave_type)
        if retained_limit is not None:
            corrected_converted = self._opening_cash_conversion_amount(
                balance=balance,
                retained_limit=retained_limit,
            )
            if corrected_converted != previous_converted:
                balance.converted_to_cash_days = corrected_converted
                self.session.add(
                    LeaveCreditTransaction(
                        company_id=balance.company_id,
                        employee_id=balance.employee_id,
                        leave_type_id=balance.leave_type_id,
                        leave_balance_id=balance.id,
                        transaction_type=(
                            "tenure_bracket_conversion_recalculation"
                        ),
                        amount_days=-(
                            corrected_converted - previous_converted
                        ),
                        note=(
                            f"Cash conversion recalculated after the annual "
                            f"tenure credit changed from {current} to "
                            f"{expected} day(s); converted amount changed "
                            f"from {previous_converted} to "
                            f"{corrected_converted} day(s)."
                        ),
                    )
                )
        self.session.add(
            LeaveCreditTransaction(
                company_id=balance.company_id,
                employee_id=balance.employee_id,
                leave_type_id=balance.leave_type_id,
                leave_balance_id=balance.id,
                transaction_type="january_annual_accrual_update",
                amount_days=difference,
                note=(
                    f"{self._annual_processing_date(year, balance.company_id):%B %d, %Y} "
                    "annual accrual recalculated from the employee's completed "
                    "service years on the configured reset date; "
                    f"credit is now {expected} day(s)."
                ),
            )
        )

    def _ensure_balance(
        self,
        *,
        company_id: int,
        employee_id: int,
        leave_type: LeaveType,
        year: int,
        employee: Employee | None = None,
        as_of: date | None = None,
    ) -> LeaveBalance:
        employee = employee or self.employee_repository.get_with_details(
            company_id=company_id,
            employee_id=employee_id,
        )
        if employee is None:
            raise ValueError("The employee record is unavailable.")

        previous = self.balance_repository.get_balance(
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=leave_type.id,
            year=year - 1,
        )
        processing_date = as_of or self._today()
        if (
            previous is not None
            and (leave_type.code or "").strip().upper() == "VACATION"
            and processing_date >= self.leave_cycle_end(company_id, year - 1)
        ):
            self._finalize_leave_utilization(
                balance=previous,
                as_of=processing_date,
            )

        existing = self.balance_repository.get_balance(
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=leave_type.id,
            year=year,
        )
        if existing is not None:
            # Historical records remain unchanged. The selected annual ledger
            # is synchronized idempotently to the January rules so databases
            # created by older checkpoints receive the corrected SL/VL credit.
            if year >= self.leave_cycle_year(company_id) or as_of is not None:
                self._sync_balance_beginning_credit(
                    balance=existing,
                    leave_type=leave_type,
                    year=year,
                )
                self._sync_balance_allocation(
                    balance=existing,
                    employee=employee,
                    leave_type=leave_type,
                    year=year,
                    as_of=as_of,
                )
            self._normalize_emergency_balance(
                balance=existing,
                leave_type=leave_type,
            )
            self._normalize_event_credit_classification(
                balance=existing,
                leave_type=leave_type,
            )
            self._sync_credit_table_columns(existing)
            self._apply_january_cash_conversion(
                balance=existing,
                leave_type=leave_type,
                year=year,
            )
            self._enforce_cash_conversion_limit(
                balance=existing,
                leave_type=leave_type,
                source="Automatic retained-limit repair",
            )
            self._repair_negative_balance(existing)
            return existing

        carry_over = self._annual_beginning_credit(
            leave_type=leave_type,
            previous_balance=previous,
        )

        allocation = self.calculate_annual_allocation(
            employee=employee,
            leave_type=leave_type,
            year=year,
            as_of=as_of,
        )
        balance = LeaveBalance(
            company_id=company_id,
            employee_id=employee_id,
            leave_type_id=leave_type.id,
            year=year,
            allocated_days=allocation,
            carry_over_days=carry_over,
            adjustment_days=Decimal("0.00"),
            used_days=Decimal("0.00"),
            reserved_days=Decimal("0.00"),
            beginning_credit_days=carry_over,
            credit_days=allocation,
            converted_to_cash_days=Decimal("0.00"),
        )
        self.session.add(balance)
        self.session.flush()
        self.session.add(
            LeaveCreditTransaction(
                company_id=company_id,
                employee_id=employee_id,
                leave_type_id=leave_type.id,
                leave_balance_id=balance.id,
                transaction_type="january_annual_accrual",
                amount_days=allocation,
                note=(
                    f"{self._annual_processing_date(year, company_id):%B %d, %Y} "
                    "annual accrual based on completed service years as of "
                    "the configured reset date"
                ),
            )
        )
        if carry_over:
            self.session.add(
                LeaveCreditTransaction(
                    company_id=company_id,
                    employee_id=employee_id,
                    leave_type_id=leave_type.id,
                    leave_balance_id=balance.id,
                    transaction_type="january_beginning_credit",
                    amount_days=carry_over,
                    note=f"Unused SL/VL balance carried from {year - 1}",
                )
            )
        self._apply_january_cash_conversion(
            balance=balance,
            leave_type=leave_type,
            year=year,
        )
        self._enforce_cash_conversion_limit(
            balance=balance,
            leave_type=leave_type,
            source="Automatic retained-limit validation",
        )
        self._validate_nonnegative_balance(balance)
        return balance

    def ensure_current_year_balances(
        self,
        company_id: int,
        year: int | None = None,
    ) -> None:
        """Run idempotent January accrual processing for company employees.

        Accessing the portal safely performs the batch when the selected year
        has not yet been processed. Running it again never duplicates credits.
        """

        selected_year = year or self.leave_cycle_year(company_id)
        leave_types = self.ensure_default_leave_types(company_id)
        active_types = [item for item in leave_types if item.is_active]
        employees = [
            employee
            for employee in self.employee_repository.list_with_details(
                company_id
            )
            if employee.employment_status == "employed"
        ]
        for employee in employees:
            for leave_type in active_types:
                self._ensure_balance(
                    company_id=company_id,
                    employee_id=employee.id,
                    leave_type=leave_type,
                    year=selected_year,
                    employee=employee,
                )

        # Automatic app-start processing must persist even when there are no
        # approved leave requests for the reconciliation step to commit.
        self.session.commit()

    def list_leave_types(self, company_id: int, *, active_only: bool = False) -> list[LeaveType]:
        self.ensure_default_leave_types(company_id)
        return self.leave_type_repository.list_company(company_id, active_only=active_only)

    def save_leave_type(self, values: LeaveTypeInput, leave_type_id: int | None = None) -> LeaveType:
        """Create or update leave rules and optionally reallocate balances."""

        existing_code = self.leave_type_repository.get_by_code(values.company_id, values.code)
        existing_name = self.leave_type_repository.get_by_name(values.company_id, values.name)
        if leave_type_id is None:
            if existing_code or existing_name:
                raise ValueError("A leave type with that code or name already exists.")
            leave_type = LeaveType(company_id=values.company_id)
            self.session.add(leave_type)
        else:
            leave_type = self.leave_type_repository.get_by_id(leave_type_id, values.company_id)
            if leave_type is None:
                raise ValueError("The selected leave type is unavailable.")
            if existing_code is not None and existing_code.id != leave_type.id:
                raise ValueError("That leave type code is already used.")
            if existing_name is not None and existing_name.id != leave_type.id:
                raise ValueError("That leave type name is already used.")

        leave_type.code = values.code
        leave_type.name = values.name
        leave_type.annual_credits = values.annual_credits
        leave_type.is_paid = values.is_paid
        leave_type.carry_over_limit = values.carry_over_limit
        # Supporting attachments are replaced by an optional handover
        # plan and optional plan file.
        leave_type.requires_attachment = False
        leave_type.handover_plan_requirement = (
            values.handover_plan_requirement
        )
        leave_type.minimum_notice_days = values.minimum_notice_days
        leave_type.is_active = values.is_active
        self.session.flush()

        if values.apply_annual_credits_to_existing:
            year = self.leave_cycle_year(values.company_id)
            balances = self.balance_repository.list_company_year(
                values.company_id,
                year,
            )
            for balance in balances:
                if balance.leave_type_id != leave_type.id:
                    continue
                self._sync_balance_allocation(
                    balance=balance,
                    employee=balance.employee,
                    leave_type=leave_type,
                    year=year,
                )
        self.session.commit()
        self.session.refresh(leave_type)
        return leave_type

    def list_company_balances(self, company_id: int, year: int | None = None) -> list[LeaveBalance]:
        selected_year = year or self.leave_cycle_year(company_id)
        self.ensure_current_year_balances(company_id, selected_year)
        return self.balance_repository.list_company_year(company_id, selected_year)

    def list_employee_balances(self, company_id: int, employee_id: int, year: int | None = None) -> list[LeaveBalance]:
        selected_year = year or self.leave_cycle_year(company_id)
        self.ensure_current_year_balances(company_id, selected_year)
        return self.balance_repository.list_employee_year(company_id, employee_id, selected_year)

    def adjust_credit(self, values: LeaveCreditAdjustmentInput) -> LeaveBalance:
        leave_type = self.leave_type_repository.get_by_id(values.leave_type_id, values.company_id)
        employee = self.employee_repository.get_with_details(company_id=values.company_id, employee_id=values.employee_id)
        if leave_type is None or employee is None:
            raise ValueError("The selected employee or leave type is unavailable.")
        selected_code = (leave_type.code or "").strip().upper()
        if selected_code == "EMERGENCY":
            raise ValueError(
                "Emergency Leave has no independent credit balance. Its "
                "three-day annual allowance is automatically deducted from "
                "Vacation Leave."
            )
        if selected_code in EVENT_LEAVE_CODES:
            raise ValueError(
                f"{leave_type.name} credits are created automatically only "
                "after manager approval of a qualifying event request."
            )
        balance = self._ensure_balance(
            company_id=values.company_id,
            employee_id=values.employee_id,
            leave_type=leave_type,
            year=values.year,
        )
        prospective = Decimal(balance.remaining_days) + Decimal(values.adjustment_days)
        if prospective < Decimal("0.00"):
            raise ValueError("The adjustment would make the remaining balance negative.")
        balance.adjustment_days = Decimal(balance.adjustment_days) + Decimal(values.adjustment_days)
        self._sync_credit_table_columns(balance)
        self._enforce_cash_conversion_limit(
            balance=balance,
            leave_type=leave_type,
            created_by_user_id=values.created_by_user_id,
            source="Manual credit adjustment",
        )
        self._validate_nonnegative_balance(balance)
        self.session.add(
            LeaveCreditTransaction(
                company_id=values.company_id,
                employee_id=values.employee_id,
                leave_type_id=values.leave_type_id,
                leave_balance_id=balance.id,
                created_by_user_id=values.created_by_user_id,
                transaction_type="manual_adjustment",
                amount_days=values.adjustment_days,
                note=values.reason,
            )
        )
        self.session.commit()
        self.session.refresh(balance)
        return balance

    def set_credit_balance(
        self,
        values: LeaveCreditBalanceSetInput,
    ) -> LeaveCreditBalanceSetResult:
        """Set credits and automatically cash-convert SL/VL excess.

        The administrator enters the intended usable balance. The service
        preserves Beginning Credit and Credit, then records only the required
        difference in Adjustment. For Sick Leave and Vacation Leave, any
        portion above the fixed retained limit is
        transferred to ``converted_to_cash_days`` during the same database
        transaction. The resulting usable balance therefore never exceeds 15
        SL days or 45 VL days.
        """

        leave_type = self.leave_type_repository.get_by_id(
            values.leave_type_id,
            values.company_id,
        )
        employee = self.employee_repository.get_with_details(
            company_id=values.company_id,
            employee_id=values.employee_id,
        )

        if leave_type is None or employee is None:
            raise ValueError(
                "The selected employee or leave type is unavailable."
            )
        selected_code = (leave_type.code or "").strip().upper()
        if selected_code == "EMERGENCY":
            raise ValueError(
                "Emergency Leave has no independent credit balance. Its "
                "three-day annual allowance is automatically deducted from "
                "Vacation Leave."
            )
        if selected_code in EVENT_LEAVE_CODES:
            raise ValueError(
                f"{leave_type.name} credits are created automatically only "
                "after manager approval of a qualifying event request."
            )

        balance = self._ensure_balance(
            company_id=values.company_id,
            employee_id=values.employee_id,
            leave_type=leave_type,
            year=values.year,
        )

        previous_remaining = Decimal(
            balance.remaining_days
        ).quantize(Decimal("0.01"))
        requested_remaining = Decimal(
            values.new_remaining_days
        ).quantize(Decimal("0.01"))

        retained_limit = self._cash_conversion_limit(leave_type)
        expected_remaining = (
            min(requested_remaining, retained_limit)
            if retained_limit is not None
            else requested_remaining
        ).quantize(Decimal("0.01"))
        expected_conversion = (
            max(
                Decimal("0.00"),
                requested_remaining - retained_limit,
            ).quantize(Decimal("0.01"))
            if retained_limit is not None
            else Decimal("0.00")
        )

        if (
            expected_remaining == previous_remaining
            and expected_conversion == Decimal("0.00")
        ):
            raise ValueError(
                f"{leave_type.name} already has "
                f"{expected_remaining} remaining credits."
            )

        # Apply the requested amount relative to the current usable balance.
        # The invariant below then removes any portion above the retained
        # limit and records it in Converted to Cash.
        internal_difference = (
            requested_remaining - previous_remaining
        )
        balance.adjustment_days = (
            Decimal(balance.adjustment_days)
            + internal_difference
        )
        self._sync_credit_table_columns(balance)

        converted_to_cash = self._enforce_cash_conversion_limit(
            balance=balance,
            leave_type=leave_type,
            created_by_user_id=values.created_by_user_id,
            source="Manual leave credit update",
        )
        self._validate_nonnegative_balance(balance)
        actual_remaining = Decimal(
            balance.remaining_days
        ).quantize(Decimal("0.01"))

        self.session.add(
            LeaveCreditTransaction(
                company_id=values.company_id,
                employee_id=values.employee_id,
                leave_type_id=values.leave_type_id,
                leave_balance_id=balance.id,
                created_by_user_id=values.created_by_user_id,
                transaction_type="manual_balance_set",
                # For this transaction type, amount_days stores the exact
                # resulting usable balance after conversion.
                amount_days=actual_remaining,
                note=(
                    f"Previous balance: {previous_remaining} days | "
                    f"New balance: {actual_remaining} days | "
                    f"Requested credits: {requested_remaining} days | "
                    f"Converted to cash: {converted_to_cash} days"
                ),
            )
        )

        self.session.commit()
        self.session.refresh(balance)

        return LeaveCreditBalanceSetResult(
            balance=balance,
            previous_remaining=previous_remaining,
            requested_remaining=requested_remaining,
            new_remaining=actual_remaining,
            converted_to_cash=converted_to_cash,
        )

    def list_credit_history(self, company_id: int, employee_id: int, year: int | None = None):
        return self.transaction_repository.list_employee_year(
            company_id,
            employee_id,
            year or self.leave_cycle_year(company_id),
        )

    def list_company_credit_history(self, company_id: int, year: int | None = None):
        """Return immutable credit transactions for the company History tab."""

        return self.transaction_repository.list_company_year(
            company_id,
            year or self.leave_cycle_year(company_id),
        )

    def _admin_cc_emails(self, company_id: int, *, exclude: set[str]) -> list[str]:
        """Return active administrator emails for system notifications."""
        emails: list[str] = []
        for user in self.user_repository.list_with_details(company_id):
            email = (user.email or "").strip()
            if user.is_active and int(user.clearance) == 1 and email and email.lower() not in exclude:
                exclude.add(email.lower())
                emails.append(email)
        return emails

    def list_searchable_recipients(self, company_id: int) -> list[User]:
        """Return active company users with a registered email for type-ahead fields."""
        return [
            user
            for user in self.user_repository.list_with_details(company_id)
            if user.is_active and (user.email or "").strip()
        ]

    def list_team_members(self, *, company_id: int, leader_employee_id: int) -> list[Employee]:
        """Return direct members that a leader may file SL/EL for."""
        return self.employee_repository.list_team_members(
            company_id=company_id,
            leader_employee_id=leader_employee_id,
        )

    def list_proxy_leave_members(
        self,
        *,
        company_id: int,
        filer_employee_id: int,
    ) -> list[Employee]:
        """Return direct Leader and Manager reports eligible for proxy filing."""

        output: dict[int, Employee] = {}
        for employee in (
            *self.employee_repository.list_team_members(
                company_id=company_id,
                leader_employee_id=filer_employee_id,
            ),
            *self.employee_repository.list_direct_reports(
                company_id=company_id,
                manager_employee_id=filer_employee_id,
            ),
        ):
            if employee.employment_status == "employed":
                output[employee.id] = employee
        return sorted(output.values(), key=lambda item: (item.last_name, item.first_name))

    def is_leader(self, *, company_id: int, employee_id: int) -> bool:
        """Return whether an employee has active direct team members."""
        return bool(self.list_team_members(
            company_id=company_id,
            leader_employee_id=employee_id,
        ))

    @staticmethod
    def recipient_display_name(user: User) -> str:
        """Build the searchable name/email label used by Streamlit selectors."""
        employee = getattr(user, "employee", None)
        name = employee.full_name if employee is not None else user.username
        return f"{name} <{user.email}>"

    def _user_by_id_with_email(self, *, company_id: int, user_id: int | None) -> User | None:
        if user_id is None:
            return None
        for user in self.list_searchable_recipients(company_id):
            if user.id == int(user_id):
                return user
        return None

    def _employee_for_requester(self, *, company_id: int, user_id: int) -> Employee | None:
        for user in self.user_repository.list_with_details(company_id):
            if user.id == user_id:
                return user.employee
        return None

    def _resolve_request_filer(
        self,
        *,
        company_id: int,
        leave_owner: Employee,
        requested_by_user_id: int,
        filed_by_employee_id: int | None,
        leave_code: str,
    ) -> tuple[Employee, bool]:
        """Validate self-filing or direct Leader/Manager proxy filing."""
        filer = self._employee_for_requester(
            company_id=company_id,
            user_id=requested_by_user_id,
        )
        if filer is None or filer.employment_status != "employed":
            raise ValueError("The signed-in account is not linked to an employed employee.")

        if filed_by_employee_id is not None and filer.id != filed_by_employee_id:
            raise ValueError("The selected filer does not match the signed-in employee.")

        if filer.id == leave_owner.id and leave_owner.user_id == requested_by_user_id:
            return filer, False

        is_direct_leader = leave_owner.leader_id == filer.id
        is_direct_manager = leave_owner.manager_id == filer.id
        if not is_direct_leader and not is_direct_manager:
            raise ValueError(
                "A Leader or Manager may file leave only for an employed direct member."
            )
        return filer, True

    def _approval_route(
        self,
        *,
        leave_owner: Employee,
        filed_on_behalf: bool,
    ) -> tuple[Employee | None, Employee, Employee, str, str]:
        """Return leader, manager, current approver, stage, and pending status."""
        manager = leave_owner.manager
        manager_email = self._email_for_employee(manager)
        if manager is None or not manager_email:
            raise ValueError(
                "Assign a manager with a work email before submitting leave."
            )

        leader = leave_owner.leader
        leader_email = self._email_for_employee(leader)
        leader_is_usable = bool(
            leader is not None
            and leader.id != leave_owner.id
            and leader.user_id is not None
            and leader_email
            and (leader.user is None or leader.user.is_active)
        )

        if leader_is_usable:
            return leader, manager, leader, "leader", "pending_leader_approval"
        return leader, manager, manager, "manager", "pending_manager_approval"

    def _requested_days_for_duration(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
        duration_code: str,
    ) -> Decimal:
        working_days = self.company_working_days(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
        )
        if duration_code in {"90501", "90502"}:
            return Decimal("0.50") if working_days > 0 else Decimal("0.00")
        return working_days

    def _validate_no_overlapping_leave(
        self,
        *,
        company_id: int,
        employee_id: int,
        start_date: date,
        end_date: date,
    ) -> None:
        """Reject every active date overlap for the leave owner."""

        for existing in self.request_repository.list_overlapping(
            company_id=company_id,
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date,
        ):
            existing_end = existing.end_date
            if (
                existing.status == "partially_cancelled"
                and existing.cancellation_status == "approved"
                and existing.cancellation_effective_date is not None
            ):
                existing_end = min(
                    existing_end,
                    existing.cancellation_effective_date - timedelta(days=1),
                )
            if existing_end < existing.start_date:
                continue
            if start_date <= existing_end and end_date >= existing.start_date:
                raise ValueError(
                    "Cannot file leave. The selected dates overlap with "
                    f"{existing.public_id or 'an existing request'} "
                    f"({existing.start_date.isoformat()} to {existing_end.isoformat()})."
                )

    def _resolve_delivery_recipients(
        self,
        *,
        company_id: int,
        current_approver: Employee,
        to_user_id: int | None,
        cc_user_ids: list[int],
    ) -> tuple[str, list[str], set[int]]:
        """Resolve searchable To/CC selections while always notifying the approver."""
        approver_email = self._email_for_employee(current_approver)
        if not approver_email:
            raise ValueError("The current approver does not have a registered email.")

        selected_to = self._user_by_id_with_email(
            company_id=company_id,
            user_id=to_user_id,
        )
        to_email = (
            selected_to.email.strip()
            if selected_to is not None and selected_to.email
            else approver_email
        )
        selected_user_ids: set[int] = set()
        if selected_to is not None:
            selected_user_ids.add(selected_to.id)

        cc_emails: list[str] = []
        seen = {to_email.lower()}
        for user_id in cc_user_ids:
            user = self._user_by_id_with_email(company_id=company_id, user_id=user_id)
            if user is None or not user.email:
                continue
            email = user.email.strip()
            if email and email.lower() not in seen:
                seen.add(email.lower())
                cc_emails.append(email)
                selected_user_ids.add(user.id)

        # The hierarchy approver cannot be removed by changing the email fields.
        if approver_email.lower() not in seen:
            cc_emails.append(approver_email)
            seen.add(approver_email.lower())
        if current_approver.user_id:
            selected_user_ids.add(current_approver.user_id)

        return to_email, cc_emails, selected_user_ids

    @staticmethod
    def to_emails(request: LeaveRequest) -> list[str]:
        """Return stored To recipients with legacy fallback."""
        try:
            values = json.loads(request.to_emails_json or "[]")
        except (TypeError, json.JSONDecodeError):
            values = []
        output = [str(value).strip() for value in values if str(value).strip()]
        if not output and request.manager_email:
            output.append(request.manager_email.strip())
        return output

    def _notification_recipients(
        self,
        *,
        company_id: int,
        employee: Employee,
        manager: Employee | None,
        filed_by_employee: Employee | None = None,
        current_approver: Employee | None = None,
        selected_user_ids: set[int] | None = None,
    ) -> set[int]:
        recipients: set[int] = set(selected_user_ids or set())
        for person in (employee, manager, filed_by_employee, current_approver):
            if person is not None and person.user_id:
                recipients.add(person.user_id)
        for user in self.user_repository.list_with_details(company_id):
            if user.is_active and int(user.clearance) == 1:
                recipients.add(user.id)
        return recipients

    def _request_allocation_plan(
        self,
        *,
        company_id: int,
        employee: Employee,
        leave_type: LeaveType,
        year: int,
        requested_days: Decimal,
        as_of: date | None = None,
        virtual_primary_credit: Decimal = Decimal("0.00"),
    ) -> LeaveAllocationPlan:
        """Split requested days into paid credits and automatic LWOP."""

        requested = max(Decimal("0.00"), Decimal(requested_days))
        code = (leave_type.code or "").strip().upper()

        if code == "LWOP" or not leave_type.is_paid:
            return LeaveAllocationPlan(
                primary_balance=None,
                primary_days=Decimal("0.00"),
                fallback_balance=None,
                fallback_days=Decimal("0.00"),
                lwop_days=requested,
            )

        primary_balance = self._ensure_balance(
            company_id=company_id,
            employee_id=employee.id,
            leave_type=leave_type,
            year=year,
            employee=employee,
            as_of=as_of,
        )

        if code == "EMERGENCY":
            # The EL row is only an annual three-day usage tracker. Paid EL
            # days are reserved and posted exclusively against Vacation Leave
            # so no additional leave credits are created.
            summary = self.emergency_allowance_summary(
                company_id=company_id,
                employee_id=employee.id,
                year=year,
            )
            vacation_type = self.leave_type_repository.get_by_code(
                company_id,
                "VACATION",
            )
            vacation_balance = None
            vacation_available = Decimal("0.00")

            if vacation_type is not None and vacation_type.is_active:
                vacation_balance = self._ensure_balance(
                    company_id=company_id,
                    employee_id=employee.id,
                    leave_type=vacation_type,
                    year=year,
                    employee=employee,
                    as_of=as_of,
                )
                vacation_available = max(
                    Decimal("0.00"),
                    Decimal(vacation_balance.remaining_days),
                )

            paid_emergency = min(
                requested,
                summary.remaining_days,
                vacation_available,
            )
            return LeaveAllocationPlan(
                primary_balance=primary_balance,
                primary_days=Decimal("0.00"),
                fallback_balance=vacation_balance,
                fallback_days=paid_emergency,
                lwop_days=max(
                    Decimal("0.00"),
                    requested - paid_emergency,
                ),
            )

        primary_available = max(
            Decimal("0.00"),
            Decimal(primary_balance.remaining_days)
            + Decimal(virtual_primary_credit),
        )
        event_limit = self.event_leave_entitlement(code)
        primary_days = min(
            requested,
            primary_available,
            event_limit,
        ) if event_limit > Decimal("0.00") else min(
            requested,
            primary_available,
        )
        remaining = requested - primary_days

        return LeaveAllocationPlan(
            primary_balance=primary_balance,
            primary_days=primary_days,
            fallback_balance=None,
            fallback_days=Decimal("0.00"),
            lwop_days=max(Decimal("0.00"), remaining),
        )

    @staticmethod
    def allocation_breakdown(request: LeaveRequest) -> str:
        """Return a readable paid-credit/LWOP split for tables and email."""

        def format_days(value: Decimal) -> str:
            return f"{value:.2f}".rstrip("0").rstrip(".")

        parts: list[str] = []
        primary_days = Decimal(
            request.primary_credit_days or Decimal("0.00")
        )
        fallback_days = Decimal(
            request.fallback_credit_days or Decimal("0.00")
        )
        lwop_days = Decimal(request.lwop_days or Decimal("0.00"))

        request_code = (
            request.leave_type.code
            if request.leave_type is not None
            else ""
        ).strip().upper()

        if request_code == "EMERGENCY":
            paid_emergency = primary_days + fallback_days
            if paid_emergency > 0:
                parts.append(
                    f"{format_days(paid_emergency)} Emergency Leave "
                    "(deducted from Vacation Leave)"
                )
        else:
            if primary_days > 0:
                parts.append(
                    f"{format_days(primary_days)} {request.leave_type.name}"
                )
            if fallback_days > 0 and request.fallback_leave_type is not None:
                parts.append(
                    f"{format_days(fallback_days)} "
                    f"{request.fallback_leave_type.name}"
                )
        if lwop_days > 0:
            parts.append(f"{format_days(lwop_days)} LWOP")

        return " + ".join(parts) or "No credit allocation"

    def submit_leave_request(
        self,
        values: LeaveRequestInput,
        *,
        plan_filename: str | None = None,
        plan_bytes: bytes | None = None,
        plan_mime_type: str | None = None,
        attachment_filename: str | None = None,
        attachment_bytes: bytes | None = None,
        attachment_mime_type: str | None = None,
    ) -> LeaveSubmissionResult:
        """Record a self-filed or leader-filed request without deducting credits."""

        if plan_filename is None:
            plan_filename = attachment_filename
        if plan_bytes is None:
            plan_bytes = attachment_bytes
        if plan_mime_type is None:
            plan_mime_type = attachment_mime_type

        employee = self.employee_repository.get_with_details(
            company_id=values.company_id,
            employee_id=values.employee_id,
        )
        leave_type = self.leave_type_repository.get_by_id(
            values.leave_type_id,
            values.company_id,
        )
        if employee is None or employee.employment_status != "employed":
            raise ValueError("The employee record is unavailable for leave requests.")
        if leave_type is None or not leave_type.is_active:
            raise ValueError("The selected leave type is unavailable.")

        selected_code = (leave_type.code or "").strip().upper()
        filer, filed_on_behalf = self._resolve_request_filer(
            company_id=values.company_id,
            leave_owner=employee,
            requested_by_user_id=values.requested_by_user_id,
            filed_by_employee_id=values.filed_by_employee_id,
            leave_code=selected_code,
        )
        self._validate_event_leave_gender_eligibility(
            employee=employee,
            leave_type_or_code=leave_type,
        )
        if selected_code == "HONEYMOON" and self._honeymoon_request_exists(
            company_id=values.company_id,
            employee_id=values.employee_id,
        ):
            raise ValueError(
                "Honeymoon Leave is a one-time five-day benefit and has already been requested or used by this employee."
            )

        self._validate_no_overlapping_leave(
            company_id=values.company_id,
            employee_id=values.employee_id,
            start_date=values.start_date,
            end_date=values.end_date,
        )

        leader, manager, current_approver, approval_stage, pending_status = self._approval_route(
            leave_owner=employee,
            filed_on_behalf=filed_on_behalf,
        )
        manager_email = self._email_for_employee(manager)
        to_email, cc_emails, selected_user_ids = self._resolve_delivery_recipients(
            company_id=values.company_id,
            current_approver=current_approver,
            to_user_id=values.to_user_id,
            cc_user_ids=values.cc_user_ids,
        )
        # The leave owner always receives a copy. A proxy-filing leader also
        # receives one because they created the request and need its outcome.
        seen_delivery = {to_email.lower(), *(email.lower() for email in cc_emails)}
        for copied_person in (employee, filer if filed_on_behalf else None):
            copied_email = self._email_for_employee(copied_person)
            if copied_email and copied_email.lower() not in seen_delivery:
                cc_emails.append(copied_email)
                seen_delivery.add(copied_email.lower())

        requested_days = self._requested_days_for_duration(
            company_id=values.company_id,
            start_date=values.start_date,
            end_date=values.end_date,
            duration_code=values.duration_code,
        )
        if requested_days <= 0:
            raise ValueError(
                "The selected dates contain no company Regular Workdays. "
                "Holidays and other unselected dates are not counted as leave."
            )

        today = self._today()
        notice_days = (values.start_date - today).days
        if leave_type.minimum_notice_days > 0 and notice_days < leave_type.minimum_notice_days:
            raise ValueError(
                f"{leave_type.name} requires at least {leave_type.minimum_notice_days} days notice."
            )

        preview_event_credit = self.event_leave_preview_entitlement(
            company_id=values.company_id,
            employee_id=values.employee_id,
            leave_type=leave_type,
        )
        allocation = self._request_allocation_plan(
            company_id=values.company_id,
            employee=employee,
            leave_type=leave_type,
            year=self.leave_cycle_year(values.company_id, values.start_date),
            requested_days=requested_days,
            as_of=today,
            virtual_primary_credit=preview_event_credit,
        )

        requirement = (leave_type.handover_plan_requirement or "optional").strip().lower()
        has_plan_text = bool((values.handover_plan or "").strip())
        has_plan_file = bool(plan_bytes)
        if requirement == "required" and not has_plan_text and not has_plan_file:
            raise ValueError(
                f"{leave_type.name} requires a work handover plan or a handover plan file."
            )

        plan_storage_path = None
        if plan_bytes:
            if not plan_filename:
                raise ValueError("The handover plan filename is missing.")
            self.storage.validate(
                filename=plan_filename,
                file_bytes=plan_bytes,
                maximum_size_bytes=self.settings.leave_attachment_max_mb * 1024 * 1024,
            )
            plan_storage_path = self.storage.write(
                company_id=values.company_id,
                filename=plan_filename,
                file_bytes=plan_bytes,
            )

        # Legacy manager-only source assertion retained for compatibility:
        # status="pending_manager_approval"
        request = LeaveRequest(
            company_id=values.company_id,
            employee_id=employee.id,
            filed_by_employee_id=filer.id,
            filed_by_user_id=values.requested_by_user_id,
            filed_on_behalf=filed_on_behalf,
            leave_type_id=leave_type.id,
            fallback_leave_type=(
                allocation.fallback_balance.leave_type
                if allocation.fallback_balance is not None else None
            ),
            manager_employee_id=manager.id,
            leader_employee_id=(leader.id if leader is not None else None),
            current_approver_employee_id=current_approver.id,
            approval_stage=approval_stage,
            start_date=values.start_date,
            end_date=values.end_date,
            requested_days=requested_days,
            duration_code=values.duration_code,
            reason_code=values.reason_code,
            reason_other=values.reason_other,
            primary_credit_days=allocation.primary_days,
            fallback_credit_days=allocation.fallback_days,
            lwop_days=allocation.lwop_days,
            reason=values.reason or LEAVE_REASON_OPTIONS[values.reason_code],
            handover_plan=values.handover_plan,
            status=pending_status,
            manager_email=manager_email or to_email,
            to_emails_json=json.dumps([to_email]),
            cc_emails_json=json.dumps(cc_emails),
            email_status="pending",
            attachment_original_filename=(plan_filename if plan_bytes else None),
            attachment_storage_path=plan_storage_path,
            attachment_mime_type=(plan_mime_type if plan_bytes else None),
            attachment_size_bytes=(len(plan_bytes) if plan_bytes else None),
            reservation_posted=False,
            posted_working_days=Decimal("0.00"),
        )
        self.session.add(request)

        try:
            self.session.flush()
            request.public_id = f"LRQ_{request.id:06d}"
            recipients = self._notification_recipients(
                company_id=values.company_id,
                employee=employee,
                manager=manager,
                filed_by_employee=filer,
                current_approver=current_approver,
                selected_user_ids=selected_user_ids,
            )
            owner_name = employee.full_name
            filer_name = filer.full_name
            for user_id in recipients:
                if user_id == current_approver.user_id:
                    title = "Leave request needs approval"
                    message = (
                        f"{owner_name}'s {leave_type.name} request {request.public_id} "
                        f"is waiting for your {approval_stage} approval. "
                        f"Credit/LWP split: {self.allocation_breakdown(request)}."
                    )
                elif user_id == employee.user_id:
                    title = "Leave request filed"
                    message = (
                        f"{request.public_id} was filed "
                        f"{'on your behalf by ' + filer_name if filed_on_behalf else 'by you'} "
                        f"and sent to {current_approver.full_name}. "
                        f"Credit/LWP split: {self.allocation_breakdown(request)}."
                    )
                elif user_id == filer.user_id:
                    title = "Team leave request sent" if filed_on_behalf else "Leave request sent"
                    message = (
                        f"{request.public_id} for {owner_name} was sent to "
                        f"{current_approver.full_name}. Credit/LWP split: "
                        f"{self.allocation_breakdown(request)}."
                    )
                else:
                    title = "New leave request submitted"
                    message = (
                        f"{request.public_id} for {owner_name} was filed by {filer_name}. "
                        f"Credit/LWP split: {self.allocation_breakdown(request)}."
                    )
                self.notification_service.create(
                    company_id=values.company_id,
                    user_id=user_id,
                    event_type="leave_request_submitted",
                    title=title,
                    message=message,
                    related_entity_type="leave_request",
                    related_entity_id=request.id,
                )
            self.session.commit()
            self.session.refresh(request)
        except Exception:
            self.session.rollback()
            self.storage.delete(plan_storage_path)
            raise

        attachments: tuple[EmailAttachment, ...] = ()
        if plan_bytes and plan_filename:
            attachments = (
                EmailAttachment(
                    filename=Path(plan_filename).name,
                    content=plan_bytes,
                    mime_type=plan_mime_type or "application/octet-stream",
                ),
            )

        base_url = (self.settings.password_reset_base_url or "http://localhost:8501").rstrip("/")
        approval_url = (
            f"{base_url}/?portal=employee&page=Leave%20Management&leave_request_id={request.id}"
        )
        filed_by_line = (
            f"Filed By: {filer.full_name} "
            f"({filer.job_title or 'Leader/Manager'}, on behalf of employee)\n"
            if filed_on_behalf
            else f"Filed By: {employee.full_name}\n"
        )
        body = (
            f"Hello,\n\n"
            f"{employee.full_name} ({employee.employee_number}) has a leave request.\n\n"
            f"Request ID: {request.public_id}\n"
            f"Leave Owner: {employee.full_name}\n"
            f"{filed_by_line}"
            f"Approval Stage: {approval_stage.title()}\n"
            f"Current Approver: {current_approver.full_name}\n"
            f"Leave Type: {leave_type.name}\n"
            f"Dates: {values.start_date.isoformat()} to {values.end_date.isoformat()}\n"
            f"Duration: {duration_label(values.duration_code)}\n"
            f"Working Days: {requested_days}\n"
            f"Credit/LWP Split: {self.allocation_breakdown(request)}\n"
            f"Reason: {reason_label(values.reason_code)}\n"
            f"Reason for Leave: Others: {values.reason_other or 'Not applicable'}\n\n"
            "Work Handover Plan / Countermeasure:\n"
            f"{values.handover_plan or 'Not provided'}\n\n"
            f"Review this request in AI HR Assistant:\n{approval_url}\n\n"
            "Credits belong to and will be deducted from the Leave Owner only "
            "after final manager approval.\n\n"
            f"CC: {', '.join(cc_emails) if cc_emails else 'None'}"
        )

        try:
            reference = self.email_sender.send(
                OutboundEmail(
                    to_email=to_email,
                    cc_emails=tuple(cc_emails),
                    subject=f"{request.public_id} - {employee.full_name} - {leave_type.name}",
                    text_body=body,
                    attachments=attachments,
                )
            )
            request.email_status = "sent"
            request.email_reference = reference
            request.email_error = None
            message = (
                f"Leave request {request.public_id} was sent. Current approver: "
                f"{current_approver.full_name}. Credit owner: {employee.full_name}."
            )
            email_sent = True
        except EmailDeliveryError as error:
            request.email_status = "failed"
            request.email_error = str(error)[:500]
            message = (
                f"Leave request {request.public_id} was recorded, but email delivery failed. "
                "The current approver can still review it in Leave Management."
            )
            email_sent = False

        if allocation.lwop_days > Decimal("0.00"):
            if allocation.paid_days <= Decimal("0.00"):
                warning = (
                    f" No available {leave_type.name} credits: all "
                    f"{allocation.lwop_days} countable day(s) are Leave "
                    "Without Pay (LWP)."
                )
            else:
                warning = (
                    f" {allocation.lwop_days} countable day(s) exceed the "
                    "available credits and are Leave Without Pay (LWP)."
                )
            message += warning

        self.session.commit()
        self.session.refresh(request)
        return LeaveSubmissionResult(request=request, email_sent=email_sent, message=message)


    def is_manager(self, *, company_id: int, employee_id: int) -> bool:
        """Return whether an employee has manager reports or leader members."""
        return bool(
            self.employee_repository.list_direct_reports(
                company_id=company_id,
                manager_employee_id=employee_id,
            )
            or self.employee_repository.list_team_members(
                company_id=company_id,
                leader_employee_id=employee_id,
            )
        )

    def list_pending_manager_requests(self, *, company_id: int, manager_employee_id: int) -> list[LeaveRequest]:
        return self.request_repository.list_pending_for_manager(
            company_id=company_id,
            manager_employee_id=manager_employee_id,
        )

    def list_reviewed_manager_requests(self, *, company_id: int, manager_employee_id: int) -> list[LeaveRequest]:
        return self.request_repository.list_reviewed_for_manager(
            company_id=company_id,
            manager_employee_id=manager_employee_id,
        )

    def list_requests_filed_for_team(self, *, company_id: int, leader_employee_id: int) -> list[LeaveRequest]:
        return self.request_repository.list_filed_by_employee(
            company_id=company_id,
            filed_by_employee_id=leader_employee_id,
        )

    def _decision_notification_recipients(
        self,
        *,
        company_id: int,
        employee: Employee,
        manager: Employee | None,
        filed_by_employee: Employee | None = None,
        current_approver: Employee | None = None,
    ) -> set[int]:
        return self._notification_recipients(
            company_id=company_id,
            employee=employee,
            manager=manager,
            filed_by_employee=filed_by_employee,
            current_approver=current_approver,
        )

    def _send_stage_forward_email(self, request: LeaveRequest) -> bool:
        """Notify the manager after first-stage leader approval."""
        manager_email = self._email_for_employee(request.manager)
        if not manager_email or request.manager is None:
            return False
        cc_emails = [
            value
            for value in self.cc_emails(request)
            if value.lower() != manager_email.lower()
        ]
        leader_name = (
            request.leader_approver.full_name
            if request.leader_approver is not None
            else "The assigned leader"
        )
        try:
            self.email_sender.send(
                OutboundEmail(
                    to_email=manager_email,
                    cc_emails=tuple(cc_emails),
                    subject=f"{request.public_id} - Manager Approval Required",
                    text_body=(
                        f"Hello {request.manager.full_name},\n\n"
                        f"{leader_name} approved the first stage of "
                        f"{request.public_id} for {request.employee.full_name}.\n\n"
                        f"Leave Type: {request.leave_type.name}\n"
                        f"Dates: {request.start_date.isoformat()} to "
                        f"{request.end_date.isoformat()}\n"
                        f"Leader Comment: {request.leader_comment or 'No comment'}\n\n"
                        "The request now requires your final manager decision. "
                        "No credit has been reserved yet."
                    ),
                )
            )
            return True
        except EmailDeliveryError:
            return False

    def _send_decision_email(
        self,
        *,
        request: LeaveRequest,
        decision_label: str,
        reviewer_name: str,
    ) -> bool:
        """Email the leave owner and copied recipients after a final decision."""
        employee_email = self._email_for_employee(request.employee)
        if not employee_email:
            return False
        cc_emails = [
            value
            for value in self.cc_emails(request)
            if value.lower() != employee_email.lower()
        ]
        filed_by = request.filed_by_employee
        filed_by_line = (
            f"Filed By: {filed_by.full_name}\n"
            if filed_by is not None
            else ""
        )
        comment = (
            request.manager_comment
            or request.leader_comment
            or "No approver comment."
        )
        body = (
            f"Hello {request.employee.full_name},\n\n"
            f"Your leave request {request.public_id} was "
            f"{decision_label.lower()} by {reviewer_name}.\n\n"
            f"{filed_by_line}"
            f"Leave Type: {request.leave_type.name}\n"
            f"Dates: {request.start_date.isoformat()} to "
            f"{request.end_date.isoformat()}\n"
            f"Working Days: {request.requested_days}\n"
            f"Comment: {comment}\n\n"
        )
        body += (
            "Paid days are now reserved against the leave owner's balance."
            if decision_label == "Approved"
            else "No leave credits were reserved or deducted."
        )
        try:
            self.email_sender.send(
                OutboundEmail(
                    to_email=employee_email,
                    cc_emails=tuple(cc_emails),
                    subject=f"{request.public_id} - {decision_label}",
                    text_body=body,
                )
            )
            return True
        except EmailDeliveryError:
            return False


    @staticmethod
    def cancellation_label(request: LeaveRequest) -> str:
        """Return a readable cancellation state without hiding leave status."""

        labels = {
            "none": "—",
            "requested": "Cancellation Requested",
            "approved": (
                "Partially Cancelled"
                if request.status == "partially_cancelled"
                else "Cancelled"
            ),
            "rejected": "Cancellation Rejected",
            "cancelled": "Cancelled Before Approval",
        }
        return labels.get(
            (request.cancellation_status or "none").strip().lower(),
            (request.cancellation_status or "none").replace("_", " ").title(),
        )

    @staticmethod
    def _next_business_day(selected_date: date) -> date:
        """Return the first Monday-to-Friday date after ``selected_date``."""

        from datetime import timedelta

        candidate = selected_date + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate

    def _cancellation_requester(
        self,
        *,
        request: LeaveRequest,
        requested_by_user_id: int,
        requested_by_employee_id: int,
    ) -> Employee:
        """Validate that the owner or original proxy filer requests cancellation."""

        requester = self._employee_for_requester(
            company_id=request.company_id,
            user_id=requested_by_user_id,
        )
        if requester is None or requester.id != requested_by_employee_id:
            raise ValueError("The signed-in account does not match the cancellation requester.")

        allowed_employee_ids = {
            int(request.employee_id),
            int(request.filed_by_employee_id or request.employee_id),
        }
        if requester.id not in allowed_employee_ids:
            raise ValueError(
                "Only the leave owner or the employee who filed the request may cancel it."
            )
        return requester

    def _cancellation_notification_recipients(
        self,
        request: LeaveRequest,
        *,
        include_manager: bool = True,
    ) -> set[int]:
        """Return owner, filer, hierarchy, and administrator recipients."""

        recipients = self._notification_recipients(
            company_id=request.company_id,
            employee=request.employee,
            manager=(request.manager if include_manager else None),
            filed_by_employee=request.filed_by_employee,
            current_approver=request.current_approver,
        )
        for person in (
            request.leader_approver,
            request.cancellation_requested_by_employee,
        ):
            if person is not None and person.user_id:
                recipients.add(person.user_id)

        stored_emails = {
            email.strip().lower()
            for email in [*self.to_emails(request), *self.cc_emails(request)]
            if email and email.strip()
        }
        for user in self.list_searchable_recipients(request.company_id):
            if (user.email or "").strip().lower() in stored_emails:
                recipients.add(user.id)
        return recipients

    def _notify_cancellation(
        self,
        *,
        request: LeaveRequest,
        event_type: str,
        title: str,
        message: str,
        priority_user_id: int | None = None,
    ) -> None:
        """Create cancellation notifications with one approver-specific message."""

        for user_id in self._cancellation_notification_recipients(request):
            notification_title = title
            notification_message = message
            if priority_user_id and user_id == priority_user_id:
                notification_title = "Leave cancellation needs approval"
                notification_message = (
                    f"{request.public_id} for {request.employee.full_name} "
                    "requires your cancellation decision."
                )
            self.notification_service.create(
                company_id=request.company_id,
                user_id=user_id,
                event_type=event_type,
                title=notification_title,
                message=notification_message,
                related_entity_type="leave_request",
                related_entity_id=request.id,
            )

    def request_leave_cancellation(
        self,
        values: LeaveCancellationRequestInput,
    ) -> LeaveRequest:
        """Cancel a pending request or open a manager-reviewed cancellation."""

        request = self.request_repository.get_with_details(
            values.company_id,
            values.request_id,
        )
        if request is None:
            raise ValueError("The selected leave request is unavailable.")

        requester = self._cancellation_requester(
            request=request,
            requested_by_user_id=values.requested_by_user_id,
            requested_by_employee_id=values.requested_by_employee_id,
        )
        if request.status in {"rejected", "cancelled", "partially_cancelled", "completed"}:
            raise ValueError(
                "This leave request can no longer be cancelled through the normal workflow."
            )
        if request.cancellation_status == "requested":
            raise ValueError("A cancellation request is already waiting for review.")

        now = datetime.now(timezone.utc)
        request.cancellation_reason = values.reason
        request.cancellation_requested_at = now
        request.cancellation_requested_by_user_id = values.requested_by_user_id
        request.cancellation_requested_by_employee_id = requester.id
        request.cancellation_reviewed_at = None
        request.cancellation_reviewed_by_user_id = None
        request.cancellation_comment = None

        if request.status in {"pending_leader_approval", "pending_manager_approval"}:
            request.status = "cancelled"
            request.cancellation_status = "cancelled"
            request.cancellation_effective_date = request.start_date
            request.approval_stage = "completed"
            request.current_approver_employee_id = None
            request.reservation_posted = False
            self._notify_cancellation(
                request=request,
                event_type="leave_request_cancelled_before_approval",
                title="Leave request cancelled",
                message=(
                    f"{request.public_id} was cancelled by {requester.full_name} "
                    "before final approval. No leave credits were deducted."
                ),
            )
            self.session.commit()
            self.session.refresh(request)
            return request

        if request.status not in {"scheduled", "approved", "in_progress"}:
            raise ValueError("Only an active approved leave may request cancellation.")

        # Post elapsed dates first. This guarantees an ongoing leave keeps
        # already-consumed days and only future unused dates can be restored.
        self.reconcile_approved_leave(
            company_id=request.company_id,
            through_date=self._today(),
        )
        request = self.request_repository.get_with_details(
            values.company_id,
            values.request_id,
        )
        if request is None or request.status == "completed":
            raise ValueError(
                "Completed leave requires an HR credit correction instead of cancellation."
            )
        if request.manager is None or request.manager.user_id is None:
            raise ValueError("An assigned manager is required to review this cancellation.")

        today = self._today()
        effective_date = (
            request.start_date
            if today < request.start_date
            else self._next_business_day(today)
        )
        if effective_date > request.end_date:
            raise ValueError(
                "No future unused leave dates remain. Ask HR to review a manual correction."
            )

        request.cancellation_status = "requested"
        request.cancellation_effective_date = effective_date
        self._notify_cancellation(
            request=request,
            event_type="leave_cancellation_requested",
            title="Leave cancellation requested",
            message=(
                f"{requester.full_name} requested cancellation of {request.public_id} "
                f"effective {effective_date.isoformat()}."
            ),
            priority_user_id=request.manager.user_id,
        )
        self.session.commit()
        self.session.refresh(request)
        return request

    def _release_cancelled_credit(
        self,
        *,
        request: LeaveRequest,
        leave_type: LeaveType | None,
        restore_days: Decimal,
        reviewer_user_id: int,
        label: str,
    ) -> None:
        """Release unused approved reservations and record an audit entry."""

        if leave_type is None or restore_days <= Decimal("0.00"):
            return
        balance = self._ensure_balance(
            company_id=request.company_id,
            employee_id=request.employee_id,
            leave_type=leave_type,
            year=self.leave_cycle_year(request.company_id, request.start_date),
            employee=request.employee,
            as_of=self._today(),
        )
        balance.reserved_days = max(
            Decimal("0.00"),
            Decimal(balance.reserved_days) - restore_days,
        )
        self._validate_nonnegative_balance(balance)
        self.session.add(
            LeaveCreditTransaction(
                company_id=request.company_id,
                employee_id=request.employee_id,
                leave_type_id=leave_type.id,
                leave_balance_id=balance.id,
                leave_request_id=request.id,
                created_by_user_id=reviewer_user_id,
                transaction_type="leave_cancellation_credit_restored",
                amount_days=restore_days,
                note=(
                    f"Released {label} unused reservation after approved "
                    f"cancellation of {request.public_id}."
                ),
            )
        )

    def _reverse_full_event_grant(
        self,
        *,
        request: LeaveRequest,
        reviewer_user_id: int,
    ) -> Decimal:
        """Reverse an unused event grant when the whole event leave is cancelled."""

        code = (request.leave_type.code or "").strip().upper()
        entitlement = self.event_leave_entitlement(code)
        if entitlement <= Decimal("0.00"):
            return Decimal("0.00")
        reversal_count = self.session.scalar(
            select(func.count(LeaveCreditTransaction.id)).where(
                LeaveCreditTransaction.leave_request_id == request.id,
                LeaveCreditTransaction.transaction_type
                == "event_leave_entitlement_reversal",
            )
        )
        if reversal_count:
            return Decimal("0.00")
        balance = self._ensure_balance(
            company_id=request.company_id,
            employee_id=request.employee_id,
            leave_type=request.leave_type,
            year=self.leave_cycle_year(request.company_id, request.start_date),
            employee=request.employee,
            as_of=self._today(),
        )
        balance.allocated_days = max(
            Decimal("0.00"),
            Decimal(balance.allocated_days) - entitlement,
        )
        self._sync_credit_table_columns(balance)
        self._validate_nonnegative_balance(balance)
        self.session.add(
            LeaveCreditTransaction(
                company_id=request.company_id,
                employee_id=request.employee_id,
                leave_type_id=request.leave_type_id,
                leave_balance_id=balance.id,
                leave_request_id=request.id,
                created_by_user_id=reviewer_user_id,
                transaction_type="event_leave_entitlement_reversal",
                amount_days=-entitlement,
                note=(
                    f"Reversed the unused qualifying-event grant after full "
                    f"cancellation of {request.public_id}."
                ),
            )
        )
        return entitlement

    def decide_leave_cancellation(
        self,
        values: LeaveCancellationDecisionInput,
    ) -> LeaveRequest:
        """Approve or reject cancellation of a final-approved leave."""

        request = self.request_repository.get_with_details(
            values.company_id,
            values.request_id,
        )
        if request is None:
            raise ValueError("The selected leave request is unavailable.")
        if request.cancellation_status != "requested":
            raise ValueError("This leave request has no cancellation awaiting review.")

        reviewer_user = next(
            (
                user
                for user in self.user_repository.list_with_details(values.company_id)
                if user.id == values.reviewer_user_id and user.is_active
            ),
            None,
        )
        if reviewer_user is None:
            raise ValueError("The signed-in cancellation reviewer is unavailable.")
        reviewer_employee = reviewer_user.employee
        is_assigned_manager = (
            reviewer_employee is not None
            and reviewer_employee.id == request.manager_employee_id
            and (
                values.reviewer_employee_id is None
                or reviewer_employee.id == values.reviewer_employee_id
            )
        )
        is_hr_admin = int(reviewer_user.clearance) == 1
        if not is_assigned_manager and not is_hr_admin:
            raise ValueError(
                "Only the assigned manager or an active HR administrator may review cancellation."
            )

        # Ensure any elapsed approved dates are already posted before deciding.
        self.reconcile_approved_leave(
            company_id=request.company_id,
            through_date=self._today(),
        )
        request = self.request_repository.get_with_details(
            values.company_id,
            values.request_id,
        )
        if request is None:
            raise ValueError("The selected leave request is unavailable.")

        now = datetime.now(timezone.utc)
        request.cancellation_reviewed_at = now
        request.cancellation_reviewed_by_user_id = values.reviewer_user_id
        request.cancellation_comment = values.comment

        reviewer_name = (
            reviewer_employee.full_name
            if reviewer_employee is not None
            else reviewer_user.username
        )
        if values.decision == "reject":
            request.cancellation_status = "rejected"
            self._notify_cancellation(
                request=request,
                event_type="leave_cancellation_rejected",
                title="Leave cancellation rejected",
                message=(
                    f"{reviewer_name} rejected cancellation of {request.public_id}. "
                    "The approved leave remains active."
                ),
            )
            self.session.commit()
            self.session.refresh(request)
            return request

        posted_days = max(
            Decimal("0.00"),
            Decimal(request.posted_working_days or Decimal("0.00")),
        )
        if posted_days >= Decimal(request.requested_days or Decimal("0.00")):
            raise ValueError(
                "All approved leave dates are already completed. Ask HR to use a manual credit correction."
            )
        primary_total = Decimal(request.primary_credit_days or Decimal("0.00"))
        fallback_total = Decimal(request.fallback_credit_days or Decimal("0.00"))
        lwop_total = Decimal(request.lwop_days or Decimal("0.00"))

        posted_primary = min(posted_days, primary_total)
        posted_fallback = min(
            max(Decimal("0.00"), posted_days - primary_total),
            fallback_total,
        )
        posted_lwop = min(
            max(Decimal("0.00"), posted_days - primary_total - fallback_total),
            lwop_total,
        )
        restore_primary = max(Decimal("0.00"), primary_total - posted_primary)
        restore_fallback = max(Decimal("0.00"), fallback_total - posted_fallback)
        remove_lwop = max(Decimal("0.00"), lwop_total - posted_lwop)

        self._release_cancelled_credit(
            request=request,
            leave_type=request.leave_type,
            restore_days=restore_primary,
            reviewer_user_id=values.reviewer_user_id,
            label="primary",
        )
        self._release_cancelled_credit(
            request=request,
            leave_type=request.fallback_leave_type,
            restore_days=restore_fallback,
            reviewer_user_id=values.reviewer_user_id,
            label="fallback",
        )
        if posted_days <= Decimal("0.00"):
            self._reverse_full_event_grant(
                request=request,
                reviewer_user_id=values.reviewer_user_id,
            )

        request.cancellation_restored_primary_days = restore_primary
        request.cancellation_restored_fallback_days = restore_fallback
        request.cancellation_removed_lwop_days = remove_lwop
        request.cancellation_status = "approved"
        request.reservation_posted = False
        request.status = (
            "cancelled"
            if posted_days <= Decimal("0.00")
            else "partially_cancelled"
        )
        request.completed_at = now

        self._notify_cancellation(
            request=request,
            event_type="leave_cancellation_approved",
            title="Leave cancellation approved",
            message=(
                f"{reviewer_name} approved cancellation of {request.public_id}. "
                f"Restored {restore_primary + restore_fallback} paid day(s); "
                f"{posted_days} elapsed day(s) remain used."
            ),
        )
        self.session.commit()
        self.session.refresh(request)
        return request

    def decide_leave_request(self, values: LeaveDecisionInput) -> LeaveRequest:
        """Record a leader-stage or final manager decision."""
        request = self.request_repository.get_with_details(values.company_id, values.request_id)
        if request is None:
            raise ValueError("The selected leave request is unavailable.")

        current_approver_id = request.current_approver_employee_id or request.manager_employee_id
        current_approver = request.current_approver or request.manager
        if current_approver_id != values.manager_employee_id:
            raise ValueError("Only the current assigned approver can review this request.")
        if current_approver is None or current_approver.user_id != values.manager_user_id:
            raise ValueError("The signed-in account is not linked to the current approver.")
        if request.status not in {"pending_leader_approval", "pending_manager_approval"}:
            raise ValueError("This leave request is not awaiting a decision.")

        now = datetime.now(timezone.utc)
        is_leader_stage = request.status == "pending_leader_approval"

        if is_leader_stage:
            request.leader_reviewed_at = now
            request.leader_reviewed_by_user_id = values.manager_user_id
            request.leader_comment = values.manager_comment
            if values.decision == "reject":
                request.status = "rejected"
                request.approval_stage = "completed"
                request.current_approver_employee_id = None
                decision_label = "Rejected"
            else:
                if request.manager is None or request.manager.user_id is None:
                    raise ValueError("A manager must be assigned before leader approval can be forwarded.")
                request.status = "pending_manager_approval"
                request.approval_stage = "manager"
                request.current_approver_employee_id = request.manager_employee_id
                self.notification_service.create(
                    company_id=request.company_id,
                    user_id=request.manager.user_id,
                    event_type="leave_request_forwarded_to_manager",
                    title="Leave request needs final approval",
                    message=(
                        f"{request.public_id} for {request.employee.full_name} was approved by "
                        f"{current_approver.full_name} and now requires your decision."
                    ),
                    related_entity_type="leave_request",
                    related_entity_id=request.id,
                )
                copied_user_ids = {
                    person.user_id
                    for person in (
                        request.employee,
                        request.filed_by_employee,
                        request.leader_approver,
                    )
                    if person is not None
                    and person.user_id
                    and person.user_id != request.manager.user_id
                }
                for copied_user_id in copied_user_ids:
                    self.notification_service.create(
                        company_id=request.company_id,
                        user_id=copied_user_id,
                        event_type="leave_request_forwarded_to_manager",
                        title="Leave request forwarded",
                        message=f"{request.public_id} is now waiting for manager approval.",
                        related_entity_type="leave_request",
                        related_entity_id=request.id,
                    )
                self.session.commit()
                self.session.refresh(request)
                self._send_stage_forward_email(request)
                return request
        else:
            if values.decision == "approve":
                self._validate_event_leave_gender_eligibility(
                    employee=request.employee,
                    leave_type_or_code=request.leave_type,
                )
            request.reviewed_at = now
            request.reviewed_by_user_id = values.manager_user_id
            request.manager_comment = values.manager_comment

            if values.decision == "reject":
                request.status = "rejected"
                request.reservation_posted = False
                request.approval_stage = "completed"
                request.current_approver_employee_id = None
                decision_label = "Rejected"
            else:
                self._grant_event_leave_entitlement(
                    request=request,
                    created_by_user_id=values.manager_user_id,
                )
                requested_days = self._requested_days_for_duration(
                    company_id=request.company_id,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    duration_code=request.duration_code or "90503",
                )
                if requested_days <= 0:
                    raise ValueError(
                        "This request now contains no company Regular Workdays. "
                        "Review the saved Attendance Schedule & OT Rules calendar."
                    )
                request.requested_days = requested_days
                allocation = self._request_allocation_plan(
                    company_id=request.company_id,
                    employee=request.employee,
                    leave_type=request.leave_type,
                    year=self.leave_cycle_year(request.company_id, request.start_date),
                    requested_days=requested_days,
                    as_of=self._today(),
                )
                request.fallback_leave_type = (
                    allocation.fallback_balance.leave_type
                    if allocation.fallback_balance is not None else None
                )
                request.primary_credit_days = allocation.primary_days
                request.fallback_credit_days = allocation.fallback_days
                request.lwop_days = allocation.lwop_days
                request.reservation_posted = allocation.paid_days > 0

                for reserved_balance, reserved_days in (
                    (allocation.primary_balance, allocation.primary_days),
                    (allocation.fallback_balance, allocation.fallback_days),
                ):
                    if reserved_balance is None or reserved_days <= 0:
                        continue
                    reserved_balance.reserved_days = Decimal(reserved_balance.reserved_days) + reserved_days
                    self._validate_nonnegative_balance(reserved_balance)
                    self.session.add(
                        LeaveCreditTransaction(
                            company_id=request.company_id,
                            employee_id=request.employee_id,
                            leave_type_id=reserved_balance.leave_type_id,
                            leave_balance_id=reserved_balance.id,
                            leave_request_id=request.id,
                            created_by_user_id=values.manager_user_id,
                            transaction_type="approval_reserved",
                            amount_days=-reserved_days,
                            note=(
                                f"Reserved after final manager approval for {request.public_id}; "
                                f"filed by {request.filed_by_employee.full_name if request.filed_by_employee else request.employee.full_name}; "
                                f"automatic split includes {allocation.lwop_days} LWOP day(s)."
                            ),
                        )
                    )
                request.approved_at = now
                request.status = "scheduled" if request.start_date > self._today() else "approved"
                request.approval_stage = "completed"
                request.current_approver_employee_id = None
                decision_label = "Approved"

        recipients = self._decision_notification_recipients(
            company_id=request.company_id,
            employee=request.employee,
            manager=request.manager,
            filed_by_employee=request.filed_by_employee,
            current_approver=current_approver,
        )
        for user_id in recipients:
            if user_id == request.employee.user_id:
                title = f"Leave request {decision_label.lower()}"
                message = (
                    f"{request.public_id} was {decision_label.lower()} by {current_approver.full_name}. "
                    f"Final split: {self.allocation_breakdown(request)}."
                )
            elif request.filed_by_employee is not None and user_id == request.filed_by_employee.user_id:
                title = "Team leave decision recorded"
                message = f"{request.public_id} for {request.employee.full_name} was {decision_label.lower()}."
            else:
                title = "Leave request reviewed"
                message = f"{current_approver.full_name} {decision_label.lower()} {request.public_id}."
            self.notification_service.create(
                company_id=request.company_id,
                user_id=user_id,
                event_type=("leave_request_approved" if values.decision == "approve" else "leave_request_rejected"),
                title=title,
                message=message,
                related_entity_type="leave_request",
                related_entity_id=request.id,
            )

        self.session.commit()
        self.session.refresh(request)
        if values.decision == "approve" and not is_leader_stage:
            self.reconcile_approved_leave(company_id=request.company_id, through_date=self._today())
            request = self.request_repository.get_with_details(request.company_id, request.id)
        self._send_decision_email(
            request=request,
            decision_label=decision_label,
            reviewer_name=current_approver.full_name,
        )
        return request


    def reconcile_approved_leave(
        self,
        *,
        company_id: int,
        through_date: date | None = None,
    ) -> int:
        """Move elapsed approved days from reserved to used exactly once."""

        selected_date = through_date or self._today()
        requests = self.request_repository.list_reconcilable(
            company_id=company_id,
            through_date=selected_date,
        )
        changed = 0

        for request in requests:
            elapsed_end = min(
                selected_date,
                request.end_date,
            )
            elapsed_days = self._requested_days_for_duration(
                company_id=request.company_id,
                start_date=request.start_date,
                end_date=elapsed_end,
                duration_code=request.duration_code or "90503",
            )
            already_posted = Decimal(
                request.posted_working_days
                or Decimal("0.00")
            )
            to_post = elapsed_days - already_posted

            if to_post > 0:
                primary_total = Decimal(
                    request.primary_credit_days or Decimal("0.00")
                )
                fallback_total = Decimal(
                    request.fallback_credit_days or Decimal("0.00")
                )

                old_primary = min(already_posted, primary_total)
                new_primary = min(elapsed_days, primary_total)
                primary_to_post = max(
                    Decimal("0.00"),
                    new_primary - old_primary,
                )

                old_fallback = min(
                    max(
                        Decimal("0.00"),
                        already_posted - primary_total,
                    ),
                    fallback_total,
                )
                new_fallback = min(
                    max(
                        Decimal("0.00"),
                        elapsed_days - primary_total,
                    ),
                    fallback_total,
                )
                fallback_to_post = max(
                    Decimal("0.00"),
                    new_fallback - old_fallback,
                )

                posting_items = (
                    (
                        request.leave_type,
                        primary_to_post,
                    ),
                    (
                        request.fallback_leave_type,
                        fallback_to_post,
                    ),
                )
                for posting_type, posting_days in posting_items:
                    if posting_type is None or posting_days <= 0:
                        continue

                    balance = self._ensure_balance(
                        company_id=request.company_id,
                        employee_id=request.employee_id,
                        leave_type=posting_type,
                        year=self.leave_cycle_year(request.company_id, request.start_date),
                        employee=request.employee,
                        as_of=selected_date,
                    )
                    balance.reserved_days = max(
                        Decimal("0.00"),
                        Decimal(balance.reserved_days) - posting_days,
                    )
                    balance.used_days = (
                        Decimal(balance.used_days) + posting_days
                    )
                    self.session.add(
                        LeaveCreditTransaction(
                            company_id=request.company_id,
                            employee_id=request.employee_id,
                            leave_type_id=posting_type.id,
                            leave_balance_id=balance.id,
                            leave_request_id=request.id,
                            transaction_type="leave_days_used",
                            amount_days=-posting_days,
                            note=(
                                f"Posted elapsed approved leave through "
                                f"{elapsed_end.isoformat()} for "
                                f"{request.public_id}"
                            ),
                        )
                    )

                # Total lifecycle progress includes automatic LWOP days even
                # though those days do not touch a credit balance.
                request.posted_working_days = elapsed_days
                changed += 1

            if (
                selected_date >= request.end_date
                and Decimal(request.posted_working_days)
                >= Decimal(request.requested_days)
            ):
                request.status = "completed"
                request.completed_at = datetime.now(
                    timezone.utc
                )
            elif selected_date >= request.start_date:
                request.status = "in_progress"
            else:
                request.status = "scheduled"

        if changed:
            self.session.commit()

        return changed
    def list_company_requests(
        self,
        company_id: int,
        year: int | None = None,
    ):
        """Return monitored requests, optionally filtered by leave year."""

        if year is None:
            return self.request_repository.list_company(company_id)
        return self.request_repository.list_company(
            company_id,
            period_start=self.leave_cycle_start(company_id, int(year)),
            period_end=self.leave_cycle_end(company_id, int(year)),
        )

    def list_employee_requests(self, company_id: int, employee_id: int):
        return self.request_repository.list_employee(company_id, employee_id)

    def get_request(self, company_id: int, request_id: int):
        return self.request_repository.get_with_details(company_id, request_id)

    @staticmethod
    def cc_emails(request: LeaveRequest) -> list[str]:
        try:
            values = json.loads(request.cc_emails_json or "[]")
            return [str(value) for value in values if str(value).strip()]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def read_plan_file(self, request: LeaveRequest) -> bytes:
        """Read an optional work handover-plan file."""

        if not request.attachment_storage_path:
            raise FileNotFoundError(
                "This leave request has no handover plan file."
            )
        return self.storage.read(
            request.attachment_storage_path
        )

    def read_attachment(self, request: LeaveRequest) -> bytes:
        """Backward-compatible alias for older admin pages."""

        return self.read_plan_file(request)

    def overview(
        self,
        company_id: int,
        year: int | None = None,
    ) -> dict[str, int]:
        """Return summary metrics for the selected Leave Year."""

        today = self._today()
        current_cycle_year = self.leave_cycle_year(company_id, today)
        selected_year = int(year or current_cycle_year)
        cycle_start = self.leave_cycle_start(company_id, selected_year)
        cycle_end = self.leave_cycle_end(company_id, selected_year)
        requests = self.list_company_requests(
            company_id,
            selected_year,
        )
        submitted_in_year = [
            request
            for request in requests
            if (
                request.submitted_at
                and cycle_start <= request.submitted_at.date() <= cycle_end
            )
        ]
        current_month = [
            request
            for request in requests
            if (
                selected_year == current_cycle_year
                and request.submitted_at
                and request.submitted_at.year == today.year
                and request.submitted_at.month == today.month
            )
        ]
        on_leave_today = [
            request
            for request in requests
            if (
                selected_year == current_cycle_year
                and request.status in {
                    "scheduled",
                    "approved",
                    "in_progress",
                    "completed",
                }
                and request.start_date <= today <= request.end_date
            )
        ]
        balances = self.list_company_balances(
            company_id,
            selected_year,
        )
        low_employee_ids = {
            balance.employee_id
            for balance in balances
            if (
                balance.leave_type.annual_credits > 0
                and Decimal(balance.remaining_days)
                <= Decimal("2.00")
            )
        }
        employees_with_leave = {
            request.employee_id
            for request in requests
        }

        # Existing keys remain for compatibility with previous callers.
        return {
            "total_requests": len(requests),
            "requests_this_month": len(current_month),
            "requests_submitted_in_year": len(
                submitted_in_year
            ),
            "employees_on_leave_today": len(
                {
                    request.employee_id
                    for request in on_leave_today
                }
            ),
            "employees_with_leave": len(
                employees_with_leave
            ),
            "employees_with_low_credits": len(
                low_employee_ids
            ),
        }
