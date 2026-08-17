"""Authentication and password-change business logic.

Flow:
Login page -> AuthService -> repositories -> database models

Security responsibilities:
- Scope every login to a company.
- Verify Argon2 password hashes.
- Reject inactive companies, users, or roles.
- Return only a safe AuthenticatedUser object to the UI.
"""

from sqlalchemy.orm import Session

from authentication.current_user import AuthenticatedUser
from authentication.password_manager import PasswordManager
from repositories.company_repository import CompanyRepository
from repositories.user_repository import UserRepository


class AuthenticationError(ValueError):
    """Raised when credentials or account state are invalid."""


class AuthService:
    """Authenticate accounts and replace passwords."""

    def __init__(
        self,
        session: Session,
        password_manager: PasswordManager | None = None,
    ) -> None:
        self.session = session
        self.company_repository = CompanyRepository(session)
        self.user_repository = UserRepository(session)
        self.password_manager = (
            password_manager or PasswordManager()
        )

    def authenticate(
        self,
        company_code: str,
        login_identifier: str,
        password: str,
    ) -> AuthenticatedUser:
        """Authenticate by company code plus username or email."""

        normalized_company_code = company_code.strip().upper()
        normalized_identifier = login_identifier.strip()

        if not normalized_company_code:
            raise AuthenticationError(
                "Company code is required."
            )

        if not normalized_identifier or not password:
            raise AuthenticationError(
                "Username/email and password are required."
            )

        company = self.company_repository.get_by_code_case_insensitive(
            normalized_company_code
        )

        if company is None or not company.is_active:
            raise AuthenticationError(
                "Invalid company or login credentials."
            )

        user = self.user_repository.get_for_authentication(
            company_id=company.id,
            login_identifier=normalized_identifier,
        )

        if user is None or not user.is_active:
            raise AuthenticationError(
                "Invalid company or login credentials."
            )

        if not self.password_manager.verify_password(
            password,
            user.password_hash,
        ):
            raise AuthenticationError(
                "Invalid company or login credentials."
            )

        # Upgrade older Argon2 parameters after a valid login.
        if self.password_manager.needs_rehash(user.password_hash):
            user.password_hash = (
                self.password_manager.hash_password(password)
            )
            self.session.commit()

        return AuthenticatedUser.from_model(user)

    def change_password(
        self,
        *,
        company_id: int,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> AuthenticatedUser:
        """Verify the current password and store a new Argon2 hash."""

        if current_password == new_password:
            raise AuthenticationError(
                "The new password must be different "
                "from the current password."
            )

        user = self.user_repository.get_for_password_change(
            company_id=company_id,
            user_id=user_id,
        )

        if user is None or not user.is_active:
            raise AuthenticationError(
                "The user account is unavailable."
            )

        if not self.password_manager.verify_password(
            current_password,
            user.password_hash,
        ):
            raise AuthenticationError(
                "The current password is incorrect."
            )

        user.password_hash = (
            self.password_manager.hash_password(new_password)
        )
        user.must_change_password = False

        self.session.commit()
        self.session.refresh(user)

        return AuthenticatedUser.from_model(user)
