"""Company-specific database queries.

Company ID is the stable tenant identifier. Company code is the human-facing
login code and may be changed by an administrator when uniqueness is preserved.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.company import Company
from repositories.base_repository import BaseRepository


class CompanyRepository(BaseRepository[Company]):
    """Repository for company records."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, Company)

    def get_by_code(self, code: str) -> Company | None:
        """Return a company using its exact stored login code."""

        return self.session.scalar(
            select(Company).where(Company.code == code)
        )

    def get_by_code_case_insensitive(
        self,
        code: str,
    ) -> Company | None:
        """Return a company by normalized code regardless of case."""

        normalized_code = code.strip().upper()

        if not normalized_code:
            return None

        return self.session.scalar(
            select(Company).where(
                func.upper(Company.code) == normalized_code
            )
        )

    def get_active_by_code(
        self,
        code: str,
    ) -> Company | None:
        """Return an active company using a case-insensitive code."""

        normalized_code = code.strip().upper()

        if not normalized_code:
            return None

        return self.session.scalar(
            select(Company).where(
                func.upper(Company.code) == normalized_code,
                Company.is_active.is_(True),
            )
        )

    def list_active(
        self,
        *,
        limit: int | None = None,
    ) -> list[Company]:
        """Return active companies for safe public-brand resolution."""

        statement = (
            select(Company)
            .where(Company.is_active.is_(True))
            .order_by(Company.id)
        )

        if limit is not None:
            statement = statement.limit(limit)

        return list(
            self.session.scalars(statement).all()
        )
    def update_profile(
        self,
        *,
        company_id: int,
        code: str,
        name: str,
    ) -> Company | None:
        """Update editable company identity fields."""

        company = self.get_by_id(company_id)

        if company is None:
            return None

        company.code = code
        company.name = name
        self.session.commit()
        self.session.refresh(company)

        return company

    def update_name(
        self,
        *,
        company_id: int,
        name: str,
    ) -> Company | None:
        """Backward-compatible display-name-only update."""

        company = self.get_by_id(company_id)

        if company is None:
            return None

        company.name = name
        self.session.commit()
        self.session.refresh(company)

        return company


    def update_theme_color(
        self,
        *,
        company_id: int,
        primary_color: str,
    ) -> Company | None:
        """Update only the company's primary accent color."""

        company = self.get_by_id(company_id)

        if company is None:
            return None

        company.theme_primary_color = primary_color
        self.session.commit()
        self.session.refresh(company)

        return company

    def update_logo_filename(
        self,
        *,
        company_id: int,
        logo_filename: str | None,
    ) -> Company | None:
        """Update only the private company-logo reference."""

        company = self.get_by_id(company_id)

        if company is None:
            return None

        company.logo_filename = logo_filename
        self.session.commit()
        self.session.refresh(company)

        return company

    def update_attendance_settings(
        self,
        *,
        company_id: int,
        values: dict[str, object],
    ) -> Company | None:
        """Update company workweek and regular-hours configuration."""

        company = self.get_by_id(company_id)
        if company is None:
            return None
        for field_name, value in values.items():
            setattr(company, field_name, value)
        self.session.commit()
        self.session.refresh(company)
        return company
