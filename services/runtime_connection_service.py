"""Centralized classification for retryable runtime connection failures.

User-facing messages stay safe and actionable. Technical exception details are
logged server-side only and are never rendered directly into Streamlit pages.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import socket
from typing import Iterable
from urllib import error as urllib_error

from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeConnectionIssue:
    code: str
    title: str
    message: str
    service: str
    retryable: bool = True


class RuntimeServiceUnavailableError(Exception):
    """Typed wrapper used when a known local/external service is unreachable."""

    def __init__(self, service: str, *, cause: BaseException | None = None) -> None:
        self.service = (service or "service").strip().casefold()
        self.cause = cause
        super().__init__(f"{self.service} is unavailable")


def _exception_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _has_type(exc: BaseException, types: tuple[type[BaseException], ...]) -> bool:
    return any(isinstance(item, types) for item in _exception_chain(exc))


def _hint(value: str | None) -> str:
    return (value or "").strip().casefold().replace("-", "_")


def classify_runtime_connection_issue(
    exc: BaseException,
    *,
    service_hint: str | None = None,
) -> RuntimeConnectionIssue | None:
    """Return a safe issue only for recognizable connection/service failures."""

    explicit_service = ""
    for item in _exception_chain(exc):
        if isinstance(item, RuntimeServiceUnavailableError):
            explicit_service = item.service
            break

    hint = explicit_service or _hint(service_hint)
    network_types: tuple[type[BaseException], ...] = (
        urllib_error.URLError,
        TimeoutError,
        ConnectionError,
        socket.timeout,
        socket.gaierror,
    )
    has_network_failure = _has_type(exc, network_types) and not _has_type(
        exc, (urllib_error.HTTPError,)
    )

    if hint in {"ollama", "ai", "ai_service", "chat_assistant"}:
        return RuntimeConnectionIssue(
            code="ollama_unavailable",
            title="AI service unavailable",
            message=(
                "The local AI service cannot be reached right now. Make sure "
                "Ollama is running and the configured model is available, then "
                "try your question again. Direct HR records remain protected "
                "and are not sent to another service."
            ),
            service="Ollama",
        )

    if _has_type(exc, (OperationalError, InterfaceError, DisconnectionError)) or hint in {
        "database",
        "db",
        "sqlalchemy",
    }:
        return RuntimeConnectionIssue(
            code="database_unavailable",
            title="HR data connection unavailable",
            message=(
                "The application cannot reach the HR database right now. No "
                "new change was completed by this failed request. Restore the "
                "database connection and try again."
            ),
            service="Database",
        )

    if hint in {"email", "smtp", "mail"} and has_network_failure:
        return RuntimeConnectionIssue(
            code="email_provider_unavailable",
            title="Email service unavailable",
            message=(
                "The email provider could not be reached. Check the internet "
                "connection and the saved email configuration, then try again."
            ),
            service="Email",
        )

    if hint in {"sms", "twilio", "sms_provider"} and has_network_failure:
        return RuntimeConnectionIssue(
            code="sms_provider_unavailable",
            title="SMS service unavailable",
            message=(
                "The SMS provider could not be reached. Check the internet "
                "connection and SMS gateway configuration, then try again."
            ),
            service="SMS",
        )

    if has_network_failure or hint in {"network", "internet"}:
        return RuntimeConnectionIssue(
            code="network_unavailable",
            title="Network connection unavailable",
            message=(
                "A required network connection could not be reached. Check the "
                "network/internet connection and try again."
            ),
            service="Network",
        )

    return None


def log_runtime_connection_issue(
    exc: BaseException,
    issue: RuntimeConnectionIssue,
    *,
    context: str,
) -> None:
    """Log technical details without exposing them in the browser."""

    logger.warning(
        "Runtime connection issue code=%s service=%s context=%s",
        issue.code,
        issue.service,
        context,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
