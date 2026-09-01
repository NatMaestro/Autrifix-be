"""Agency membership workflow — SPEC-017.

All agency and membership state changes go through this module. The authorization rules
live here rather than in DRF permission classes for the same reason the job transitions do:
they must hold for every caller, admin actions included, and they are the part worth reading
in one place.

Two invariants are load-bearing:

- **`verification_level` is never writable through this module.** An agency that could set
  its own level would lift every member's effective level with it (SPEC-014 REQ-7), which
  turns the trust ladder into a self-service form. It is granted by platform review only.
- **An agency always keeps at least one owner.** Otherwise a membership can be removed or
  demoted into an agency nobody can administer, recoverable only from the Django admin.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import User, UserRole
from apps.accounts.phone import normalize_phone
from apps.core import audit
from apps.core.exceptions import Conflict
from apps.core.models import AuditAction
from apps.notifications import services as notifications
from apps.providers.agencies import AGENCY_ADMIN_ROLES, AgencyRole, MembershipStatus
from apps.providers.models import Agency, AgencyMembership

#: Membership states that occupy a provider's single live slot.
LIVE_MEMBERSHIP_STATUSES = frozenset({MembershipStatus.INVITED, MembershipStatus.ACTIVE})


# --------------------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------------------


def live_membership(provider) -> AgencyMembership | None:
    """The provider's current membership or outstanding invitation, if any."""
    return (
        AgencyMembership.objects.filter(
            provider=provider, status__in=LIVE_MEMBERSHIP_STATUSES
        )
        .select_related("agency")
        .first()
    )


def membership_for(agency, provider) -> AgencyMembership | None:
    return AgencyMembership.objects.filter(
        agency=agency, provider=provider, status__in=LIVE_MEMBERSHIP_STATUSES
    ).first()


def visible_agency_or_404(provider, agency_id) -> Agency:
    """An agency the provider belongs to, or `404`.

    `404` rather than `403`: an agency id should not be confirmable by someone outside it,
    which is the same reasoning applied to job ids.
    """
    membership = AgencyMembership.objects.filter(
        agency_id=agency_id, provider=provider, status__in=LIVE_MEMBERSHIP_STATUSES
    ).first()
    if membership is None:
        raise NotFound("Agency not found.")
    return membership.agency


def _require_admin(agency, provider) -> AgencyMembership:
    membership = AgencyMembership.objects.filter(
        agency=agency, provider=provider, status=MembershipStatus.ACTIVE
    ).first()
    if membership is None or membership.role not in AGENCY_ADMIN_ROLES:
        raise PermissionDenied("Only an owner or manager can do that.")
    return membership


def _active_owner_count(agency, *, excluding=None) -> int:
    qs = AgencyMembership.objects.filter(
        agency=agency, status=MembershipStatus.ACTIVE, role=AgencyRole.OWNER
    )
    if excluding is not None:
        qs = qs.exclude(pk=excluding)
    return qs.count()


def _unique_slug(name: str) -> str:
    base = slugify(name)[:200] or "agency"
    slug = base
    suffix = 2
    while Agency.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"[:220]
        suffix += 1
    return slug


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------


@transaction.atomic
def create_agency(*, provider, **fields) -> Agency:
    """Register a business. The creator becomes its first active owner."""
    if live_membership(provider) is not None:
        raise Conflict(
            "You already belong to an agency. Leave it before creating another."
        )

    agency = Agency.objects.create(slug=_unique_slug(fields.get("name", "")), **fields)
    AgencyMembership.objects.create(
        agency=agency,
        provider=provider,
        role=AgencyRole.OWNER,
        status=MembershipStatus.ACTIVE,
        joined_at=timezone.now(),
    )

    audit.record(
        AuditAction.AGENCY_CREATED,
        actor=provider.user,
        target_type="agency",
        target_id=agency.id,
        metadata={"name": agency.name, "provider_type": agency.provider_type},
    )
    return agency


@transaction.atomic
def update_agency(*, agency, provider, **fields) -> Agency:
    """Edit the business details. `verification_level` is not among them, by design."""
    _require_admin(agency, provider)

    for field, value in fields.items():
        setattr(agency, field, value)
    agency.save()
    return agency


@transaction.atomic
def invite_provider(*, agency, actor_provider, phone: str, role: str) -> AgencyMembership:
    """Invite a provider to join, addressed by the phone number they signed up with."""
    _require_admin(agency, actor_provider)

    if role == AgencyRole.OWNER:
        # Ownership is transferred by promoting an existing member, not handed to someone
        # who has not yet accepted — an unaccepted owner is an agency with no live admin.
        raise ValidationError({"role": "Invite as manager or operator, then promote."})

    user = User.objects.filter(
        phone=normalize_phone(phone), role=UserRole.PROVIDER
    ).select_related("provider_profile").first()
    invitee = getattr(user, "provider_profile", None) if user else None
    if invitee is None:
        raise NotFound("No provider account uses that number.")

    if invitee.id == actor_provider.id:
        raise Conflict("You are already a member of this agency.")

    existing = live_membership(invitee)
    if existing is not None:
        raise Conflict(
            "That provider is already in an agency."
            if existing.status == MembershipStatus.ACTIVE
            else "That provider already has a pending invitation."
        )

    try:
        membership = AgencyMembership.objects.create(
            agency=agency, provider=invitee, role=role, status=MembershipStatus.INVITED
        )
    except IntegrityError as exc:  # raced with another invitation
        raise Conflict("That provider already has a live membership.") from exc

    audit.record(
        AuditAction.AGENCY_MEMBER_INVITED,
        actor=actor_provider.user,
        target_type="agency_membership",
        target_id=membership.id,
        metadata={
            "agency_id": str(agency.id),
            "provider_id": str(invitee.id),
            "role": role,
        },
    )
    notifications.notify_agency_invitation(membership)
    return membership


@transaction.atomic
def respond_to_invitation(*, membership, provider, accept: bool) -> AgencyMembership:
    """The invited provider accepts or declines."""
    membership = (
        AgencyMembership.objects.select_for_update()
        .select_related("agency", "provider__user")
        .get(pk=membership.pk)
    )

    if membership.provider_id != provider.id:
        raise NotFound("Invitation not found.")
    if membership.status != MembershipStatus.INVITED:
        raise Conflict(f"This invitation is already '{membership.status}'.")

    now = timezone.now()
    if accept:
        membership.status = MembershipStatus.ACTIVE
        membership.joined_at = now
        membership.save(update_fields=["status", "joined_at"])
    else:
        # Declining frees the provider's single live slot, so it must land in `removed`
        # rather than a fourth state the unique constraint does not know about.
        membership.status = MembershipStatus.REMOVED
        membership.removed_at = now
        membership.save(update_fields=["status", "removed_at"])

    audit.record(
        AuditAction.AGENCY_MEMBERSHIP_CHANGED,
        actor=provider.user,
        target_type="agency_membership",
        target_id=membership.id,
        metadata={
            "agency_id": str(membership.agency_id),
            "change": "accepted" if accept else "declined",
        },
    )
    notifications.notify_agency_invitation_answered(membership, accepted=accept)
    return membership


@transaction.atomic
def change_member_role(*, agency, actor_provider, membership, role: str) -> AgencyMembership:
    _require_admin(agency, actor_provider)

    if membership.agency_id != agency.id:
        raise NotFound("Member not found.")
    if membership.status != MembershipStatus.ACTIVE:
        raise Conflict("Only an active member's role can be changed.")

    if (
        membership.role == AgencyRole.OWNER
        and role != AgencyRole.OWNER
        and _active_owner_count(agency, excluding=membership.pk) == 0
    ):
        raise Conflict("An agency must keep at least one owner. Promote someone first.")

    previous = membership.role
    membership.role = role
    membership.save(update_fields=["role"])

    audit.record(
        AuditAction.AGENCY_MEMBERSHIP_CHANGED,
        actor=actor_provider.user,
        target_type="agency_membership",
        target_id=membership.id,
        metadata={
            "agency_id": str(agency.id),
            "change": "role_changed",
            "from": previous,
            "to": role,
        },
    )
    return membership


@transaction.atomic
def remove_member(*, agency, actor_provider, membership) -> AgencyMembership:
    """Remove a member, or leave the agency yourself.

    Removal is a status change, not a delete: the membership is history, and an agency that
    could erase who worked for it would erase the attribution the audit trail depends on.
    """
    membership = (
        AgencyMembership.objects.select_for_update()
        .select_related("agency", "provider__user")
        .get(pk=membership.pk)
    )
    if membership.agency_id != agency.id:
        raise NotFound("Member not found.")

    leaving = membership.provider_id == actor_provider.id
    if not leaving:
        _require_admin(agency, actor_provider)

    if membership.status == MembershipStatus.REMOVED:
        raise Conflict("That membership has already ended.")

    if (
        membership.role == AgencyRole.OWNER
        and membership.status == MembershipStatus.ACTIVE
        and _active_owner_count(agency, excluding=membership.pk) == 0
    ):
        raise Conflict("An agency must keep at least one owner. Promote someone first.")

    membership.status = MembershipStatus.REMOVED
    membership.removed_at = timezone.now()
    membership.save(update_fields=["status", "removed_at"])

    audit.record(
        AuditAction.AGENCY_MEMBERSHIP_CHANGED,
        actor=actor_provider.user,
        target_type="agency_membership",
        target_id=membership.id,
        metadata={
            "agency_id": str(agency.id),
            "change": "left" if leaving else "removed",
            "provider_id": str(membership.provider_id),
        },
    )
    if not leaving:
        notifications.notify_agency_membership_ended(membership)
    return membership
