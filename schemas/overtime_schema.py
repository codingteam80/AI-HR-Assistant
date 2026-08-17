"""Validated contracts for employee OT filing and approval."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


OTType = Literal[
    "Regular Overtime",
    "Rest Day Overtime",
    "Special Holiday",
    "Legal Holiday",
    "Special Holiday on a Rest Day",
]

OT_TYPE_OPTIONS = (
    "Regular Overtime",
    "Rest Day Overtime",
    "Special Holiday",
    "Legal Holiday",
    "Special Holiday on a Rest Day",
)


class OvertimeRequestInput(BaseModel):
    """Employee-owned OT values linked to one source DTR date."""

    company_id: int
    employee_id: int
    requested_by_user_id: int
    date_rendered: date
    ot_time_start: datetime
    ot_time_end: datetime
    estimated_hours: Decimal = Field(gt=0, le=24, decimal_places=2)
    ot_type: OTType
    ot_purpose: str = Field(min_length=3, max_length=2000)
    travel_fare: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    travel_route: str | None = Field(default=None, max_length=500)
    dinner_break_flag: bool

    @field_validator("ot_purpose", "travel_route")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None

    @model_validator(mode="after")
    def validate_request(self):
        if self.ot_time_end <= self.ot_time_start:
            raise ValueError("OT End Time must be later than OT Start Time.")
        if self.travel_fare is not None and self.travel_fare > 0 and not self.travel_route:
            raise ValueError("Travel Route is required when Travel Fare has a value.")
        return self


class OvertimeReviewInput(BaseModel):
    """Leader, manager, or administrator OT decision."""

    company_id: int
    overtime_request_id: int
    reviewed_by_user_id: int
    reviewer_employee_id: int | None = None
    clearance: int
    decision: Literal["approved", "rejected"]
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None
