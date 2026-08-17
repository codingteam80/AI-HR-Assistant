"""Leave requests with employee ownership and staged approval routing."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin
from models.employee import Employee
from models.leave_type import LeaveType


class LeaveRequest(TimestampMixin, Base):
    """One employee-owned leave request with leader/manager audit history."""

    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    public_id: Mapped[str | None] = mapped_column(String(30), unique=True, index=True)

    # Leave ownership never changes even when a leader files on behalf.
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filed_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    filed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    filed_on_behalf: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )

    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("leave_types.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    fallback_leave_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("leave_types.id", ondelete="SET NULL"), index=True
    )

    # Final assigned manager and optional first-stage leader.
    manager_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    leader_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    current_approver_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    approval_stage: Mapped[str] = mapped_column(
        String(30), default="manager", server_default="manager", nullable=False
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    duration_code: Mapped[str] = mapped_column(
        String(10), default="90503", server_default="90503", nullable=False
    )
    reason_code: Mapped[str] = mapped_column(
        String(10), default="0", server_default="0", nullable=False
    )
    reason_other: Mapped[str | None] = mapped_column(Text)
    primary_credit_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0", nullable=False
    )
    fallback_credit_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0", nullable=False
    )
    lwop_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0", nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    handover_plan: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(50), default="pending_manager_approval",
        server_default="pending_manager_approval", nullable=False, index=True
    )

    # Searchable UI stores the resolved emails for audit and delivery.
    manager_email: Mapped[str] = mapped_column(String(255), nullable=False)
    to_emails_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    cc_emails_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]", nullable=False)
    email_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    email_reference: Mapped[str | None] = mapped_column(String(500))
    email_error: Mapped[str | None] = mapped_column(String(500))

    attachment_original_filename: Mapped[str | None] = mapped_column(String(255))
    attachment_storage_path: Mapped[str | None] = mapped_column(String(700))
    attachment_mime_type: Mapped[str | None] = mapped_column(String(150))
    attachment_size_bytes: Mapped[int | None] = mapped_column()

    # Leader stage audit. Final manager fields remain backward compatible.
    leader_comment: Mapped[str | None] = mapped_column(Text)
    leader_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leader_reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    manager_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Cancellation workflow is separate from the active leave lifecycle.
    # Pending approvals may be cancelled immediately, while an approved leave
    # keeps its current lifecycle status until the manager decides the
    # cancellation request.
    cancellation_status: Mapped[str] = mapped_column(
        String(30), default="none", server_default="none", nullable=False, index=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    cancellation_requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    cancellation_requested_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    cancellation_effective_date: Mapped[date | None] = mapped_column(Date)
    cancellation_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    cancellation_reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    cancellation_comment: Mapped[str | None] = mapped_column(Text)
    cancellation_restored_primary_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0", nullable=False
    )
    cancellation_restored_fallback_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0", nullable=False
    )
    cancellation_removed_lwop_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0", nullable=False
    )

    reservation_posted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    posted_working_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0", nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    employee: Mapped[Employee] = relationship(foreign_keys=[employee_id], lazy="joined")
    filed_by_employee: Mapped[Employee | None] = relationship(
        foreign_keys=[filed_by_employee_id], lazy="joined"
    )
    manager: Mapped[Employee | None] = relationship(
        foreign_keys=[manager_employee_id], lazy="joined"
    )
    leader_approver: Mapped[Employee | None] = relationship(
        foreign_keys=[leader_employee_id], lazy="joined"
    )
    current_approver: Mapped[Employee | None] = relationship(
        foreign_keys=[current_approver_employee_id], lazy="joined"
    )
    cancellation_requested_by_employee: Mapped[Employee | None] = relationship(
        foreign_keys=[cancellation_requested_by_employee_id], lazy="joined"
    )
    leave_type: Mapped[LeaveType] = relationship(foreign_keys=[leave_type_id], lazy="joined")
    fallback_leave_type: Mapped[LeaveType | None] = relationship(
        foreign_keys=[fallback_leave_type_id], lazy="joined"
    )
