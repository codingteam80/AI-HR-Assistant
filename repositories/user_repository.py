"""User-account queries for authentication and administration.

Every public method accepts company_id when accessing tenant-owned data.
"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload
from models.user import User
from repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for company-scoped login accounts."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, User)

    def get_by_username(self, company_id: int, username: str) -> User | None:
        """Find a username inside one company."""
        normalized = username.strip().casefold()
        return self.session.scalar(
            select(User).where(
                User.company_id == company_id,
                func.lower(func.trim(User.username)) == normalized,
            )
        )

    def get_by_email(self, company_id: int, email: str) -> User | None:
        """Find an email inside one company."""
        normalized = email.strip().casefold()
        return self.session.scalar(
            select(User).where(
                User.company_id == company_id,
                func.lower(func.trim(User.email)) == normalized,
            )
        )


    def get_by_username_excluding(
        self,
        *,
        company_id: int,
        username: str,
        user_id: int,
    ) -> User | None:
        """Check username uniqueness while editing one account."""

        normalized = username.strip().casefold()
        return self.session.scalar(
            select(User).where(
                User.company_id == company_id,
                func.lower(func.trim(User.username)) == normalized,
                User.id != user_id,
            )
        )

    def get_by_email_excluding(
        self,
        *,
        company_id: int,
        email: str,
        user_id: int,
    ) -> User | None:
        """Check login-email uniqueness while editing one account."""

        normalized = email.strip().casefold()
        return self.session.scalar(
            select(User).where(
                User.company_id == company_id,
                func.lower(func.trim(User.email)) == normalized,
                User.id != user_id,
            )
        )


    def list_by_email_for_password_reset(
        self,
        *,
        email: str,
    ) -> list[User]:
        """Load every account using one registered Login Email.

        Email may legitimately exist in more than one company. The reset
        service sends a separately company-labeled reset link for each
        active matching account.
        """

        normalized_email = email.strip().lower()

        statement = (
            select(User)
            .options(
                joinedload(User.company),
                joinedload(User.role),
                joinedload(User.employee),
            )
            .where(
                func.lower(User.email) == normalized_email,
            )
            .order_by(
                User.company_id,
                User.id,
            )
        )

        return list(
            self.session.scalars(statement).unique().all()
        )

    def get_for_authentication(self, company_id: int, login_identifier: str) -> User | None:
        """Load an account by username or email with required relations."""
        statement = (
            select(User)
            .options(
                joinedload(User.company),
                joinedload(User.role),
                joinedload(User.employee),
            )
            .where(
                User.company_id == company_id,
                or_(User.username == login_identifier, User.email == login_identifier),
            )
        )
        return self.session.scalar(statement)

    def get_for_password_change(self, company_id: int, user_id: int) -> User | None:
        """Load one account and relations for password replacement."""
        statement = (
            select(User)
            .options(
                joinedload(User.company),
                joinedload(User.role),
                joinedload(User.employee),
            )
            .where(User.company_id == company_id, User.id == user_id)
        )
        return self.session.scalar(statement)

    def list_with_details(self, company_id: int) -> list[User]:
        """Return company users with role and employee details."""
        statement = (
            select(User)
            .options(joinedload(User.role), joinedload(User.employee))
            .where(User.company_id == company_id)
            .order_by(User.username)
        )
        return list(self.session.scalars(statement).unique().all())

    def update_active_status(
        self,
        *,
        company_id: int,
        user_id: int,
        is_active: bool,
    ) -> User | None:
        """Activate or deactivate one account inside a company."""
        user = self.get_by_id(record_id=user_id, company_id=company_id)
        if user is None:
            return None
        user.is_active = is_active
        self.session.commit()
        self.session.refresh(user)
        return user




    def list_active_admin_ids(
        self,
        *,
        company_id: int,
    ) -> list[int]:
        """Return every active administrator account in one company."""

        statement = (
            select(User.id)
            .where(
                User.company_id == company_id,
                User.is_active.is_(True),
                User.clearance == 1,
            )
            .order_by(User.id)
        )

        return list(self.session.scalars(statement).all())

    def list_active_ids(
        self,
        *,
        company_id: int,
        exclude_user_id: int | None = None,
    ) -> list[int]:
        """Return active account IDs for company-wide notifications."""

        statement = select(User.id).where(
            User.company_id == company_id,
            User.is_active.is_(True),
        )

        if exclude_user_id is not None:
            statement = statement.where(
                User.id != exclude_user_id
            )

        return list(
            self.session.scalars(statement).all()
        )
