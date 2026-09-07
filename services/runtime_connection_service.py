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


class RuntimeServiceTimeoutError(Exception):
    """Typed wrapper for a reachable/runtime operation that exceeded its limit."""

    def __init__(
        self,
        service: str,
        *,
        operation: str,
        timeout_seconds: float | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.service = (service or "service").strip().casefold()
        self.operation = (operation or "request").strip().casefold()
        self.timeout_seconds = timeout_seconds
        self.cause = cause
        super().__init__(f"{self.service} {self.operation} timed out")


class RuntimeServiceModelUnavailableError(Exception):
    """Typed wrapper for a running local AI service with a missing model."""

    def __init__(
        self,
        service: str,
        *,
        model: str,
        cause: BaseException | None = None,
    ) -> None:
        self.service = (service or "service").strip().casefold()
        self.model = (model or "configured model").strip()
        self.cause = cause
        super().__init__(f"{self.service} model is unavailable: {self.model}")


class RuntimeServiceResponseError(Exception):
    """Typed wrapper for a reachable service that rejected/failed a request.

    ``detail`` is kept for server-side diagnostics only. UI classification
    below always returns a fixed safe message and never exposes it directly.
    """

    def __init__(
        self,
        service: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.service = (service or "service").strip().casefold()
        self.status_code = status_code
        self.detail = (detail or "").strip()[:2000]
        self.cause = cause
        label = f" HTTP {status_code}" if status_code is not None else ""
        diagnostic = f": {self.detail}" if self.detail else ""
        super().__init__(f"{self.service}{label} request failed{diagnostic}")


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
    response_error: RuntimeServiceResponseError | None = None
    timeout_error: RuntimeServiceTimeoutError | None = None
    model_error: RuntimeServiceModelUnavailableError | None = None

    for item in _exception_chain(exc):
        if isinstance(item, RuntimeServiceResponseError):
            explicit_service = item.service
            response_error = item
            break
        if isinstance(item, RuntimeServiceTimeoutError):
            explicit_service = item.service
            timeout_error = item
            break
        if isinstance(item, RuntimeServiceModelUnavailableError):
            explicit_service = item.service
            model_error = item
            break
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
        if model_error is not None:
            return RuntimeConnectionIssue(
                code="ollama_model_missing",
                title="AI model unavailable",
                message=(
                    f"Ollama is running, but the configured local model "
                    f"'{model_error.model}' is not available. Install or restore "
                    "that model, then try the question again. The HR Assistant "
                    "will keep any verified company answer it already produced."
                ),
                service="Ollama",
            )

        if timeout_error is not None:
            operation = timeout_error.operation
            if operation == "health_check":
                return RuntimeConnectionIssue(
                    code="ollama_health_timeout",
                    title="AI service check timed out",
                    message=(
                        "Ollama did not answer the local availability check within "
                        "the allowed time. The service may still be starting or "
                        "busy. The HR Assistant will keep any verified company "
                        "answer it already produced; try again after Ollama is ready."
                    ),
                    service="Ollama",
                )
            return RuntimeConnectionIssue(
                code="ollama_response_timeout",
                title="AI response timed out",
                message=(
                    "The local AI model took too long to complete the response. "
                    "A smaller one-time retry was attempted when safe. The HR "
                    "Assistant will keep any verified company answer it already "
                    "produced."
                ),
                service="Ollama",
            )

        if response_error is not None:
            detail = response_error.detail.casefold()
            context_limit_terms = (
                "context length",
                "context window",
                "too many tokens",
                "prompt too long",
                "input too long",
                "maximum context",
            )
            if any(term in detail for term in context_limit_terms):
                return RuntimeConnectionIssue(
                    code="ollama_context_limit",
                    title="AI request was too large",
                    message=(
                        "The local AI model could not process the full request "
                        "within its safe context limit. The HR Assistant will "
                        "keep any verified portal answer it already produced. "
                        "Try narrowing the question if more detail is needed."
                    ),
                    service="Ollama",
                )
            return RuntimeConnectionIssue(
                code="ollama_generation_failed",
                title="AI response generation issue",
                message=(
                    "Ollama is running, but the local model could not complete "
                    "this enhancement request. Any verified HR result already "
                    "produced by the portal is kept. Try the question again; "
                    "if it repeats, review the local Ollama log."
                ),
                service="Ollama",
            )

        return RuntimeConnectionIssue(
            code="ollama_unavailable",
            title="AI service unavailable",
            message=(
                "The local Ollama service cannot be reached right now. Make sure "
                "Ollama is running, then try your question again. Any verified "
                "company answer already produced by the HR Assistant is kept, and "
                "private HR records are not sent to another service."
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
