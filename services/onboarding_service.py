"""Business rules for company onboarding and permanent employee benefits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.attendance_record import AttendanceRecord
from models.employee import Employee
from models.employee_training import EmployeeTraining
from models.onboarding import (
    CompanyBenefit,
    EmployeeOnboardingProgress,
    OnboardingChecklistItem,
)
from repositories.employee_repository import EmployeeRepository
from repositories.onboarding_repository import OnboardingRepository


VALID_PROGRESS_STATUSES = {"pending", "in_progress", "completed"}
VALID_COMPLETION_MODES = {"employee", "admin", "automatic"}
VALID_AUTO_RULES = {"password_changed", "first_time_in", "training_complete"}


@dataclass(frozen=True, slots=True)
class ChecklistProgressView:
    item_id: int
    title: str
    description: str
    sort_order: int
    is_required: bool
    completion_mode: str
    auto_rule: str | None
    target_page: str | None
    target_query_key: str | None
    target_query_value: str | None
    status: str
    completed_at: datetime | None
    note: str


DEFAULT_CHECKLIST_ITEMS = (
    {
        "title": "Change temporary password",
        "description": "Replace the temporary password issued with your account.",
        "completion_mode": "automatic",
        "auto_rule": "password_changed",
        "target_page": "Dashboard",
    },
    {
        "title": "Review company policies",
        "description": "Read the currently published company policies.",
        "completion_mode": "employee",
        "target_page": "Company Policies",
    },
    {
        "title": "Review required company forms",
        "description": "Open the forms workspace and review required forms or documents.",
        "completion_mode": "employee",
        "target_page": "Company Form/Documents",
        "target_query_key": "form_view",
        "target_query_value": "view",
    },
    {
        "title": "Record the first Time In",
        "description": "Use the Dashboard Time In control for the first attendance entry.",
        "completion_mode": "automatic",
        "auto_rule": "first_time_in",
        "target_page": "Dashboard",
        "target_query_key": "dashboard_view",
        "target_query_value": "attendance",
    },
    {
        "title": "Review Attendance / DTR and overtime",
        "description": "Learn where attendance records and overtime requests are maintained.",
        "completion_mode": "employee",
        "target_page": "Attendance Hub",
    },
    {
        "title": "Review leave balances and filing",
        "description": "Review leave credits, utilization, filing, and request status.",
        "completion_mode": "employee",
        "target_page": "Leave Management",
        "target_query_key": "leave_view",
        "target_query_value": "overview",
    },
    {
        "title": "Review employee benefits",
        "description": "Read the benefits configured by your company.",
        "completion_mode": "employee",
        "target_page": "Onboarding",
        "target_query_key": "onboarding_view",
        "target_query_value": "benefits",
    },
    {
        "title": "Complete assigned training",
        "description": "Complete every training item assigned in the employee record.",
        "completion_mode": "automatic",
        "auto_rule": "training_complete",
        "target_page": "Onboarding",
        "target_query_key": "onboarding_view",
        "target_query_value": "checklist",
    },
    {
        "title": "Review HR contact information",
        "description": "Know where to contact HR for assistance.",
        "completion_mode": "employee",
        "target_page": "HR Contacts",
    },
    {
        "title": "Review frequently asked questions",
        "description": "Read the default FAQ answers and direct workspace links.",
        "completion_mode": "employee",
        "target_page": "FAQ",
    },
)


class OnboardingService:
    """Manage onboarding without duplicating documents or policy content."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = OnboardingRepository(session)
        self.employee_repository = EmployeeRepository(session)

    def ensure_default_checklist(self, company_id: int) -> list[OnboardingChecklistItem]:
        """Create a practical default checklist only for a company with none."""

        existing = self.repository.list_items(company_id)
        if existing:
            return existing

        items = []
        for index, values in enumerate(DEFAULT_CHECKLIST_ITEMS, start=1):
            item = OnboardingChecklistItem(
                company_id=company_id,
                sort_order=index * 10,
                is_required=True,
                is_active=True,
                **values,
            )
            self.session.add(item)
            items.append(item)
        self.session.commit()
        for item in items:
            self.session.refresh(item)
        return items

    def _employee_exists(self, *, company_id: int, employee_id: int) -> Employee:
        employee = self.employee_repository.get_with_details(
            company_id=company_id,
            employee_id=employee_id,
        )
        if employee is None:
            raise ValueError("The selected employee does not exist in this company.")
        return employee

    def _automatic_completed(
        self,
        *,
        employee: Employee,
        auto_rule: str | None,
    ) -> bool:
        if auto_rule == "password_changed":
            return employee.user is not None and not employee.user.must_change_password
        if auto_rule == "first_time_in":
            return self.session.scalar(
                select(AttendanceRecord.id)
                .where(
                    AttendanceRecord.company_id == employee.company_id,
                    AttendanceRecord.employee_id == employee.id,
                    AttendanceRecord.time_in.is_not(None),
                )
                .limit(1)
            ) is not None
        if auto_rule == "training_complete":
            training_values = list(
                self.session.scalars(
                    select(EmployeeTraining.is_completed).where(
                        EmployeeTraining.company_id == employee.company_id,
                        EmployeeTraining.employee_id == employee.id,
                    )
                ).all()
            )
            return bool(training_values) and all(training_values)
        return False

    def sync_employee(
        self,
        *,
        company_id: int,
        employee_id: int,
    ) -> list[ChecklistProgressView]:
        """Ensure progress rows and refresh automatic completion rules."""

        employee = self._employee_exists(company_id=company_id, employee_id=employee_id)
        items = self.ensure_default_checklist(company_id)
        progress_by_item = {
            row.checklist_item_id: row
            for row in self.repository.list_progress(
                company_id=company_id,
                employee_id=employee_id,
            )
        }
        changed = False
        now = datetime.now(timezone.utc)
        for item in items:
            progress = progress_by_item.get(item.id)
            if progress is None:
                progress = EmployeeOnboardingProgress(
                    company_id=company_id,
                    employee_id=employee_id,
                    checklist_item_id=item.id,
                    status="pending",
                    note="",
                )
                self.session.add(progress)
                progress_by_item[item.id] = progress
                changed = True
            if item.completion_mode == "automatic":
                completed = self._automatic_completed(employee=employee, auto_rule=item.auto_rule)
                target_status = "completed" if completed else "pending"
                if progress.status != target_status:
                    progress.status = target_status
                    progress.completed_at = now if completed else None
                    progress.completed_by_user_id = None
                    changed = True
        if changed:
            self.session.commit()

        active_items = [item for item in items if item.is_active]
        return [
            ChecklistProgressView(
                item_id=item.id,
                title=item.title,
                description=item.description,
                sort_order=item.sort_order,
                is_required=item.is_required,
                completion_mode=item.completion_mode,
                auto_rule=item.auto_rule,
                target_page=item.target_page,
                target_query_key=item.target_query_key,
                target_query_value=item.target_query_value,
                status=progress_by_item[item.id].status,
                completed_at=progress_by_item[item.id].completed_at,
                note=progress_by_item[item.id].note,
            )
            for item in active_items
        ]

    def set_progress(
        self,
        *,
        company_id: int,
        employee_id: int,
        item_id: int,
        status: str,
        actor_user_id: int,
        note: str = "",
        employee_self_service: bool = False,
    ) -> None:
        """Update an authorized checklist status and retain completion metadata."""

        if status not in VALID_PROGRESS_STATUSES:
            raise ValueError("Select a valid onboarding status.")
        self._employee_exists(company_id=company_id, employee_id=employee_id)
        item = self.repository.get_item(company_id=company_id, item_id=item_id)
        if item is None or not item.is_active:
            raise ValueError("The selected checklist item is unavailable.")
        if item.completion_mode == "automatic":
            raise ValueError("This item is completed automatically from the related record.")
        if employee_self_service and item.completion_mode != "employee":
            raise ValueError("This checklist item must be updated by an administrator.")

        progress = self.repository.get_progress(
            company_id=company_id,
            employee_id=employee_id,
            item_id=item_id,
        )
        if progress is None:
            progress = EmployeeOnboardingProgress(
                company_id=company_id,
                employee_id=employee_id,
                checklist_item_id=item_id,
            )
            self.session.add(progress)
        progress.status = status
        progress.completed_at = (
            datetime.now(timezone.utc) if status == "completed" else None
        )
        progress.completed_by_user_id = actor_user_id if status == "completed" else None
        progress.note = note.strip()[:2000]
        self.session.commit()

    def create_checklist_item(self, *, company_id: int, values: dict[str, object]) -> None:
        normalized = self._validated_item_values(values)
        self.session.add(OnboardingChecklistItem(company_id=company_id, **normalized))
        self.session.commit()

    def update_checklist_item(
        self,
        *,
        company_id: int,
        item_id: int,
        values: dict[str, object],
    ) -> None:
        item = self.repository.get_item(company_id=company_id, item_id=item_id)
        if item is None:
            raise ValueError("The selected checklist item does not exist.")
        for field, value in self._validated_item_values(values).items():
            setattr(item, field, value)
        self.session.commit()

    def archive_checklist_item(
        self,
        *,
        company_id: int,
        item_id: int,
    ) -> str:
        """Safely hide one checklist item without deleting its progress history."""

        item = self.repository.get_item(company_id=company_id, item_id=item_id)
        if item is None:
            raise ValueError("The selected checklist item does not exist.")
        if not item.is_active:
            raise ValueError("The selected checklist item is already archived.")
        item.is_active = False
        self.session.commit()
        return item.title

    def restore_checklist_item(
        self,
        *,
        company_id: int,
        item_id: int,
    ) -> str:
        """Return an archived checklist item to the employee checklist."""

        item = self.repository.get_item(company_id=company_id, item_id=item_id)
        if item is None:
            raise ValueError("The selected checklist item does not exist.")
        if item.is_active:
            raise ValueError("The selected checklist item is already active.")
        item.is_active = True
        self.session.commit()
        return item.title

    @staticmethod
    def _validated_item_values(values: dict[str, object]) -> dict[str, object]:
        title = str(values.get("title") or "").strip()
        if not title:
            raise ValueError("Checklist title is required.")
        mode = str(values.get("completion_mode") or "employee")
        if mode not in VALID_COMPLETION_MODES:
            raise ValueError("Select a valid completion mode.")
        auto_rule = str(values.get("auto_rule") or "").strip() or None
        if mode == "automatic" and auto_rule not in VALID_AUTO_RULES:
            raise ValueError("Select a valid automatic completion rule.")
        if mode != "automatic":
            auto_rule = None
        return {
            "title": title[:180],
            "description": str(values.get("description") or "").strip()[:5000],
            "sort_order": int(values.get("sort_order") or 0),
            "is_required": bool(values.get("is_required", True)),
            "completion_mode": mode,
            "auto_rule": auto_rule,
            "target_page": str(values.get("target_page") or "").strip()[:100] or None,
            "target_query_key": str(values.get("target_query_key") or "").strip()[:80] or None,
            "target_query_value": str(values.get("target_query_value") or "").strip()[:100] or None,
            "is_active": bool(values.get("is_active", True)),
        }

    def create_benefit(self, *, company_id: int, values: dict[str, object]) -> None:
        normalized = self._validated_benefit_values(values)
        self.session.add(CompanyBenefit(company_id=company_id, **normalized))
        self.session.commit()

    def update_benefit(
        self,
        *,
        company_id: int,
        benefit_id: int,
        values: dict[str, object],
    ) -> None:
        benefit = self.repository.get_benefit(
            company_id=company_id,
            benefit_id=benefit_id,
        )
        if benefit is None:
            raise ValueError("The selected benefit does not exist.")
        for field, value in self._validated_benefit_values(values).items():
            setattr(benefit, field, value)
        self.session.commit()

    def archive_benefit(
        self,
        *,
        company_id: int,
        benefit_id: int,
    ) -> str:
        """Safely hide one benefit while retaining its company record."""

        benefit = self.repository.get_benefit(
            company_id=company_id,
            benefit_id=benefit_id,
        )
        if benefit is None:
            raise ValueError("The selected benefit does not exist.")
        if not benefit.is_active:
            raise ValueError("The selected benefit is already archived.")
        benefit.is_active = False
        self.session.commit()
        return benefit.name

    def restore_benefit(
        self,
        *,
        company_id: int,
        benefit_id: int,
    ) -> str:
        """Return an archived benefit to the employee Benefits tab."""

        benefit = self.repository.get_benefit(
            company_id=company_id,
            benefit_id=benefit_id,
        )
        if benefit is None:
            raise ValueError("The selected benefit does not exist.")
        if benefit.is_active:
            raise ValueError("The selected benefit is already active.")
        benefit.is_active = True
        self.session.commit()
        return benefit.name

    @staticmethod
    def _validated_benefit_values(values: dict[str, object]) -> dict[str, object]:
        name = str(values.get("name") or "").strip()
        if not name:
            raise ValueError("Benefit name is required.")
        effective_date = values.get("effective_date")
        if effective_date is not None and not isinstance(effective_date, date):
            raise ValueError("Select a valid effective date.")
        return {
            "name": name[:180],
            "category": str(values.get("category") or "General").strip()[:100] or "General",
            "description": str(values.get("description") or "").strip()[:8000],
            "eligibility": str(values.get("eligibility") or "All employees").strip()[:300],
            "effective_date": effective_date,
            "enrollment_instructions": str(
                values.get("enrollment_instructions") or ""
            ).strip()[:8000],
            "contact_person": str(values.get("contact_person") or "").strip()[:180] or None,
            "target_page": str(values.get("target_page") or "").strip()[:100] or None,
            "target_query_key": str(values.get("target_query_key") or "").strip()[:80] or None,
            "target_query_value": str(values.get("target_query_value") or "").strip()[:100] or None,
            "sort_order": int(values.get("sort_order") or 0),
            "is_active": bool(values.get("is_active", True)),
        }

    def list_benefits(
        self,
        company_id: int,
        *,
        active_only: bool = False,
    ) -> list[CompanyBenefit]:
        return self.repository.list_benefits(company_id, active_only=active_only)

    def list_items(
        self,
        company_id: int,
        *,
        active_only: bool = False,
    ) -> list[OnboardingChecklistItem]:
        self.ensure_default_checklist(company_id)
        return self.repository.list_items(company_id, active_only=active_only)

    def company_progress_rows(self, company_id: int) -> list[dict[str, object]]:
        """Return detached company summaries for the admin progress table."""

        employees = self.employee_repository.list_with_details(company_id, archived=False)
        rows: list[dict[str, object]] = []
        for employee in employees:
            checklist = self.sync_employee(
                company_id=company_id,
                employee_id=employee.id,
            )
            required = [item for item in checklist if item.is_required]
            completed = sum(item.status == "completed" for item in required)
            total = len(required)
            percentage = round((completed / total) * 100) if total else 100
            rows.append(
                {
                    "employee_id": employee.id,
                    "employee_number": employee.employee_number,
                    "employee_name": employee.full_name,
                    "department": employee.department.name if employee.department else "N/A",
                    "position": employee.job_title or "N/A",
                    "hire_date": employee.hire_date,
                    "completed": completed,
                    "total": total,
                    "percentage": percentage,
                    "status": "Completed" if percentage == 100 else "In Progress",
                }
            )
        return rows
