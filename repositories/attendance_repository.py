"""Company-scoped attendance and correction-history database queries."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from models.attendance_correction import AttendanceCorrection
from models.attendance_record import AttendanceRecord
from models.employee import Employee
from repositories.base_repository import BaseRepository


class AttendanceRepository(BaseRepository[AttendanceRecord]):
    """Queries for daily records with strict tenant ownership."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, AttendanceRecord)

    def get_daily(
        self,
        *,
        company_id: int,
        employee_id: int,
        attendance_date: date,
    ) -> AttendanceRecord | None:
        return self.session.scalar(
            select(AttendanceRecord)
            .options(
                joinedload(AttendanceRecord.employee),
                selectinload(AttendanceRecord.sessions),
            )
            .where(
                AttendanceRecord.company_id == company_id,
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.attendance_date == attendance_date,
            )
        )

    def list_range(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
        employee_ids: list[int] | None = None,
    ) -> list[AttendanceRecord]:
        statement = (
            select(AttendanceRecord)
            .join(
                Employee,
                Employee.id == AttendanceRecord.employee_id,
            )
            .options(
                joinedload(AttendanceRecord.employee),
                selectinload(AttendanceRecord.sessions),
            )
            .where(
                AttendanceRecord.company_id == company_id,
                AttendanceRecord.attendance_date >= start_date,
                AttendanceRecord.attendance_date <= end_date,
            )
            .order_by(
                AttendanceRecord.attendance_date,
                Employee.last_name,
                Employee.first_name,
            )
        )

        # An explicitly empty visibility list must return no rows instead of
        # accidentally falling back to the whole company.
        if employee_ids is not None:
            if not employee_ids:
                return []
            statement = statement.where(
                AttendanceRecord.employee_id.in_(employee_ids)
            )

        return list(self.session.scalars(statement).unique().all())

    def list_leave_linked_range(
        self,
        *,
        company_id: int,
        start_date: date,
        end_date: date,
    ) -> list[AttendanceRecord]:
        statement = select(AttendanceRecord).options(
            selectinload(AttendanceRecord.sessions)
        ).where(
            AttendanceRecord.company_id == company_id,
            AttendanceRecord.attendance_date >= start_date,
            AttendanceRecord.attendance_date <= end_date,
            AttendanceRecord.leave_request_id.is_not(None),
        )
        return list(self.session.scalars(statement).all())


class AttendanceCorrectionRepository(BaseRepository[AttendanceCorrection]):
    """Immutable correction history queries."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, AttendanceCorrection)

    def list_for_record(
        self,
        *,
        company_id: int,
        attendance_record_id: int,
    ) -> list[AttendanceCorrection]:
        statement = (
            select(AttendanceCorrection)
            .where(
                AttendanceCorrection.company_id == company_id,
                AttendanceCorrection.attendance_record_id
                == attendance_record_id,
            )
            .order_by(
                AttendanceCorrection.created_at.desc(),
                AttendanceCorrection.id.desc(),
            )
        )
        return list(self.session.scalars(statement).all())
