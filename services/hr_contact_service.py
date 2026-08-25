"""Business rules for the company HR contact directory."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models.hr_contact import HRContact
from repositories.hr_contact_repository import HRContactRepository


class HRContactService:
    """Manage published and archived HR contacts within one company."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = HRContactRepository(session)

    @staticmethod
    def _clean(value: Any, max_length: int) -> str:
        return str(value or "").strip()[:max_length]

    def _normalize_values(self, values: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "name": self._clean(values.get("name"), 180),
            "job_title": self._clean(values.get("job_title"), 180),
            "team": self._clean(values.get("team"), 180),
            "email": self._clean(values.get("email"), 255),
            "phone": self._clean(values.get("phone"), 80),
            "office_location": self._clean(values.get("office_location"), 255),
            "availability": self._clean(values.get("availability"), 255),
            "notes": self._clean(values.get("notes"), 2000),
        }

        if not normalized["name"]:
            raise ValueError("Contact name is required.")
        if not (normalized["email"] or normalized["phone"]):
            raise ValueError("Enter at least an email address or phone number.")
        if normalized["email"]:
            email = normalized["email"]
            if "@" not in email or " " in email or email.startswith("@") or email.endswith("@"):
                raise ValueError("Enter a valid email address.")
        return normalized

    def list_contacts(
        self,
        company_id: int,
        *,
        active_only: bool = False,
    ) -> list[HRContact]:
        return self.repository.list_contacts(
            company_id,
            active_only=active_only,
        )

    def create_contact(
        self,
        *,
        company_id: int,
        values: dict[str, Any],
    ) -> HRContact:
        normalized = self._normalize_values(values)
        contact = HRContact(
            company_id=company_id,
            sort_order=self.repository.next_sort_order(company_id),
            is_active=True,
            **normalized,
        )
        self.session.add(contact)
        self.session.commit()
        self.session.refresh(contact)
        return contact

    def update_contact(
        self,
        *,
        company_id: int,
        contact_id: int,
        values: dict[str, Any],
    ) -> HRContact:
        contact = self.repository.get_contact(
            company_id=company_id,
            contact_id=contact_id,
        )
        if contact is None:
            raise ValueError("The selected HR contact does not exist in this company.")
        if not contact.is_active:
            raise ValueError("Restore this HR contact before editing it.")

        for field_name, value in self._normalize_values(values).items():
            setattr(contact, field_name, value)
        self.session.commit()
        self.session.refresh(contact)
        return contact

    def archive_contact(
        self,
        *,
        company_id: int,
        contact_id: int,
        archived_by_user_id: int,
    ) -> str:
        contact = self.repository.get_contact(
            company_id=company_id,
            contact_id=contact_id,
        )
        if contact is None:
            raise ValueError("The selected HR contact does not exist in this company.")
        if not contact.is_active:
            raise ValueError("The selected HR contact is already archived.")

        contact.is_active = False
        contact.archived_at = datetime.now(timezone.utc)
        contact.archived_by_user_id = archived_by_user_id
        self.session.commit()
        return contact.name

    def restore_contact(
        self,
        *,
        company_id: int,
        contact_id: int,
    ) -> str:
        contact = self.repository.get_contact(
            company_id=company_id,
            contact_id=contact_id,
        )
        if contact is None:
            raise ValueError("The selected HR contact does not exist in this company.")
        if contact.is_active:
            raise ValueError("The selected HR contact is already active.")

        contact.is_active = True
        contact.archived_at = None
        contact.archived_by_user_id = None
        self.session.commit()
        return contact.name

    def permanently_delete_contact(
        self,
        *,
        company_id: int,
        contact_id: int,
    ) -> str:
        contact = self.repository.get_contact(
            company_id=company_id,
            contact_id=contact_id,
        )
        if contact is None:
            raise ValueError("The selected HR contact does not exist in this company.")
        if contact.is_active:
            raise ValueError("Move this HR contact to Archive before permanently deleting it.")

        name = contact.name
        self.session.delete(contact)
        self.session.commit()
        return name
