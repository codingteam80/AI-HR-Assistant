"""Request-local administrator identity used by central audit logging."""

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuditActorContext:
    """Authenticated actor and currently open administration module."""

    company_id: int
    user_id: int
    module: str


_CURRENT_AUDIT_ACTOR: ContextVar[AuditActorContext | None] = ContextVar(
    "current_audit_actor",
    default=None,
)


def set_audit_actor(
    *,
    company_id: int,
    user_id: int,
    module: str,
) -> Token:
    """Set the actor for database writes during the current render."""

    return _CURRENT_AUDIT_ACTOR.set(
        AuditActorContext(
            company_id=company_id,
            user_id=user_id,
            module=module.strip() or "Administration",
        )
    )


def clear_audit_actor() -> None:
    """Remove an earlier administrator context before employee rendering."""

    _CURRENT_AUDIT_ACTOR.set(None)


def get_audit_actor() -> AuditActorContext | None:
    """Return the current authenticated administrator, if one was set."""

    return _CURRENT_AUDIT_ACTOR.get()

