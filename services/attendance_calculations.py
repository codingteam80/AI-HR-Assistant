"""Pure attendance hour and schedule calculations."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


TWO_PLACES = Decimal("0.01")
QUARTER_HOUR_MINUTES = 15


def calculate_work_rate(
    total_hours: Decimal | int | float,
    total_workdays: int,
    regular_paid_hours_per_day: Decimal | int | float,
) -> Decimal:
    """Return the monthly Work Rate percentage without a 100% cap.

    Work Rate = 100 * Total Hours / (Regular Workdays * Paid Hours per Day).
    Total Hours is supplied by DTR computation, so unpaid lunch and leave-hour
    credits are not added here. Overtime remains part of Total Hours and may
    therefore raise the result above 100%.
    """

    hours = max(Decimal("0.00"), Decimal(str(total_hours)))
    workdays = max(0, int(total_workdays))
    daily_target = max(
        Decimal("0.00"),
        Decimal(str(regular_paid_hours_per_day)),
    )
    denominator = Decimal(workdays) * daily_target
    if denominator <= Decimal("0.00"):
        return Decimal("0.00")
    return (
        Decimal("100") * hours / denominator
    ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_time_in_up(value: datetime) -> datetime:
    """Round an actual login up to the next quarter hour."""

    normalized = value.replace(second=0, microsecond=0)
    remainder = normalized.minute % QUARTER_HOUR_MINUTES
    if remainder == 0 and value.second == 0 and value.microsecond == 0:
        return normalized
    minutes = QUARTER_HOUR_MINUTES - remainder if remainder else QUARTER_HOUR_MINUTES
    return normalized + timedelta(minutes=minutes)


def round_time_out_down(value: datetime) -> datetime:
    """Round an actual logout down to the completed quarter hour."""

    normalized = value.replace(second=0, microsecond=0)
    return normalized - timedelta(minutes=normalized.minute % QUARTER_HOUR_MINUTES)


def calculate_session_hours(
    sessions: list[object],
    *,
    scheduled_workday: bool,
    regular_hours: Decimal | int | float,
    lunch_break_minutes: int,
    leave_hours: Decimal | int | float = Decimal("0.00"),
) -> tuple[Decimal, Decimal, Decimal]:
    """Return paid, OT, and undertime from non-overlapping rounded sessions.

    A configured lunch is removed once only when recorded session duration
    reaches the regular paid target plus the lunch allowance. Split sessions
    that already exclude lunch therefore are not charged twice.
    """

    elapsed_minutes = Decimal("0")
    for session in sessions:
        start = getattr(session, "rounded_time_in", None)
        end = getattr(session, "rounded_time_out", None)
        if start is None or end is None:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if end > start:
            elapsed_minutes += Decimal(str((end - start).total_seconds())) / Decimal("60")

    target_minutes = Decimal(str(regular_hours)) * Decimal("60")
    lunch_minutes = Decimal(max(0, lunch_break_minutes))
    if elapsed_minutes >= target_minutes + lunch_minutes and lunch_minutes > 0:
        elapsed_minutes -= lunch_minutes

    paid = max(Decimal("0"), elapsed_minutes / Decimal("60")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    target = Decimal(str(regular_hours))
    approved_leave = max(Decimal("0"), Decimal(str(leave_hours)))
    required_work = max(Decimal("0"), target - approved_leave)
    overtime = (
        max(Decimal("0"), paid - required_work)
        if scheduled_workday
        else paid
    ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    # Leave lowers the regular work requirement but never creates OT.
    regular_worked = min(paid, required_work)
    undertime = (
        max(Decimal("0"), required_work - regular_worked)
        if scheduled_workday
        else Decimal("0")
    ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return paid, overtime, undertime


def calculate_attendance_hours(
    time_in: datetime | None,
    time_out: datetime | None,
    *,
    scheduled_workday: bool,
    regular_hours: Decimal | int | float,
    lunch_break_minutes: int,
) -> tuple[Decimal, Decimal]:
    """Return paid total hours and OT without producing negative values.

    The regular paid target is earned first. Any following time up to the
    configured lunch duration remains unpaid, so an 8-hour paid day with a
    60-minute lunch requires a 9-hour attendance span before OT begins. On a
    rest day every paid hour is OT.
    """

    if time_in is None or time_out is None:
        return Decimal("0.00"), Decimal("0.00")

    # SQLite may return timezone-aware columns as naive UTC values. Normalize
    # both operands so mixed drivers cannot break the calculation.
    normalized_in = (
        time_in.replace(tzinfo=timezone.utc) if time_in.tzinfo is None else time_in
    )
    normalized_out = (
        time_out.replace(tzinfo=timezone.utc) if time_out.tzinfo is None else time_out
    )
    if normalized_out <= normalized_in:
        return Decimal("0.00"), Decimal("0.00")

    elapsed = Decimal(
        str((normalized_out - normalized_in).total_seconds())
    ) / Decimal("3600")
    target = Decimal(str(regular_hours))
    lunch = Decimal(max(0, lunch_break_minutes)) / Decimal("60")
    # Example for an 8-hour target plus a 1-hour unpaid lunch:
    # 08:00 elapsed -> 8.00 paid, 0.00 OT
    # 08:30 elapsed -> 8.00 paid, 0.00 OT (inside unpaid break allowance)
    # 09:00 elapsed -> 8.00 paid, 0.00 OT
    # 10:00 elapsed -> 9.00 paid, 1.00 OT
    paid = min(elapsed, target) + max(
        Decimal("0"),
        elapsed - target - lunch,
    )
    paid = max(Decimal("0"), paid).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    overtime = (
        max(Decimal("0"), paid - target)
        if scheduled_workday
        else paid
    ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return paid, overtime


def company_workday(company: object, weekday: int) -> bool:
    """Return whether Monday=0 through Sunday=6 is a regular workday."""

    field = (
        "work_monday",
        "work_tuesday",
        "work_wednesday",
        "work_thursday",
        "work_friday",
        "work_saturday",
        "work_sunday",
    )[weekday]
    return bool(getattr(company, field))
