"""Application user-account model.

This table stores login-related data. Employee profile details are kept in
the separate Employee model so authentication and HR data remain modular.
"""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.company import Company
    from models.employee import Employee
    from models.role import Role


class User(TimestampMixin, Base):
    """A company-scoped account that can log in later."""

    __tablename__ = "users"

    # Username and email must be unique inside one company.
    # Another company may reuse the same username or email if required.
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "username",
            name="uq_users_company_username",
        ),
        UniqueConstraint(
            "company_id",
            "email",
            name="uq_users_company_email",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Legacy internal role mapping is retained so existing databases,
    # password-reset records, and older integrations continue to work.
    # Administrators no longer manage this field in the UI.
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id"),
        index=True,
        nullable=False,
    )

    # User-facing access rule:
    # 1 = Admin, 2 = User
    clearance: Mapped[int] = mapped_column(
        Integer,
        default=2,
        nullable=False,
        index=True,
    )

    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)

    # Never store a plain-text password.
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Initial accounts are forced to change password during login.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    company: Mapped["Company"] = relationship(back_populates="users")
    role: Mapped["Role"] = relationship(back_populates="users")

    # One login account may be linked to one employee profile.
    employee: Mapped["Employee | None"] = relationship(
        back_populates="user",
        foreign_keys="Employee.user_id",
        uselist=False,
    )
