"""Validated contracts for attendance, schedule, status, and corrections."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


AttendanceStatus = Literal["WFO", "WFH", "VL", "SL", "EL"]
WorkLocation = Literal["WFO", "WFH"]


class AttendanceStatusInput(BaseModel):
    """Employee-owned daily work-location or provisional leave status."""

    company_id: int
    employee_id: int
    user_id: int
    attendance_date: date
    work_status: AttendanceStatus


class AttendancePunchInput(AttendanceStatusInput):
    """Employee-owned Login/Logout attendance action."""

    occurred_at: datetime | None = None


class AttendanceSessionInput(BaseModel):
    """One editable WFO/WFH session using exact local timestamps."""

    work_status: WorkLocation
    time_in: datetime
    time_out: datetime | None = None

    @model_validator(mode="after")
    def validate_time_order(self):
        if self.time_out is not None and self.time_out <= self.time_in:
            raise ValueError("Session Time Out must be later than Time In.")
        return self


class AttendanceSelfEditInput(AttendanceStatusInput):
    """Employee-owned edit of a selected daily attendance record."""

    time_in: datetime | None = None
    time_out: datetime | None = None
    sessions: list[AttendanceSessionInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_time_order(self):
        if self.time_out is not None and self.time_in is None:
            raise ValueError("Time In is required when Time Out is provided.")
        if (
            self.time_in is not None
            and self.time_out is not None
            and self.time_out <= self.time_in
        ):
            raise ValueError("Time Out must be later than Time In.")
        if self.sessions:
            ordered = sorted(self.sessions, key=lambda item: item.time_in)
            for previous, current in zip(ordered, ordered[1:]):
                if previous.time_out is None:
                    raise ValueError("Only the final attendance session may remain open.")
                if current.time_in < previous.time_out:
                    raise ValueError("Attendance sessions cannot overlap.")
        return self


class AttendanceCorrectionInput(BaseModel):
    """Administrator correction for one company-owned daily record."""

    company_id: int
    employee_id: int
    attendance_date: date
    corrected_by_user_id: int
    time_in: datetime | None = None
    time_out: datetime | None = None
    work_status: AttendanceStatus | None = None
    sessions: list[AttendanceSessionInput] = Field(default_factory=list)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @model_validator(mode="after")
    def validate_time_order(self):
        if (
            self.time_in is not None
            and self.time_out is not None
            and self.time_out <= self.time_in
        ):
            raise ValueError("Time Out must be later than Time In.")
        if self.sessions:
            ordered = sorted(self.sessions, key=lambda item: item.time_in)
            for previous, current in zip(ordered, ordered[1:]):
                if previous.time_out is None:
                    raise ValueError("Only the final attendance session may remain open.")
                if current.time_in < previous.time_out:
                    raise ValueError("Attendance sessions cannot overlap.")
        return self


class CompanyAttendanceSettingsInput(BaseModel):
    """Company schedule used for regular-hours and rest-day OT rules."""

    company_id: int
    regular_hours: Decimal = Field(ge=1, le=24)
    lunch_break_minutes: int = Field(ge=0, le=240)
    work_monday: bool = True
    work_tuesday: bool = True
    work_wednesday: bool = True
    work_thursday: bool = True
    work_friday: bool = True
    work_saturday: bool = False
    work_sunday: bool = False

    @model_validator(mode="after")
    def require_one_regular_workday(self):
        if not any(
            (
                self.work_monday,
                self.work_tuesday,
                self.work_wednesday,
                self.work_thursday,
                self.work_friday,
                self.work_saturday,
                self.work_sunday,
            )
        ):
            raise ValueError("At least one regular workday is required.")
        return self


class CompanyAttendanceCalendarInput(BaseModel):
    """Paid-hour rules and selected workdays for one company month."""

    company_id: int
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)
    regular_hours: Decimal = Field(ge=1, le=24)
    lunch_break_minutes: int = Field(ge=0, le=240)
    work_dates: list[date] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_month_dates(self):
        invalid_dates = [
            work_date
            for work_date in self.work_dates
            if work_date.year != self.year or work_date.month != self.month
        ]
        if invalid_dates:
            raise ValueError(
                "Every selected workday must belong to the selected month."
            )
        self.work_dates = sorted(set(self.work_dates))
        return self
