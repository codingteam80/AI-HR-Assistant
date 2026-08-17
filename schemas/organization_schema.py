"""Validation schemas for company, department, and role management.

Purpose:
- Validate administrator form values before service execution.
- Keep Streamlit pages independent from SQLAlchemy model details.
- Provide consistent length, required-field, and status validation.
"""

from pydantic import BaseModel, Field, field_validator


class CompanyProfileUpdate(BaseModel):
    """Editable company identity fields shown in Company Profile."""

    company_id: int
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=200)

    @field_validator("code")
    @classmethod
    def normalize_company_code(cls, value: str) -> str:
        """Normalize login code and reject ambiguous characters."""

        normalized = value.strip().upper()

        if not normalized:
            raise ValueError("Company code is required.")

        if not 2 <= len(normalized) <= 50:
            raise ValueError("Company code must be 2 to 50 characters long.")

        if not normalized.isascii():
            raise ValueError(
                "Company code may contain only ASCII letters, numbers, "
                "hyphens, and underscores."
            )

        if not normalized[0].isalnum() or any(
            not (character.isalnum() or character in {"_", "-"})
            for character in normalized
        ):
            raise ValueError(
                "Company code may contain only letters, numbers, "
                "hyphens, and underscores."
            )

        return normalized

    @field_validator("name")
    @classmethod
    def normalize_company_name(cls, value: str) -> str:
        """Trim the display name before persistence."""

        normalized = value.strip()

        if not 2 <= len(normalized) <= 200:
            raise ValueError("Company name must be 2 to 200 characters long.")

        return normalized


class CompanyNameUpdate(BaseModel):
    """Values allowed when updating the current company profile."""

    company_id: int
    name: str = Field(min_length=2, max_length=200)



class CompanyThemeColorUpdate(BaseModel):
    """Company-specific primary accent color."""

    company_id: int
    primary_color: str = Field(
        min_length=7,
        max_length=7,
        pattern=r"^#[0-9A-Fa-f]{6}$",
    )


class DepartmentCreate(BaseModel):
    """Values required to create a company-scoped department."""

    company_id: int
    name: str = Field(min_length=2, max_length=150)
    code: str | None = Field(default=None, max_length=50)


class DepartmentStatusUpdate(BaseModel):
    """Values required to activate or deactivate a department."""

    company_id: int
    department_id: int
    is_active: bool


class RoleCreateRequest(BaseModel):
    """Values required to create a custom company role."""

    company_id: int
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=255)


class RoleStatusUpdate(BaseModel):
    """Values required to activate or deactivate a custom role."""

    company_id: int
    role_id: int
    is_active: bool
