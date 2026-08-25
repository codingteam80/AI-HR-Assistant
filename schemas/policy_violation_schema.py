"""Validation schemas for company violation and disciplinary rules."""

from datetime import date

from pydantic import BaseModel, Field


class PolicyViolationCreateRequest(BaseModel):
    company_id: int
    created_by_user_id: int
    violation_code: str = Field(min_length=2, max_length=40)
    category: str = Field(min_length=2, max_length=100)
    offense_title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=4000)
    severity: str = Field(min_length=3, max_length=20)
    first_offense_action: str = Field(min_length=2, max_length=2000)
    second_offense_action: str = Field(min_length=2, max_length=2000)
    third_offense_action: str = Field(min_length=2, max_length=2000)
    final_action: str = Field(min_length=2, max_length=2000)
    related_policy_id: int | None = None
    effective_date: date | None = None
    status: str = Field(default="active", min_length=3, max_length=20)
    notes: str | None = Field(default=None, max_length=4000)


class PolicyViolationUpdateRequest(BaseModel):
    company_id: int
    violation_id: int
    edited_by_user_id: int
    violation_code: str = Field(min_length=2, max_length=40)
    category: str = Field(min_length=2, max_length=100)
    offense_title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=4000)
    severity: str = Field(min_length=3, max_length=20)
    first_offense_action: str = Field(min_length=2, max_length=2000)
    second_offense_action: str = Field(min_length=2, max_length=2000)
    third_offense_action: str = Field(min_length=2, max_length=2000)
    final_action: str = Field(min_length=2, max_length=2000)
    related_policy_id: int | None = None
    effective_date: date | None = None
    status: str = Field(default="active", min_length=3, max_length=20)
    notes: str | None = Field(default=None, max_length=4000)
