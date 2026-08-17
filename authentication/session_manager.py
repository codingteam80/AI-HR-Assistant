"""Streamlit authentication-session management.

Normal widget reruns use Streamlit session_state. Full browser refreshes
restore the user from a signed token in browser localStorage. The bundled
component waits for the browser response before Login can be rendered.
"""

import streamlit as st

from authentication.browser_auth_storage import (
    read_browser_auth_token,
    remove_browser_auth_token,
    replace_browser_auth_token_and_continue,
    write_browser_auth_token,
)
from authentication.current_user import AuthenticatedUser
from authentication.signed_cookie_auth_service import (
    SignedCookieAuthenticationError,
    SignedCookieAuthService,
)
from database.session import SessionFactory
from ui.navigation_state import clear_navigation_state
from ui.components.browser_bridge import render_browser_bridge


class AuthSessionManager:
    """Create, restore, update, and clear authentication state."""

    AUTHENTICATED_KEY = "is_authenticated"
    USER_KEY = "authenticated_user"
    TOKEN_KEY = "signed_auth_token"
    PENDING_BROWSER_TOKEN_KEY = "_pending_browser_auth_token"

    # Prevent the original WebSocket request cookie from restoring the user
    # immediately after explicit logout.
    LOGOUT_PENDING_KEY = "_auth_logout_pending"

    # Private HR Assistant state must not cross authenticated accounts.
    HR_CHAT_STATE_PREFIXES = (
        "hr_assistant_chat_messages__",
        "hr_assistant_chat_input__",
        "new_hr_assistant_conversation__",
        "admin_hr_assistant_chat_messages__",
        "admin_hr_assistant_chat_input__",
        "new_admin_hr_assistant_conversation__",
    )
    HR_CHAT_UNSCOPED_KEYS = {
        "hr_assistant_chat_messages",
        "policy_chat_messages",
    }

    @classmethod
    def initialize(cls) -> None:
        """Create required keys for a new Streamlit browser session."""

        st.session_state.setdefault(
            cls.AUTHENTICATED_KEY,
            False,
        )
        st.session_state.setdefault(
            cls.USER_KEY,
            None,
        )
        st.session_state.setdefault(
            cls.TOKEN_KEY,
            None,
        )
        st.session_state.setdefault(
            cls.PENDING_BROWSER_TOKEN_KEY,
            None,
        )
        st.session_state.setdefault(
            cls.LOGOUT_PENDING_KEY,
            False,
        )

    @staticmethod
    def _identity_from_session_values(
        values,
    ) -> tuple[int, int] | None:
        """Return company/user identity from stored safe session values."""

        if not isinstance(values, dict):
            return None

        try:
            return (
                int(values["company_id"]),
                int(values["user_id"]),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return None

    @classmethod
    def _clear_hr_assistant_browser_state(
        cls,
    ) -> None:
        """Remove private and legacy chat data from this browser session."""

        for key in list(
            st.session_state.keys()
        ):
            if (
                key in cls.HR_CHAT_UNSCOPED_KEYS
                or any(
                    str(key).startswith(prefix)
                    for prefix
                    in cls.HR_CHAT_STATE_PREFIXES
                )
            ):
                st.session_state.pop(
                    key,
                    None,
                )

    @classmethod
    def _save_session(
        cls,
        user: AuthenticatedUser,
        signed_token: str,
    ) -> None:
        """Store safe user data in the current Streamlit session."""

        previous_identity = cls._identity_from_session_values(
            st.session_state.get(
                cls.USER_KEY
            )
        )
        current_identity = (
            user.company_id,
            user.user_id,
        )

        if (
            previous_identity is not None
            and previous_identity != current_identity
        ):
            cls._clear_hr_assistant_browser_state()

        # Remove legacy unscoped values even when the same user is restored.
        for key in cls.HR_CHAT_UNSCOPED_KEYS:
            st.session_state.pop(
                key,
                None,
            )

        st.session_state[cls.AUTHENTICATED_KEY] = True
        st.session_state[cls.USER_KEY] = user.to_session_dict()
        st.session_state[cls.TOKEN_KEY] = signed_token
        st.session_state[cls.LOGOUT_PENDING_KEY] = False
        st.session_state[
            "public_company_code"
        ] = user.company_code

    @classmethod
    def complete_login(
        cls,
        user: AuthenticatedUser,
        *,
        signed_token: str,
    ) -> None:
        """Open the portal on the first submit and persist in the background."""

        cls._save_session(user, signed_token)
        st.session_state[
            cls.PENDING_BROWSER_TOKEN_KEY
        ] = signed_token

        # Do not stop on the Login page while a browser component writes the
        # persistence token. The current Streamlit session is already safely
        # authenticated, so route to the portal immediately.
        st.rerun()

    @classmethod
    def flush_pending_browser_token(cls) -> None:
        """Persist a pending token without blocking an authenticated page."""

        pending = st.session_state.get(
            cls.PENDING_BROWSER_TOKEN_KEY
        )

        if not isinstance(pending, str) or not pending:
            return

        try:
            if write_browser_auth_token(pending):
                st.session_state[
                    cls.PENDING_BROWSER_TOKEN_KEY
                ] = None
        except (ValueError, RuntimeError):
            # Keep the portal usable. Persistence can retry on the next rerun;
            # the separate full-refresh issue remains tracked independently.
            return

    @classmethod
    def _clear_local_session(cls) -> None:
        """Clear authentication values without starting a transition."""

        st.session_state[cls.AUTHENTICATED_KEY] = False
        st.session_state[cls.USER_KEY] = None
        st.session_state[cls.TOKEN_KEY] = None
        st.session_state[
            cls.PENDING_BROWSER_TOKEN_KEY
        ] = None

    @classmethod
    def restore_from_browser(cls) -> bool:
        """Restore the account from memory or persistent browser storage.

        A full F5 refresh creates a new Streamlit session. The bundled
        component returns ``ready=False`` during its first render, so the
        application stops before Login and resumes only after localStorage
        has returned the signed token (or confirmed that none exists).
        """

        if st.session_state.get(cls.LOGOUT_PENDING_KEY):
            return False

        token = st.session_state.get(cls.TOKEN_KEY)

        if not isinstance(token, str) or not token:
            token = read_browser_auth_token()

        if not isinstance(token, str) or not token:
            cls._clear_local_session()
            return False

        try:
            # Revalidation means a password reset, disabled account, or
            # inactive company invalidates the stored browser token.
            with SessionFactory() as session:
                current_user = SignedCookieAuthService(
                    session
                ).restore_user(token)

            cls._save_session(current_user, token)
            return True

        except (
            SignedCookieAuthenticationError,
            ValueError,
        ):
            cls._clear_local_session()
            remove_browser_auth_token(
                wait_for_completion=False
            )
            return False

    @classmethod
    def restore_from_cookie(cls) -> bool:
        """Compatibility alias retained for older integrations."""

        return cls.restore_from_browser()

    @classmethod
    def complete_password_change(
        cls,
        user: AuthenticatedUser,
        *,
        signed_token: str,
    ) -> None:
        """Save updated user data and replace the cookie."""

        cls._save_session(user, signed_token)
        replace_browser_auth_token_and_continue(
            signed_token
        )

    @classmethod
    def logout(cls) -> None:
        """Clear authentication while preserving company branding."""

        current_user = cls.get_current_user()

        if current_user is not None:
            st.session_state[
                "public_company_code"
            ] = current_user.company_code
            st.query_params[
                "company"
            ] = current_user.company_code

        cls._clear_hr_assistant_browser_state()

        st.session_state[cls.AUTHENTICATED_KEY] = False
        st.session_state[cls.USER_KEY] = None
        st.session_state[cls.TOKEN_KEY] = None
        st.session_state[
            cls.PENDING_BROWSER_TOKEN_KEY
        ] = None
        st.session_state[cls.LOGOUT_PENDING_KEY] = True
        clear_navigation_state()

        remove_browser_auth_token(
            wait_for_completion=True
        )
        st.rerun()

    @classmethod
    def complete_logout_transition(cls) -> None:
        """Replace retained portal DOM with a clean public-login document."""

        # A clean browser reload removes the protected portal DOM and its
        # injected layout CSS before Login is rendered. A normal Streamlit
        # rerun can briefly retain that old DOM, which previously hid the
        # Welcome Back heading until the user manually refreshed the page.
        render_browser_bridge(
            "<script>window.parent.location.reload();</script>"
        )
        st.stop()

    @classmethod
    def clear_after_password_reset(cls) -> None:
        """Clear this browser session after an external password reset."""

        cls._clear_hr_assistant_browser_state()
        cls._clear_local_session()
        st.session_state[cls.LOGOUT_PENDING_KEY] = False
        clear_navigation_state()
        remove_browser_auth_token(
            wait_for_completion=False
        )

    @classmethod
    def is_authenticated(cls) -> bool:
        """Return True only when safe authenticated user data exists."""

        return bool(
            st.session_state.get(cls.AUTHENTICATED_KEY)
            and st.session_state.get(cls.USER_KEY)
        )

    @classmethod
    def get_current_user(cls) -> AuthenticatedUser | None:
        """Return the typed current user or None."""

        values = st.session_state.get(cls.USER_KEY)

        if not values:
            return None

        return AuthenticatedUser.from_session_dict(values)
