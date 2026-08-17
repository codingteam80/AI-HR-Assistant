"""Validated leave-management input contracts."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from core.leave_codes import LEAVE_DURATION_OPTIONS, LEAVE_REASON_OPTIONS


class LeaveTypeInput(BaseModel):
    """Create or update one leave type and its rules."""

    company_id: int
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=3, max_length=120)
    annual_credits: Decimal = Field(ge=0, le=365)
    is_paid: bool = True
    carry_over_limit: Decimal = Field(ge=0, le=365)
    # Retained for compatibility with older service callers.
    requires_attachment: bool = False
    handover_plan_requirement: Literal[
        "optional",
        "recommended",
        "required",
    ] = "optional"
    minimum_notice_days: int = Field(ge=0, le=365)
    is_active: bool = True
    apply_annual_credits_to_existing: bool = False

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return "_".join(value.strip().upper().split())

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


class LeaveCreditAdjustmentInput(BaseModel):
    """Signed manual adjustment for one employee's annual balance."""

    company_id: int
    employee_id: int
    leave_type_id: int
    year: int = Field(ge=2000, le=2200)
    adjustment_days: Decimal = Field(ge=-365, le=365)
    reason: str = Field(min_length=3, max_length=500)
    created_by_user_id: int

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return " ".join(value.strip().split())



class LeaveCreditBalanceSetInput(BaseModel):
    """Set the exact remaining credits for one annual leave balance."""

    company_id: int
    employee_id: int
    leave_type_id: int
    year: int = Field(ge=2000, le=2200)
    new_remaining_days: Decimal = Field(ge=0, le=365)
    reason: str = Field(min_length=3, max_length=500)
    created_by_user_id: int

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return " ".join(value.strip().split())


class LeaveRequestInput(BaseModel):
    """Employee leave request delivered to the assigned manager."""

    company_id: int
    employee_id: int
    requested_by_user_id: int
    leave_type_id: int
    start_date: date
    end_date: date
    duration_code: str = "90503"
    reason_code: str = "0"
    reason_other: str | None = Field(default=None, max_length=4000)
    # Compatibility input for callers from earlier checkpoints. It is copied
    # to Reason for Leave: Others when no explicit structured value is sent.
    reason: str | None = Field(default=None, max_length=4000)
    handover_plan: str | None = Field(
        default=None,
        max_length=10000,
    )
    filed_by_employee_id: int | None = None
    to_user_id: int | None = None
    cc_user_ids: list[int] = Field(default_factory=list)

    @field_validator("reason", "reason_other")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None

    @field_validator("duration_code")
    @classmethod
    def validate_duration_code(cls, value: str) -> str:
        normalized = str(value).strip()
        if normalized not in LEAVE_DURATION_OPTIONS:
            raise ValueError("Select a valid leave duration.")
        return normalized

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str) -> str:
        normalized = str(value).strip()
        if normalized not in LEAVE_REASON_OPTIONS:
            raise ValueError("Select a valid Reason for Leave.")
        return normalized

    @field_validator("handover_plan")
    @classmethod
    def normalize_handover_plan(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("cc_user_ids")
    @classmethod
    def normalize_cc_user_ids(cls, value: list[int]) -> list[int]:
        """Keep positive unique recipients while preserving display order."""
        output: list[int] = []
        for user_id in value:
            normalized = int(user_id)
            if normalized > 0 and normalized not in output:
                output.append(normalized)
        return output

    @model_validator(mode="after")
    def validate_date_order(self):
        if self.end_date < self.start_date:
            raise ValueError("End date cannot be earlier than start date.")
        if self.start_date.year != self.end_date.year:
            raise ValueError("A leave request cannot cross calendar years.")
        if self.duration_code != "90503" and self.start_date != self.end_date:
            raise ValueError("AM Only and PM Only leave must use one date only.")
        if self.reason_other is None and self.reason:
            self.reason_other = self.reason
        if self.reason_code == "0":
            if not self.reason_other or len(self.reason_other) < 5:
                raise ValueError(
                    "Reason for Leave: Others is required when 0 - OTHERS is selected."
                )
        # Keep the legacy text field populated for email, search, and old UI
        # code while the structured fields remain the report source of truth.
        self.reason = self.reason_other or LEAVE_REASON_OPTIONS[self.reason_code]
        return self



class LeaveDecisionInput(BaseModel):
    """Approve or reject a request as its assigned manager."""

    company_id: int
    request_id: int
    manager_employee_id: int
    manager_user_id: int
    decision: Literal["approve", "reject"]
    manager_comment: str | None = Field(
        default=None,
        max_length=2000,
    )

    @field_validator("manager_comment")
    @classmethod
    def normalize_manager_comment(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None

class LeaveCancellationRequestInput(BaseModel):
    """Cancel a pending request or ask to cancel an approved leave."""

    company_id: int
    request_id: int
    requested_by_user_id: int
    requested_by_employee_id: int
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return " ".join(value.strip().split())


class LeaveCancellationDecisionInput(BaseModel):
    """Approve or reject one approved-leave cancellation request."""

    company_id: int
    request_id: int
    reviewer_user_id: int
    reviewer_employee_id: int | None = None
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None
