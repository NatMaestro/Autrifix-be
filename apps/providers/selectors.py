"""Single source of truth for resolving a provider's profile.

Four call sites previously used a bare ``ProviderProfile.objects.get(user=...)``, which
raised ``DoesNotExist`` (an unhandled 500) for a provider who had registered but never
opened their profile. See ``specs/003-provider-profiles.md`` CONFLICT-003-A.
"""

from __future__ import annotations

from apps.accounts.models import UserRole
from apps.core.exceptions import Conflict
from apps.providers.models import ProviderProfile


def default_business_name(user) -> str:
    if user.email:
        return user.email.split("@")[0]
    return user.phone or "Workshop"


def ensure_provider_profile(user) -> ProviderProfile:
    """Return the user's provider profile, creating it on first use."""
    if getattr(user, "role", None) != UserRole.PROVIDER:
        raise Conflict("This account is not a provider account.")
    profile, _created = ProviderProfile.objects.get_or_create(
        user=user,
        defaults={"business_name": default_business_name(user)},
    )
    return profile


def get_provider_profile(user) -> ProviderProfile:
    """Return an existing provider profile, or raise a handled 409.

    Used where implicitly creating a profile would be wrong (accepting a job, browsing
    the request feed) — the provider must set one up deliberately first.
    """
    try:
        return ProviderProfile.objects.get(user=user)
    except ProviderProfile.DoesNotExist as exc:
        raise Conflict(
            "Set up your provider profile before using this endpoint.",
        ) from exc
