"""Agency API — SPEC-017.

SPEC-014 built the agency model, memberships, and inherited verification, and gave them no
endpoints. These tests cover the surface that makes them usable, and pin the two invariants
that make it safe: an agency cannot grant itself a verification level, and it cannot be left
without an owner.
"""

import pytest
from django.urls import reverse

from apps.core.models import AuditAction, AuditEvent
from apps.notifications.models import Notification, NotificationKind
from apps.providers.agencies import AgencyRole, MembershipStatus
from apps.providers.models import Agency, AgencyMembership
from apps.providers.verification import VerificationLevel, effective_verification_level

pytestmark = pytest.mark.django_db

CREATE_URL = reverse("agency-create")
MY_MEMBERSHIPS_URL = reverse("my-memberships")


def detail_url(agency):
    return reverse("agency-detail", kwargs={"id": agency.id})


def members_url(agency):
    return reverse("agency-members", kwargs={"id": agency.id})


def member_url(agency, membership):
    return reverse(
        "agency-member-detail", kwargs={"id": agency.id, "membership_id": membership.id}
    )


def respond_url(membership):
    return reverse("membership-respond", kwargs={"id": membership.id})


@pytest.fixture
def agency(provider_profile):
    """An agency owned by `provider_profile`."""
    agency = Agency.objects.create(name="Kaneshie Towing", slug="kaneshie-towing")
    AgencyMembership.objects.create(
        agency=agency,
        provider=provider_profile,
        role=AgencyRole.OWNER,
        status=MembershipStatus.ACTIVE,
    )
    return agency


@pytest.fixture
def invited(agency, other_provider_profile):
    return AgencyMembership.objects.create(
        agency=agency,
        provider=other_provider_profile,
        role=AgencyRole.OPERATOR,
        status=MembershipStatus.INVITED,
    )


# --- creation -----------------------------------------------------------------------


def test_create_requires_authentication(api):
    assert api.post(CREATE_URL, {"name": "X"}, format="json").status_code == 401


def test_customer_cannot_create_an_agency(as_user, customer_user):
    assert as_user(customer_user).post(CREATE_URL, {"name": "X"}, format="json").status_code == 403


def test_provider_creates_an_agency_and_becomes_its_owner(
    as_user, provider_user, provider_profile
):
    response = as_user(provider_user).post(
        CREATE_URL, {"name": "Kaneshie Towing", "provider_type": "tow"}, format="json"
    )
    assert response.status_code == 201
    assert response.data["slug"] == "kaneshie-towing"
    assert response.data["my_role"] == AgencyRole.OWNER
    assert response.data["member_count"] == 1

    membership = AgencyMembership.objects.get(provider=provider_profile)
    assert membership.role == AgencyRole.OWNER
    assert membership.status == MembershipStatus.ACTIVE
    assert membership.joined_at is not None


def test_a_new_agency_starts_unverified(as_user, provider_user):
    """Verification is granted by review, never by registering a business."""
    response = as_user(provider_user).post(CREATE_URL, {"name": "X"}, format="json")
    assert response.data["verification_level"] == VerificationLevel.NONE


def test_slug_collisions_are_resolved(as_user, provider_user, other_provider_user, other_provider_profile):
    as_user(provider_user).post(CREATE_URL, {"name": "City Motors"}, format="json")
    second = as_user(other_provider_user).post(CREATE_URL, {"name": "City Motors"}, format="json")
    assert second.status_code == 201
    assert second.data["slug"] == "city-motors-2"


def test_cannot_create_a_second_agency_while_in_one(as_user, provider_user, agency):
    response = as_user(provider_user).post(CREATE_URL, {"name": "Another"}, format="json")
    assert response.status_code == 409


def test_creation_is_audited(as_user, provider_user):
    as_user(provider_user).post(CREATE_URL, {"name": "Kaneshie Towing"}, format="json")
    event = AuditEvent.objects.get(action=AuditAction.AGENCY_CREATED)
    assert event.actor_id == provider_user.id
    assert event.metadata["name"] == "Kaneshie Towing"


# --- reading and editing ------------------------------------------------------------


def test_member_reads_their_agency(as_user, provider_user, agency):
    response = as_user(provider_user).get(detail_url(agency))
    assert response.status_code == 200
    assert response.data["name"] == "Kaneshie Towing"


def test_outsider_gets_404_not_403(as_user, other_provider_user, other_provider_profile, agency):
    """An agency id should not be confirmable from outside it."""
    assert as_user(other_provider_user).get(detail_url(agency)).status_code == 404


def test_customer_cannot_read_an_agency(as_user, customer_user, agency):
    assert as_user(customer_user).get(detail_url(agency)).status_code == 403


def test_admin_edits_business_details(as_user, provider_user, agency):
    response = as_user(provider_user).patch(
        detail_url(agency), {"contact_email": "ops@kaneshie.gh"}, format="json"
    )
    assert response.status_code == 200
    agency.refresh_from_db()
    assert agency.contact_email == "ops@kaneshie.gh"


def test_verification_level_cannot_be_set_through_the_api(as_user, provider_user, agency):
    """The load-bearing one: an agency that sets its own level lifts every member with it."""
    response = as_user(provider_user).patch(
        detail_url(agency), {"verification_level": VerificationLevel.GHANA_CARD}, format="json"
    )
    assert response.status_code == 200  # accepted, but the field is simply not applied
    agency.refresh_from_db()
    assert agency.verification_level == VerificationLevel.NONE


def test_operator_cannot_edit_the_agency(
    as_user, other_provider_user, other_provider_profile, agency, invited
):
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])

    response = as_user(other_provider_user).patch(
        detail_url(agency), {"name": "Renamed"}, format="json"
    )
    assert response.status_code == 403


# --- inviting -----------------------------------------------------------------------


def test_admin_invites_a_provider_by_phone(
    as_user, provider_user, agency, other_provider_user, other_provider_profile
):
    response = as_user(provider_user).post(
        members_url(agency), {"phone": other_provider_user.phone, "role": "operator"}, format="json"
    )
    assert response.status_code == 201
    assert response.data["status"] == MembershipStatus.INVITED
    assert response.data["role"] == AgencyRole.OPERATOR


def test_invitation_notifies_the_invitee(
    as_user, provider_user, agency, other_provider_user, other_provider_profile
):
    as_user(provider_user).post(
        members_url(agency), {"phone": other_provider_user.phone}, format="json"
    )
    kinds = list(
        Notification.objects.filter(user=other_provider_user).values_list("kind", flat=True)
    )
    assert NotificationKind.AGENCY_INVITED in kinds


def test_inviting_an_unknown_number_is_404(as_user, provider_user, agency):
    response = as_user(provider_user).post(
        members_url(agency), {"phone": "+233200000999"}, format="json"
    )
    assert response.status_code == 404


def test_cannot_invite_a_customer(as_user, provider_user, agency, customer_user):
    response = as_user(provider_user).post(
        members_url(agency), {"phone": customer_user.phone}, format="json"
    )
    assert response.status_code == 404


def test_cannot_invite_as_owner(
    as_user, provider_user, agency, other_provider_user, other_provider_profile
):
    """An unaccepted owner is an agency with no live admin. Promote instead."""
    response = as_user(provider_user).post(
        members_url(agency), {"phone": other_provider_user.phone, "role": "owner"}, format="json"
    )
    assert response.status_code == 400


def test_cannot_invite_someone_already_in_an_agency(
    as_user, provider_user, agency, other_provider_user, invited
):
    response = as_user(provider_user).post(
        members_url(agency), {"phone": other_provider_user.phone}, format="json"
    )
    assert response.status_code == 409


def test_operator_cannot_invite(
    as_user, other_provider_user, agency, invited, make_user, make_provider_profile
):
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])
    third = make_user(role="provider", phone="+233200000777")
    make_provider_profile(third)

    response = as_user(other_provider_user).post(
        members_url(agency), {"phone": third.phone}, format="json"
    )
    assert response.status_code == 403


def test_invitation_is_audited(
    as_user, provider_user, agency, other_provider_user, other_provider_profile
):
    as_user(provider_user).post(
        members_url(agency), {"phone": other_provider_user.phone}, format="json"
    )
    event = AuditEvent.objects.get(action=AuditAction.AGENCY_MEMBER_INVITED)
    assert event.actor_id == provider_user.id


# --- responding ---------------------------------------------------------------------


def test_invitee_accepts(as_user, other_provider_user, invited):
    response = as_user(other_provider_user).post(
        respond_url(invited), {"accept": True}, format="json"
    )
    assert response.status_code == 200
    invited.refresh_from_db()
    assert invited.status == MembershipStatus.ACTIVE
    assert invited.joined_at is not None


def test_invitee_declines_and_frees_their_slot(
    as_user, other_provider_user, other_provider_profile, invited, agency
):
    """Declining must land in `removed`, or the one-live-membership constraint traps them."""
    as_user(other_provider_user).post(respond_url(invited), {"accept": False}, format="json")
    invited.refresh_from_db()
    assert invited.status == MembershipStatus.REMOVED

    second = AgencyMembership.objects.create(
        agency=agency, provider=other_provider_profile, status=MembershipStatus.INVITED
    )
    assert second.pk is not None


def test_someone_else_cannot_answer_your_invitation(as_user, provider_user, invited):
    assert as_user(provider_user).post(
        respond_url(invited), {"accept": True}, format="json"
    ).status_code == 404


def test_an_invitation_cannot_be_answered_twice(as_user, other_provider_user, invited):
    client = as_user(other_provider_user)
    client.post(respond_url(invited), {"accept": True}, format="json")
    assert client.post(respond_url(invited), {"accept": False}, format="json").status_code == 409


def test_accepting_notifies_the_owner(as_user, other_provider_user, provider_user, invited):
    as_user(other_provider_user).post(respond_url(invited), {"accept": True}, format="json")
    kinds = list(Notification.objects.filter(user=provider_user).values_list("kind", flat=True))
    assert NotificationKind.AGENCY_INVITATION_ANSWERED in kinds


def test_my_memberships_lists_pending_invitations(as_user, other_provider_user, invited):
    response = as_user(other_provider_user).get(MY_MEMBERSHIPS_URL)
    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [str(invited.id)]
    assert response.data[0]["status"] == MembershipStatus.INVITED


# --- roles and removal --------------------------------------------------------------


def test_owner_promotes_a_member(as_user, provider_user, agency, invited):
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])

    response = as_user(provider_user).patch(
        member_url(agency, invited), {"role": "manager"}, format="json"
    )
    assert response.status_code == 200
    invited.refresh_from_db()
    assert invited.role == AgencyRole.MANAGER


def test_the_last_owner_cannot_be_demoted(as_user, provider_user, agency, provider_profile):
    own = AgencyMembership.objects.get(agency=agency, provider=provider_profile)
    response = as_user(provider_user).patch(
        member_url(agency, own), {"role": "operator"}, format="json"
    )
    assert response.status_code == 409
    own.refresh_from_db()
    assert own.role == AgencyRole.OWNER


def test_the_last_owner_cannot_leave(as_user, provider_user, agency, provider_profile):
    own = AgencyMembership.objects.get(agency=agency, provider=provider_profile)
    assert as_user(provider_user).delete(member_url(agency, own)).status_code == 409


def test_admin_removes_a_member(as_user, provider_user, agency, invited):
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])

    response = as_user(provider_user).delete(member_url(agency, invited))
    assert response.status_code == 200
    invited.refresh_from_db()
    assert invited.status == MembershipStatus.REMOVED
    assert invited.removed_at is not None


def test_removal_is_history_not_a_delete(as_user, provider_user, agency, invited):
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])
    as_user(provider_user).delete(member_url(agency, invited))
    assert AgencyMembership.objects.filter(pk=invited.pk).exists()


def test_removal_notifies_the_provider(
    as_user, provider_user, other_provider_user, agency, invited
):
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])
    as_user(provider_user).delete(member_url(agency, invited))

    kinds = list(
        Notification.objects.filter(user=other_provider_user).values_list("kind", flat=True)
    )
    assert NotificationKind.AGENCY_MEMBERSHIP_ENDED in kinds


def test_a_member_can_leave_on_their_own(
    as_user, other_provider_user, agency, invited
):
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])

    response = as_user(other_provider_user).delete(member_url(agency, invited))
    assert response.status_code == 200
    invited.refresh_from_db()
    assert invited.status == MembershipStatus.REMOVED


def test_an_operator_cannot_remove_someone_else(
    as_user, other_provider_user, agency, invited, provider_profile
):
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])
    owner_membership = AgencyMembership.objects.get(agency=agency, provider=provider_profile)

    response = as_user(other_provider_user).delete(member_url(agency, owner_membership))
    assert response.status_code == 403


def test_membership_changes_are_audited(as_user, provider_user, agency, invited):
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])
    as_user(provider_user).delete(member_url(agency, invited))

    event = AuditEvent.objects.get(action=AuditAction.AGENCY_MEMBERSHIP_CHANGED)
    assert event.metadata["change"] == "removed"


# --- the point of the whole feature -------------------------------------------------


def test_joining_a_verified_agency_lifts_the_members_effective_level(
    as_user, other_provider_user, other_provider_profile, agency, invited
):
    """SPEC-014 REQ-7: onboarding into a verified agency skips a second document review."""
    agency.verification_level = VerificationLevel.DOCUMENTS
    agency.save(update_fields=["verification_level"])
    other_provider_profile.verification_level = VerificationLevel.NONE
    other_provider_profile.save(update_fields=["verification_level"])

    assert effective_verification_level(other_provider_profile) == VerificationLevel.NONE

    as_user(other_provider_user).post(respond_url(invited), {"accept": True}, format="json")

    other_provider_profile.refresh_from_db()
    assert effective_verification_level(other_provider_profile) == VerificationLevel.DOCUMENTS


def test_removal_drops_the_inherited_level_again(
    as_user, provider_user, other_provider_profile, agency, invited
):
    agency.verification_level = VerificationLevel.DOCUMENTS
    agency.save(update_fields=["verification_level"])
    # The provider has no level of their own — the agency is the only thing lifting them.
    other_provider_profile.verification_level = VerificationLevel.NONE
    other_provider_profile.save(update_fields=["verification_level"])
    invited.status = MembershipStatus.ACTIVE
    invited.save(update_fields=["status"])
    assert effective_verification_level(other_provider_profile) == VerificationLevel.DOCUMENTS

    as_user(provider_user).delete(member_url(agency, invited))

    other_provider_profile.refresh_from_db()
    assert effective_verification_level(other_provider_profile) == VerificationLevel.NONE
