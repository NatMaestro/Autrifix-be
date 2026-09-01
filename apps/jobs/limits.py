"""Volume limits on requests and jobs — SPEC-016 REQ-4/REQ-5, closing SEC-GAP-28.

These are abuse controls first and product rules second, and the distinction matters when
tuning them. Nothing stopped a customer opening a hundred requests, or a provider claiming
every request in a city to deny competitors the work — neither needs malice to hurt, just a
retry loop or an over-eager operator.

Both limits live in the service layer rather than in a serializer so they hold for every
caller, including the admin and any future dispatch.
"""

from __future__ import annotations

from django.conf import settings

from apps.core.exceptions import Conflict
from apps.jobs.models import Job, JobStatus, ServiceRequest, ServiceRequestStatus

#: Request states that count against a customer's open-request allowance. `assigned` is
#: excluded: once a provider is committed the request is no longer competing for attention,
#: and counting it would stop a customer with one job in progress from reporting a second
#: unrelated breakdown.
COUNTED_REQUEST_STATUSES = frozenset(
    {ServiceRequestStatus.OPEN, ServiceRequestStatus.MATCHING}
)

#: Job states that count against a provider's concurrent-work allowance.
#:
#: ``awaiting_confirmation`` is deliberately **excluded**. The provider has finished; they
#: are waiting on someone else. Counting it would let an unresponsive customer block a
#: provider from working at all — punishing the wrong party for the other's silence, and
#: exactly the failure mode SPEC-015 OQ-015-D already worries about.
COUNTED_JOB_STATUSES = frozenset({JobStatus.PENDING_ACCEPT, JobStatus.ACTIVE})


def open_request_count(customer) -> int:
    return ServiceRequest.objects.filter(
        customer=customer, status__in=COUNTED_REQUEST_STATUSES
    ).count()


def live_job_count(provider) -> int:
    return Job.objects.filter(provider=provider, status__in=COUNTED_JOB_STATUSES).count()


def assert_can_open_request(customer) -> None:
    """Raise ``Conflict`` if the customer already holds the maximum unclaimed requests."""
    cap = settings.MAX_OPEN_REQUESTS_PER_CUSTOMER
    if cap and open_request_count(customer) >= cap:
        raise Conflict(
            f"You already have {cap} requests waiting for a provider. "
            "Cancel one before creating another."
        )


def assert_can_accept_job(provider) -> None:
    """Raise ``Conflict`` if the provider is already at their concurrent-work limit."""
    cap = settings.MAX_CONCURRENT_JOBS_PER_PROVIDER
    if cap and live_job_count(provider) >= cap:
        raise Conflict(
            f"You are already handling {cap} jobs. Finish or release one before accepting more."
        )
