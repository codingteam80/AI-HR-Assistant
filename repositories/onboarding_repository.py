"""Company-scoped onboarding persistence helpers."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.onboarding import (
    CompanyBenefit,
    EmployeeOnboardingProgress,
    OnboardingChecklistItem,
)


class OnboardingRepository:
    """Keep onboarding queries tenant-scoped and consistently ordered."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_items(
        self,
        company_id: int,
        *,
        active_only: bool = False,
    ) -> list[OnboardingChecklistItem]:
        statement = select(OnboardingChecklistItem).where(
            OnboardingChecklistItem.company_id == company_id
        )
        if active_only:
            statement = statement.where(OnboardingChecklistItem.is_active.is_(True))
        statement = statement.order_by(
            OnboardingChecklistItem.sort_order,
            OnboardingChecklistItem.id,
        )
        return list(self.session.scalars(statement).all())

    def get_item(
        self,
        *,
        company_id: int,
        item_id: int,
    ) -> OnboardingChecklistItem | None:
        return self.session.scalar(
            select(OnboardingChecklistItem).where(
                OnboardingChecklistItem.company_id == company_id,
                OnboardingChecklistItem.id == item_id,
            )
        )

    def list_progress(
        self,
        *,
        company_id: int,
        employee_id: int | None = None,
    ) -> list[EmployeeOnboardingProgress]:
        statement = select(EmployeeOnboardingProgress).where(
            EmployeeOnboardingProgress.company_id == company_id
        )
        if employee_id is not None:
            statement = statement.where(
                EmployeeOnboardingProgress.employee_id == employee_id
            )
        return list(self.session.scalars(statement).all())

    def get_progress(
        self,
        *,
        company_id: int,
        employee_id: int,
        item_id: int,
    ) -> EmployeeOnboardingProgress | None:
        return self.session.scalar(
            select(EmployeeOnboardingProgress).where(
                EmployeeOnboardingProgress.company_id == company_id,
                EmployeeOnboardingProgress.employee_id == employee_id,
                EmployeeOnboardingProgress.checklist_item_id == item_id,
            )
        )

    def list_benefits(
        self,
        company_id: int,
        *,
        active_only: bool = False,
    ) -> list[CompanyBenefit]:
        statement = select(CompanyBenefit).where(
            CompanyBenefit.company_id == company_id
        )
        if active_only:
            statement = statement.where(CompanyBenefit.is_active.is_(True))
        statement = statement.order_by(
            CompanyBenefit.sort_order,
            CompanyBenefit.name,
            CompanyBenefit.id,
        )
        return list(self.session.scalars(statement).all())

    def get_benefit(
        self,
        *,
        company_id: int,
        benefit_id: int,
    ) -> CompanyBenefit | None:
        return self.session.scalar(
            select(CompanyBenefit).where(
                CompanyBenefit.company_id == company_id,
                CompanyBenefit.id == benefit_id,
            )
        )
