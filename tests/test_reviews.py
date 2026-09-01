"""Review eligibility and rating aggregation — SPEC-011.

Before this slice any authenticated user could review any job in any state
(CONFLICT-011-B), and no rating summary was ever written (CONFLICT-011-A).
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.jobs.models import JobStatus
from apps.notifications.models import Notification, NotificationKind
from apps.reviews.models import Review

pytestmark = pytest.mark.django_db

URL = reverse("reviews")


def payload(job, rating=5, comment="Fast and honest."):
    return {"job": str(job.id), "rating": rating, "comment": comment}


# --- eligibility ------------------------------------------------------------------


def test_customer_can_review_completed_job(as_user, customer_user, completed_job):
    response = as_user(customer_user).post(URL, payload(completed_job), format="json")
    assert response.status_code == 201
    review = Review.objects.get()
    assert review.author_id == customer_user.id
    assert review.job_id == completed_job.id
    assert response.data["provider_name"] == "Kofi Auto Works"


def test_unrelated_customer_cannot_review(as_user, other_customer_user, completed_job):
    response = as_user(other_customer_user).post(URL, payload(completed_job), format="json")
    assert response.status_code == 400
    assert not Review.objects.exists()


def test_provider_cannot_review_their_own_job(as_user, provider_user, completed_job):
    response = as_user(provider_user).post(URL, payload(completed_job), format="json")
    assert response.status_code == 400
    assert not Review.objects.exists()


@pytest.mark.parametrize("status", [JobStatus.PENDING_ACCEPT, JobStatus.ACTIVE, JobStatus.CANCELLED])
def test_incomplete_job_cannot_be_reviewed(as_user, customer_user, job, status):
    job.status = status
    job.save(update_fields=["status"])
    response = as_user(customer_user).post(URL, payload(job), format="json")
    assert response.status_code == 400
    assert not Review.objects.exists()


def test_duplicate_review_is_409(as_user, customer_user, completed_job):
    client = as_user(customer_user)
    assert client.post(URL, payload(completed_job), format="json").status_code == 201
    response = client.post(URL, payload(completed_job, rating=1), format="json")
    assert response.status_code == 409
    assert Review.objects.count() == 1


def test_anonymous_cannot_review(api, completed_job):
    assert api.post(URL, payload(completed_job), format="json").status_code == 401


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_rating_must_be_between_one_and_five(as_user, customer_user, completed_job, rating):
    response = as_user(customer_user).post(URL, payload(completed_job, rating=rating), format="json")
    assert response.status_code == 400


def test_author_cannot_be_forged(as_user, customer_user, other_customer_user, completed_job):
    body = payload(completed_job)
    body["author"] = str(other_customer_user.id)
    response = as_user(customer_user).post(URL, body, format="json")
    assert response.status_code == 201
    assert Review.objects.get().author_id == customer_user.id


# --- aggregation ------------------------------------------------------------------


def test_review_updates_provider_rating(as_user, customer_user, completed_job, provider_profile):
    assert provider_profile.rating_count == 0

    as_user(customer_user).post(URL, payload(completed_job, rating=4), format="json")

    provider_profile.refresh_from_db()
    assert provider_profile.rating_count == 1
    assert provider_profile.rating_avg == Decimal("4.00")


def test_rating_average_across_multiple_jobs(
    as_user, customer_user, customer_profile, provider_profile, make_service_request, make_job
):
    from apps.jobs.models import ServiceRequestStatus

    ratings = [5, 4]
    for rating in ratings:
        request = make_service_request(customer_profile, status=ServiceRequestStatus.COMPLETED)
        job = make_job(request, provider_profile, status=JobStatus.COMPLETED)
        as_user(customer_user).post(URL, payload(job, rating=rating), format="json")

    provider_profile.refresh_from_db()
    assert provider_profile.rating_count == 2
    assert provider_profile.rating_avg == Decimal("4.50")


def test_deleting_a_review_recalculates(as_user, customer_user, completed_job, provider_profile):
    as_user(customer_user).post(URL, payload(completed_job, rating=5), format="json")
    Review.objects.get().delete()

    provider_profile.refresh_from_db()
    assert provider_profile.rating_count == 0
    assert provider_profile.rating_avg == Decimal("0.00")


def test_rating_appears_in_provider_profile_response(
    as_user, customer_user, provider_user, completed_job, provider_profile
):
    as_user(customer_user).post(URL, payload(completed_job, rating=5), format="json")
    response = as_user(provider_user).get(reverse("provider-profile"))
    assert response.data["rating_count"] == 1
    assert Decimal(response.data["rating_avg"]) == Decimal("5.00")


def test_review_notifies_the_provider(as_user, customer_user, provider_user, completed_job):
    as_user(customer_user).post(URL, payload(completed_job, rating=5), format="json")
    notification = Notification.objects.get(user=provider_user, kind=NotificationKind.REVIEW_RECEIVED)
    assert notification.payload["rating"] == 5


# --- listing ----------------------------------------------------------------------


def test_customer_lists_own_reviews(as_user, customer_user, completed_job):
    as_user(customer_user).post(URL, payload(completed_job), format="json")
    response = as_user(customer_user).get(URL)
    assert response.data["count"] == 1


def test_provider_sees_reviews_about_them(as_user, customer_user, provider_user, completed_job):
    """Previously a provider could only see reviews they had written — i.e. none."""
    as_user(customer_user).post(URL, payload(completed_job), format="json")
    response = as_user(provider_user).get(URL)
    assert response.data["count"] == 1


def test_unrelated_user_sees_no_reviews(as_user, customer_user, other_customer_user, completed_job):
    as_user(customer_user).post(URL, payload(completed_job), format="json")
    assert as_user(other_customer_user).get(URL).data["count"] == 0
