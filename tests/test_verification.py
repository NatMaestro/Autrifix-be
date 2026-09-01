"""Provider verification — SPEC-013."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.geo import coarsen_coordinate, distance_meters
from apps.core.models import AuditAction, AuditEvent
from apps.providers.models import ProviderVerification
from apps.providers.verification import (
    VerificationLevel,
    VerificationStatus,
    evaluate_automatic_level,
    level_at_least,
)
from tests.conftest import ACCRA_LAT, ACCRA_LNG

pytestmark = pytest.mark.django_db

VERIFICATION_URL = reverse("provider-verification")
NEARBY_REQUESTS = reverse("service-requests-nearby")


def feed_url(lat=ACCRA_LAT, lng=ACCRA_LNG, radius_km=50):
    return f"{NEARBY_REQUESTS}?lat={lat}&lng={lng}&radius_km={radius_km}"


def fake_image(name="doc.png"):
    """A minimal valid PNG so Pillow accepts the upload."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), color="grey").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def submission_payload():
    return {
        "id_document": fake_image("id.png"),
        "selfie": fake_image("selfie.png"),
        "workshop_photo": fake_image("shop.png"),
    }


# --- levels -------------------------------------------------------------------------


def test_level_ordering():
    assert level_at_least(VerificationLevel.DOCUMENTS, VerificationLevel.PHONE)
    assert level_at_least(VerificationLevel.PHONE, VerificationLevel.PHONE)
    assert not level_at_least(VerificationLevel.PHONE, VerificationLevel.DOCUMENTS)
    assert not level_at_least(VerificationLevel.NONE, VerificationLevel.PHONE)


def test_new_provider_starts_unverified(unverified_provider_profile):
    assert unverified_provider_profile.verification_level == VerificationLevel.NONE


def test_phone_level_needs_both_phone_and_complete_profile(
    unverified_provider_profile, provider_user, category
):
    from apps.providers.models import ProviderServiceOffering

    # Phone verified, but no active offering yet.
    provider_user.is_phone_verified = True
    provider_user.save(update_fields=["is_phone_verified"])
    assert evaluate_automatic_level(unverified_provider_profile) == VerificationLevel.NONE

    ProviderServiceOffering.objects.create(provider=unverified_provider_profile, category=category)
    assert evaluate_automatic_level(unverified_provider_profile) == VerificationLevel.PHONE


def test_losing_completeness_demotes_to_none(unverified_provider_profile, provider_user, category):
    from apps.providers.models import ProviderServiceOffering

    provider_user.is_phone_verified = True
    provider_user.save(update_fields=["is_phone_verified"])
    offering = ProviderServiceOffering.objects.create(provider=unverified_provider_profile, category=category)
    assert evaluate_automatic_level(unverified_provider_profile) == VerificationLevel.PHONE

    offering.is_active = False
    offering.save(update_fields=["is_active"])
    assert evaluate_automatic_level(unverified_provider_profile) == VerificationLevel.NONE


def test_reviewer_granted_level_is_never_auto_downgraded(provider_profile, provider_user):
    """Losing an offering must not silently undo a human decision."""
    provider_profile.verification_level = VerificationLevel.DOCUMENTS
    provider_profile.save(update_fields=["verification_level"])

    assert evaluate_automatic_level(provider_profile) == VerificationLevel.DOCUMENTS


# --- location disclosure (REQ-2) -----------------------------------------------------


def test_unverified_provider_sees_coarsened_coordinates(
    as_user, provider_user, unverified_provider_profile, service_request
):
    row = as_user(provider_user).get(feed_url()).data[0]

    assert row["latitude"] != service_request.latitude
    expected_lat, expected_lng = coarsen_coordinate(
        service_request.latitude, service_request.longitude
    )
    assert row["latitude"] == expected_lat
    assert row["longitude"] == expected_lng


def test_verified_provider_sees_exact_coordinates(
    as_user, provider_user, provider_profile, service_request
):
    provider_profile.verification_level = VerificationLevel.DOCUMENTS
    provider_profile.save(update_fields=["verification_level"])

    row = as_user(provider_user).get(feed_url()).data[0]
    assert row["latitude"] == service_request.latitude
    assert row["longitude"] == service_request.longitude


def test_distance_is_consistent_with_the_coarsened_point(
    as_user, provider_user, unverified_provider_profile, service_request
):
    """The published distance must be measured to the point that was published."""
    row = as_user(provider_user).get(feed_url()).data[0]

    recomputed_km = (
        distance_meters(ACCRA_LAT, ACCRA_LNG, row["latitude"], row["longitude"]) / 1000.0
    )
    assert row["distance_km"] == pytest.approx(recomputed_km, abs=0.02)


def test_trilateration_cannot_recover_the_true_coordinate(
    as_user, provider_user, unverified_provider_profile, make_service_request, customer_profile
):
    """The attack the coarsening is designed to defeat.

    A provider chooses the point they search from. If an exact distance were published
    beside a coarsened coordinate, three queries would pin the true location. Because
    distance is derived from the *snapped* point, every vantage agrees on the snapped
    point and the true one never leaks.
    """
    true_lat, true_lng = 5.61234, -0.18567
    make_service_request(customer_profile, lat=true_lat, lng=true_lng)
    client = as_user(provider_user)

    vantages = [(ACCRA_LAT, ACCRA_LNG), (ACCRA_LAT + 0.05, ACCRA_LNG), (ACCRA_LAT, ACCRA_LNG + 0.05)]
    snapped = coarsen_coordinate(true_lat, true_lng)

    for lat, lng in vantages:
        row = client.get(feed_url(lat=lat, lng=lng)).data[0]
        # Every vantage sees the same snapped point...
        assert (row["latitude"], row["longitude"]) == snapped
        # ...and a distance measured to it, not to the true location.
        assert row["distance_km"] == pytest.approx(
            distance_meters(lat, lng, *snapped) / 1000.0, abs=0.02
        )
        true_distance_km = distance_meters(lat, lng, true_lat, true_lng) / 1000.0
        assert row["distance_km"] != pytest.approx(true_distance_km, abs=0.001)


def test_accepted_job_exposes_the_exact_location_regardless_of_level(
    as_user, provider_user, provider_profile, service_request
):
    """Navigation needs the real point; acceptance is audited and identity-bound."""
    as_user(provider_user).post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    detail = as_user(provider_user).get(
        reverse("service-request-detail", kwargs={"id": service_request.id})
    )
    # The customer-scoped detail endpoint is not open to providers...
    assert detail.status_code == 403
    # ...but the request row itself is untouched: coarsening is a presentation concern.
    service_request.refresh_from_db()
    assert service_request.latitude == pytest.approx(ACCRA_LAT)


def test_coarsening_does_not_mutate_the_stored_request(
    as_user, provider_user, unverified_provider_profile, service_request
):
    as_user(provider_user).get(feed_url())
    service_request.refresh_from_db()
    assert service_request.latitude == pytest.approx(ACCRA_LAT)
    assert service_request.longitude == pytest.approx(ACCRA_LNG)


# --- browse freely, accept only when verified (REQ-3) --------------------------------


def test_unverified_provider_can_browse_but_not_accept(
    as_user, provider_user, unverified_provider_profile, service_request
):
    """The conversion lever: they see the work, and see what verification unlocks."""
    client = as_user(provider_user)
    assert unverified_provider_profile.verification_level == VerificationLevel.NONE

    # Browsing is unrestricted.
    assert len(client.get(feed_url()).data) == 1

    response = client.post(reverse("job-accept", kwargs={"request_id": service_request.id}))
    assert response.status_code == 403
    assert response.data["code"] == "verification_required"
    assert response.data["current_level"] == VerificationLevel.NONE
    assert response.data["required_level"] == VerificationLevel.DOCUMENTS
    assert response.data["verification_url"]


def test_blocked_acceptance_leaves_no_trace(
    as_user, provider_user, unverified_provider_profile, service_request
):
    """A refused accept must not consume the request or create a job."""
    from apps.jobs.models import Job, ServiceRequestStatus

    as_user(provider_user).post(reverse("job-accept", kwargs={"request_id": service_request.id}))

    assert not Job.objects.exists()
    service_request.refresh_from_db()
    assert service_request.status == ServiceRequestStatus.OPEN


def test_phone_level_alone_does_not_unlock_accepting(
    as_user, provider_user, unverified_provider_profile, service_request
):
    """Default threshold is `documents`: self-service phone verification is not enough."""
    unverified_provider_profile.verification_level = VerificationLevel.PHONE
    unverified_provider_profile.save(update_fields=["verification_level"])

    response = as_user(provider_user).post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    assert response.status_code == 403
    assert response.data["current_level"] == VerificationLevel.PHONE


def test_threshold_is_configurable(
    as_user, provider_user, unverified_provider_profile, service_request, settings
):
    """The cold-start dial: `phone` lets a self-service provider work immediately."""
    settings.PROVIDER_MIN_ACCEPT_LEVEL = VerificationLevel.PHONE
    unverified_provider_profile.verification_level = VerificationLevel.PHONE
    unverified_provider_profile.save(update_fields=["verification_level"])

    response = as_user(provider_user).post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    assert response.status_code == 201


def test_verified_provider_can_accept(as_user, provider_user, provider_profile, service_request):
    response = as_user(provider_user).post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    assert response.status_code == 201


def test_approval_unlocks_accepting_end_to_end(
    as_user, provider_user, unverified_provider_profile, service_request
):
    from apps.providers.services import review_verification

    client = as_user(provider_user)
    assert client.post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    ).status_code == 403

    client.post(VERIFICATION_URL, submission_payload(), format="multipart")
    review_verification(submission=ProviderVerification.objects.get(), approve=True)

    assert client.post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    ).status_code == 201


def test_an_existing_job_is_unaffected_by_losing_entitlement(
    as_user, provider_user, provider_profile, job
):
    """Demotion blocks *new* accepts; work already in hand continues."""
    provider_profile.verification_level = VerificationLevel.NONE
    provider_profile.save(update_fields=["verification_level"])

    response = as_user(provider_user).patch(
        reverse("job-detail", kwargs={"id": job.id}), {"status": "active"}, format="json"
    )
    assert response.status_code == 200


def test_status_endpoint_reports_the_accept_entitlement(
    as_user, provider_user, unverified_provider_profile
):
    data = as_user(provider_user).get(VERIFICATION_URL).data
    assert data["can_accept_jobs"] is False
    assert data["accept_requires_level"] == VerificationLevel.DOCUMENTS


# --- badge (REQ-4) -------------------------------------------------------------------


def test_customer_sees_the_provider_badge_on_a_job(as_user, customer_user, job, provider_profile):
    provider_profile.verification_level = VerificationLevel.DOCUMENTS
    provider_profile.save(update_fields=["verification_level"])

    row = as_user(customer_user).get(reverse("job-list")).data["results"][0]
    assert row["provider_verification_level"] == VerificationLevel.DOCUMENTS


def test_badge_appears_in_nearby_provider_discovery(as_user, customer_user, unverified_provider_profile):
    response = as_user(customer_user).get(
        reverse("services-nearby") + f"?lat={ACCRA_LAT}&lng={ACCRA_LNG}"
    )
    assert response.data["providers"][0]["verification_level"] == VerificationLevel.NONE


# --- submission (REQ-7) --------------------------------------------------------------


def test_provider_submits_documents(as_user, provider_user, provider_profile):
    response = as_user(provider_user).post(
        VERIFICATION_URL, submission_payload(), format="multipart"
    )
    assert response.status_code == 201
    assert response.data["submission"]["status"] == VerificationStatus.PENDING
    assert ProviderVerification.objects.count() == 1


def test_submission_response_never_exposes_the_documents(
    as_user, provider_user, provider_profile
):
    response = as_user(provider_user).post(
        VERIFICATION_URL, submission_payload(), format="multipart"
    )
    body = str(response.data)
    for field in ProviderVerification.DOCUMENT_FIELDS:
        assert field not in body


def test_second_pending_submission_is_409(as_user, provider_user, provider_profile):
    client = as_user(provider_user)
    assert client.post(VERIFICATION_URL, submission_payload(), format="multipart").status_code == 201
    assert client.post(VERIFICATION_URL, submission_payload(), format="multipart").status_code == 409


def test_customer_cannot_submit_verification(as_user, customer_user):
    response = as_user(customer_user).post(
        VERIFICATION_URL, submission_payload(), format="multipart"
    )
    assert response.status_code == 403


def test_status_endpoint_reports_what_is_missing(as_user, provider_user, unverified_provider_profile):
    data = as_user(provider_user).get(VERIFICATION_URL).data
    assert data["verification_level"] == VerificationLevel.NONE
    assert data["exact_location_unlocked"] is False
    assert data["phone_verified"] is False
    assert "active_service_offering" in data["missing_requirements"]


# --- review (REQ-7, REQ-8, REQ-9) ----------------------------------------------------


def test_approval_raises_level_and_purges_documents(as_user, provider_user, provider_profile):
    from apps.providers.services import review_verification

    as_user(provider_user).post(VERIFICATION_URL, submission_payload(), format="multipart")
    submission = ProviderVerification.objects.get()
    assert submission.id_document

    review_verification(submission=submission, approve=True, reviewer=None, notes="Looks good")

    submission.refresh_from_db()
    provider_profile.refresh_from_db()
    assert submission.status == VerificationStatus.APPROVED
    assert provider_profile.verification_level == VerificationLevel.DOCUMENTS
    for field in ProviderVerification.DOCUMENT_FIELDS:
        assert not getattr(submission, field)
    assert submission.review_notes == "Looks good"


def test_rejection_leaves_level_and_purges_documents(as_user, provider_user, unverified_provider_profile):
    from apps.providers.services import review_verification

    as_user(provider_user).post(VERIFICATION_URL, submission_payload(), format="multipart")
    submission = ProviderVerification.objects.get()

    review_verification(submission=submission, approve=False, reviewer=None, notes="Blurry ID")

    submission.refresh_from_db()
    unverified_provider_profile.refresh_from_db()
    assert submission.status == VerificationStatus.REJECTED
    assert unverified_provider_profile.verification_level == VerificationLevel.NONE
    for field in ProviderVerification.DOCUMENT_FIELDS:
        assert not getattr(submission, field)


def test_rejected_provider_may_resubmit(as_user, provider_user, provider_profile):
    from apps.providers.services import review_verification

    client = as_user(provider_user)
    client.post(VERIFICATION_URL, submission_payload(), format="multipart")
    review_verification(submission=ProviderVerification.objects.get(), approve=False)

    assert client.post(VERIFICATION_URL, submission_payload(), format="multipart").status_code == 201
    assert ProviderVerification.objects.count() == 2


def test_reviewing_twice_is_409(as_user, provider_user, provider_profile):
    from apps.core.exceptions import Conflict
    from apps.providers.services import review_verification

    as_user(provider_user).post(VERIFICATION_URL, submission_payload(), format="multipart")
    submission = ProviderVerification.objects.get()
    review_verification(submission=submission, approve=True)

    with pytest.raises(Conflict):
        review_verification(submission=submission, approve=True)


def test_submission_and_review_are_audited(as_user, provider_user, provider_profile):
    from apps.providers.services import review_verification

    as_user(provider_user).post(VERIFICATION_URL, submission_payload(), format="multipart")
    submission = ProviderVerification.objects.get()
    review_verification(submission=submission, approve=True, reviewer=None)

    assert AuditEvent.objects.filter(action=AuditAction.VERIFICATION_SUBMITTED).exists()
    reviewed = AuditEvent.objects.get(action=AuditAction.VERIFICATION_REVIEWED)
    assert reviewed.metadata["outcome"] == VerificationStatus.APPROVED
    assert reviewed.metadata["granted_level"] == VerificationLevel.DOCUMENTS


def test_approved_provider_unlocks_exact_locations_end_to_end(
    as_user, provider_user, unverified_provider_profile, service_request
):
    from apps.providers.services import review_verification

    client = as_user(provider_user)
    assert client.get(feed_url()).data[0]["latitude"] != service_request.latitude

    client.post(VERIFICATION_URL, submission_payload(), format="multipart")
    review_verification(submission=ProviderVerification.objects.get(), approve=True)

    assert client.get(feed_url()).data[0]["latitude"] == service_request.latitude


# --- phone verification (REQ-5) ------------------------------------------------------


def test_phone_verification_with_a_valid_code(as_user, provider_user, provider_profile):
    from apps.accounts.otp_service import issue_otp

    code = issue_otp(provider_user.phone)
    response = as_user(provider_user).post(
        reverse("me-verify-phone"), {"code": code}, format="json"
    )
    assert response.status_code == 200
    provider_user.refresh_from_db()
    assert provider_user.is_phone_verified is True


def test_phone_verification_with_a_wrong_code_is_409(as_user, customer_user):
    response = as_user(customer_user).post(
        reverse("me-verify-phone"), {"code": "000000"}, format="json"
    )
    assert response.status_code == 409
    customer_user.refresh_from_db()
    assert customer_user.is_phone_verified is False


def test_phone_verification_requires_a_code(as_user, customer_user):
    assert as_user(customer_user).post(reverse("me-verify-phone"), {}, format="json").status_code == 400


def test_verifying_phone_promotes_a_complete_provider(
    as_user, provider_user, unverified_provider_profile, category
):
    from apps.accounts.otp_service import issue_otp
    from apps.providers.models import ProviderServiceOffering

    ProviderServiceOffering.objects.create(provider=unverified_provider_profile, category=category)
    code = issue_otp(provider_user.phone)

    as_user(provider_user).post(reverse("me-verify-phone"), {"code": code}, format="json")

    unverified_provider_profile.refresh_from_db()
    assert unverified_provider_profile.verification_level == VerificationLevel.PHONE


def test_otp_login_marks_the_phone_verified(api, make_user):
    from apps.accounts.otp_service import issue_otp

    user = make_user(phone="+233540000090")
    code = issue_otp(user.phone)

    response = api.post(
        reverse("auth-verify-otp"), {"phone": user.phone, "code": code}, format="json"
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.is_phone_verified is True
