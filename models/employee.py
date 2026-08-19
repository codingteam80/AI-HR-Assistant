"""Employee master-record model.

Full names are not unique. Employee number is the stable company-scoped
identifier. Login data remains in ``users`` while training checklist items
remain in ``employee_trainings``.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.company import Company
    from models.department import Department
    from models.employee_training import EmployeeTraining
    from models.user import User


class Employee(TimestampMixin, Base):
    """A company-scoped employee master record."""

    __tablename__ = "employees"

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "employee_number",
            name="uq_employees_company_employee_number",
        ),
        UniqueConstraint(
            "user_id",
            name="uq_employees_user_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Increments on every Employee Master Record save. The value is shown to
    # neither portal, but prevents two administrators from silently
    # overwriting one another when both opened the same older form.
    edit_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
    )

    # Stored on the same versioned row so a stale-save warning can name the
    # exact administrator even when two saves reach the database almost at
    # the same time (before the secondary history row is written).
    last_edited_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    __mapper_args__ = {
        "version_id_col": edit_version,
        "version_id_generator": False,
    }

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )

    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"),
        index=True,
    )

    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"),
        index=True,
    )

    leader_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"),
        index=True,
    )

    employee_number: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    middle_name: Mapped[str | None] = mapped_column(
        String(100)
    )
    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    suffix: Mapped[str | None] = mapped_column(
        String(30)
    )

    work_email: Mapped[str | None] = mapped_column(
        String(255)
    )
    telephone_mobile_no: Mapped[str | None] = mapped_column(
        String(50)
    )
    job_title: Mapped[str | None] = mapped_column(
        String(150)
    )

    # User-facing values are limited to employed and resigned.
    employment_status: Mapped[str] = mapped_column(
        String(50),
        default="employed",
        nullable=False,
    )

    hire_date: Mapped[date | None] = mapped_column(Date)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    archived_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(50))
    civil_status: Mapped[str | None] = mapped_column(String(50))

    company: Mapped["Company"] = relationship(
        back_populates="employees"
    )
    user: Mapped["User | None"] = relationship(
        back_populates="employee",
        foreign_keys=[user_id],
    )
    department: Mapped["Department | None"] = relationship(
        back_populates="employees"
    )

    manager: Mapped["Employee | None"] = relationship(
        foreign_keys=[manager_id],
        remote_side="Employee.id",
        back_populates="direct_reports",
    )
    direct_reports: Mapped[list["Employee"]] = relationship(
        foreign_keys=[manager_id],
        back_populates="manager",
    )

    leader: Mapped["Employee | None"] = relationship(
        foreign_keys=[leader_id],
        remote_side="Employee.id",
        back_populates="team_members",
    )
    team_members: Mapped[list["Employee"]] = relationship(
        foreign_keys=[leader_id],
        back_populates="leader",
    )

    trainings: Mapped[list["EmployeeTraining"]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
        order_by="EmployeeTraining.display_order",
    )

    @property
    def full_name(self) -> str:
        """Build the display name without storing duplicate full-name data."""

        name_parts = [
            self.first_name,
            self.middle_name,
            self.last_name,
            self.suffix,
        ]

        missing_tokens = {"n/a", "na", "none", "null", "-", "—"}

        return " ".join(
            part.strip()
            for part in name_parts
            if (
                part
                and part.strip()
                and part.strip().casefold() not in missing_tokens
            )
        )

    @property
    def age(self) -> int | None:
        """Calculate the current age from the stored date of birth."""

        if self.date_of_birth is None:
            return None

        today = date.today()
        return (
            today.year
            - self.date_of_birth.year
            - (
                (today.month, today.day)
                < (self.date_of_birth.month, self.date_of_birth.day)
            )
        )

    @property
    def years_of_service(self) -> int | None:
        """Return completed service years from the employee's hire date."""

        if self.hire_date is None:
            return None

        today = date.today()
        if self.hire_date > today:
            return 0

        return (
            today.year
            - self.hire_date.year
            - (
                (today.month, today.day)
                < (self.hire_date.month, self.hire_date.day)
            )
        )
