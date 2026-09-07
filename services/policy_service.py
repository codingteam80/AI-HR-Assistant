"""Business logic for file-based policy management and Policy Q&A.

Employee answers use only:
- The authenticated company
- Active published policy versions
- Versions not stored in the Bin
- Text extracted from the uploaded source file

No outside knowledge or generative model is used in this version.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.hr_policy import HRPolicy
from models.hr_policy_document import HRPolicyDocument
from models.hr_policy_section import HRPolicySection
from models.policy_violation import PolicyViolation
from modules.documents.policy_file_parser import (
    ParsedPolicyDocument,
    PolicyFileParser,
)
from modules.documents.policy_file_storage import (
    PolicyFileStorage,
)
from repositories.policy_document_repository import (
    PolicyDocumentRepository,
)
from repositories.policy_repository import PolicyRepository
from repositories.policy_section_repository import (
    PolicySectionRepository,
)
from schemas.policy_schema import (
    PolicyCreateRequest,
    PolicyMetadataUpdate,
    PolicyPermanentDeleteRequest,
    PolicyUploadRequest,
)
from utils.search_utils import normalize_search_terms, text_matches_search_terms


POLICY_STATUSES = {"draft", "published", "archived", "trashed"}

NO_POLICY_ANSWER = (
    "Information not found in approved company policies."
)

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "can",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "may",
    "my",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}

# Generic company/policy words are not sufficient evidence that a policy
# actually covers the user's requested subject.  This prevents a nearest
# Leave Policy from answering an unrelated query such as ``Laptop policy``.
_POLICY_GENERIC_QUERY_TERMS = {
    "company", "detail", "details", "employee", "employees", "information",
    "policy", "policies", "rule", "rules",
}


@dataclass(slots=True)
class PolicySource:
    """One approved source reference shown with an answer."""

    policy_id: int
    title: str
    category: str
    version: str
    effective_date: date | None
    uploaded_at: datetime | None
    section_heading: str
    filename: str | None = None
    page_number: int | None = None


@dataclass(slots=True)
class PolicyAnswer:
    """Direct extracted answer and its approved file sources."""

    answer: str
    sources: list[PolicySource]
    matched: bool


@dataclass(slots=True)
class PolicyFileDownload:
    """Authorized file bytes returned to a Streamlit download button."""

    filename: str
    mime_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class PolicyPermanentDeleteResult:
    """Summary returned after one Bin version is permanently removed."""

    policy_id: int
    public_id: str
    title: str
    version: str
    original_filename: str | None
    file_removed: bool


@dataclass(slots=True)
class PolicyContentSection:
    """One section displayed in the administrator content viewer."""

    sequence_number: int
    heading: str
    text: str
    page_number: int | None


@dataclass(slots=True)
class PolicyAdminView:
    """Company-authorized policy metadata and extracted content."""

    policy: HRPolicy
    document: HRPolicyDocument | None
    extracted_text: str
    sections: list[PolicyContentSection]
    source_type: str



@dataclass(slots=True)
class PolicyVersionRecord:
    """One previous version shown during upload and management."""

    policy_id: int
    public_id: str
    title: str
    version: str
    uploaded_at: datetime | None
    in_bin: bool


@dataclass(slots=True)
class PolicyUploadPreview:
    """Parsed upload preview plus automatic metadata suggestions."""

    parsed: ParsedPolicyDocument
    display_title: str
    suggested_category: str
    previous_versions: list[PolicyVersionRecord]
    latest_version: str | None


@dataclass(slots=True)
class _SearchableSection:
    """Internal normalized search candidate."""

    policy: HRPolicy
    heading: str
    text: str
    filename: str | None
    page_number: int | None


class PolicyService:
    """Manage policies, uploaded files, publication, and Q&A."""

    def __init__(
        self,
        session: Session,
        *,
        storage: PolicyFileStorage | None = None,
    ) -> None:
        self.session = session
        self.repository = PolicyRepository(session)
        self.document_repository = PolicyDocumentRepository(
            session
        )
        self.section_repository = PolicySectionRepository(
            session
        )
        self.storage = storage or PolicyFileStorage()

    @staticmethod
    def _normalize_spaces(value: str) -> str:
        """Collapse repeated whitespace for metadata and answers."""

        return re.sub(r"\s+", " ", value).strip()


    @staticmethod
    def public_id_for(policy: HRPolicy) -> str:
        """Return the stable user-facing ID for old and new rows."""

        return policy.public_id or f"PID_{policy.id:03d}"

    @staticmethod
    def format_datetime(
        value: datetime | None,
        timezone_name: str = "Asia/Manila",
    ) -> str:
        """Format a stored timestamp with date, time, and configured zone."""

        if value is None:
            return "—"

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            zone = timezone.utc

        return value.astimezone(zone).strftime("%Y-%m-%d %I:%M %p")

    @classmethod
    def title_from_filename(cls, filename: str) -> str:
        """Create a readable policy title from the uploaded filename."""

        stem = Path(filename or "policy").stem
        stem = re.sub(r"[_-]+", " ", stem)
        stem = re.sub(
            r"\s+(?:v|ver|version|rev|revision)\s*\d+(?:[._-]\d+)*$",
            "",
            stem,
            flags=re.IGNORECASE,
        )
        stem = re.sub(r"\s+(?:final|copy)$", "", stem, flags=re.IGNORECASE)
        stem = cls._normalize_spaces(stem)

        if not stem:
            return "Uploaded Policy"

        return stem.title()[:200]

    @classmethod
    def _title_key(cls, value: str) -> str:
        return "".join(re.findall(r"[a-z0-9]+", value.lower()))

    @classmethod
    def suggest_category(
        cls,
        parsed: ParsedPolicyDocument,
        display_title: str,
    ) -> str:
        """Suggest an editable grouping label from headings or filename."""

        generic = {
            "policy details", "overview", "introduction", "purpose",
            "scope", "definitions", "general", "document",
        }

        for section in parsed.sections[:12]:
            heading = cls._normalize_spaces(section.heading).strip(" :-")
            lowered = heading.lower()

            if (
                not heading
                or lowered in generic
                or lowered.startswith("page ")
                or lowered.startswith("table ")
                or len(heading) > 100
            ):
                continue

            heading = re.sub(r"^\d+(?:\.\d+)*[.)]?\s*", "", heading)
            return heading.title()[:100]

        fallback = re.sub(
            r"\b(policy|guidelines?|procedures?|manual|handbook|rules?)\b",
            "",
            display_title,
            flags=re.IGNORECASE,
        )
        fallback = cls._normalize_spaces(fallback).strip(" -")
        return (fallback or "General")[:100]

    def _matching_canonical_title(
        self,
        *,
        company_id: int,
        derived_title: str,
    ) -> str:
        key = self._title_key(derived_title)

        for policy in self.repository.list_all_versions(company_id):
            if self._title_key(policy.title) == key:
                return policy.title

        return derived_title

    def version_history(
        self,
        *,
        company_id: int,
        title: str,
    ) -> list[PolicyVersionRecord]:
        return [
            PolicyVersionRecord(
                policy_id=policy.id,
                public_id=self.public_id_for(policy),
                title=policy.title,
                version=policy.version,
                uploaded_at=policy.created_at,
                in_bin=policy.status == "trashed",
            )
            for policy in self.repository.list_by_title(
                company_id=company_id,
                title=title,
            )
        ]

    def preview_policy_upload(
        self,
        *,
        company_id: int,
        filename: str,
        file_bytes: bytes,
        maximum_size_bytes: int,
        mime_type: str | None = None,
        selected_existing_title: str | None = None,
    ) -> PolicyUploadPreview:
        """Parse once for preview and resolve title/version history."""

        parsed = PolicyFileParser.parse(
            filename=filename,
            file_bytes=file_bytes,
            maximum_size_bytes=maximum_size_bytes,
            supplied_mime_type=mime_type,
        )
        derived = self.title_from_filename(parsed.original_filename)
        display_title = (
            self._normalize_spaces(selected_existing_title)
            if selected_existing_title
            else self._matching_canonical_title(
                company_id=company_id,
                derived_title=derived,
            )
        )
        previous = self.version_history(
            company_id=company_id,
            title=display_title,
        )

        return PolicyUploadPreview(
            parsed=parsed,
            display_title=display_title,
            suggested_category=self.suggest_category(parsed, display_title),
            previous_versions=previous,
            latest_version=(previous[0].version if previous else None),
        )

    @staticmethod
    def _tokens(value: str) -> set[str]:
        """Return meaningful lowercase search tokens."""

        raw_tokens = re.findall(
            r"[a-z0-9]+",
            value.lower(),
        )

        return {
            token
            for token in raw_tokens
            if len(token) >= 2
            and token not in _STOP_WORDS
        }

    @classmethod
    def _topic_terms(cls, value: str) -> set[str]:
        """Return lightly stemmed subject terms for fail-closed topic matching."""

        terms: set[str] = set()
        for token in cls._tokens(value):
            if token in _POLICY_GENERIC_QUERY_TERMS:
                continue
            stem = token
            if stem.endswith("ies") and len(stem) > 5:
                stem = stem[:-3] + "y"
            else:
                for suffix in ("ingly", "edly", "ing", "ed", "es", "s"):
                    if stem.endswith(suffix) and len(stem) - len(suffix) >= 4:
                        stem = stem[:-len(suffix)]
                        break
            terms.add(stem)
        return terms

    @classmethod
    def _topic_is_supported(
        cls,
        *,
        question: str,
        section: _SearchableSection,
    ) -> bool:
        """Require the best section to cover the question's specific subject."""

        anchors = cls._topic_terms(question)
        if not anchors:
            return True
        policy = section.policy
        evidence_terms = cls._topic_terms(
            " ".join(
                [
                    policy.title or "",
                    policy.category or "",
                    policy.summary or "",
                    section.heading or "",
                    section.text or "",
                ]
            )
        )
        matched = anchors.intersection(evidence_terms)
        if len(anchors) == 1:
            return len(matched) == 1
        if len(anchors) == 2:
            return len(matched) == 2
        return len(matched) >= 2 and (len(matched) / len(anchors)) >= 0.50

    @staticmethod
    def _manual_sections(
        policy: HRPolicy,
    ) -> list[_SearchableSection]:
        """Keep old v8.0 manually entered policies backward-compatible."""

        sections: list[_SearchableSection] = []
        heading = "Policy Details"
        lines: list[str] = []

        def flush() -> None:
            text = "\n".join(lines).strip()

            if text:
                sections.append(
                    _SearchableSection(
                        policy=policy,
                        heading=heading,
                        text=text,
                        filename=None,
                        page_number=None,
                    )
                )

            lines.clear()

        for raw_line in policy.content.splitlines():
            line = raw_line.strip()

            if (
                line.startswith("#")
                or (
                    line.endswith(":")
                    and len(line) <= 140
                )
            ):
                flush()
                heading = (
                    line.lstrip("#").strip().rstrip(":")
                    or "Policy Details"
                )
            else:
                lines.append(line)

        flush()

        if not sections and policy.content.strip():
            sections.append(
                _SearchableSection(
                    policy=policy,
                    heading="Policy Details",
                    text=policy.content.strip(),
                    filename=None,
                    page_number=None,
                )
            )

        return sections


    def create_policy(self, values: PolicyCreateRequest) -> HRPolicy:
        """Preserve the manual API for compatibility and tests."""

        title = self._normalize_spaces(values.title)
        version = self._normalize_spaces(values.version)

        if self.repository.get_by_title_version(
            company_id=values.company_id,
            title=title,
            version=version,
        ):
            raise ValueError(
                "The same policy title and version already exist "
                "inside this company."
            )

        status = "published" if values.publish_immediately else "draft"
        policy = HRPolicy(
            company_id=values.company_id,
            created_by_user_id=values.created_by_user_id,
            title=title,
            category=self._normalize_spaces(values.category),
            summary=(self._normalize_spaces(values.summary) if values.summary else None),
            content=values.content.strip(),
            version=version,
            status=status,
            effective_date=values.effective_date,
            published_at=(datetime.now(timezone.utc) if status == "published" else None),
        )
        self.session.add(policy)
        self.session.flush()
        policy.public_id = f"PID_{policy.id:03d}"
        self.session.commit()
        self.session.refresh(policy)
        return policy


    def create_policy_from_upload(
        self,
        *,
        values: PolicyUploadRequest,
        filename: str,
        file_bytes: bytes,
        mime_type: str | None = None,
        maximum_size_bytes: int,
    ) -> HRPolicy:
        """Parse, store, index, and immediately publish one file version."""

        title = self._normalize_spaces(values.title)
        category = self._normalize_spaces(values.category)
        version = self._normalize_spaces(values.version)

        if self.repository.get_by_title_version(
            company_id=values.company_id,
            title=title,
            version=version,
        ):
            raise ValueError(
                "The same policy title and version already exist "
                "inside this company."
            )

        parsed = PolicyFileParser.parse(
            filename=filename,
            file_bytes=file_bytes,
            maximum_size_bytes=maximum_size_bytes,
            supplied_mime_type=mime_type,
        )
        duplicate = self.document_repository.get_by_hash(
            company_id=values.company_id,
            sha256=parsed.sha256,
        )
        if duplicate is not None:
            raise ValueError(
                "This exact file has already been uploaded for the company."
            )

        stored = self.storage.save(
            company_id=values.company_id,
            original_filename=parsed.original_filename,
            file_bytes=file_bytes,
        )
        now = datetime.now(timezone.utc)
        generated_summary = self._normalize_spaces(parsed.full_text)[:1000] or None

        try:
            policy = HRPolicy(
                company_id=values.company_id,
                created_by_user_id=values.created_by_user_id,
                title=title,
                category=category,
                summary=generated_summary,
                content=parsed.full_text,
                version=version,
                status="published",
                effective_date=None,
                published_at=now,
            )
            self.session.add(policy)
            self.session.flush()
            policy.public_id = f"PID_{policy.id:03d}"

            document = HRPolicyDocument(
                company_id=values.company_id,
                policy_id=policy.id,
                uploaded_by_user_id=values.created_by_user_id,
                original_filename=parsed.original_filename,
                stored_filename=stored.stored_filename,
                storage_path=stored.relative_path,
                mime_type=parsed.mime_type,
                file_extension=parsed.file_extension,
                sha256=parsed.sha256,
                size_bytes=parsed.size_bytes,
                page_count=parsed.page_count,
                extracted_text=parsed.full_text,
            )
            self.session.add(document)
            self.session.flush()

            for sequence_number, section in enumerate(parsed.sections, start=1):
                self.session.add(HRPolicySection(
                    company_id=values.company_id,
                    policy_id=policy.id,
                    document_id=document.id,
                    sequence_number=sequence_number,
                    heading=section.heading,
                    text=section.text,
                    page_number=section.page_number,
                ))

            self.session.commit()
            self.session.refresh(policy)
            return policy
        except Exception:
            self.session.rollback()
            self.storage.delete(stored.relative_path)
            raise

    def list_for_admin(self, company_id: int) -> list[HRPolicy]:
        """Return active company policy versions."""
        return self.repository.list_for_admin(company_id)

    def list_bin(self, company_id: int) -> list[HRPolicy]:
        """Return retained policy versions stored in the Bin."""
        return self.repository.list_bin(company_id)

    def list_all_versions(self, company_id: int) -> list[HRPolicy]:
        return self.repository.list_all_versions(company_id)

    def list_published(
        self,
        company_id: int,
    ) -> list[HRPolicy]:
        """Return approved, effective policies for employees."""

        return self.repository.list_published(
            company_id=company_id,
            as_of_date=date.today(),
        )

    def get_document_map(
        self,
        *,
        company_id: int,
        policies: list[HRPolicy],
    ) -> dict[int, HRPolicyDocument]:
        """Return policy ID to source-file metadata."""

        documents = self.document_repository.list_for_policies(
            company_id=company_id,
            policy_ids=[
                policy.id
                for policy in policies
            ],
        )

        return {
            document.policy_id: document
            for document in documents
        }

    def get_admin_policy_view(
        self,
        *,
        company_id: int,
        policy_id: int,
    ) -> PolicyAdminView:
        """Return policy content only after company ownership validation.

        Uploaded policies use the persisted extracted document text and
        searchable section records. Older v8.0 manual entries remain
        viewable through the same administrator interface.
        """

        policy = self.repository.get_by_id(
            record_id=policy_id,
            company_id=company_id,
        )

        if policy is None:
            raise ValueError(
                "The selected policy does not belong "
                "to this company."
            )

        document = self.document_repository.get_by_policy(
            company_id=company_id,
            policy_id=policy_id,
        )

        if document is not None:
            stored_sections = (
                self.section_repository.list_for_document(
                    company_id=company_id,
                    document_id=document.id,
                )
            )

            sections = [
                PolicyContentSection(
                    sequence_number=section.sequence_number,
                    heading=section.heading,
                    text=section.text,
                    page_number=section.page_number,
                )
                for section in stored_sections
            ]

            extracted_text = document.extracted_text
            source_type = "uploaded_file"

        else:
            manual_sections = self._manual_sections(policy)

            sections = [
                PolicyContentSection(
                    sequence_number=index,
                    heading=section.heading,
                    text=section.text,
                    page_number=section.page_number,
                )
                for index, section in enumerate(
                    manual_sections,
                    start=1,
                )
            ]

            extracted_text = policy.content
            source_type = "manual_entry"

        return PolicyAdminView(
            policy=policy,
            document=document,
            extracted_text=extracted_text,
            sections=sections,
            source_type=source_type,
        )

    def get_policy_download(
        self,
        *,
        company_id: int,
        policy_id: int,
        published_only: bool,
    ) -> PolicyFileDownload:
        """Return file bytes only after company and publication checks."""

        policy = self.repository.get_by_id(
            record_id=policy_id,
            company_id=company_id,
        )

        if policy is None:
            raise ValueError(
                "The selected policy does not belong "
                "to this company."
            )

        if published_only:
            if policy.status != "published":
                raise ValueError(
                    "The policy is not published."
                )

            if (
                policy.effective_date
                and policy.effective_date > date.today()
            ):
                raise ValueError(
                    "The policy is not effective yet."
                )

        document = self.document_repository.get_by_policy(
            company_id=company_id,
            policy_id=policy_id,
        )

        if document is None:
            raise ValueError(
                "This policy does not have an uploaded source file."
            )

        return PolicyFileDownload(
            filename=document.original_filename,
            mime_type=document.mime_type,
            data=self.storage.read(
                document.storage_path
            ),
        )


    def update_policy_metadata(
        self,
        values: PolicyMetadataUpdate,
    ) -> HRPolicy:
        """Update one policy version while preserving its family history.

        Title and category are policy-family metadata, so they are applied to
        all versions currently sharing the selected title. Version and edited
        content apply only to the selected record. The original uploaded file
        remains unchanged while database text and searchable sections are
        regenerated.
        """

        policy = self.repository.get_by_id(
            record_id=values.policy_id,
            company_id=values.company_id,
        )

        if policy is None:
            raise ValueError(
                "The selected policy does not belong to this company."
            )

        if policy.status == "trashed":
            raise ValueError(
                "Restore the policy from the Bin before editing it."
            )

        new_title = self._normalize_spaces(values.title)
        new_category = self._normalize_spaces(values.category)
        new_version = self._normalize_spaces(values.version)
        old_title = policy.title

        edited_content: str | None = None
        edited_sections = []

        if values.content is not None:
            (
                edited_content,
                edited_sections,
            ) = PolicyFileParser.parse_edited_content(
                content=values.content,
                default_heading=new_title,
            )

        family = self.repository.list_by_title(
            company_id=values.company_id,
            title=old_title,
        )
        family_ids = {item.id for item in family}

        # Do not silently merge two different policy families.
        if new_title != old_title:
            target_family = self.repository.list_by_title(
                company_id=values.company_id,
                title=new_title,
            )

            if any(
                item.id not in family_ids
                for item in target_family
            ):
                raise ValueError(
                    "Another policy already uses this title. "
                    "Choose a different policy title."
                )

        for item in family:
            target_version = (
                new_version
                if item.id == policy.id
                else item.version
            )
            conflict = self.repository.get_by_title_version(
                company_id=values.company_id,
                title=new_title,
                version=target_version,
            )

            if (
                conflict is not None
                and conflict.id != item.id
            ):
                raise ValueError(
                    "The selected policy title and version already exist."
                )

        try:
            for item in family:
                item.title = new_title
                item.category = new_category

                if item.id == policy.id:
                    item.version = new_version

            if edited_content is not None:
                policy.content = edited_content
                policy.summary = (
                    self._normalize_spaces(
                        edited_content
                    )[:1000]
                    or None
                )

                document = (
                    self.document_repository.get_by_policy(
                        company_id=values.company_id,
                        policy_id=policy.id,
                    )
                )

                if document is not None:
                    # Preserve original file metadata, hash, and storage path.
                    # Only approved searchable database text is replaced.
                    document.extracted_text = edited_content

                    self.session.execute(
                        delete(HRPolicySection).where(
                            HRPolicySection.company_id
                            == values.company_id,
                            HRPolicySection.policy_id
                            == policy.id,
                            HRPolicySection.document_id
                            == document.id,
                        )
                    )
                    self.session.flush()

                    for sequence_number, section in enumerate(
                        edited_sections,
                        start=1,
                    ):
                        self.session.add(
                            HRPolicySection(
                                company_id=values.company_id,
                                policy_id=policy.id,
                                document_id=document.id,
                                sequence_number=sequence_number,
                                heading=section.heading,
                                text=section.text,
                                # Edited content is not guaranteed to match
                                # the original file's page positions.
                                page_number=None,
                            )
                        )

            self.session.commit()
            self.session.refresh(policy)
            return policy
        except IntegrityError as error:
            self.session.rollback()
            raise ValueError(
                "The selected policy title and version already exist."
            ) from error

    def permanently_delete_from_bin(
        self,
        values: PolicyPermanentDeleteRequest,
    ) -> PolicyPermanentDeleteResult:
        """Permanently remove one exact policy version from the Bin.

        The original file, extracted document row, searchable sections, and
        policy row are removed. Other versions sharing the same title remain.
        """

        policy = self.repository.get_by_id(
            record_id=values.policy_id,
            company_id=values.company_id,
        )

        if policy is None:
            raise ValueError(
                "The selected policy does not belong to this company."
            )

        if policy.status != "trashed":
            raise ValueError(
                "Only policy versions stored in the Bin can be "
                "permanently deleted."
            )

        public_id = self.public_id_for(policy)

        if (
            values.confirmation_public_id.strip()
            != public_id
        ):
            raise ValueError(
                "The confirmation Policy ID does not match."
            )

        if not values.permanent_delete_acknowledged:
            raise ValueError(
                "Confirm that the policy version will be permanently "
                "deleted."
            )

        document = self.document_repository.get_by_policy(
            company_id=values.company_id,
            policy_id=policy.id,
        )
        storage_path = (
            document.storage_path
            if document is not None
            else None
        )
        original_filename = (
            document.original_filename
            if document is not None
            else None
        )

        result = PolicyPermanentDeleteResult(
            policy_id=policy.id,
            public_id=public_id,
            title=policy.title,
            version=policy.version,
            original_filename=original_filename,
            file_removed=storage_path is not None,
        )

        try:
            # Keep violation rules valid if their source policy version is
            # permanently removed. The rule remains, but its optional policy
            # link is cleared instead of causing a foreign-key failure.
            linked_violations = self.session.scalars(
                select(PolicyViolation).where(
                    PolicyViolation.company_id == values.company_id,
                    PolicyViolation.related_policy_id == policy.id,
                )
            ).all()
            for violation in linked_violations:
                violation.related_policy_id = None

            self.session.flush()
            self.session.execute(
                delete(HRPolicySection).where(
                    HRPolicySection.company_id
                    == values.company_id,
                    HRPolicySection.policy_id
                    == policy.id,
                )
            )
            self.session.execute(
                delete(HRPolicyDocument).where(
                    HRPolicyDocument.company_id
                    == values.company_id,
                    HRPolicyDocument.policy_id
                    == policy.id,
                )
            )
            self.session.execute(
                delete(HRPolicy).where(
                    HRPolicy.company_id
                    == values.company_id,
                    HRPolicy.id == policy.id,
                    HRPolicy.status == "trashed",
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        if storage_path is not None:
            self.storage.delete(storage_path)

        return result


    def set_status(self, *, company_id: int, policy_id: int, status: str) -> HRPolicy:
        """Legacy compatibility status API."""
        normalized_status = status.strip().lower()
        if normalized_status not in POLICY_STATUSES:
            raise ValueError("Unsupported policy status.")
        published_at = datetime.now(timezone.utc) if normalized_status == "published" else None
        policy = self.repository.update_status(
            company_id=company_id,
            policy_id=policy_id,
            status=normalized_status,
            published_at=published_at,
        )
        if policy is None:
            raise ValueError("The selected policy does not belong to this company.")
        return policy

    def move_to_bin(
        self,
        *,
        company_id: int,
        policy_id: int,
        user_id: int,
        confirmation_public_id: str,
    ) -> HRPolicy:
        policy = self.repository.get_by_id(record_id=policy_id, company_id=company_id)
        if policy is None:
            raise ValueError("The selected policy does not belong to this company.")
        if policy.status == "trashed":
            raise ValueError("The selected policy is already in the Bin.")
        if confirmation_public_id.strip() != self.public_id_for(policy):
            raise ValueError("The confirmation Policy ID does not match.")
        moved = self.repository.move_to_bin(
            company_id=company_id,
            policy_id=policy_id,
            user_id=user_id,
            moved_at=datetime.now(timezone.utc),
        )
        if moved is None:
            raise ValueError("The selected policy could not be moved to the Bin.")
        return moved

    def restore_from_bin(
        self,
        *,
        company_id: int,
        policy_id: int,
    ) -> HRPolicy:
        policy = self.repository.get_by_id(record_id=policy_id, company_id=company_id)
        if policy is None:
            raise ValueError("The selected policy does not belong to this company.")
        if policy.status != "trashed":
            raise ValueError("The selected policy is not in the Bin.")
        restored = self.repository.restore_from_bin(
            company_id=company_id,
            policy_id=policy_id,
            restored_at=datetime.now(timezone.utc),
        )
        if restored is None:
            raise ValueError("The selected policy could not be restored.")
        return restored

    def search_published(
        self,
        *,
        company_id: int,
        search_text: object = "",
        category: str | None = None,
    ) -> list[HRPolicy]:
        """Search approved policies with one or more free-text OR terms."""

        policies = self.list_published(company_id)
        search_terms = normalize_search_terms(search_text)
        normalized_category = (
            category.strip().lower()
            if category
            else None
        )

        documents = self.get_document_map(
            company_id=company_id,
            policies=policies,
        )
        results = []

        for policy in policies:
            if (
                normalized_category
                and policy.category.lower()
                != normalized_category
            ):
                continue

            document = documents.get(policy.id)
            searchable = " ".join(
                str(value or "")
                for value in (
                    self.public_id_for(policy),
                    policy.title,
                    policy.category,
                    policy.version,
                    policy.status,
                    policy.summary,
                    policy.content,
                    document.original_filename if document else "Manual policy entry",
                    document.file_extension if document else "",
                    document.mime_type if document else "",
                    self.format_datetime(policy.created_at),
                )
            )

            if text_matches_search_terms(search_terms, searchable):
                results.append(policy)

        return results

    def _searchable_sections(
        self,
        company_id: int,
    ) -> list[_SearchableSection]:
        """Return file sections plus backward-compatible manual sections."""

        file_rows = self.section_repository.list_searchable(
            company_id=company_id,
            as_of_date=date.today(),
        )

        sections = [
            _SearchableSection(
                policy=policy,
                heading=section.heading,
                text=section.text,
                filename=document.original_filename,
                page_number=section.page_number,
            )
            for policy, document, section in file_rows
        ]

        file_policy_ids = {
            item.policy.id
            for item in sections
        }

        for policy in self.list_published(company_id):
            if policy.id not in file_policy_ids:
                sections.extend(
                    self._manual_sections(policy)
                )

        return sections

    @staticmethod
    def _qa_question_profile(question: str) -> str:
        clean = PolicyService._normalize_spaces(question).lower()
        if re.search(r"\b(compare|comparison|difference|versus|vs\.?)\b", clean):
            return "comparison"
        if re.search(r"^\s*(?:what|which)\s+(?:benefits|requirements|reasons|documents|conditions|options|rules)\b|^\s*(?:list|show|give me)\b", clean):
            return "list"
        if re.search(r"^how much\b|\b(amount|allowance|reimbursement|cash award|cost)\b", clean):
            return "amount"
        if re.search(r"^how (?:many|long)\b", clean):
            return "duration_or_count"
        if re.search(r"^when\b|\bwhat (?:time|date)\b", clean):
            return "date_or_time"
        if re.search(r"\bwhat happens\b|\bpenalt(?:y|ies)\b|\bconsequence\b|\bdisciplin", clean):
            return "consequence"
        if re.search(r"\b(eligible|eligibility|qualify|qualified|entitled|covered|allowed|prohibited)\b", clean):
            return "eligibility"
        if re.search(r"^\s*(?:what should|how (?:do|does|can|should|to)|what do)\b|\bprocedure\b|\bprocess\b", clean):
            return "procedure"
        return "standard"

    @classmethod
    def _qa_answerability_bonus(cls, question: str, text: str) -> float:
        profile = cls._qa_question_profile(question)
        clean = cls._normalize_spaces(text).lower()
        if profile == "amount":
            if re.search(r"(?:₱|\$|¥|€)\s*\d|\b\d[\d,]*(?:\.\d+)?\s*(?:peso|pesos|php|yen|dollar|dollars)\b", clean):
                return 4.0
            if re.search(r"\b(amount|allowance|reimbursement|cash|pay|rate|cost|award)\b", clean):
                return 2.0
        elif profile == "duration_or_count":
            if re.search(r"\b\d+(?:\.\d+)?\s*(?:day|days|week|weeks|month|months|year|years|hour|hours|minute|minutes|dependent|dependents|credit|credits)\b", clean):
                return 4.0
        elif profile == "date_or_time":
            if re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", clean):
                return 4.0
            if re.search(r"\b(before|after|within|effective|date|time|month|year|day)\b", clean):
                return 2.0
        elif profile == "consequence":
            if re.search(r"\b(disqualif|absent|penalt|sanction|suspend|dismiss|forfeit|deduct|warning|violation|terminate)\w*\b", clean):
                return 4.0
            if re.search(r"\b(shall|will|must|required)\b", clean):
                return 1.5
        elif profile == "eligibility":
            if re.search(r"\b(eligible|qualif|entitled|covered|allowed|prohibit|required|shall|may|must|not)\w*\b", clean):
                return 3.0
        elif profile == "procedure":
            if re.search(r"\b(submit|notify|inform|request|approval|approve|form|report|contact|within|before|after)\w*\b", clean):
                return 3.0
        return 0.0

    @classmethod
    def _focused_policy_excerpt(
        cls,
        *,
        question: str,
        text: str,
        max_chars: int = 1200,
    ) -> str:
        """Return the matching clause and nearby sentences instead of text[0:N]."""

        clean = cls._normalize_spaces(text)
        profile = cls._qa_question_profile(question)
        if profile in {"amount", "duration_or_count", "date_or_time", "consequence", "eligibility"}:
            target_chars = min(max_chars, 820)
        elif profile in {"comparison", "list", "procedure"}:
            target_chars = max_chars
        else:
            target_chars = min(max_chars, 950)

        if len(clean) <= target_chars:
            return clean

        raw_units = [
            cls._normalize_spaces(item)
            for item in re.split(r"(?:\n+|(?<=[.!?])\s+(?=[A-Z0-9]))", str(text or ""))
            if cls._normalize_spaces(item)
        ]
        if not raw_units:
            return clean[:max_chars].rstrip()

        question_tokens = cls._tokens(question)
        normalized_question = " ".join(re.findall(r"[a-z0-9]+", question.lower()))

        def score(unit: str) -> float:
            unit_tokens = cls._tokens(unit)
            lexical = len(question_tokens.intersection(unit_tokens)) * 2.0
            cue = cls._qa_answerability_bonus(question, unit)
            phrase = 0.0
            normalized_unit = " ".join(re.findall(r"[a-z0-9]+", unit.lower()))
            if normalized_question and len(normalized_question) <= 120 and normalized_question in normalized_unit:
                phrase = 4.0
            return lexical + cue + phrase

        best_index = max(range(len(raw_units)), key=lambda index: score(raw_units[index]))
        selected = [best_index]
        radius = 1
        while radius < len(raw_units):
            changed = False
            for candidate in (best_index - radius, best_index + radius):
                if candidate < 0 or candidate >= len(raw_units) or candidate in selected:
                    continue
                indexes = sorted(selected + [candidate])
                rendered = " ".join(raw_units[index] for index in indexes)
                if len(rendered) <= target_chars:
                    selected.append(candidate)
                    changed = True
            if not changed and len(" ".join(raw_units[index] for index in sorted(selected))) >= int(target_chars * 0.72):
                break
            radius += 1

        return " ".join(raw_units[index] for index in sorted(selected))[:target_chars].rstrip()

    def answer_question(
        self,
        *,
        company_id: int,
        question: str,
    ) -> PolicyAnswer:
        """Extract a direct, question-focused answer from approved policy files."""

        normalized_question = question.strip()
        question_tokens = self._tokens(normalized_question)

        if not question_tokens:
            return PolicyAnswer(
                answer=NO_POLICY_ANSWER,
                sources=[],
                matched=False,
            )

        normalized_phrase = " ".join(
            re.findall(r"[a-z0-9]+", normalized_question.lower())
        )
        candidates: list[tuple[float, _SearchableSection]] = []

        for section in self._searchable_sections(company_id):
            policy = section.policy
            title_tokens = self._tokens(f"{policy.title} {policy.category}")
            summary_tokens = self._tokens(policy.summary or "")
            heading_tokens = self._tokens(section.heading)
            text_tokens = self._tokens(section.text)

            title_overlap = len(question_tokens & title_tokens)
            summary_overlap = len(question_tokens & summary_tokens)
            heading_overlap = len(question_tokens & heading_tokens)
            text_overlap = len(question_tokens & text_tokens)
            coverage = text_overlap / max(1, len(question_tokens))

            score = (
                title_overlap * 4.5
                + heading_overlap * 3.5
                + summary_overlap * 2.0
                + text_overlap
                + coverage * 7.0
                + self._qa_answerability_bonus(normalized_question, section.text)
            )

            normalized_section = " ".join(
                re.findall(r"[a-z0-9]+", section.text.lower())
            )
            if normalized_phrase and normalized_phrase in normalized_section:
                score += 6.0
            else:
                meaningful = [
                    token
                    for token in re.findall(r"[a-z0-9]+", normalized_question.lower())
                    if token not in _STOP_WORDS and len(token) >= 2
                ]
                phrase_hits = 0
                for size in (3, 2):
                    for index in range(0, max(0, len(meaningful) - size + 1)):
                        phrase = " ".join(meaningful[index:index + size])
                        if phrase and phrase in normalized_section:
                            phrase_hits += 1
                score += min(4.0, phrase_hits * 1.25)

            if score > 0:
                candidates.append((score, section))

        if not candidates:
            return PolicyAnswer(
                answer=NO_POLICY_ANSWER,
                sources=[],
                matched=False,
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score, best_section = candidates[0]
        if not self._topic_is_supported(
            question=normalized_question,
            section=best_section,
        ):
            return PolicyAnswer(
                answer=NO_POLICY_ANSWER,
                sources=[],
                matched=False,
            )
        if best_score < 2.0:
            return PolicyAnswer(
                answer=NO_POLICY_ANSWER,
                sources=[],
                matched=False,
            )

        profile = self._qa_question_profile(normalized_question)
        if profile in {"comparison", "list", "procedure"}:
            threshold_ratio = 0.38
            max_distinct_policies = 3
        elif profile in {"amount", "duration_or_count", "date_or_time"}:
            threshold_ratio = 0.62
            max_distinct_policies = 2
        elif profile in {"consequence", "eligibility"}:
            threshold_ratio = 0.55
            max_distinct_policies = 2
        else:
            threshold_ratio = 0.50
            max_distinct_policies = 2

        threshold = max(2.0, best_score * threshold_ratio)
        selected: list[_SearchableSection] = []
        seen_sections: set[tuple[int, str, int | None]] = set()
        seen_policies: set[int] = set()

        # First pass preserves cross-policy coverage when the wording is broad
        # enough to trigger more than one directly applicable company rule.
        for score, section in candidates:
            if score < threshold:
                continue
            key = (section.policy.id, section.heading, section.page_number)
            if key in seen_sections or section.policy.id in seen_policies:
                continue
            selected.append(section)
            seen_sections.add(key)
            seen_policies.add(section.policy.id)
            if len(selected) >= max_distinct_policies:
                break

        # Second pass adds nearby/supporting clauses from already-relevant
        # policies so conditions/exceptions are not lost.
        for score, section in candidates:
            if len(selected) >= 4:
                break
            if score < threshold:
                continue
            key = (section.policy.id, section.heading, section.page_number)
            if key in seen_sections or section.policy.id not in seen_policies:
                continue
            selected.append(section)
            seen_sections.add(key)

        answer_parts = [
            self._focused_policy_excerpt(
                question=normalized_question,
                text=section.text,
                max_chars=1200,
            )
            for section in selected
        ]

        sources = [
            PolicySource(
                policy_id=section.policy.id,
                title=section.policy.title,
                category=section.policy.category,
                version=section.policy.version,
                effective_date=section.policy.effective_date,
                uploaded_at=section.policy.created_at,
                section_heading=section.heading,
                filename=section.filename,
                page_number=section.page_number,
            )
            for section in selected
        ]

        return PolicyAnswer(
            answer="\n\n".join(answer_parts),
            sources=sources,
            matched=True,
        )
