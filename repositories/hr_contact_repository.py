"""Tenant-safe persistence for the HR contact directory."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.hr_contact import HRContact
from repositories.base_repository import BaseRepository


class HRContactRepository(BaseRepository[HRContact]):
    """Read and write company-scoped HR contact records."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, HRContact)

    def list_contacts(
        self,
        company_id: int,
        *,
        active_only: bool = False,
    ) -> list[HRContact]:
        statement = select(HRContact).where(HRContact.company_id == company_id)
        if active_only:
            statement = statement.where(HRContact.is_active.is_(True))
        statement = statement.order_by(
            HRContact.sort_order,
            HRContact.name,
            HRContact.id,
        )
        return list(self.session.scalars(statement).all())

    def next_sort_order(self, company_id: int) -> int:
        """Return the next automatic display order for one company."""

        maximum = self.session.scalar(
            select(func.max(HRContact.sort_order)).where(
                HRContact.company_id == company_id
            )
        )
        current = int(maximum or 0)
        return ((current // 10) + 1) * 10

    def get_contact(
        self,
        *,
        company_id: int,
        contact_id: int,
    ) -> HRContact | None:
        return self.session.scalar(
            select(HRContact).where(
                HRContact.company_id == company_id,
                HRContact.id == contact_id,
            )
        )
