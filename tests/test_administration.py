"""Operator API — SPEC-012 REQ-4.

The authorization tests carry most of the weight here. This is the first surface where
`IsAdmin` is actually applied to anything, and an operator endpoint that leaks to a customer
or provider is worse than no operator endpoint: it exposes every user's contact details and
every job on the platform.
"""

import pytest
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.core.models import AuditAction, AuditEvent
from apps.jobs.models import JobStatus
from apps.providers.models import ProviderVerification
from apps.providers.verification import VerificationLevel, VerificationStatus

pytestmark = pytest.mark.django_db

STATS_URL = reverse("admin-stats")
USERS_URL = reverse("admin-users")
JOBS_URL = reverse("admin-jobs")
VERIFICATIONS_URL = reverse("admin-verifications")


@pytest.fixture
def admin_user(make_user):
    return make_user(UserRole.ADMIN)


@pytest.fixture
def submission(unverified_provider_profile):
    return ProviderVerification.objects.create(
        provider=unverified_provider_profile,
        requested_level=VerificationLevel.DOCUMENTS,
        status=VerificationStatus.PENDING,
    )


def review_url(submission):
    return reverse("admin-verification-review", kwargs={"id": submission.id})


# --- authorization ------------------------------------------------------------------


@pytest.mark.parametrize("url", [STATS_URL, USERS_URL, JOBS_URL, VERIFICATIONS_URL])
def test_every_admin_endpoint_requires_authentication(api, url):
    assert api.get(url).status_code == 401


@pytest.mark.parametrize("url", [STATS_URL, USERS_URL, JOBS_URL, VERIFICATIONS_URL])
def test_customers_are_refused(as_user, customer_user, url):
    assert as_user(customer_user).get(url).status_code == 403


@pytest.mark.parametrize("url", [STATS_URL, USERS_URL, JOBS_URL, VERIFICATIONS_URL])
def test_providers_are_refused(as_user, provider_user, provider_profile, url):
    """A provider must not be able to read the verification queue they are waiting in."""
    assert as_user(provider_user).get(url).status_code == 403


def test_a_provider_cannot_approve_their_own_submission(as_user, provider_user, submission):
    # `submission` already supplies the profile; asking for `provider_profile` too would
    # build a second one for the same user and trip the one-profile-per-user constraint.
    response = as_user(provider_user).post(
        review_url(submission), {"approve": True}, format="json"
    )
    assert response.status_code == 403
    submission.refresh_from_db()
    assert submission.status == VerificationStatus.PENDING


def test_admins_are_allowed(as_user, admin_user):
    assert as_user(admin_user).get(STATS_URL).status_code == 200


# --- verification review ------------------------------------------------------------


def test_queue_lists_pending_submissions_oldest_first(as_user, admin_user, submission):
    response = as_user(admin_user).get(VERIFICATIONS_URL)
    assert response.status_code == 200

    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    assert [r["id"] for r in rows] == [str(submission.id)]
    assert rows[0]["requested_level"] == VerificationLevel.DOCUMENTS


def test_queue_does_not_expose_the_documents(as_user, admin_user, submission):
    """Identity documents behind a JSON URL would be protected by nothing but obscurity."""
    response = as_user(admin_user).get(VERIFICATIONS_URL)
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    for field in ("id_document", "selfie", "workshop_photo"):
        assert field not in rows[0]


def test_approving_raises_the_provider_level(
    as_user, admin_user, submission, unverified_provider_profile
):
    response = as_user(admin_user).post(review_url(submission), {"approve": True}, format="json")
    assert response.status_code == 200

    unverified_provider_profile.refresh_from_db()
    assert unverified_provider_profile.verification_level == VerificationLevel.DOCUMENTS
    submission.refresh_from_db()
    assert submission.status == VerificationStatus.APPROVED
    assert submission.reviewed_by_id == admin_user.id


def test_declining_requires_a_reason(as_user, admin_user, submission):
    """A rejection with no reason leaves the provider unable to fix anything."""
    response = as_user(admin_user).post(review_url(submission), {"approve": False}, format="json")
    assert response.status_code == 400
    assert "notes" in response.data
    submission.refresh_from_db()
    assert submission.status == VerificationStatus.PENDING


def test_declining_with_a_reason_records_it(
    as_user, admin_user, submission, unverified_provider_profile
):
    response = as_user(admin_user).post(
        review_url(submission),
        {"approve": False, "notes": "ID photo unreadable."},
        format="json",
    )
    assert response.status_code == 200

    submission.refresh_from_db()
    assert submission.status == VerificationStatus.REJECTED
    assert submission.review_notes == "ID photo unreadable."
    # A refusal must never lower a level already granted.
    unverified_provider_profile.refresh_from_db()
    assert unverified_provider_profile.verification_level == VerificationLevel.NONE


def test_a_submission_cannot_be_reviewed_twice(as_user, admin_user, submission):
    client = as_user(admin_user)
    client.post(review_url(submission), {"approve": True}, format="json")
    second = client.post(review_url(submission), {"approve": True}, format="json")
    assert second.status_code == 409


def test_review_is_audited(as_user, admin_user, submission):
    as_user(admin_user).post(review_url(submission), {"approve": True}, format="json")
    event = AuditEvent.objects.get(action=AuditAction.VERIFICATION_REVIEWED)
    assert event.actor_id == admin_user.id


# --- users ---------------------------------------------------------------------------


def test_user_search_matches_name_and_phone(as_user, admin_user, customer_user):
    customer_user.first_name = "Akosua"
    customer_user.save(update_fields=["first_name"])

    response = as_user(admin_user).get(USERS_URL, {"q": "Akosua"})
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    assert str(customer_user.id) in [r["id"] for r in rows]


def test_user_list_can_be_filtered_by_role(as_user, admin_user, customer_user, provider_user):
    response = as_user(admin_user).get(USERS_URL, {"role": "provider"})
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    assert all(r["role"] == UserRole.PROVIDER for r in rows)


def test_user_list_never_exposes_credentials(as_user, admin_user, customer_user):
    response = as_user(admin_user).get(USERS_URL)
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    assert "password" not in rows[0]


# --- jobs and stats -------------------------------------------------------------------


def test_job_history_is_visible_to_an_operator(as_user, admin_user, completed_job):
    response = as_user(admin_user).get(JOBS_URL)
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    row = next(r for r in rows if r["id"] == str(completed_job.id))
    assert row["status"] == JobStatus.COMPLETED
    assert row["final_amount"] == "250.00"


def test_stats_surface_auto_confirmations(as_user, admin_user, completed_job):
    """A rising count means customers are being charged by timeout rather than agreement."""
    completed_job.auto_confirmed = True
    completed_job.save(update_fields=["auto_confirmed"])

    response = as_user(admin_user).get(STATS_URL)
    assert response.status_code == 200
    assert response.data["jobs_auto_confirmed"] == 1
    assert response.data["jobs_completed"] == 1
    assert response.data["currency"] == "GHS"


def test_stats_count_the_verification_backlog(as_user, admin_user, submission):
    response = as_user(admin_user).get(STATS_URL)
    assert response.data["verifications_pending"] == 1
