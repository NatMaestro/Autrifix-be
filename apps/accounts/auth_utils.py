"""Resolve login / lookup by a single identifier string (email or phone)."""

from __future__ import annotations

from apps.accounts.models import User
from apps.accounts.phone import normalize_phone


def user_for_identifier(identifier: str) -> User | None:
    raw = (identifier or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    if "@" in raw:
        return User.objects.filter(email__iexact=lowered).first()
    try:
        phone = normalize_phone(raw)
    except ValueError:
        return None
    return User.objects.filter(phone=phone).first()
