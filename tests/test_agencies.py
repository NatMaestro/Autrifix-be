"""Agencies — SPEC-014 REQ-6/REQ-7.

An agency is who the *business* is; the individual provider stays the unit of work, so a
customer always knows which person is coming and the audit trail has someone to attribute
actions to.
"""

import pytest
from django.db.utils import IntegrityError
from django.urls import reverse
from django.utils import timezone

from apps.providers.agencies import AGENCY_ADMIN_ROLES, AgencyRole, MembershipStatus
from apps.providers.models import Agency, AgencyMembership
from apps.providers.verification import (
    ProviderType,
    VerificationLevel,
    agency_of,
    can_accept_jobs,
    can_see_exact_locations,
    effective_verification_level,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def agency(db):
    return Agency.objects.create(
        name="Accra Recovery Ltd",
        slug="accra-recovery",
        provider_type=ProviderType.TOW,
        registration_number="RGD-12345",
    )


@pytest.fixture
def verified_agency(agency):
    agency.verification_level = VerificationLevel.DOCUMENTS
    agency.save(update_fields=["verification_level"])
    return agency


def join(agency, provider, *, role=AgencyRole.OPERATOR, status=MembershipStatus.ACTIVE):
    return AgencyMembership.objects.create(
        agency=agency,
        provider=provider,
        role=role,
        status=status,
        joined_at=timezone.now() if status == MembershipStatus.ACTIVE else None,
    )


# --- membership ----------------------------------------------------------------------


def test_provider_without_an_agency(unverified_provider_profile):
    assert agency_of(unverified_provider_profile) is None


def test_active_membership_resolves_the_agency(agency, unverified_provider_profile):
    join(agency, unverified_provider_profile)
    assert agency_of(unverified_provider_profile) == agency


def test_an_invitation_is_not_yet_membership(agency, unverified_provider_profile):
    join(agency, unverified_provider_profile, status=MembershipStatus.INVITED)
    assert agency_of(unverified_provider_profile) is None


def test_a_provider_may_hold_only_one_live_membership(
    agency, unverified_provider_profile, db
):
    other = Agency.objects.create(name="Tema Towing", slug="tema-towing")
    join(agency, unverified_provider_profile)
    with pytest.raises(IntegrityError):
        join(other, unverified_provider_profile)


def test_leaving_frees_the_provider_to_rejoin(agency, unverified_provider_profile):
    first = join(agency, unverified_provider_profile)
    first.status = MembershipStatus.REMOVED
    first.removed_at = timezone.now()
    first.save(update_fields=["status", "removed_at"])

    other = Agency.objects.create(name="Tema Towing", slug="tema-towing")
    join(other, unverified_provider_profile)

    assert agency_of(unverified_provider_profile) == other
    # History is kept rather than overwritten.
    assert AgencyMembership.objects.filter(provider=unverified_provider_profile).count() == 2


def test_admin_roles_are_owner_and_manager():
    assert AGENCY_ADMIN_ROLES == {AgencyRole.OWNER, AgencyRole.MANAGER}
    assert AgencyRole.OPERATOR not in AGENCY_ADMIN_ROLES


# --- inherited verification (REQ-7) ---------------------------------------------------


def test_unaffiliated_provider_keeps_its_own_level(unverified_provider_profile):
    assert effective_verification_level(unverified_provider_profile) == VerificationLevel.NONE


def test_agency_verification_lifts_its_members(verified_agency, unverified_provider_profile):
    """Verify the business once rather than making every operator resubmit."""
    join(verified_agency, unverified_provider_profile)

    assert effective_verification_level(unverified_provider_profile) == VerificationLevel.DOCUMENTS
    assert can_accept_jobs(unverified_provider_profile)
    assert can_see_exact_locations(unverified_provider_profile)


def test_an_unverified_agency_lifts_nobody(agency, unverified_provider_profile):
    join(agency, unverified_provider_profile)
    assert effective_verification_level(unverified_provider_profile) == VerificationLevel.NONE
    assert not can_accept_jobs(unverified_provider_profile)


def test_membership_never_lowers_an_individual_level(agency, provider_profile):
    """A provider who earned `documents` keeps it inside an unverified agency."""
    join(agency, provider_profile)
    assert effective_verification_level(provider_profile) == VerificationLevel.DOCUMENTS


def test_inherited_level_ends_when_membership_does(
    verified_agency, unverified_provider_profile
):
    membership = join(verified_agency, unverified_provider_profile)
    assert can_accept_jobs(unverified_provider_profile)

    membership.status = MembershipStatus.REMOVED
    membership.save(update_fields=["status"])

    assert effective_verification_level(unverified_provider_profile) == VerificationLevel.NONE
    assert not can_accept_jobs(unverified_provider_profile)


# --- end to end -----------------------------------------------------------------------


def test_agency_member_can_accept_work_without_own_documents(
    as_user, provider_user, unverified_provider_profile, verified_agency, service_request
):
    """The point of agencies: onboard an operator without a second document review."""
    client = as_user(provider_user)
    assert client.post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    ).status_code == 403

    join(verified_agency, unverified_provider_profile)

    assert client.post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    ).status_code == 201


def test_the_job_belongs_to_the_person_not_the_agency(
    as_user, provider_user, unverified_provider_profile, verified_agency, service_request
):
    """A customer needs to know who is coming; audit needs someone to attribute to."""
    join(verified_agency, unverified_provider_profile)
    response = as_user(provider_user).post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    assert str(response.data["provider"]) == str(unverified_provider_profile.id)
