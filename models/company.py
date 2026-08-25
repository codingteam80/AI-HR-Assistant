"""Company model.

A company is the tenant boundary of the application. Every company-scoped
record must contain company_id so data from different companies cannot mix.
"""

from typing import TYPE_CHECKING

from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.constants import DEFAULT_COMPANY_THEME_COLOR
from database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.department import Department
    from models.employee import Employee
    from models.employee_training import EmployeeTraining
    from models.role import Role
    from models.user import User


class Company(TimestampMixin, Base):
    """A company or organization using the HR Assistant."""

    __tablename__ = "companies"

    # Primary database identifier.
    id: Mapped[int] = mapped_column(primary_key=True)

    # Human-facing company code used for login and integrations. Company ID
    # remains the immutable tenant boundary if this code is renamed.
    code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    # Company-specific primary accent used across both portals.
    theme_primary_color: Mapped[str] = mapped_column(
        String(7),
        default=DEFAULT_COMPANY_THEME_COLOR,
        server_default=DEFAULT_COMPANY_THEME_COLOR,
        nullable=False,
    )

    # Canonical company-scoped logo filename stored under the private
    # company-logo upload directory. The file is never served publicly.
    logo_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Company-configurable attendance schedule. Saturday and Sunday are rest
    # days by default, so all hours worked on them are treated as OT unless an
    # administrator marks the day as a regular workday.
    attendance_regular_hours: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        default=Decimal("8.00"),
        server_default="8.00",
        nullable=False,
    )
    attendance_lunch_minutes: Mapped[int] = mapped_column(
        Integer,
        default=60,
        server_default="60",
        nullable=False,
    )

    # Company-configurable OT and shifting-credit policy.  These defaults
    # preserve the HR rules currently used by the company while keeping the
    # exclusions editable instead of hard-coding a senior-position ladder.
    ot_dinner_break_deduction_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("0.75"),
        server_default="0.75",
        nullable=False,
    )
    shifting_credits_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    shifting_credit_block_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("4.00"),
        server_default="4.00",
        nullable=False,
    )
    shifting_credit_required_blocks: Mapped[int] = mapped_column(
        Integer, default=2, server_default="2", nullable=False
    )
    shifting_credit_cutoff_day: Mapped[int] = mapped_column(
        Integer, default=15, server_default="15", nullable=False
    )
    shifting_credit_additional_vl_threshold_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("8.00"),
        server_default="8.00",
        nullable=False,
    )
    shifting_credit_additional_vl_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("0.50"),
        server_default="0.50",
        nullable=False,
    )
    shifting_credit_excluded_positions_json: Mapped[str] = mapped_column(
        Text,
        default='["Trainee", "Design Engineer I", "Design Engineer II"]',
        server_default='["Trainee", "Design Engineer I", "Design Engineer II"]',
        nullable=False,
    )
    work_monday: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    work_tuesday: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    work_wednesday: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    work_thursday: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    work_friday: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    work_saturday: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    work_sunday: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )

    # Company leave-cycle and Vacation Leave utilization policy. January 1
    # and 50% preserve the behavior of existing databases until an
    # administrator deliberately changes the settings.
    leave_reset_month: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    leave_reset_day: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    leave_utilization_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    leave_utilization_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=Decimal("50.00"),
        server_default="50.00",
        nullable=False,
    )
    manager_vl_retention_limit: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        default=Decimal("13.00"),
        server_default="13.00",
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Deleting a company also removes its owned records.
    users: Mapped[list["User"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    roles: Mapped[list["Role"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    departments: Mapped[list["Department"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    employees: Mapped[list["Employee"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    employee_trainings: Mapped[list["EmployeeTraining"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
