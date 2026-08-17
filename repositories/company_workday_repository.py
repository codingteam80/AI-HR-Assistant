"""Persistence operations for company-specific workday calendars."""

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.company_workday import CompanyWorkday
from repositories.base_repository import BaseRepository


class CompanyWorkdayRepository(BaseRepository[CompanyWorkday]):
    """Read and replace workday settings without crossing company scope."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, CompanyWorkday)

    def list_range(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
    ) -> list[CompanyWorkday]:
        statement = (
            select(CompanyWorkday)
            .where(
                CompanyWorkday.company_id == company_id,
                CompanyWorkday.work_date >= start_date,
                CompanyWorkday.work_date <= end_date,
            )
            .order_by(CompanyWorkday.work_date)
        )
        return list(self.session.scalars(statement).all())

    def replace_range(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
        workday_values: dict[date, bool],
    ) -> None:
        """Replace only the selected period; other months remain unchanged."""

        self.session.execute(
            delete(CompanyWorkday).where(
                CompanyWorkday.company_id == company_id,
                CompanyWorkday.work_date >= start_date,
                CompanyWorkday.work_date <= end_date,
            )
        )
        self.session.add_all(
            CompanyWorkday(
                company_id=company_id,
                work_date=work_date,
                is_workday=is_workday,
            )
            for work_date, is_workday in sorted(workday_values.items())
        )
