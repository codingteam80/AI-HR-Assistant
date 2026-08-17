"""Browser bridge for refresh-safe authentication and route state.

The browser uses sessionStorage rather than localStorage:
- Refreshing the same tab keeps the login.
- Closing the tab does not create a permanent "remember me" login.
- Only an opaque token and navigation labels are stored.
"""

import json

import streamlit as st

from authentication.access_control import AccessControl
from authentication.persistent_auth_service import (
    PersistentAuthService,
    PersistentSessionError,
)
from authentication.session_manager import AuthSessionManager
from database.session import SessionFactory
from ui.components.browser_bridge import render_browser_bridge


TOKEN_QUERY_KEY = "auth_session"
CHECKED_QUERY_KEY = "auth_checked"
PORTAL_QUERY_KEY = "portal"
PAGE_QUERY_KEY = "page"

TOKEN_STORAGE_KEY = "ai_hr_auth_session"
PORTAL_STORAGE_KEY = "ai_hr_portal_mode"
PAGE_STORAGE_KEY = "ai_hr_current_page"


def _clean_route_value(
    value: object,
    *,
    max_length: int = 100,
) -> str | None:
    """Accept a small printable route value or return None."""

    if isinstance(value, (list, tuple)):
        value = value[0] if value else None

    if not isinstance(value, str):
        return None

    cleaned = value.strip()

    if not cleaned or len(cleaned) > max_length:
        return None

    return cleaned


def _restore_route_from_query(current_user) -> None:
    """Restore the last portal/page after a full browser refresh."""

    requested_portal = _clean_route_value(
        st.query_params.get(PORTAL_QUERY_KEY),
        max_length=20,
    )
    requested_page = _clean_route_value(
        st.query_params.get(PAGE_QUERY_KEY)
    )

    if (
        requested_portal == "admin"
        and AccessControl.is_admin(current_user)
    ):
        st.session_state.portal_mode = "admin"
        st.session_state.current_page = (
            requested_page or "Admin Dashboard"
        )
        return

    st.session_state.portal_mode = "employee"
    st.session_state.current_page = (
        requested_page or "Chat Assistant"
    )


def _render_browser_bridge(
    *,
    current_token: str | None,
    clear_browser: bool,
) -> None:
    """Save, restore, or clear browser sessionStorage values."""

    portal_mode = str(
        st.session_state.get("portal_mode", "employee")
    )
    current_page = str(
        st.session_state.get("current_page", "Chat Assistant")
    )

    token_json = json.dumps(current_token)
    portal_json = json.dumps(portal_mode)
    page_json = json.dumps(current_page)
    clear_json = "true" if clear_browser else "false"

    script = """
        <script>
        (() => {
            const parentWindow = window.parent;
            const currentUrl = new URL(parentWindow.location.href);

            const tokenKey = "__TOKEN_STORAGE_KEY__";
            const portalKey = "__PORTAL_STORAGE_KEY__";
            const pageKey = "__PAGE_STORAGE_KEY__";

            const currentToken = __CURRENT_TOKEN__;
            const currentPortal = __CURRENT_PORTAL__;
            const currentPage = __CURRENT_PAGE__;
            const clearBrowser = __CLEAR_BROWSER__;

            const removeAuthQuery = () => {
                currentUrl.searchParams.delete("auth_session");
                currentUrl.searchParams.delete("auth_checked");
                currentUrl.searchParams.delete("portal");
                currentUrl.searchParams.delete("page");

                parentWindow.history.replaceState(
                    null,
                    "",
                    currentUrl.toString()
                );
            };

            if (clearBrowser) {
                try {
                    parentWindow.sessionStorage.removeItem(tokenKey);
                    parentWindow.sessionStorage.removeItem(portalKey);
                    parentWindow.sessionStorage.removeItem(pageKey);
                } catch (error) {
                    // Python state is already logged out.
                }

                removeAuthQuery();
                return;
            }

            if (currentToken) {
                try {
                    parentWindow.sessionStorage.setItem(
                        tokenKey,
                        currentToken
                    );
                    parentWindow.sessionStorage.setItem(
                        portalKey,
                        currentPortal
                    );
                    parentWindow.sessionStorage.setItem(
                        pageKey,
                        currentPage
                    );
                } catch (error) {
                    // Current Streamlit session remains authenticated.
                }

                removeAuthQuery();
                return;
            }

            const alreadyChecked =
                currentUrl.searchParams.get("auth_checked") === "1";

            if (alreadyChecked) {
                return;
            }

            let savedToken = null;
            let savedPortal = null;
            let savedPage = null;

            try {
                savedToken = parentWindow.sessionStorage.getItem(
                    tokenKey
                );
                savedPortal = parentWindow.sessionStorage.getItem(
                    portalKey
                );
                savedPage = parentWindow.sessionStorage.getItem(
                    pageKey
                );
            } catch (error) {
                // Continue to login when storage is blocked.
            }

            currentUrl.searchParams.set("auth_checked", "1");

            if (savedToken) {
                currentUrl.searchParams.set(
                    "auth_session",
                    savedToken
                );

                if (savedPortal) {
                    currentUrl.searchParams.set(
                        "portal",
                        savedPortal
                    );
                }

                if (savedPage) {
                    currentUrl.searchParams.set(
                        "page",
                        savedPage
                    );
                }
            }

            parentWindow.location.replace(currentUrl.toString());
        })();
        </script>
    """

    replacements = {
        "__TOKEN_STORAGE_KEY__": TOKEN_STORAGE_KEY,
        "__PORTAL_STORAGE_KEY__": PORTAL_STORAGE_KEY,
        "__PAGE_STORAGE_KEY__": PAGE_STORAGE_KEY,
        "__CURRENT_TOKEN__": token_json,
        "__CURRENT_PORTAL__": portal_json,
        "__CURRENT_PAGE__": page_json,
        "__CLEAR_BROWSER__": clear_json,
    }

    for placeholder, replacement in replacements.items():
        script = script.replace(placeholder, replacement)

    render_browser_bridge(script)


def prepare_persistent_authentication() -> None:
    """Restore/validate authentication before protected routing.

    Full-refresh flow:
    1. First execution asks sessionStorage for the opaque token.
    2. The browser reloads once with a transient query parameter.
    3. Python validates the token against its database hash.
    4. Safe user and route state are restored.
    5. JavaScript immediately removes the token from the URL.
    """

    clear_browser = AuthSessionManager.should_clear_browser_auth()

    if clear_browser:
        _render_browser_bridge(
            current_token=None,
            clear_browser=True,
        )
        AuthSessionManager.mark_browser_auth_cleared()
        st.query_params[CHECKED_QUERY_KEY] = "1"
        return

    session_token = AuthSessionManager.get_auth_token()

    # Validate the active token on every execution. This immediately blocks
    # users whose account, company, or role has been deactivated.
    if session_token:
        try:
            with SessionFactory() as session:
                refreshed_user = PersistentAuthService(
                    session
                ).restore_session(session_token)

            AuthSessionManager.update_user(refreshed_user)

        except (PersistentSessionError, ValueError):
            AuthSessionManager.logout(revoke_token=False)
            _render_browser_bridge(
                current_token=None,
                clear_browser=True,
            )
            AuthSessionManager.mark_browser_auth_cleared()
            st.query_params[CHECKED_QUERY_KEY] = "1"
            return

        _render_browser_bridge(
            current_token=session_token,
            clear_browser=False,
        )
        return

    query_token = _clean_route_value(
        st.query_params.get(TOKEN_QUERY_KEY),
        max_length=500,
    )

    if query_token:
        try:
            with SessionFactory() as session:
                restored_user = PersistentAuthService(
                    session
                ).restore_session(query_token)

            AuthSessionManager.login(
                restored_user,
                query_token,
            )
            _restore_route_from_query(restored_user)

            _render_browser_bridge(
                current_token=query_token,
                clear_browser=False,
            )
            return

        except (PersistentSessionError, ValueError):
            AuthSessionManager.logout(revoke_token=False)
            _render_browser_bridge(
                current_token=None,
                clear_browser=True,
            )
            AuthSessionManager.mark_browser_auth_cleared()
            st.query_params[CHECKED_QUERY_KEY] = "1"
            return

    # Compatibility for a user who was already logged in before upgrading:
    # issue a persistent token without forcing another credential entry.
    if (
        st.session_state.get(
            AuthSessionManager.AUTHENTICATED_KEY
        )
        and st.session_state.get(AuthSessionManager.USER_KEY)
    ):
        existing_user = AuthSessionManager.get_current_user()

        if existing_user is not None:
            with SessionFactory() as session:
                new_token = PersistentAuthService(
                    session
                ).issue_session(existing_user)

            AuthSessionManager.login(
                existing_user,
                new_token,
            )
            _render_browser_bridge(
                current_token=new_token,
                clear_browser=False,
            )
            return

    already_checked = (
        str(
            st.query_params.get(CHECKED_QUERY_KEY, "")
        )
        == "1"
    )

    _render_browser_bridge(
        current_token=None,
        clear_browser=False,
    )

    if not already_checked:
        # The browser bridge runs asynchronously. Do not call st.stop()
        # here because the app can remain completely blank before the
        # component finishes checking sessionStorage.
        return
