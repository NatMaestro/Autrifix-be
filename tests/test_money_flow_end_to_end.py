"""The money loop, walked in the exact order the web client performs it.

The unit tests cover each transition in isolation. This walks the whole path once, in
sequence, because the web app's failure was never in a single call — it was that the second
half of the flow had no caller, so nobody noticed the loop did not close.

If this test breaks, a screen in `autrifix-web` breaks with it.
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.jobs.models import Job, JobStatus, QuoteStatus, ServiceRequestStatus

pytestmark = pytest.mark.django_db


def test_quote_accept_finish_confirm(
    as_user, customer_user, customer_profile, provider_user, provider_profile, category
):
    customer = as_user(customer_user)
    provider = as_user(provider_user)

    # 1. Customer reports a problem — `createRequest` on /customer/issues.
    created = customer.post(
        reverse("service-requests"),
        {
            "category": str(category.id),
            "description": "Engine will not start",
            "latitude": 5.6037,
            "longitude": -0.187,
        },
        format="json",
    )
    assert created.status_code == 201
    request_id = created.data["id"]
    # The read shape nests the category even though the write took a UUID.
    assert created.data["category"]["id"] == str(category.id)

    # 2. Provider claims it — `acceptJob` on /provider.
    accepted = provider.post(reverse("job-accept", kwargs={"request_id": request_id}))
    assert accepted.status_code == 201
    job_id = accepted.data["id"]
    job_url = reverse("job-detail", kwargs={"id": job_id})

    # 3. Provider quotes — ProviderQuotePanel.
    quoted = provider.post(
        reverse("job-quotes", kwargs={"job_id": job_id}),
        {"amount": "200.00", "notes": "Alternator replacement"},
        format="json",
    )
    assert quoted.status_code == 201
    quote_id = quoted.data["id"]
    assert quoted.data["currency"] == "GHS"

    # 4. Customer accepts the price — JobMoneyPanel.
    answered = customer.post(
        reverse("job-quote-respond", kwargs={"job_id": job_id, "quote_id": quote_id}),
        {"accept": True},
        format="json",
    )
    assert answered.status_code == 200
    assert answered.data["status"] == QuoteStatus.ACCEPTED

    # 5. Provider starts, then finishes with an amount above the quote.
    assert provider.patch(job_url, {"status": "active"}, format="json").status_code == 200
    finished = provider.patch(
        job_url,
        {"status": "awaiting_confirmation", "final_amount": "275.00"},
        format="json",
    )
    assert finished.status_code == 200
    assert finished.data["status"] == JobStatus.AWAITING_CONFIRMATION

    # 6. The customer sees the gap before agreeing — the disclosure the panel renders.
    seen = customer.get(job_url)
    assert seen.data["final_amount"] == "275.00"
    assert Decimal(seen.data["amount_variance"]) == Decimal("75.00")
    assert seen.data["latest_quote"]["amount"] == "200.00"

    # 7. Cancelling is refused now the work is done.
    refused = customer.post(reverse("service-request-cancel", kwargs={"id": request_id}))
    assert refused.status_code == 409

    # 8. Customer confirms — the step that had no caller at all until now.
    confirmed = customer.patch(job_url, {"status": "completed"}, format="json")
    assert confirmed.status_code == 200

    job = Job.objects.get(id=job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.final_amount == Decimal("275.00")
    assert job.auto_confirmed is False
    job.service_request.refresh_from_db()
    assert job.service_request.status == ServiceRequestStatus.COMPLETED


def test_provider_cannot_close_the_loop_alone(
    as_user, customer_user, customer_profile, provider_user, provider_profile, make_service_request
):
    """The reason the customer UI had to exist: without it the flow simply stops."""
    provider = as_user(provider_user)
    service_request = make_service_request(customer_profile)

    accepted = provider.post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    job_url = reverse("job-detail", kwargs={"id": accepted.data["id"]})

    provider.patch(job_url, {"status": "active"}, format="json")
    provider.patch(
        job_url,
        {"status": "awaiting_confirmation", "final_amount": "120.00"},
        format="json",
    )

    assert provider.patch(job_url, {"status": "completed"}, format="json").status_code == 409

    as_user(customer_user).patch(job_url, {"status": "completed"}, format="json")
    assert Job.objects.get(id=accepted.data["id"]).status == JobStatus.COMPLETED


def test_a_job_needs_no_quote_to_finish(
    as_user, customer_user, customer_profile, provider_user, provider_profile, make_service_request
):
    """Towing prices out of distance; small jobs are not worth the round trip."""
    provider = as_user(provider_user)
    service_request = make_service_request(customer_profile)

    accepted = provider.post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    job_url = reverse("job-detail", kwargs={"id": accepted.data["id"]})

    provider.patch(job_url, {"status": "active"}, format="json")
    provider.patch(
        job_url, {"status": "awaiting_confirmation", "final_amount": "80.00"}, format="json"
    )

    seen = as_user(customer_user).get(job_url)
    # Nothing to compare against, so the panel shows the amount without a variance warning.
    assert seen.data["amount_variance"] is None
    assert seen.data["latest_quote"] is None

    assert (
        as_user(customer_user).patch(job_url, {"status": "completed"}, format="json").status_code
        == 200
    )
