"""Audit trail writing.

One entry point, so every auditable action is recorded the same way and the set of audited
actions stays reviewable in one place (``AuditAction``).

Writing an audit row must never break the action being audited: a failure here is logged
and swallowed. The trade-off is deliberate — losing one audit row is preferable to failing
a job transition a customer and provider are waiting on. If auditing ever becomes a
compliance requirement rather than an operational one, this must be revisited.
"""

from __future__ import annotations

import logging

from apps.core.models import AuditEvent

logger = logging.getLogger(__name__)


def actor_label_for(user) -> str:
    """Stable human identifier, captured so the row outlives the account."""
    if user is None or getattr(user, "is_anonymous", False):
        return ""
    name = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip()
    identifier = getattr(user, "email", None) or getattr(user, "phone", None) or str(getattr(user, "pk", ""))
    role = getattr(user, "role", "")
    return f"{name or identifier} ({role})" if role else (name or identifier)


def record(
    action: str,
    *,
    actor=None,
    target_type: str = "",
    target_id=None,
    metadata: dict | None = None,
) -> AuditEvent | None:
    """Append one audit row. Returns ``None`` if the write failed."""
    try:
        return AuditEvent.objects.create(
            action=action,
            actor=actor if (actor is not None and not getattr(actor, "is_anonymous", False)) else None,
            actor_label=actor_label_for(actor),
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else "",
            metadata=metadata or {},
        )
    except Exception:  # pragma: no cover - auditing must not break the audited action
        logger.exception("audit write failed action=%s target=%s:%s", action, target_type, target_id)
        return None


def client_ip(request) -> str:
    """Best-effort client address for security events.

    ``X-Forwarded-For`` is attacker-controllable unless a trusted proxy overwrites it; it is
    recorded as a hint, not as proof.
    """
    if request is None:
        return ""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]
