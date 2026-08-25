"""Business rules for confidential employee disciplinary case records."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import re
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from config.settings import get_settings
from models.employee_disciplinary_record import EmployeeDisciplinaryRecord
from models.employee_history import EmployeeHistory
from models.policy_violation import PolicyViolation
from repositories.disciplinary_record_repository import DisciplinaryRecordRepository
from repositories.employee_repository import EmployeeRepository
from repositories.policy_violation_repository import PolicyViolationRepository
from repositories.user_repository import UserRepository
from schemas.disciplinary_record_schema import (
    DisciplinaryRecordCreateRequest,
    DisciplinaryRecordUpdateRequest,
)
from services.notification_service import NotificationService


CASE_STATUSES = ("Draft", "For Review", "Issued", "Closed", "Cancelled")
ACKNOWLEDGMENT_STATUSES = ("Pending", "Acknowledged", "Declined", "Not Required")


class DisciplinaryRecordService:
    """Manage employee cases while preserving tenant and privacy boundaries."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = DisciplinaryRecordRepository(session)
        self.employee_repository = EmployeeRepository(session)
        self.violation_repository = PolicyViolationRepository(session)
        self.user_repository = UserRepository(session)
        self.notification_service = NotificationService(session)

    @staticmethod
    def _clean(value: object, max_length: int) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()[:max_length]

    @staticmethod
    def _optional(value: object, max_length: int) -> str | None:
        cleaned = DisciplinaryRecordService._clean(value, max_length)
        return cleaned or None

    def _require_admin_actor(self, *, company_id: int, user_id: int) -> None:
        user = self.user_repository.get_by_id(record_id=user_id, company_id=company_id)
        if user is None or not user.is_active or int(user.clearance) != 1:
            raise PermissionError("Administrator access is required for disciplinary records.")

    def _employee(self, *, company_id: int, employee_id: int):
        employee = self.employee_repository.get_with_details(
            company_id=company_id,
            employee_id=employee_id,
        )
        if employee is None:
            raise ValueError("The selected employee does not belong to this company.")
        return employee

    def _violation(self, *, company_id: int, violation_id: int) -> PolicyViolation:
        violation = self.violation_repository.get_violation(
            company_id=company_id,
            violation_id=violation_id,
        )
        if violation is None:
            raise ValueError("The selected violation does not belong to this company.")
        return violation

    def _company_user(self, *, company_id: int, user_id: int | None):
        if user_id is None:
            return None
        user = self.user_repository.get_by_id(record_id=user_id, company_id=company_id)
        if user is None:
            raise ValueError("The selected issuer/reviewer does not belong to this company.")
        return user

    @staticmethod
    def offense_level(previous_offense_count: int) -> str:
        current = max(0, int(previous_offense_count)) + 1
        if current == 1:
            return "1st"
        if current == 2:
            return "2nd"
        if current == 3:
            return "3rd"
        return "Succeeding"

    @staticmethod
    def suggested_action(violation: PolicyViolation, offense_level: str) -> str:
        if offense_level == "1st":
            return violation.first_offense_action
        if offense_level == "2nd":
            return violation.second_offense_action
        if offense_level == "3rd":
            return violation.third_offense_action
        return violation.final_action

    def suggested_action_for_record(self, record: EmployeeDisciplinaryRecord) -> str:
        if record.violation_id is None:
            return "Master violation is no longer available."
        violation = self.violation_repository.get_violation(
            company_id=record.company_id,
            violation_id=record.violation_id,
        )
        if violation is None:
            return "Master violation is no longer available."
        return self.suggested_action(violation, record.offense_level)

    @staticmethod
    def _status(value: str) -> str:
        cleaned = value.strip()
        if cleaned not in CASE_STATUSES:
            raise ValueError("Select a valid disciplinary case status.")
        return cleaned

    @staticmethod
    def _acknowledgment(value: str) -> str:
        cleaned = value.strip()
        if cleaned not in ACKNOWLEDGMENT_STATUSES:
            raise ValueError("Select a valid employee acknowledgment status.")
        return cleaned

    @staticmethod
    def _validate_issue_fields(
        *,
        status: str,
        actual_action_taken: str | None,
        issued_by_user_id: int | None,
        date_issued: date | None,
    ) -> None:
        if status not in {"Issued", "Closed"}:
            return
        if not actual_action_taken:
            raise ValueError("Actual Action Taken is required before a case can be issued or closed.")
        if issued_by_user_id is None:
            raise ValueError("Issued By is required before a case can be issued or closed.")
        if date_issued is None:
            raise ValueError("Date Issued is required before a case can be issued or closed.")

    @staticmethod
    def _history_row(
        *,
        record: EmployeeDisciplinaryRecord,
        actor_user_id: int,
        action_type: str,
        summary: str,
        old_values: dict[str, object] | None,
        new_values: dict[str, object] | None,
    ) -> EmployeeHistory:
        return EmployeeHistory(
            company_id=record.company_id,
            employee_id=record.employee_id,
            employee_number=record.employee_number,
            employee_name=record.employee_name,
            performed_by_user_id=actor_user_id,
            action_type=action_type,
            source="disciplinary_record",
            summary=summary[:500],
            old_values_json=json.dumps(old_values, sort_keys=True, default=str) if old_values else None,
            new_values_json=json.dumps(new_values, sort_keys=True, default=str) if new_values else None,
        )

    @staticmethod
    def _snapshot(record: EmployeeDisciplinaryRecord) -> dict[str, object]:
        return {
            "case_id": record.public_id,
            "violation": f"{record.violation_code} — {record.violation_title}",
            "incident_date": record.incident_date.isoformat(),
            "offense_level": record.offense_level,
            "actual_action_taken": record.actual_action_taken,
            "date_issued": record.date_issued.isoformat() if record.date_issued else None,
            "employee_acknowledgment": record.employee_acknowledgment,
            "case_status": record.case_status,
        }

    def _notify_if_issued(self, record: EmployeeDisciplinaryRecord) -> None:
        if record.case_status not in {"Issued", "Closed"} or record.employee_id is None:
            return
        employee = self.employee_repository.get_with_details(
            company_id=record.company_id,
            employee_id=record.employee_id,
        )
        if employee is None or employee.user_id is None:
            return
        event_type = "disciplinary_case_issued"
        entity_type = "employee_disciplinary_record"
        if self.notification_service.exists_for_entity_event(
            company_id=record.company_id,
            user_id=employee.user_id,
            event_type=event_type,
            related_entity_type=entity_type,
            related_entity_id=record.id,
        ):
            return
        self.notification_service.create(
            company_id=record.company_id,
            user_id=employee.user_id,
            event_type=event_type,
            title="Disciplinary Record Issued",
            message=(
                f"{record.public_id}: {record.violation_code} — {record.violation_title}. "
                "Open Company Policies → My Disciplinary Records to review the issued record."
            ),
            related_entity_type=entity_type,
            related_entity_id=record.id,
        )

    def list_admin_records(self, *, company_id: int, requester_user_id: int) -> list[EmployeeDisciplinaryRecord]:
        self._require_admin_actor(company_id=company_id, user_id=requester_user_id)
        return self.repository.list_company(company_id)

    def list_admin_archived_records(
        self, *, company_id: int, requester_user_id: int
    ) -> list[EmployeeDisciplinaryRecord]:
        self._require_admin_actor(company_id=company_id, user_id=requester_user_id)
        return self.repository.list_company(company_id, archived=True)

    def list_employee_records(
        self,
        *,
        company_id: int,
        employee_id: int,
        requester_user_id: int,
    ) -> list[EmployeeDisciplinaryRecord]:
        employee = self._employee(company_id=company_id, employee_id=employee_id)
        if employee.user_id is None or int(employee.user_id) != int(requester_user_id):
            raise PermissionError("You may only view your own issued disciplinary records.")
        if not get_settings().employee_disciplinary_records_visible:
            return []
        return self.repository.list_employee_issued(
            company_id=company_id,
            employee_id=employee_id,
        )

    def _stage_new_record(
        self, values: DisciplinaryRecordCreateRequest
    ) -> EmployeeDisciplinaryRecord:
        """Validate and stage one new case without committing the transaction."""

        self._require_admin_actor(
            company_id=values.company_id, user_id=values.created_by_user_id
        )
        employee = self._employee(
            company_id=values.company_id, employee_id=values.employee_id
        )
        if employee.archived_at is not None or str(employee.employment_status).casefold() != "employed":
            raise ValueError("Select an active employed employee for the disciplinary case.")
        violation = self._violation(
            company_id=values.company_id, violation_id=values.violation_id
        )
        if violation.archived_at is not None or violation.status != "active":
            raise ValueError("Select an active, non-archived violation from the master list.")

        issuer = self._company_user(
            company_id=values.company_id, user_id=values.issued_by_user_id
        )
        reviewer = self._company_user(
            company_id=values.company_id,
            user_id=values.reviewed_approved_by_user_id,
        )
        status = self._status(values.case_status)
        acknowledgment = self._acknowledgment(values.employee_acknowledgment)
        description = self._clean(values.incident_description, 8000)
        if not description:
            raise ValueError("Incident / Case Description is required.")
        action = self._optional(values.actual_action_taken, 4000)
        self._validate_issue_fields(
            status=status,
            actual_action_taken=action,
            issued_by_user_id=issuer.id if issuer is not None else None,
            date_issued=values.date_issued,
        )

        previous = self.repository.count_previous_offenses(
            company_id=values.company_id,
            employee_id=employee.id,
            violation_id=violation.id,
            incident_date=values.incident_date,
        )
        level = self.offense_level(previous)
        default_context = (
            employee.department.name if employee.department is not None else None
        )
        record = EmployeeDisciplinaryRecord(
            public_id=f"DR_{uuid.uuid4().hex[:12].upper()}",
            company_id=values.company_id,
            employee_id=employee.id,
            violation_id=violation.id,
            created_by_user_id=values.created_by_user_id,
            last_edited_by_user_id=values.created_by_user_id,
            employee_number=employee.employee_number,
            employee_name=employee.full_name,
            violation_code=violation.violation_code,
            violation_title=violation.offense_title,
            incident_date=values.incident_date,
            incident_description=description,
            evidence_remarks=self._optional(values.evidence_remarks, 12000),
            context_snapshot=self._optional(values.context_snapshot, 300) or default_context,
            previous_offense_count=previous,
            offense_level=level,
            actual_action_taken=action,
            issued_by_user_id=issuer.id if issuer is not None else None,
            reviewed_approved_by_user_id=reviewer.id if reviewer is not None else None,
            date_issued=values.date_issued,
            employee_acknowledgment=acknowledgment,
            case_status=status,
            notes=self._optional(values.notes, 8000),
        )
        self.session.add(record)
        self.session.flush()
        self.session.add(
            self._history_row(
                record=record,
                actor_user_id=values.created_by_user_id,
                action_type="disciplinary_case_created",
                summary=(
                    f"Created disciplinary case {record.public_id}: "
                    f"{record.violation_code} — {record.violation_title}."
                ),
                old_values=None,
                new_values=self._snapshot(record),
            )
        )
        self._notify_if_issued(record)
        return record

    def _recalculate_offense_progression(
        self, *, company_id: int, employee_id: int, violation_id: int
    ) -> None:
        """Keep later offense levels correct after create/edit/archive/restore."""

        records = self.repository.list_employee_violation_active(
            company_id=company_id,
            employee_id=employee_id,
            violation_id=violation_id,
        )
        previous = 0
        for record in records:
            record.previous_offense_count = previous
            record.offense_level = self.offense_level(previous)
            if record.case_status != "Cancelled":
                previous += 1

    def create_record(
        self, values: DisciplinaryRecordCreateRequest
    ) -> EmployeeDisciplinaryRecord:
        record = self._stage_new_record(values)
        self._recalculate_offense_progression(
            company_id=record.company_id,
            employee_id=int(record.employee_id),
            violation_id=int(record.violation_id),
        )
        self.session.commit()
        self.session.refresh(record)
        return record

    def create_many(
        self, requests: list[DisciplinaryRecordCreateRequest]
    ) -> list[EmployeeDisciplinaryRecord]:
        """Atomically create a validated batch and keep offense order deterministic."""

        if not requests:
            raise ValueError("There are no disciplinary case rows to import.")
        if len(requests) > 1000:
            raise ValueError("A maximum of 1,000 disciplinary cases can be imported at once.")
        company_ids = {int(item.company_id) for item in requests}
        actor_ids = {int(item.created_by_user_id) for item in requests}
        if len(company_ids) != 1 or len(actor_ids) != 1:
            raise ValueError("Every imported disciplinary case must use the same company and administrator.")

        created: list[EmployeeDisciplinaryRecord] = []
        touched: set[tuple[int, int, int]] = set()
        indexed = list(enumerate(requests))
        indexed.sort(key=lambda pair: (pair[1].incident_date, pair[0]))
        try:
            for _index, request in indexed:
                record = self._stage_new_record(request)
                created.append(record)
                if record.employee_id is not None and record.violation_id is not None:
                    touched.add((record.company_id, record.employee_id, record.violation_id))
            for company_id, employee_id, violation_id in touched:
                self._recalculate_offense_progression(
                    company_id=company_id,
                    employee_id=employee_id,
                    violation_id=violation_id,
                )
            self.session.commit()
            for record in created:
                self.session.refresh(record)
            return created
        except Exception:
            self.session.rollback()
            raise

    def update_record(self, values: DisciplinaryRecordUpdateRequest) -> EmployeeDisciplinaryRecord:
        self._require_admin_actor(company_id=values.company_id, user_id=values.edited_by_user_id)
        record = self.repository.get_record(company_id=values.company_id, record_id=values.record_id)
        if record is None:
            raise ValueError("The selected disciplinary record does not belong to this company.")
        if record.archived_at is not None:
            raise ValueError("Restore the disciplinary case from Archive before editing it.")
        issuer = self._company_user(company_id=values.company_id, user_id=values.issued_by_user_id)
        reviewer = self._company_user(
            company_id=values.company_id,
            user_id=values.reviewed_approved_by_user_id,
        )
        status = self._status(values.case_status)
        acknowledgment = self._acknowledgment(values.employee_acknowledgment)
        description = self._clean(values.incident_description, 8000)
        if not description:
            raise ValueError("Incident / Case Description is required.")
        action = self._optional(values.actual_action_taken, 4000)
        self._validate_issue_fields(
            status=status,
            actual_action_taken=action,
            issued_by_user_id=issuer.id if issuer is not None else None,
            date_issued=values.date_issued,
        )

        old_status = record.case_status
        old_snapshot = self._snapshot(record)
        if record.employee_id is not None and record.violation_id is not None:
            previous = self.repository.count_previous_offenses(
                company_id=record.company_id,
                employee_id=record.employee_id,
                violation_id=record.violation_id,
                incident_date=values.incident_date,
                exclude_record_id=record.id,
            )
            record.previous_offense_count = previous
            record.offense_level = self.offense_level(previous)
        record.incident_date = values.incident_date
        record.incident_description = description
        record.evidence_remarks = self._optional(values.evidence_remarks, 12000)
        record.context_snapshot = self._optional(values.context_snapshot, 300)
        record.actual_action_taken = action
        record.issued_by_user_id = issuer.id if issuer is not None else None
        record.reviewed_approved_by_user_id = reviewer.id if reviewer is not None else None
        record.date_issued = values.date_issued
        record.employee_acknowledgment = acknowledgment
        record.case_status = status
        record.notes = self._optional(values.notes, 8000)
        record.last_edited_by_user_id = values.edited_by_user_id

        action_type = "disciplinary_case_updated"
        if status != old_status:
            action_type = f"disciplinary_case_{status.casefold().replace(' ', '_')}"
        self.session.add(
            self._history_row(
                record=record,
                actor_user_id=values.edited_by_user_id,
                action_type=action_type,
                summary=f"Updated disciplinary case {record.public_id}: status {old_status} → {status}.",
                old_values=old_snapshot,
                new_values=self._snapshot(record),
            )
        )
        self.session.flush()
        if record.employee_id is not None and record.violation_id is not None:
            self._recalculate_offense_progression(
                company_id=record.company_id,
                employee_id=record.employee_id,
                violation_id=record.violation_id,
            )
        self._notify_if_issued(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def archive_record(
        self, *, company_id: int, record_id: int, actor_user_id: int
    ) -> str:
        """Move one case to the recoverable Archive instead of deleting it."""

        self._require_admin_actor(company_id=company_id, user_id=actor_user_id)
        record = self.repository.get_record(company_id=company_id, record_id=record_id)
        if record is None:
            raise ValueError("The selected disciplinary case does not exist in this company.")
        if record.archived_at is not None:
            raise ValueError("The selected disciplinary case is already archived.")
        old_snapshot = self._snapshot(record)
        record.archived_at = datetime.now(timezone.utc)
        record.archived_by_user_id = actor_user_id
        record.last_edited_by_user_id = actor_user_id
        self.session.add(
            self._history_row(
                record=record,
                actor_user_id=actor_user_id,
                action_type="disciplinary_case_archived",
                summary=f"Moved disciplinary case {record.public_id} to Archive.",
                old_values=old_snapshot,
                new_values={**self._snapshot(record), "archived": True},
            )
        )
        self.session.flush()
        if record.employee_id is not None and record.violation_id is not None:
            self._recalculate_offense_progression(
                company_id=record.company_id,
                employee_id=record.employee_id,
                violation_id=record.violation_id,
            )
        self.session.commit()
        return record.public_id

    def restore_record(
        self, *, company_id: int, record_id: int, actor_user_id: int
    ) -> str:
        """Restore one archived case without rewriting its factual details."""

        self._require_admin_actor(company_id=company_id, user_id=actor_user_id)
        record = self.repository.get_record(company_id=company_id, record_id=record_id)
        if record is None:
            raise ValueError("The selected disciplinary case does not exist in this company.")
        if record.archived_at is None:
            raise ValueError("The selected disciplinary case is already active.")
        old_snapshot = {**self._snapshot(record), "archived": True}
        record.archived_at = None
        record.archived_by_user_id = None
        record.last_edited_by_user_id = actor_user_id
        self.session.flush()
        if record.employee_id is not None and record.violation_id is not None:
            self._recalculate_offense_progression(
                company_id=record.company_id,
                employee_id=record.employee_id,
                violation_id=record.violation_id,
            )
        self.session.add(
            self._history_row(
                record=record,
                actor_user_id=actor_user_id,
                action_type="disciplinary_case_restored",
                summary=f"Restored disciplinary case {record.public_id} from Archive.",
                old_values=old_snapshot,
                new_values=self._snapshot(record),
            )
        )
        self.session.commit()
        return record.public_id

    @staticmethod
    def _month_bounds(question: str, today: date) -> tuple[date | None, date | None]:
        q = question.casefold()
        if "this month" in q:
            start = today.replace(day=1)
            if start.month == 12:
                end = date(start.year + 1, 1, 1)
            else:
                end = date(start.year, start.month + 1, 1)
            return start, end
        months = {
            name.casefold(): index
            for index, name in enumerate(
                ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
                start=1,
            )
        }
        for name, month in months.items():
            if name in q:
                match = re.search(r"\b(20\d{2})\b", q)
                year = int(match.group(1)) if match else today.year
                start = date(year, month, 1)
                end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
                return start, end
        if "this year" in q:
            return date(today.year, 1, 1), date(today.year + 1, 1, 1)
        return None, None

    @staticmethod
    def _is_record_question(question: str) -> bool:
        q = question.casefold()
        domain = any(term in q for term in ("violation", "disciplinary", "offense", "case"))
        actual = any(
            term in q
            for term in (
                "received", "issued", "record", "records", "case", "cases",
                "who", "employee", "employees", "this month", "this year",
                "january", "february", "march", "april", "may", "june", "july",
                "august", "september", "october", "november", "december",
            )
        )
        master_only = any(term in q for term in ("penalty", "penalties", "what is", "meaning of", "rule for"))
        return domain and actual and not (master_only and "record" not in q and "case" not in q and "issued" not in q)

    def answer_admin_question(self, *, company_id: int, requester_user_id: int, question: str) -> str | None:
        if not self._is_record_question(question):
            return None
        records = self.list_admin_records(company_id=company_id, requester_user_id=requester_user_id)
        q = question.casefold()
        today = datetime.now(ZoneInfo(get_settings().display_timezone)).date()
        start, end = self._month_bounds(question, today)
        use_issued_date = "issued" in q or "received" in q
        if start is not None and end is not None:
            records = [
                item for item in records
                if (item.date_issued if use_issued_date else item.incident_date) is not None
                and start <= (item.date_issued if use_issued_date else item.incident_date) < end
            ]
        code_match = re.search(r"\b[A-Z]{2,}[A-Z0-9._/-]*-\d+[A-Z0-9._/-]*\b", question.upper())
        if code_match:
            code = code_match.group(0)
            # Employee numbers can have the same ABC-001 shape. Only treat the
            # token as a violation-code filter when it is an actual code present
            # in the authorized disciplinary records.
            known_violation_codes = {item.violation_code.upper() for item in records}
            if code in known_violation_codes:
                records = [item for item in records if item.violation_code.upper() == code]

        # Match an explicit employee number or name when present.
        employees = self.employee_repository.list_with_details(company_id)
        matched_employee_ids: set[int] = set()
        for employee in employees:
            number = employee.employee_number.casefold()
            name = employee.full_name.casefold()
            if number in q or (len(name) >= 4 and name in q):
                matched_employee_ids.add(employee.id)
        if matched_employee_ids:
            records = [item for item in records if item.employee_id in matched_employee_ids]
        elif any(
            marker in q
            for marker in ("this employee", "that employee", "same employee", "this person", "that person")
        ):
            return "Please specify the employee number or full name for that disciplinary-record lookup."

        if "how many" in q or "count" in q:
            return f"**{len(records)}** matching disciplinary case(s) were found in the authorized company records."
        if not records:
            return "No matching employee disciplinary records were found in the authorized company records."
        lines = [f"Matching disciplinary records: **{len(records)}**"]
        for item in records[:20]:
            issue_text = item.date_issued.isoformat() if item.date_issued else "Not issued"
            lines.append(
                f"- **{item.employee_number} — {item.employee_name}:** {item.violation_code} — "
                f"{item.violation_title} | Incident {item.incident_date.isoformat()} | "
                f"{item.offense_level} offense | Status {item.case_status} | Issued {issue_text}"
            )
        if len(records) > 20:
            lines.append(f"- Showing 20 of {len(records)} records.")
        return "\n".join(lines)

    def answer_employee_question(
        self,
        *,
        company_id: int,
        employee_id: int | None,
        requester_user_id: int,
        question: str,
    ) -> str | None:
        q = question.casefold()
        if not any(term in q for term in ("disciplinary", "violation", "offense", "case")):
            return None
        case_terms = any(term in q for term in ("record", "records", "case", "cases"))
        personal_terms = any(
            term in q
            for term in ("my", "mine", "ako", "ko", "do i", "i have", "for me", "show me")
        )
        if not case_terms and not ("active" in q and personal_terms):
            return None
        if not personal_terms:
            return (
                "You may only view your own issued disciplinary records. "
                "Ask **Show my disciplinary records** to view your authorized records."
            )
        if not get_settings().employee_disciplinary_records_visible:
            return "Employee access to disciplinary records is currently disabled."
        if employee_id is None:
            return "Your login account is not linked to an employee master record."
        records = self.list_employee_records(
            company_id=company_id,
            employee_id=employee_id,
            requester_user_id=requester_user_id,
        )
        if "active" in q:
            active = [item for item in records if item.case_status == "Issued"]
            if active:
                return f"YES — you have **{len(active)}** active issued disciplinary case(s)."
            return "NO — you have no active issued disciplinary cases."
        if not records:
            return "You have no issued disciplinary records available in the Employee Portal."
        lines = [f"Your issued disciplinary records: **{len(records)}**"]
        for item in records[:20]:
            lines.append(
                f"- **{item.violation_code} — {item.violation_title}:** Incident {item.incident_date.isoformat()} | "
                f"{item.offense_level} offense | Status {item.case_status} | "
                f"Date Issued {item.date_issued.isoformat() if item.date_issued else '—'}"
            )
        return "\n".join(lines)
