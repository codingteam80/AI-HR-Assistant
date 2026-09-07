"""Business rules for company violations and disciplinary-action matrices."""

from __future__ import annotations

from datetime import date, datetime, timezone
import uuid
from zoneinfo import ZoneInfo
import re
from typing import Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.settings import get_settings
from models.hr_policy import HRPolicy
from models.policy_violation import PolicyViolation
from repositories.policy_repository import PolicyRepository
from repositories.policy_violation_repository import PolicyViolationRepository
from repositories.user_repository import UserRepository
from schemas.policy_violation_schema import (
    PolicyViolationCreateRequest,
    PolicyViolationUpdateRequest,
)
from utils.search_utils import text_matches_search_terms


VIOLATION_SEVERITIES = ("Minor", "Moderate", "Major", "Grave")
VIOLATION_STATUSES = ("active", "inactive")


class PolicyViolationService:
    """Manage the violation master list with tenant and publication safety."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = PolicyViolationRepository(session)
        self.policy_repository = PolicyRepository(session)
        self.user_repository = UserRepository(session)

    @staticmethod
    def _clean(value: object, max_length: int) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()[:max_length]

    @classmethod
    def normalize_code(cls, value: object) -> str:
        code = cls._clean(value, 40).upper().replace(" ", "-")
        code = re.sub(r"-+", "-", code)
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{1,39}", code):
            raise ValueError(
                "Violation Code must use letters/numbers and may include -, _, ., or /."
            )
        return code

    @staticmethod
    def public_id_for(item: PolicyViolation) -> str:
        return item.public_id or f"VIO_{item.id:03d}"

    def _require_admin_actor(
        self,
        *,
        company_id: int,
        user_id: int,
    ) -> None:
        user = self.user_repository.get_by_id(
            record_id=user_id,
            company_id=company_id,
        )
        if user is None or not user.is_active or int(user.clearance) != 1:
            raise ValueError(
                "Only an active administrator from this company can manage violation rules."
            )

    @staticmethod
    def _status(value: object) -> str:
        status = str(value or "active").strip().casefold()
        if status not in VIOLATION_STATUSES:
            raise ValueError("Status must be Active or Inactive.")
        return status

    @staticmethod
    def _severity(value: object) -> str:
        raw = str(value or "").strip().casefold()
        lookup = {item.casefold(): item for item in VIOLATION_SEVERITIES}
        if raw not in lookup:
            raise ValueError(
                "Severity must be Minor, Moderate, Major, or Grave."
            )
        return lookup[raw]

    def _related_policy(
        self,
        *,
        company_id: int,
        policy_id: int | None,
    ) -> HRPolicy | None:
        if policy_id in (None, 0):
            return None
        policy = self.policy_repository.get_by_id(
            record_id=int(policy_id),
            company_id=company_id,
        )
        if policy is None:
            raise ValueError("The selected related policy is not in this company.")
        if policy.status == "trashed":
            raise ValueError("Restore the related policy from the Bin before linking it.")
        return policy

    def _validate_unique_code(
        self,
        *,
        company_id: int,
        violation_code: str,
        exclude_id: int | None = None,
    ) -> None:
        existing = self.repository.get_by_code(
            company_id=company_id,
            violation_code=violation_code,
        )
        if existing is not None and existing.id != exclude_id:
            raise ValueError(
                f"Violation Code {violation_code} already exists in this company."
            )

    def _normalized_values(
        self,
        *,
        company_id: int,
        violation_code: object,
        category: object,
        offense_title: object,
        description: object,
        severity: object,
        first_offense_action: object,
        second_offense_action: object,
        third_offense_action: object,
        final_action: object,
        related_policy_id: int | None,
        effective_date: date | None,
        status: object,
        notes: object,
    ) -> dict[str, object]:
        code = self.normalize_code(violation_code)
        category_clean = self._clean(category, 100)
        title = self._clean(offense_title, 200)
        description_clean = self._clean(description, 4000)
        first = self._clean(first_offense_action, 2000)
        second = self._clean(second_offense_action, 2000)
        third = self._clean(third_offense_action, 2000)
        final = self._clean(final_action, 2000)
        notes_clean = self._clean(notes, 4000)

        if not category_clean:
            raise ValueError("Category is required.")
        if not title:
            raise ValueError("Violation / Offense is required.")
        if not description_clean:
            raise ValueError("Description is required.")
        if not all((first, second, third, final)):
            raise ValueError(
                "Enter the disciplinary action for 1st, 2nd, 3rd, and Final / Maximum Action."
            )

        related = self._related_policy(
            company_id=company_id,
            policy_id=related_policy_id,
        )
        return {
            "violation_code": code,
            "category": category_clean,
            "offense_title": title,
            "description": description_clean,
            "severity": self._severity(severity),
            "first_offense_action": first,
            "second_offense_action": second,
            "third_offense_action": third,
            "final_action": final,
            "related_policy_id": related.id if related is not None else None,
            "effective_date": effective_date,
            "status": self._status(status),
            "notes": notes_clean or None,
        }

    def list_current(self, company_id: int) -> list[PolicyViolation]:
        return self.repository.list_current(company_id)

    def list_archived(self, company_id: int) -> list[PolicyViolation]:
        return self.repository.list_archived(company_id)

    def list_employee_visible(
        self,
        *,
        company_id: int,
        as_of_date: date | None = None,
    ) -> list[PolicyViolation]:
        effective_date = as_of_date or datetime.now(
            ZoneInfo(get_settings().display_timezone)
        ).date()
        return self.repository.list_employee_visible(
            company_id=company_id,
            as_of_date=effective_date,
        )

    def create_violation(
        self,
        values: PolicyViolationCreateRequest,
    ) -> PolicyViolation:
        self._require_admin_actor(
            company_id=values.company_id,
            user_id=values.created_by_user_id,
        )
        normalized = self._normalized_values(
            company_id=values.company_id,
            violation_code=values.violation_code,
            category=values.category,
            offense_title=values.offense_title,
            description=values.description,
            severity=values.severity,
            first_offense_action=values.first_offense_action,
            second_offense_action=values.second_offense_action,
            third_offense_action=values.third_offense_action,
            final_action=values.final_action,
            related_policy_id=values.related_policy_id,
            effective_date=values.effective_date,
            status=values.status,
            notes=values.notes,
        )
        self._validate_unique_code(
            company_id=values.company_id,
            violation_code=str(normalized["violation_code"]),
        )
        item = PolicyViolation(
            public_id=f"VIO_{uuid.uuid4().hex[:12].upper()}",
            company_id=values.company_id,
            created_by_user_id=values.created_by_user_id,
            last_edited_by_user_id=values.created_by_user_id,
            **normalized,
        )
        try:
            self.session.add(item)
            self.session.commit()
            self.session.refresh(item)
            return item
        except IntegrityError as error:
            self.session.rollback()
            raise ValueError(
                "The violation could not be saved because its code already exists."
            ) from error


    def create_many(
        self,
        values_list: list[PolicyViolationCreateRequest],
    ) -> list[PolicyViolation]:
        """Create a validated violation batch in one atomic transaction."""

        if not values_list:
            raise ValueError("There are no violation rows ready to import.")

        company_ids = {int(values.company_id) for values in values_list}
        actor_ids = {int(values.created_by_user_id) for values in values_list}
        if len(company_ids) != 1 or len(actor_ids) != 1:
            raise ValueError("Every imported violation must use one company and one administrator.")

        company_id = next(iter(company_ids))
        actor_user_id = next(iter(actor_ids))
        self._require_admin_actor(company_id=company_id, user_id=actor_user_id)

        normalized_rows: list[dict[str, object]] = []
        seen_codes: set[str] = set()
        for values in values_list:
            normalized = self._normalized_values(
                company_id=values.company_id,
                violation_code=values.violation_code,
                category=values.category,
                offense_title=values.offense_title,
                description=values.description,
                severity=values.severity,
                first_offense_action=values.first_offense_action,
                second_offense_action=values.second_offense_action,
                third_offense_action=values.third_offense_action,
                final_action=values.final_action,
                related_policy_id=values.related_policy_id,
                effective_date=values.effective_date,
                status=values.status,
                notes=values.notes,
            )
            code = str(normalized["violation_code"])
            if code in seen_codes:
                raise ValueError(f"Violation Code {code} is duplicated in the import batch.")
            seen_codes.add(code)
            self._validate_unique_code(company_id=company_id, violation_code=code)
            normalized_rows.append(normalized)

        items = [
            PolicyViolation(
                public_id=f"VIO_{uuid.uuid4().hex[:12].upper()}",
                company_id=company_id,
                created_by_user_id=actor_user_id,
                last_edited_by_user_id=actor_user_id,
                **normalized,
            )
            for normalized in normalized_rows
        ]
        try:
            self.session.add_all(items)
            self.session.commit()
            for item in items:
                self.session.refresh(item)
            return items
        except IntegrityError as error:
            self.session.rollback()
            raise ValueError(
                "The violation batch could not be saved because one or more codes already exist."
            ) from error

    def update_violation(
        self,
        values: PolicyViolationUpdateRequest,
    ) -> PolicyViolation:
        self._require_admin_actor(
            company_id=values.company_id,
            user_id=values.edited_by_user_id,
        )
        item = self.repository.get_violation(
            company_id=values.company_id,
            violation_id=values.violation_id,
        )
        if item is None:
            raise ValueError("The selected violation does not belong to this company.")
        if item.archived_at is not None:
            raise ValueError("Restore this violation before editing it.")

        normalized = self._normalized_values(
            company_id=values.company_id,
            violation_code=values.violation_code,
            category=values.category,
            offense_title=values.offense_title,
            description=values.description,
            severity=values.severity,
            first_offense_action=values.first_offense_action,
            second_offense_action=values.second_offense_action,
            third_offense_action=values.third_offense_action,
            final_action=values.final_action,
            related_policy_id=values.related_policy_id,
            effective_date=values.effective_date,
            status=values.status,
            notes=values.notes,
        )
        self._validate_unique_code(
            company_id=values.company_id,
            violation_code=str(normalized["violation_code"]),
            exclude_id=item.id,
        )
        for field_name, field_value in normalized.items():
            setattr(item, field_name, field_value)
        item.last_edited_by_user_id = values.edited_by_user_id
        try:
            self.session.commit()
            self.session.refresh(item)
            return item
        except IntegrityError as error:
            self.session.rollback()
            raise ValueError(
                "The violation could not be updated because its code already exists."
            ) from error

    def archive_violation(
        self,
        *,
        company_id: int,
        violation_id: int,
        archived_by_user_id: int,
    ) -> PolicyViolation:
        self._require_admin_actor(
            company_id=company_id,
            user_id=archived_by_user_id,
        )
        item = self.repository.get_violation(
            company_id=company_id,
            violation_id=violation_id,
        )
        if item is None:
            raise ValueError("The selected violation does not belong to this company.")
        if item.archived_at is not None:
            raise ValueError("The selected violation is already archived.")
        item.archived_at = datetime.now(timezone.utc)
        item.archived_by_user_id = archived_by_user_id
        item.last_edited_by_user_id = archived_by_user_id
        self.session.commit()
        self.session.refresh(item)
        return item

    def restore_violation(
        self,
        *,
        company_id: int,
        violation_id: int,
        restored_by_user_id: int,
    ) -> PolicyViolation:
        self._require_admin_actor(
            company_id=company_id,
            user_id=restored_by_user_id,
        )
        item = self.repository.get_violation(
            company_id=company_id,
            violation_id=violation_id,
        )
        if item is None:
            raise ValueError("The selected violation does not belong to this company.")
        if item.archived_at is None:
            raise ValueError("The selected violation is not archived.")
        item.archived_at = None
        item.archived_by_user_id = None
        item.last_edited_by_user_id = restored_by_user_id
        self.session.commit()
        self.session.refresh(item)
        return item

    def related_policy_label(
        self,
        *,
        company_id: int,
        violation: PolicyViolation,
    ) -> str:
        if violation.related_policy_id is None:
            return "—"
        policy = self.policy_repository.get_by_id(
            record_id=violation.related_policy_id,
            company_id=company_id,
        )
        if policy is None or policy.status != "published":
            return "Unavailable / not published"
        today = datetime.now(ZoneInfo(get_settings().display_timezone)).date()
        if policy.effective_date is not None and policy.effective_date > today:
            return "Policy not yet effective"
        return f"{policy.title} · v{policy.version}"

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", (value or "").casefold())
            if len(token) > 1
        }

    def answer_question(
        self,
        *,
        company_id: int,
        question: str,
        as_of_date: date | None = None,
    ) -> str | None:
        """Return a deterministic answer from active/effective violation rules."""

        query = str(question or "").strip()
        if not query:
            return None
        items = self.list_employee_visible(
            company_id=company_id,
            as_of_date=as_of_date,
        )
        if not items:
            return None

        normalized = query.casefold()
        code_match = None
        for item in items:
            if item.violation_code.casefold() in normalized:
                code_match = item
                break

        severity_filter = next(
            (
                severity
                for severity in VIOLATION_SEVERITIES
                if re.search(rf"\b{re.escape(severity.casefold())}\b", normalized)
            ),
            None,
        )

        list_request = bool(
            re.search(
                r"\b(list|show|what are|which|violations|offenses)\b",
                normalized,
            )
        )
        if code_match is None and re.search(r"\b(how many|count)\b", normalized):
            if severity_filter:
                count = sum(1 for item in items if item.severity == severity_filter)
                return f"**{count}** active {severity_filter} violation(s) are currently configured."
            return f"**{len(items)}** active company violation(s) are currently configured."
        if code_match is None and severity_filter and list_request:
            matched = [item for item in items if item.severity == severity_filter]
            if not matched:
                return f"No active {severity_filter} violations are currently configured."
            lines = [f"Active **{severity_filter}** violations:"]
            for item in matched[:25]:
                lines.append(
                    f"- **{item.violation_code} — {item.offense_title}:** {item.description}"
                )
            return "\n".join(lines)

        if code_match is None:
            query_tokens = self._tokens(query) - {
                "what", "which", "show", "list", "tell", "about", "company",
                "policy", "policies", "violation", "violations", "offense",
                "offenses", "penalty", "penalties", "disciplinary", "action",
                "actions", "first", "second", "third", "final", "maximum",
                "for", "the", "and", "does", "happen", "happens",
            }
            scored: list[tuple[int, PolicyViolation]] = []
            for item in items:
                title_tokens = self._tokens(
                    " ".join(
                        (
                            item.violation_code,
                            item.offense_title,
                            item.category,
                            item.description,
                        )
                    )
                )
                score = len(query_tokens & title_tokens)
                if score:
                    scored.append((score, item))
            scored.sort(
                key=lambda pair: (
                    pair[0],
                    -len(pair[1].offense_title),
                ),
                reverse=True,
            )
            if scored and (
                scored[0][0] >= 2
                or len(query_tokens) <= 2
            ):
                code_match = scored[0][1]

        if code_match is not None and re.match(
            r"^\s*(?:is|are|was|were)\b", normalized
        ):
            if severity_filter is not None:
                matches = code_match.severity == severity_filter
                if matches:
                    return (
                        f"**YES.** {code_match.violation_code} — "
                        f"{code_match.offense_title} is classified as "
                        f"**{code_match.severity}**."
                    )
                return (
                    f"**NO.** {code_match.violation_code} — "
                    f"{code_match.offense_title} is classified as "
                    f"**{code_match.severity}**, not {severity_filter}."
                )

            if re.search(r"\binactive\b", normalized):
                return (
                    f"**NO.** {code_match.violation_code} — "
                    f"{code_match.offense_title} is currently an "
                    "active/effective company violation rule."
                )
            if re.search(r"\bactive\b", normalized):
                return (
                    f"**YES.** {code_match.violation_code} — "
                    f"{code_match.offense_title} is an active/effective "
                    "company violation rule."
                )

        if code_match is None:
            if list_request and re.search(r"\b(violation|offense)s?\b", normalized):
                lines = ["Active company violations:"]
                for item in items[:25]:
                    lines.append(
                        f"- **{item.violation_code} — {item.offense_title}:** "
                        f"{item.severity} · {item.category}"
                    )
                return "\n".join(lines)
            return None

        item = code_match
        if re.search(r"\b(1st|first)\b", normalized):
            return (
                f"**{item.violation_code} — {item.offense_title}**: "
                f"1st offense action is **{item.first_offense_action}**."
            )
        if re.search(r"\b(2nd|second)\b", normalized):
            return (
                f"**{item.violation_code} — {item.offense_title}**: "
                f"2nd offense action is **{item.second_offense_action}**."
            )
        if re.search(r"\b(3rd|third)\b", normalized):
            return (
                f"**{item.violation_code} — {item.offense_title}**: "
                f"3rd offense action is **{item.third_offense_action}**."
            )
        if re.search(r"\b(final|maximum|max)\b", normalized):
            return (
                f"**{item.violation_code} — {item.offense_title}**: "
                f"Final / maximum action is **{item.final_action}**."
            )

        return (
            f"**{item.violation_code} — {item.offense_title}**\n"
            f"- **Category:** {item.category}\n"
            f"- **Severity:** {item.severity}\n"
            f"- **Description:** {item.description}\n"
            f"- **1st Offense:** {item.first_offense_action}\n"
            f"- **2nd Offense:** {item.second_offense_action}\n"
            f"- **3rd Offense:** {item.third_offense_action}\n"
            f"- **Final / Maximum Action:** {item.final_action}"
        )

    def searchable_text(self, item: PolicyViolation) -> str:
        return " ".join(
            str(value or "")
            for value in (
                item.violation_code,
                item.category,
                item.offense_title,
                item.description,
                item.severity,
                item.first_offense_action,
                item.second_offense_action,
                item.third_offense_action,
                item.final_action,
                getattr(item, "effective_date", None),
                item.status,
                getattr(item, "related_policy_id", None),
                item.notes,
            )
        ).casefold()

    def filter_items(
        self,
        items: Iterable[PolicyViolation],
        *,
        search_text: object = "",
        category: str | None = None,
        severity: str | None = None,
        status: str | None = None,
    ) -> list[PolicyViolation]:
        output: list[PolicyViolation] = []
        for item in items:
            if category and item.category != category:
                continue
            if severity and item.severity != severity:
                continue
            if status and item.status != status:
                continue
            if not text_matches_search_terms(search_text, self.searchable_text(item)):
                continue
            output.append(item)
        return output
