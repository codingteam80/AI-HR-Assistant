"""Validation schemas for employee disciplinary case records."""

from datetime import date

from pydantic import BaseModel, Field


class DisciplinaryRecordCreateRequest(BaseModel):
    company_id: int
    employee_id: int
    violation_id: int
    incident_date: date
    incident_description: str = Field(min_length=3, max_length=8000)
    evidence_remarks: str | None = Field(default=None, max_length=12000)
    context_snapshot: str | None = Field(default=None, max_length=300)
    actual_action_taken: str | None = Field(default=None, max_length=4000)
    issued_by_user_id: int | None = None
    reviewed_approved_by_user_id: int | None = None
    date_issued: date | None = None
    employee_acknowledgment: str = Field(default="Pending", max_length=30)
    case_status: str = Field(default="Draft", max_length=30)
    notes: str | None = Field(default=None, max_length=8000)
    created_by_user_id: int


class DisciplinaryRecordUpdateRequest(BaseModel):
    company_id: int
    record_id: int
    incident_date: date
    incident_description: str = Field(min_length=3, max_length=8000)
    evidence_remarks: str | None = Field(default=None, max_length=12000)
    context_snapshot: str | None = Field(default=None, max_length=300)
    actual_action_taken: str | None = Field(default=None, max_length=4000)
    issued_by_user_id: int | None = None
    reviewed_approved_by_user_id: int | None = None
    date_issued: date | None = None
    employee_acknowledgment: str = Field(default="Pending", max_length=30)
    case_status: str = Field(default="Draft", max_length=30)
    notes: str | None = Field(default=None, max_length=8000)
    edited_by_user_id: int
