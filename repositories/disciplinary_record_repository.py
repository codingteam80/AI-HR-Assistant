"""Tenant-safe queries for confidential employee disciplinary cases."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.employee_disciplinary_record import EmployeeDisciplinaryRecord
from repositories.base_repository import BaseRepository


class DisciplinaryRecordRepository(BaseRepository[EmployeeDisciplinaryRecord]):
    """Read/write disciplinary cases only inside one company."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, EmployeeDisciplinaryRecord)

    def get_record(self, *, company_id: int, record_id: int) -> EmployeeDisciplinaryRecord | None:
        return self.session.scalar(
            select(EmployeeDisciplinaryRecord).where(
                EmployeeDisciplinaryRecord.company_id == company_id,
                EmployeeDisciplinaryRecord.id == record_id,
            )
        )

    def list_company(
        self,
        company_id: int,
        *,
        archived: bool = False,
    ) -> list[EmployeeDisciplinaryRecord]:
        statement = select(EmployeeDisciplinaryRecord).where(
            EmployeeDisciplinaryRecord.company_id == company_id
        )
        if archived:
            statement = statement.where(EmployeeDisciplinaryRecord.archived_at.is_not(None))
        else:
            statement = statement.where(EmployeeDisciplinaryRecord.archived_at.is_(None))
        statement = statement.order_by(
            EmployeeDisciplinaryRecord.incident_date.desc(),
            EmployeeDisciplinaryRecord.id.desc(),
        )
        return list(self.session.scalars(statement).all())

    def list_employee_issued(
        self, *, company_id: int, employee_id: int
    ) -> list[EmployeeDisciplinaryRecord]:
        return list(
            self.session.scalars(
                select(EmployeeDisciplinaryRecord)
                .where(
                    EmployeeDisciplinaryRecord.company_id == company_id,
                    EmployeeDisciplinaryRecord.employee_id == employee_id,
                    EmployeeDisciplinaryRecord.case_status.in_(("Issued", "Closed")),
                    EmployeeDisciplinaryRecord.date_issued.is_not(None),
                    EmployeeDisciplinaryRecord.archived_at.is_(None),
                )
                .order_by(
                    EmployeeDisciplinaryRecord.date_issued.desc(),
                    EmployeeDisciplinaryRecord.id.desc(),
                )
            ).all()
        )

    def list_employee_violation_active(
        self,
        *,
        company_id: int,
        employee_id: int,
        violation_id: int,
    ) -> list[EmployeeDisciplinaryRecord]:
        return list(
            self.session.scalars(
                select(EmployeeDisciplinaryRecord)
                .where(
                    EmployeeDisciplinaryRecord.company_id == company_id,
                    EmployeeDisciplinaryRecord.employee_id == employee_id,
                    EmployeeDisciplinaryRecord.violation_id == violation_id,
                    EmployeeDisciplinaryRecord.archived_at.is_(None),
                )
                .order_by(
                    EmployeeDisciplinaryRecord.incident_date.asc(),
                    EmployeeDisciplinaryRecord.id.asc(),
                )
            ).all()
        )

    def count_previous_offenses(
        self,
        *,
        company_id: int,
        employee_id: int,
        violation_id: int,
        incident_date: date,
        exclude_record_id: int | None = None,
    ) -> int:
        statement = select(func.count(EmployeeDisciplinaryRecord.id)).where(
            EmployeeDisciplinaryRecord.company_id == company_id,
            EmployeeDisciplinaryRecord.employee_id == employee_id,
            EmployeeDisciplinaryRecord.violation_id == violation_id,
            EmployeeDisciplinaryRecord.case_status != "Cancelled",
            EmployeeDisciplinaryRecord.archived_at.is_(None),
            EmployeeDisciplinaryRecord.incident_date <= incident_date,
        )
        if exclude_record_id is not None:
            statement = statement.where(EmployeeDisciplinaryRecord.id != exclude_record_id)
        value = self.session.scalar(statement)
        return int(value or 0)
