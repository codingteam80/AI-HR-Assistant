"""Backward-compatible aliases for browser authentication storage.

Authentication persistence uses the bundled browser-storage component.
Current authentication tokens are stored in tab-scoped ``sessionStorage``
so separate browser tabs/windows can use independent accounts. New code
should import from ``authentication.browser_auth_storage``.
"""

from authentication.browser_auth_storage import (
    read_browser_auth_token,
    remove_browser_auth_token,
    replace_browser_auth_token_and_continue,
    write_browser_auth_token_and_continue,
)


def request_auth_cookie() -> str | None:
    """Compatibility alias for the persistent browser token reader."""

    return read_browser_auth_token()


def write_auth_cookie_and_continue(token: str) -> None:
    """Compatibility alias for token persistence after login."""

    write_browser_auth_token_and_continue(token)


def replace_auth_cookie_and_continue(token: str) -> None:
    """Compatibility alias for password-change token replacement."""

    replace_browser_auth_token_and_continue(token)


def remove_auth_cookie(*, wait_for_completion: bool) -> None:
    """Compatibility alias for persistent-token removal."""

    remove_browser_auth_token(
        wait_for_completion=wait_for_completion
    )
