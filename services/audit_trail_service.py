"""Central audit-trail recording and company-scoped listing."""

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from sqlalchemy.orm import Session

from repositories.audit_event_repository import AuditEventRepository
from repositories.employee_history_repository import EmployeeHistoryRepository
from repositories.user_repository import UserRepository


@dataclass(frozen=True, slots=True)
class AuditTrailEntry:
    """Normalized central or legacy history row for the Audit Trail page."""

    occurred_at: datetime
    event_id: str
    module: str
    actor_user_id: int | None
    actor_label: str
    action: str
    entity: str
    result: str
    summary: str
    old_values_json: str | None
    new_values_json: str | None
    metadata_json: str | None = None


class AuditTrailService:
    """Record conflicts and combine central events with Employee history."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AuditEventRepository(session)

    def record_event(
        self,
        *,
        company_id: int,
        actor_user_id: int | None,
        module: str,
        action: str,
        entity_type: str,
        entity_id: str | int | None,
        entity_label: str | None,
        result: str,
        summary: str,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Commit one explicit event such as a blocked stale-form save."""

        self.repository.create(
            {
                "company_id": company_id,
                "actor_user_id": actor_user_id,
                "module": module,
                "action": action,
                "entity_type": entity_type,
                "entity_id": str(entity_id) if entity_id is not None else None,
                "entity_label": entity_label,
                "result": result,
                "summary": summary,
                "old_values_json": (
                    json.dumps(old_values, sort_keys=True)
                    if old_values
                    else None
                ),
                "new_values_json": (
                    json.dumps(new_values, sort_keys=True)
                    if new_values
                    else None
                ),
                "metadata_json": (
                    json.dumps(metadata, sort_keys=True)
                    if metadata
                    else None
                ),
            }
        )

    def list_entries(self, company_id: int) -> list[AuditTrailEntry]:
        """Return central events plus existing Employee workspace history."""

        users = UserRepository(self.session).list_with_details(company_id)
        user_labels = {
            user.id: (
                user.employee.full_name
                if user.employee is not None
                else user.username
            )
            for user in users
        }

        entries = [
            AuditTrailEntry(
                occurred_at=item.created_at,
                event_id=f"AUD-{item.id}",
                module=item.module,
                actor_user_id=item.actor_user_id,
                actor_label=user_labels.get(
                    item.actor_user_id,
                    "System / Former User",
                ),
                action=item.action,
                entity=(
                    f"{item.entity_type} · {item.entity_label}"
                    if item.entity_label
                    else item.entity_type
                ),
                result=item.result,
                summary=item.summary,
                old_values_json=item.old_values_json,
                new_values_json=item.new_values_json,
                metadata_json=item.metadata_json,
            )
            for item in self.repository.list_for_company(company_id)
        ]

        # Preserve all Employee history created before and after this central
        # page was introduced. Employee tables are intentionally excluded from
        # the automatic listener to avoid duplicate rows.
        entries.extend(
            AuditTrailEntry(
                occurred_at=item.created_at,
                event_id=f"EMP-{item.id}",
                module="Employees",
                actor_user_id=item.performed_by_user_id,
                actor_label=user_labels.get(
                    item.performed_by_user_id,
                    "System / Former User",
                ),
                action=item.action_type.replace("_", " ").title(),
                entity=f"Employee · {item.employee_number} — {item.employee_name}",
                result="successful",
                summary=item.summary,
                old_values_json=item.old_values_json,
                new_values_json=item.new_values_json,
                metadata_json=(
                    json.dumps(
                        {
                            "source": item.source,
                            "upload_filename": item.upload_filename,
                            "upload_batch_id": item.upload_batch_id,
                        },
                        sort_keys=True,
                    )
                ),
            )
            for item in EmployeeHistoryRepository(
                self.session
            ).list_for_company(company_id)
        )

        return sorted(
            entries,
            key=lambda item: (item.occurred_at, item.event_id),
            reverse=True,
        )

