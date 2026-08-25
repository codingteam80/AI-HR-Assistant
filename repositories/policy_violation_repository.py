"""Tenant-safe queries for the violation and disciplinary-action master list."""

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models.policy_violation import PolicyViolation
from repositories.base_repository import BaseRepository


class PolicyViolationRepository(BaseRepository[PolicyViolation]):
    """Read/write violation definitions only inside one company."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, PolicyViolation)

    def get_violation(
        self,
        *,
        company_id: int,
        violation_id: int,
    ) -> PolicyViolation | None:
        return self.session.scalar(
            select(PolicyViolation).where(
                PolicyViolation.company_id == company_id,
                PolicyViolation.id == violation_id,
            )
        )

    def get_by_code(
        self,
        *,
        company_id: int,
        violation_code: str,
    ) -> PolicyViolation | None:
        normalized = violation_code.strip().upper()
        return self.session.scalar(
            select(PolicyViolation).where(
                PolicyViolation.company_id == company_id,
                func.upper(PolicyViolation.violation_code) == normalized,
            )
        )

    def list_current(self, company_id: int) -> list[PolicyViolation]:
        return list(
            self.session.scalars(
                select(PolicyViolation)
                .where(
                    PolicyViolation.company_id == company_id,
                    PolicyViolation.archived_at.is_(None),
                )
                .order_by(
                    PolicyViolation.category,
                    PolicyViolation.violation_code,
                    PolicyViolation.offense_title,
                )
            ).all()
        )

    def list_archived(self, company_id: int) -> list[PolicyViolation]:
        return list(
            self.session.scalars(
                select(PolicyViolation)
                .where(
                    PolicyViolation.company_id == company_id,
                    PolicyViolation.archived_at.is_not(None),
                )
                .order_by(
                    PolicyViolation.archived_at.desc(),
                    PolicyViolation.violation_code,
                )
            ).all()
        )

    def list_employee_visible(
        self,
        *,
        company_id: int,
        as_of_date: date,
    ) -> list[PolicyViolation]:
        return list(
            self.session.scalars(
                select(PolicyViolation)
                .where(
                    PolicyViolation.company_id == company_id,
                    PolicyViolation.archived_at.is_(None),
                    PolicyViolation.status == "active",
                    or_(
                        PolicyViolation.effective_date.is_(None),
                        PolicyViolation.effective_date <= as_of_date,
                    ),
                )
                .order_by(
                    PolicyViolation.category,
                    PolicyViolation.severity,
                    PolicyViolation.violation_code,
                )
            ).all()
        )
