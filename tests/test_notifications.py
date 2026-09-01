"""Notifications — SPEC-010.

The read API existed before this slice but nothing ever created a notification. These
tests pin both the production side and the ownership rules on the read side.
"""

import uuid

import pytest
from django.urls import reverse

from apps.notifications.models import Notification, NotificationKind
from apps.notifications.services import notify, user_group_name

pytestmark = pytest.mark.django_db

LIST_URL = reverse("notifications")
UNREAD_URL = reverse("notification-unread-count")


def read_url(notification):
    return reverse("notification-read", kwargs={"pk": notification.id})


@pytest.fixture
def notification(customer_user):
    return notify(
        customer_user,
        kind=NotificationKind.JOB_COMPLETED,
        title="Job completed",
        payload={"job_id": "abc"},
    )


# --- production -------------------------------------------------------------------


def test_notify_creates_a_row(customer_user):
    created = notify(customer_user, kind=NotificationKind.JOB_ACTIVE, title="Started")
    assert Notification.objects.get(pk=created.pk).user_id == customer_user.id
    assert created.read_at is None


def test_user_group_name_is_derived_from_the_user(customer_user):
    assert user_group_name(customer_user.id) == f"user_{customer_user.id}"


def test_every_kind_is_in_the_declared_catalogue():
    """``kind`` is an enum so clients can switch on it safely."""
    assert set(NotificationKind.values) == {
        "request.accepted",
        "job.active",
        "quote.submitted",
        "quote.accepted",
        "quote.declined",
        "job.awaiting_confirmation",
        "job.completed",
        "job.auto_confirmed",
        "job.cancelled",
        "request.cancelled",
        "request.expired",
        "review.received",
        "agency.invited",
        "agency.invitation_answered",
        "agency.membership_ended",
    }


# --- reading ----------------------------------------------------------------------


def test_list_requires_authentication(api):
    assert api.get(LIST_URL).status_code == 401


def test_list_returns_own_notifications(as_user, customer_user, notification):
    response = as_user(customer_user).get(LIST_URL)
    assert response.data["count"] == 1
    assert response.data["results"][0]["kind"] == NotificationKind.JOB_COMPLETED
    assert response.data["results"][0]["payload"] == {"job_id": "abc"}


def test_list_excludes_other_users_notifications(as_user, other_customer_user, notification):
    assert as_user(other_customer_user).get(LIST_URL).data["count"] == 0


def test_unread_filter(as_user, customer_user, notification):
    client = as_user(customer_user)
    assert client.get(LIST_URL + "?unread=true").data["count"] == 1
    client.post(read_url(notification))
    assert client.get(LIST_URL + "?unread=true").data["count"] == 0
    assert client.get(LIST_URL).data["count"] == 1


def test_unread_count_endpoint(as_user, customer_user, notification):
    assert as_user(customer_user).get(UNREAD_URL).data["unread_count"] == 1


# --- marking read -----------------------------------------------------------------


def test_mark_read_stamps_the_row(as_user, customer_user, notification):
    response = as_user(customer_user).post(read_url(notification))
    assert response.status_code == 200
    assert response.data == {"updated": 1, "unread_count": 0}
    notification.refresh_from_db()
    assert notification.read_at is not None


def test_marking_twice_is_idempotent(as_user, customer_user, notification):
    client = as_user(customer_user)
    client.post(read_url(notification))
    assert client.post(read_url(notification)).data["updated"] == 0


def test_cannot_mark_another_users_notification(as_user, other_customer_user, notification):
    response = as_user(other_customer_user).post(read_url(notification))
    assert response.data["updated"] == 0
    notification.refresh_from_db()
    assert notification.read_at is None


def test_marking_unknown_id_is_a_noop(as_user, customer_user):
    url = reverse("notification-read", kwargs={"pk": uuid.uuid4()})
    assert as_user(customer_user).post(url).data["updated"] == 0


# --- end to end -------------------------------------------------------------------


def test_full_job_flow_produces_the_expected_notifications(
    as_user, customer_user, provider_user, provider_profile, service_request
):
    provider = as_user(provider_user)
    accept = provider.post(reverse("job-accept", kwargs={"request_id": service_request.id}))
    job_id = accept.data["id"]
    job_url = reverse("job-detail", kwargs={"id": job_id})
    provider.patch(job_url, {"status": "active"}, format="json")
    provider.patch(
        job_url,
        {"status": "awaiting_confirmation", "final_amount": "250.00"},
        format="json",
    )
    as_user(customer_user).patch(job_url, {"status": "completed"}, format="json")

    # Compared as a multiset: the rows can share a timestamp, so their relative order is
    # not a guarantee the storage layer makes.
    kinds = sorted(Notification.objects.filter(user=customer_user).values_list("kind", flat=True))
    assert kinds == sorted(
        [
            NotificationKind.REQUEST_ACCEPTED,
            NotificationKind.JOB_ACTIVE,
            NotificationKind.JOB_AWAITING_CONFIRMATION,
        ]
    )
    # Each side hears about the other's actions and never about their own. Completion is
    # now the customer's act, so `job.completed` lands on the provider.
    provider_kinds = list(
        Notification.objects.filter(user=provider_user).values_list("kind", flat=True)
    )
    assert provider_kinds == [NotificationKind.JOB_COMPLETED]


# --- navigability -------------------------------------------------------------------
#
# `Notification` has no foreign key to its subject; `payload` carries the correlation ids
# instead. The web client's notification bell routes by those ids, so a kind that arrives
# without one is a notification the recipient cannot act on.


def test_actionable_notifications_carry_the_job_id(
    as_user, customer_user, provider_user, provider_profile, service_request
):
    """The three kinds that ask the recipient to *do* something must be navigable."""
    provider = as_user(provider_user)
    accept = provider.post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    job_id = accept.data["id"]
    job_url = reverse("job-detail", kwargs={"id": job_id})

    provider.post(
        reverse("job-quotes", kwargs={"job_id": job_id}),
        {"amount": "200.00"},
        format="json",
    )
    provider.patch(job_url, {"status": "active"}, format="json")
    provider.patch(
        job_url,
        {"status": "awaiting_confirmation", "final_amount": "250.00"},
        format="json",
    )

    for kind in (NotificationKind.QUOTE_SUBMITTED, NotificationKind.JOB_AWAITING_CONFIRMATION):
        row = Notification.objects.filter(user=customer_user, kind=kind).first()
        assert row is not None, f"{kind} was never sent"
        assert row.payload.get("job_id") == str(job_id), f"{kind} is not navigable"


def test_awaiting_confirmation_payload_carries_the_amount(
    as_user, provider_user, provider_profile, customer_user, service_request
):
    """The client shows the amount straight from the notification, without a second fetch."""
    provider = as_user(provider_user)
    accept = provider.post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    job_url = reverse("job-detail", kwargs={"id": accept.data["id"]})
    provider.patch(job_url, {"status": "active"}, format="json")
    provider.patch(
        job_url,
        {"status": "awaiting_confirmation", "final_amount": "250.00"},
        format="json",
    )

    row = Notification.objects.get(
        user=customer_user, kind=NotificationKind.JOB_AWAITING_CONFIRMATION
    )
    assert row.payload["final_amount"] == "250.00"
    assert row.payload["currency"] == "GHS"
