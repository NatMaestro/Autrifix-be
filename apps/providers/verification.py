"""Provider verification levels — SPEC-013.

Verification is an **ordered level**, never a boolean. Comparisons go through
:func:`level_at_least` so the ordering is defined in exactly one place and adding a tier
later does not mean auditing scattered ``==`` checks.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class VerificationLevel(models.TextChoices):
    NONE = "none", _("Not verified")
    PHONE = "phone", _("Phone verified")
    DOCUMENTS = "documents", _("Documents verified")
    GHANA_CARD = "ghana_card", _("Ghana Card verified")


class ProviderType(models.TextChoices):
    """What trade a provider is in — SPEC-014 REQ-1.

    A *type*, not a role: verification, discovery, jobs, chat, reviews and ratings are
    identical for all of them, so splitting the role would duplicate every path. A garage
    that also runs a tow truck is one record with ``BOTH``.

    Finer-grained capability stays where it already lived: ``ProviderServiceOffering``
    against a ``ServiceCategory``.
    """

    MECHANIC = "mechanic", _("Mechanic")
    TOW = "tow", _("Tow operator")
    BOTH = "both", _("Mechanic and tow operator")


#: Types that can service a towing request.
TOW_CAPABLE_TYPES = frozenset({ProviderType.TOW, ProviderType.BOTH})
#: Types that can service a repair request.
REPAIR_CAPABLE_TYPES = frozenset({ProviderType.MECHANIC, ProviderType.BOTH})


class VerificationStatus(models.TextChoices):
    PENDING = "pending", _("Pending review")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")


#: Lowest to highest. The single source of truth for ordering.
VERIFICATION_LEVEL_ORDER: tuple[str, ...] = (
    VerificationLevel.NONE,
    VerificationLevel.PHONE,
    VerificationLevel.DOCUMENTS,
    VerificationLevel.GHANA_CARD,
)

#: Levels a provider can reach without a human reviewing anything.
AUTOMATIC_LEVELS = frozenset({VerificationLevel.NONE, VerificationLevel.PHONE})


def level_rank(level: str) -> int:
    try:
        return VERIFICATION_LEVEL_ORDER.index(level)
    except ValueError:
        return 0


def level_at_least(level: str, minimum: str) -> bool:
    """True when ``level`` is at or above ``minimum`` in the ordering."""
    return level_rank(level) >= level_rank(minimum)


def exact_location_min_level() -> str:
    """Level at which a provider sees exact customer coordinates while browsing.

    A setting rather than a constant, so the supply-versus-privacy trade can be retuned
    without shipping code (SPEC-013 OQ-013-B).
    """
    return getattr(settings, "PROVIDER_EXACT_LOCATION_MIN_LEVEL", VerificationLevel.DOCUMENTS)


def agency_of(provider):
    """The provider's live agency, or ``None`` — SPEC-014 REQ-7."""
    membership = (
        provider.memberships.filter(status="active").select_related("agency").first()
        if provider is not None
        else None
    )
    return membership.agency if membership else None


def effective_verification_level(provider) -> str:
    """The higher of the provider's own level and their agency's.

    An agency verified once should not make every operator re-submit the same business
    documents. The individual's own level is never *reduced* by this — it can only be
    lifted (SPEC-014 REQ-7).
    """
    if provider is None:
        return VerificationLevel.NONE
    own = provider.verification_level
    agency = agency_of(provider)
    if agency is None:
        return own
    return own if level_rank(own) >= level_rank(agency.verification_level) else agency.verification_level


def can_see_exact_locations(provider) -> bool:
    if provider is None:
        return False
    return level_at_least(effective_verification_level(provider), exact_location_min_level())


def accept_min_level() -> str:
    """Level required to accept work (SPEC-013 REQ-3).

    A setting because it is the marketplace's cold-start dial: set to ``documents`` it is a
    hard quality gate, but no provider can work until reviewed. Set to ``phone`` it is
    self-service and instant. See OQ-013-G.
    """
    return getattr(settings, "PROVIDER_MIN_ACCEPT_LEVEL", VerificationLevel.DOCUMENTS)


def can_accept_jobs(provider) -> bool:
    if provider is None:
        return False
    return level_at_least(effective_verification_level(provider), accept_min_level())


def missing_profile_requirements(provider) -> list[str]:
    """What still stands between this profile and being 'complete' (REQ-6)."""
    missing: list[str] = []
    if not (provider.business_name or "").strip():
        missing.append("business_name")
    if provider.base_latitude is None or provider.base_longitude is None:
        missing.append("workshop_location")
    if not provider.service_offerings.filter(is_active=True).exists():
        missing.append("active_service_offering")
    return missing


def is_profile_complete(provider) -> bool:
    return not missing_profile_requirements(provider)


def evaluate_automatic_level(provider, *, save: bool = True) -> str:
    """Recompute the level a provider qualifies for without human review.

    Only ever moves between ``none`` and ``phone``. A reviewer-granted level
    (``documents`` and above) is never downgraded here — losing an offering must not
    silently undo a human decision.
    """
    if provider.verification_level not in AUTOMATIC_LEVELS:
        return provider.verification_level

    qualifies = bool(getattr(provider.user, "is_phone_verified", False)) and is_profile_complete(provider)
    target = VerificationLevel.PHONE if qualifies else VerificationLevel.NONE

    if target != provider.verification_level:
        provider.verification_level = target
        if save:
            # update_fields avoids touching other columns; the post_save presence
            # broadcast still fires, which is harmless and keeps clients current.
            provider.save(update_fields=["verification_level", "updated_at"])
    return provider.verification_level
