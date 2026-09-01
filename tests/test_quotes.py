"""Price quotes — SPEC-015.

A quote is a provider's proposal *before* the work is done, and the customer's acceptance
of it is the only record that a price was ever agreed. It is deliberately optional: a tow
price falls out of per-km × distance, and a trivial repair may not be worth the round trip.
What these tests pin down is that when a quote does exist, it cannot be quietly rewritten,
answered by the wrong party, or contradicted at completion without the gap being visible.
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import AuditAction, AuditEvent
from apps.jobs.models import JobStatus, Quote, QuoteStatus
from apps.notifications.models import Notification, NotificationKind

pytestmark = pytest.mark.django_db


def quotes_url(job):
    return reverse("job-quotes", kwargs={"job_id": job.id})


def respond_url(job, quote):
    return reverse("job-quote-respond", kwargs={"job_id": job.id, "quote_id": quote.id})


def job_url(job):
    return reverse("job-detail", kwargs={"id": job.id})


@pytest.fixture
def quote(job, provider_profile):
    return Quote.objects.create(job=job, amount=Decimal("200.00"), currency="GHS")


# --- submitting ---------------------------------------------------------------------


def test_submit_requires_authentication(api, job):
    assert api.post(quotes_url(job), {"amount": "200.00"}, format="json").status_code == 401


def test_provider_submits_a_quote(as_user, provider_user, job):
    response = as_user(provider_user).post(
        quotes_url(job), {"amount": "200.00", "notes": "Alternator replacement"}, format="json"
    )
    assert response.status_code == 201
    assert response.data["amount"] == "200.00"
    assert response.data["status"] == QuoteStatus.PENDING
    assert response.data["notes"] == "Alternator replacement"


def test_quote_currency_is_the_platforms_not_the_callers(as_user, provider_user, job):
    """A client must not be able to quote in a currency nobody settles in."""
    response = as_user(provider_user).post(
        quotes_url(job), {"amount": "200.00", "currency": "USD"}, format="json"
    )
    assert response.status_code == 201
    assert response.data["currency"] == "GHS"


def test_customer_cannot_submit_a_quote(as_user, customer_user, job):
    response = as_user(customer_user).post(quotes_url(job), {"amount": "200.00"}, format="json")
    assert response.status_code == 403
    assert not Quote.objects.exists()


def test_unrelated_provider_cannot_quote(as_user, other_provider_user, other_provider_profile, job):
    """404 rather than 403 — a stranger should not learn the job id is real."""
    response = as_user(other_provider_user).post(
        quotes_url(job), {"amount": "200.00"}, format="json"
    )
    assert response.status_code == 404


def test_quote_must_be_positive(as_user, provider_user, job):
    response = as_user(provider_user).post(quotes_url(job), {"amount": "0"}, format="json")
    assert response.status_code == 400


def test_quote_amount_is_required(as_user, provider_user, job):
    response = as_user(provider_user).post(quotes_url(job), {}, format="json")
    assert response.status_code == 400
    assert "amount" in response.data


def test_cannot_quote_on_a_completed_job(as_user, provider_user, completed_job):
    response = as_user(provider_user).post(
        quotes_url(completed_job), {"amount": "200.00"}, format="json"
    )
    assert response.status_code == 409


def test_cannot_quote_once_work_is_finished(as_user, provider_user, awaiting_confirmation_job):
    """The amount is already in front of the customer; a new quote would muddy it."""
    response = as_user(provider_user).post(
        quotes_url(awaiting_confirmation_job), {"amount": "200.00"}, format="json"
    )
    assert response.status_code == 409


def test_a_revised_quote_supersedes_the_outstanding_one(as_user, provider_user, job):
    client = as_user(provider_user)
    first = client.post(quotes_url(job), {"amount": "200.00"}, format="json")
    second = client.post(quotes_url(job), {"amount": "350.00"}, format="json")
    assert second.status_code == 201

    first_quote = Quote.objects.get(id=first.data["id"])
    assert first_quote.status == QuoteStatus.SUPERSEDED
    assert first_quote.responded_at is not None
    assert Quote.objects.filter(job=job, status=QuoteStatus.PENDING).count() == 1


def test_submitting_notifies_the_customer_only(as_user, provider_user, job):
    as_user(provider_user).post(quotes_url(job), {"amount": "200.00"}, format="json")
    kinds = list(
        Notification.objects.filter(user=job.service_request.customer.user).values_list(
            "kind", flat=True
        )
    )
    assert NotificationKind.QUOTE_SUBMITTED in kinds
    assert not Notification.objects.filter(user=provider_user).exists()


def test_submitting_is_audited(as_user, provider_user, job):
    as_user(provider_user).post(quotes_url(job), {"amount": "200.00"}, format="json")
    event = AuditEvent.objects.get(action=AuditAction.QUOTE_SUBMITTED)
    assert event.actor_id == provider_user.id
    assert event.metadata["amount"] == "200.00"
    assert event.metadata["currency"] == "GHS"


# --- responding ---------------------------------------------------------------------


def test_customer_accepts_a_quote(as_user, customer_user, job, quote):
    response = as_user(customer_user).post(respond_url(job, quote), {"accept": True}, format="json")
    assert response.status_code == 200
    quote.refresh_from_db()
    assert quote.status == QuoteStatus.ACCEPTED
    assert quote.responded_at is not None


def test_customer_declines_a_quote(as_user, customer_user, job, quote):
    response = as_user(customer_user).post(respond_url(job, quote), {"accept": False}, format="json")
    assert response.status_code == 200
    quote.refresh_from_db()
    assert quote.status == QuoteStatus.DECLINED


def test_declining_does_not_cancel_the_job(as_user, customer_user, job, quote):
    """Declining invites a revised quote; it is not a withdrawal."""
    as_user(customer_user).post(respond_url(job, quote), {"accept": False}, format="json")
    job.refresh_from_db()
    assert job.status == JobStatus.PENDING_ACCEPT


def test_provider_cannot_answer_their_own_quote(as_user, provider_user, job, quote):
    response = as_user(provider_user).post(respond_url(job, quote), {"accept": True}, format="json")
    assert response.status_code == 403
    quote.refresh_from_db()
    assert quote.status == QuoteStatus.PENDING


def test_unrelated_customer_cannot_respond(as_user, other_customer_user, job, quote):
    response = as_user(other_customer_user).post(
        respond_url(job, quote), {"accept": True}, format="json"
    )
    assert response.status_code == 404


def test_a_quote_cannot_be_answered_twice(as_user, customer_user, job, quote):
    client = as_user(customer_user)
    client.post(respond_url(job, quote), {"accept": True}, format="json")
    response = client.post(respond_url(job, quote), {"accept": False}, format="json")
    assert response.status_code == 409
    quote.refresh_from_db()
    assert quote.status == QuoteStatus.ACCEPTED


def test_superseded_quote_cannot_be_answered(as_user, provider_user, customer_user, job):
    provider = as_user(provider_user)
    first = provider.post(quotes_url(job), {"amount": "200.00"}, format="json")
    provider.post(quotes_url(job), {"amount": "350.00"}, format="json")

    stale = Quote.objects.get(id=first.data["id"])
    response = as_user(customer_user).post(respond_url(job, stale), {"accept": True}, format="json")
    assert response.status_code == 409


def test_responding_notifies_the_provider_only(as_user, customer_user, provider_user, job, quote):
    as_user(customer_user).post(respond_url(job, quote), {"accept": True}, format="json")
    kinds = list(Notification.objects.filter(user=provider_user).values_list("kind", flat=True))
    assert kinds == [NotificationKind.QUOTE_ACCEPTED]


def test_declining_notifies_the_provider_with_a_distinct_kind(
    as_user, customer_user, provider_user, job, quote
):
    as_user(customer_user).post(respond_url(job, quote), {"accept": False}, format="json")
    kinds = list(Notification.objects.filter(user=provider_user).values_list("kind", flat=True))
    assert kinds == [NotificationKind.QUOTE_DECLINED]


def test_responding_is_audited(as_user, customer_user, job, quote):
    as_user(customer_user).post(respond_url(job, quote), {"accept": True}, format="json")
    event = AuditEvent.objects.get(action=AuditAction.QUOTE_RESPONDED)
    assert event.actor_id == customer_user.id
    assert event.metadata["response"] == QuoteStatus.ACCEPTED


# --- reading ------------------------------------------------------------------------


def test_both_parties_can_read_the_price_thread(as_user, customer_user, provider_user, job, quote):
    for user in (customer_user, provider_user):
        response = as_user(user).get(quotes_url(job))
        assert response.status_code == 200
        ids = [row["id"] for row in response.data["results"]]
        assert str(quote.id) in ids


def test_outsider_cannot_read_the_price_thread(as_user, other_customer_user, job, quote):
    assert as_user(other_customer_user).get(quotes_url(job)).status_code == 404


def test_job_exposes_the_latest_quote(as_user, customer_user, job, quote):
    response = as_user(customer_user).get(job_url(job))
    assert response.data["latest_quote"]["id"] == str(quote.id)
    assert response.data["latest_quote"]["amount"] == "200.00"


def test_job_latest_quote_is_null_when_none_exists(as_user, customer_user, job):
    assert as_user(customer_user).get(job_url(job)).data["latest_quote"] is None


# --- the quote against the final amount ---------------------------------------------


def test_variance_is_reported_when_the_bill_exceeds_the_agreed_price(
    as_user, provider_user, customer_user, job, quote
):
    """SPEC-015 REQ-6: the customer must see the gap before they confirm."""
    as_user(customer_user).post(respond_url(job, quote), {"accept": True}, format="json")

    provider = as_user(provider_user)
    provider.patch(job_url(job), {"status": "active"}, format="json")
    provider.patch(
        job_url(job),
        {"status": "awaiting_confirmation", "final_amount": "275.00"},
        format="json",
    )

    response = as_user(customer_user).get(job_url(job))
    assert response.data["final_amount"] == "275.00"
    assert Decimal(response.data["amount_variance"]) == Decimal("75.00")


def test_variance_is_null_without_an_accepted_quote(
    as_user, provider_user, customer_user, job, quote
):
    """A quote nobody accepted is not a promise, so there is nothing to measure against."""
    provider = as_user(provider_user)
    provider.patch(job_url(job), {"status": "active"}, format="json")
    provider.patch(
        job_url(job),
        {"status": "awaiting_confirmation", "final_amount": "275.00"},
        format="json",
    )

    response = as_user(customer_user).get(job_url(job))
    assert response.data["amount_variance"] is None


def test_variance_is_null_before_work_is_finished(as_user, customer_user, job, quote):
    as_user(customer_user).post(respond_url(job, quote), {"accept": True}, format="json")
    response = as_user(customer_user).get(job_url(job))
    assert response.data["amount_variance"] is None


def test_a_job_can_be_finished_without_any_quote(as_user, provider_user, customer_user, job):
    """Quoting is optional — towing prices out of distance, and small jobs do not need it."""
    provider = as_user(provider_user)
    provider.patch(job_url(job), {"status": "active"}, format="json")
    response = provider.patch(
        job_url(job),
        {"status": "awaiting_confirmation", "final_amount": "80.00"},
        format="json",
    )
    assert response.status_code == 200

    confirm = as_user(customer_user).patch(job_url(job), {"status": "completed"}, format="json")
    assert confirm.status_code == 200
    job.refresh_from_db()
    assert job.status == JobStatus.COMPLETED
