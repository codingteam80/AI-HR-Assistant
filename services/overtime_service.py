"""DTR-grounded employee overtime filing, approval, and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import get_settings
from models.attendance_record import AttendanceRecord
from models.employee import Employee
from models.overtime_request import OvertimeRequest
from models.user import User
from repositories.attendance_repository import AttendanceRepository
from repositories.overtime_repository import OvertimeRequestRepository
from schemas.overtime_schema import OvertimeRequestInput, OvertimeReviewInput
from services.notification_service import NotificationService


@dataclass(slots=True)
class OvertimeDTRReference:
    """Read-only DTR values used to prefill an OT request."""

    record_id: int
    date_rendered: date
    time_in: datetime | None
    time_out: datetime | None
    ot_start: datetime | None
    ot_end: datetime | None
    estimated_hours: Decimal


class OvertimeService:
    """Enforce ownership, DTR grounding, routing, and OT decisions."""

    ACTIVE_STATUSES = {"pending_approval", "approved"}

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = OvertimeRequestRepository(session)
        self.attendance_repository = AttendanceRepository(session)
        self.timezone = ZoneInfo(get_settings().display_timezone)

    def _employee(self, company_id: int, employee_id: int) -> Employee:
        employee = self.session.scalar(
            select(Employee).where(
                Employee.company_id == company_id,
                Employee.id == employee_id,
            )
        )
        if employee is None:
            raise ValueError("The employee record was not found.")
        return employee

    def _require_owner(self, *, company_id: int, employee_id: int, user_id: int) -> Employee:
        employee = self._employee(company_id, employee_id)
        if employee.user_id != user_id:
            raise ValueError("You can file overtime only for your own employee account.")
        return employee

    def _to_local(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(self.timezone)

    def _to_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=self.timezone)
        return value.astimezone(timezone.utc)

    def dtr_reference(
        self, *, company_id: int, employee_id: int, date_rendered: date
    ) -> OvertimeDTRReference | None:
        record = self.attendance_repository.get_daily(
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=date_rendered,
        )
        if record is None:
            return None
        local_in = self._to_local(record.time_in)
        local_out = self._to_local(record.time_out)
        hours = Decimal(record.ot_hours or 0).quantize(Decimal("0.01"))
        rounded_session_ends: list[datetime] = []
        for item in list(getattr(record, "sessions", ()) or ()):
            if item.rounded_time_out is None:
                continue
            local_end = self._to_local(item.rounded_time_out)
            if local_end is not None:
                rounded_session_ends.append(local_end)
        payroll_out = max(rounded_session_ends) if rounded_session_ends else local_out
        ot_end = payroll_out if hours > 0 else None
        ot_start = (
            payroll_out - timedelta(hours=float(hours))
            if payroll_out is not None and hours > 0
            else None
        )
        return OvertimeDTRReference(
            record_id=record.id,
            date_rendered=date_rendered,
            time_in=local_in,
            time_out=local_out,
            ot_start=ot_start,
            ot_end=ot_end,
            estimated_hours=hours,
        )

    def list_own(self, *, company_id: int, employee_id: int) -> list[OvertimeRequest]:
        return self.repository.list_employee(
            company_id=company_id, employee_id=employee_id
        )

    def list_pending(
        self, *, company_id: int, reviewer_employee_id: int | None, clearance: int
    ) -> list[OvertimeRequest]:
        return self.repository.list_pending_for_approver(
            company_id=company_id,
            employee_id=reviewer_employee_id,
            include_all=clearance == 1,
        )

    def list_company_range(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
        employee_ids: list[int] | None = None,
    ) -> list[OvertimeRequest]:
        return self.repository.list_company_range(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
            employee_ids=employee_ids,
        )

    def _next_public_id(self) -> str:
        next_id = int(self.session.scalar(select(func.max(OvertimeRequest.id))) or 0) + 1
        return f"OTR_{next_id:06d}"

    def submit(self, values: OvertimeRequestInput) -> OvertimeRequest:
        employee = self._require_owner(
            company_id=values.company_id,
            employee_id=values.employee_id,
            user_id=values.requested_by_user_id,
        )
        reference = self.dtr_reference(
            company_id=values.company_id,
            employee_id=values.employee_id,
            date_rendered=values.date_rendered,
        )
        if reference is None:
            raise ValueError("No DTR record is available for the selected date.")
        if reference.time_out is None:
            raise ValueError("Complete the DTR Time Out before filing overtime.")
        if reference.estimated_hours <= 0:
            raise ValueError("The selected DTR date has no detected overtime.")

        start_utc = self._to_utc(values.ot_time_start)
        end_utc = self._to_utc(values.ot_time_end)
        if values.ot_time_start.date() != values.date_rendered:
            raise ValueError("OT Start Time must begin on the selected Date Rendered.")

        overlapping = self.session.scalar(
            select(OvertimeRequest.id).where(
                OvertimeRequest.company_id == values.company_id,
                OvertimeRequest.employee_id == values.employee_id,
                OvertimeRequest.status.in_(self.ACTIVE_STATUSES),
                OvertimeRequest.ot_time_start < end_utc,
                OvertimeRequest.ot_time_end > start_utc,
            ).limit(1)
        )
        if overlapping is not None:
            raise ValueError("This OT time overlaps an existing active overtime request.")

        detected_start_utc = self._to_utc(reference.ot_start) if reference.ot_start else None
        detected_end_utc = self._to_utc(reference.ot_end) if reference.ot_end else None
        tolerance = Decimal("0.01")
        has_mismatch = (
            detected_start_utc != start_utc
            or detected_end_utc != end_utc
            or abs(Decimal(values.estimated_hours) - reference.estimated_hours) > tolerance
        )
        approver_id = employee.leader_id or employee.manager_id
        request = OvertimeRequest(
            public_id=self._next_public_id(),
            company_id=values.company_id,
            employee_id=values.employee_id,
            attendance_record_id=reference.record_id,
            filed_by_user_id=values.requested_by_user_id,
            current_approver_employee_id=approver_id,
            date_rendered=values.date_rendered,
            dtr_time_in=self._to_utc(reference.time_in) if reference.time_in else None,
            dtr_time_out=self._to_utc(reference.time_out) if reference.time_out else None,
            dtr_ot_start=detected_start_utc,
            dtr_ot_end=detected_end_utc,
            dtr_estimated_hours=reference.estimated_hours,
            ot_time_start=start_utc,
            ot_time_end=end_utc,
            estimated_hours=values.estimated_hours,
            ot_type=values.ot_type,
            ot_purpose=values.ot_purpose,
            travel_fare=values.travel_fare,
            travel_route=values.travel_route,
            dinner_break_flag=values.dinner_break_flag,
            has_dtr_mismatch=has_mismatch,
            status="pending_approval",
        )
        self.session.add(request)
        self.session.flush()

        if approver_id is not None:
            approver = self._employee(values.company_id, approver_id)
            if approver.user_id is not None:
                NotificationService(self.session).create(
                    company_id=values.company_id,
                    user_id=approver.user_id,
                    event_type="overtime_request_filed",
                    title="Overtime · Request filed",
                    message=(
                        f"{employee.full_name} filed {values.estimated_hours} hour(s) "
                        f"of OT for {values.date_rendered:%b %d, %Y}."
                    ),
                    related_entity_type="overtime_request",
                    related_entity_id=request.id,
                )
        self.session.commit()
        self.session.refresh(request)
        return request

    def cancel_own(
        self, *, company_id: int, request_id: int, employee_id: int, user_id: int
    ) -> OvertimeRequest:
        self._require_owner(
            company_id=company_id, employee_id=employee_id, user_id=user_id
        )
        request = self.repository.get_by_id(request_id, company_id)
        if request is None or request.employee_id != employee_id:
            raise ValueError("The overtime request was not found.")
        if request.status != "pending_approval":
            raise ValueError("Only a pending overtime request may be cancelled.")
        request.status = "cancelled"
        self.session.commit()
        self.session.refresh(request)
        return request

    def review(self, values: OvertimeReviewInput) -> OvertimeRequest:
        request = self.repository.get_by_id(
            values.overtime_request_id, values.company_id
        )
        if request is None:
            raise ValueError("The overtime request was not found.")
        if request.status != "pending_approval":
            raise ValueError("This overtime request is no longer pending.")
        is_admin = values.clearance == 1
        is_assigned = (
            values.reviewer_employee_id is not None
            and request.current_approver_employee_id == values.reviewer_employee_id
        )
        if not (is_admin or is_assigned):
            raise ValueError("You are not the assigned overtime approver.")

        request.status = values.decision
        request.reviewer_comment = values.comment
        request.reviewed_by_user_id = values.reviewed_by_user_id
        request.reviewed_at = datetime.now(timezone.utc)
        owner = self._employee(values.company_id, request.employee_id)
        if owner.user_id is not None:
            NotificationService(self.session).create(
                company_id=values.company_id,
                user_id=owner.user_id,
                event_type=f"overtime_request_{values.decision}",
                title=f"Overtime · Request {values.decision}",
                message=(
                    f"{request.public_id} for {request.date_rendered:%b %d, %Y} "
                    f"was {values.decision}."
                ),
                related_entity_type="overtime_request",
                related_entity_id=request.id,
            )
        self.session.commit()
        self.session.refresh(request)
        return request
