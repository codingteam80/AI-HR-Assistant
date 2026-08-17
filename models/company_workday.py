"""Company-specific calendar dates used by Attendance/DTR/OT."""

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class CompanyWorkday(TimestampMixin, Base):
    """Persist one company's selected workday state for one calendar date."""

    __tablename__ = "company_workdays"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "work_date",
            name="uq_company_workdays_company_date",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    is_workday: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
