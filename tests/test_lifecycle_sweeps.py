"""Lifecycle sweeps and volume limits — SPEC-016.

Two states can be entered and never left by any user action: a job nobody confirms and a
request nobody claims. These tests pin down that the sweep resolves both, that it records
*why* (silence is not agreement, and expiry is not cancellation), and that it is safe to run
repeatedly against live traffic.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditAction, AuditEvent
from apps.jobs import sweeps
from apps.jobs.models import Job, JobStatus, ServiceRequest, ServiceRequestStatus
from apps.notifications.models import Notification, NotificationKind

pytestmark = pytest.mark.django_db


def _age_job(job, hours):
    """Backdate a job's finish so the sweep considers it stale."""
    Job.objects.filter(pk=job.pk).update(
        work_finished_at=timezone.now() - timedelta(hours=hours)
    )
    job.refresh_from_db()
    return job


def _age_request(service_request, hours):
    # `updated_at` is auto_now, so it must be written with an UPDATE rather than a save().
    ServiceRequest.objects.filter(pk=service_request.pk).update(
        updated_at=timezone.now() - timedelta(hours=hours)
    )
    service_request.refresh_from_db()
    return service_request


# --- auto-confirmation --------------------------------------------------------------


def test_a_stale_job_is_auto_confirmed(awaiting_confirmation_job):
    _age_job(awaiting_confirmation_job, hours=100)

    confirmed = sweeps.auto_confirm_stale_jobs()

    assert [j.id for j in confirmed] == [awaiting_confirmation_job.id]
    awaiting_confirmation_job.refresh_from_db()
    assert awaiting_confirmation_job.status == JobStatus.COMPLETED
    assert awaiting_confirmation_job.completed_at is not None
    awaiting_confirmation_job.service_request.refresh_from_db()
    assert (
        awaiting_confirmation_job.service_request.status == ServiceRequestStatus.COMPLETED
    )


def test_auto_confirmation_is_distinguishable_from_agreement(awaiting_confirmation_job):
    """A dispute must be able to tell "the customer agreed" from "the customer went quiet"."""
    _age_job(awaiting_confirmation_job, hours=100)
    sweeps.auto_confirm_stale_jobs()

    awaiting_confirmation_job.refresh_from_db()
    assert awaiting_confirmation_job.auto_confirmed is True

    event = AuditEvent.objects.get(action=AuditAction.JOB_AUTO_CONFIRMED)
    assert event.actor_id is None
    assert event.metadata["automatic"] is True
    assert event.metadata["final_amount"] == "250.00"


def test_a_customer_confirmation_is_not_marked_automatic(
    as_user, customer_user, awaiting_confirmation_job
):
    as_user(customer_user).patch(
        reverse("job-detail", kwargs={"id": awaiting_confirmation_job.id}),
        {"status": "completed"},
        format="json",
    )
    awaiting_confirmation_job.refresh_from_db()
    assert awaiting_confirmation_job.auto_confirmed is False
    assert not AuditEvent.objects.filter(action=AuditAction.JOB_AUTO_CONFIRMED).exists()


def test_a_fresh_job_is_left_alone(awaiting_confirmation_job):
    assert sweeps.auto_confirm_stale_jobs() == []
    awaiting_confirmation_job.refresh_from_db()
    assert awaiting_confirmation_job.status == JobStatus.AWAITING_CONFIRMATION


def test_auto_confirmation_tells_both_parties(
    awaiting_confirmation_job, customer_user, provider_user
):
    _age_job(awaiting_confirmation_job, hours=100)
    sweeps.auto_confirm_stale_jobs()

    # The customer is told *because* they did not act — an amount that became binding by
    # timeout should never be discovered later.
    customer_kinds = list(
        Notification.objects.filter(user=customer_user).values_list("kind", flat=True)
    )
    assert NotificationKind.JOB_AUTO_CONFIRMED in customer_kinds

    provider_kinds = list(
        Notification.objects.filter(user=provider_user).values_list("kind", flat=True)
    )
    assert NotificationKind.JOB_COMPLETED in provider_kinds


def test_sweeping_twice_changes_nothing_the_second_time(awaiting_confirmation_job):
    _age_job(awaiting_confirmation_job, hours=100)
    assert len(sweeps.auto_confirm_stale_jobs()) == 1
    assert sweeps.auto_confirm_stale_jobs() == []
    assert AuditEvent.objects.filter(action=AuditAction.JOB_AUTO_CONFIRMED).count() == 1


def test_active_and_cancelled_jobs_are_never_swept(job):
    job.status = JobStatus.ACTIVE
    job.work_finished_at = timezone.now() - timedelta(hours=100)
    job.save(update_fields=["status", "work_finished_at"])

    assert sweeps.auto_confirm_stale_jobs() == []
    job.refresh_from_db()
    assert job.status == JobStatus.ACTIVE


# --- request expiry -----------------------------------------------------------------


def test_a_stale_open_request_expires(service_request):
    _age_request(service_request, hours=48)

    expired = sweeps.expire_stale_requests()

    assert [r.id for r in expired] == [service_request.id]
    service_request.refresh_from_db()
    assert service_request.status == ServiceRequestStatus.EXPIRED


def test_expiry_is_not_cancellation(service_request):
    """Conflating the two loses the difference between a change of mind and no supply."""
    _age_request(service_request, hours=48)
    sweeps.expire_stale_requests()

    service_request.refresh_from_db()
    assert service_request.status != ServiceRequestStatus.CANCELLED

    event = AuditEvent.objects.get(action=AuditAction.REQUEST_EXPIRED)
    assert event.actor_id is None
    assert event.metadata["automatic"] is True


def test_a_matching_request_is_not_expired(job):
    """A provider is mid-decision on it; pulling it out from under them is worse."""
    _age_request(job.service_request, hours=48)
    assert sweeps.expire_stale_requests() == []
    job.service_request.refresh_from_db()
    assert job.service_request.status == ServiceRequestStatus.MATCHING


def test_a_fresh_request_is_left_alone(service_request):
    assert sweeps.expire_stale_requests() == []
    service_request.refresh_from_db()
    assert service_request.status == ServiceRequestStatus.OPEN


def test_expiry_notifies_the_customer(service_request, customer_user):
    _age_request(service_request, hours=48)
    sweeps.expire_stale_requests()

    kinds = list(Notification.objects.filter(user=customer_user).values_list("kind", flat=True))
    assert NotificationKind.REQUEST_EXPIRED in kinds


def test_an_expired_request_cannot_be_accepted(
    as_user, other_provider_user, other_provider_profile, service_request
):
    _age_request(service_request, hours=48)
    sweeps.expire_stale_requests()

    response = as_user(other_provider_user).post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    assert response.status_code == 409


def test_an_expired_request_cannot_be_cancelled(as_user, customer_user, service_request):
    _age_request(service_request, hours=48)
    sweeps.expire_stale_requests()

    response = as_user(customer_user).post(
        reverse("service-request-cancel", kwargs={"id": service_request.id})
    )
    assert response.status_code == 409


# --- the management command ---------------------------------------------------------


@pytest.fixture
def unclaimed_request(customer_profile, make_service_request):
    """A second, independent request — the `job` fixture consumes `service_request`."""
    return make_service_request(customer_profile)


def test_dry_run_changes_nothing(awaiting_confirmation_job, unclaimed_request):
    _age_job(awaiting_confirmation_job, hours=100)
    _age_request(unclaimed_request, hours=48)

    call_command("sweep_stale_state", "--dry-run")

    awaiting_confirmation_job.refresh_from_db()
    unclaimed_request.refresh_from_db()
    assert awaiting_confirmation_job.status == JobStatus.AWAITING_CONFIRMATION
    assert unclaimed_request.status == ServiceRequestStatus.OPEN
    assert not AuditEvent.objects.filter(action=AuditAction.REQUEST_EXPIRED).exists()


def test_command_runs_both_sweeps(awaiting_confirmation_job, unclaimed_request):
    _age_job(awaiting_confirmation_job, hours=100)
    _age_request(unclaimed_request, hours=48)

    call_command("sweep_stale_state")

    awaiting_confirmation_job.refresh_from_db()
    unclaimed_request.refresh_from_db()
    assert awaiting_confirmation_job.status == JobStatus.COMPLETED
    assert unclaimed_request.status == ServiceRequestStatus.EXPIRED


def test_only_flag_scopes_the_sweep(awaiting_confirmation_job, unclaimed_request):
    _age_job(awaiting_confirmation_job, hours=100)
    _age_request(unclaimed_request, hours=48)

    call_command("sweep_stale_state", "--only", "requests")

    awaiting_confirmation_job.refresh_from_db()
    unclaimed_request.refresh_from_db()
    assert awaiting_confirmation_job.status == JobStatus.AWAITING_CONFIRMATION
    assert unclaimed_request.status == ServiceRequestStatus.EXPIRED


# --- volume limits ------------------------------------------------------------------


REQUESTS_URL = reverse("service-requests")


def _request_payload(category, **overrides):
    return {
        "category": str(category.id),
        "description": "Engine will not start",
        "latitude": 5.6037,
        "longitude": -0.187,
        **overrides,
    }


def test_customer_open_request_cap_is_enforced(
    as_user, customer_user, customer_profile, category, settings
):
    settings.MAX_OPEN_REQUESTS_PER_CUSTOMER = 2
    client = as_user(customer_user)

    for _ in range(2):
        assert client.post(REQUESTS_URL, _request_payload(category), format="json").status_code == 201

    response = client.post(REQUESTS_URL, _request_payload(category), format="json")
    assert response.status_code == 409
    assert ServiceRequest.objects.filter(customer=customer_profile).count() == 2


def test_cancelling_frees_an_open_request_slot(
    as_user, customer_user, customer_profile, category, settings
):
    settings.MAX_OPEN_REQUESTS_PER_CUSTOMER = 1
    client = as_user(customer_user)

    first = client.post(REQUESTS_URL, _request_payload(category), format="json")
    assert client.post(REQUESTS_URL, _request_payload(category), format="json").status_code == 409

    client.post(reverse("service-request-cancel", kwargs={"id": first.data["id"]}))
    assert client.post(REQUESTS_URL, _request_payload(category), format="json").status_code == 201


def test_an_assigned_request_does_not_count_against_the_cap(
    as_user, customer_user, customer_profile, category, make_service_request, settings
):
    """A customer with one job underway may still report a second, unrelated breakdown."""
    settings.MAX_OPEN_REQUESTS_PER_CUSTOMER = 1
    assigned = make_service_request(customer_profile)
    assigned.status = ServiceRequestStatus.ASSIGNED
    assigned.save(update_fields=["status"])

    response = as_user(customer_user).post(REQUESTS_URL, _request_payload(category), format="json")
    assert response.status_code == 201


def test_provider_concurrent_job_cap_is_enforced(
    as_user, provider_user, provider_profile, customer_profile, make_service_request, settings
):
    settings.MAX_CONCURRENT_JOBS_PER_PROVIDER = 1
    client = as_user(provider_user)

    first = make_service_request(customer_profile)
    assert client.post(reverse("job-accept", kwargs={"request_id": first.id})).status_code == 201

    second = make_service_request(customer_profile)
    response = client.post(reverse("job-accept", kwargs={"request_id": second.id}))
    assert response.status_code == 409
    assert Job.objects.filter(provider=provider_profile).count() == 1


def test_awaiting_confirmation_does_not_count_against_the_provider_cap(
    as_user, provider_user, provider_profile, customer_profile, make_service_request, settings
):
    """An unresponsive customer must not be able to stop a provider from working.

    This is the same failure mode SPEC-015 OQ-015-D worries about, arriving by a different
    door: if finished-but-unconfirmed work occupied a slot, one silent customer could idle
    a provider for the whole confirmation window.
    """
    settings.MAX_CONCURRENT_JOBS_PER_PROVIDER = 1
    client = as_user(provider_user)

    first = make_service_request(customer_profile)
    accept = client.post(reverse("job-accept", kwargs={"request_id": first.id}))
    job_url = reverse("job-detail", kwargs={"id": accept.data["id"]})
    client.patch(job_url, {"status": "active"}, format="json")
    client.patch(
        job_url,
        {"status": "awaiting_confirmation", "final_amount": "250.00"},
        format="json",
    )

    second = make_service_request(customer_profile)
    response = client.post(reverse("job-accept", kwargs={"request_id": second.id}))
    assert response.status_code == 201


def test_a_zero_cap_disables_the_limit(
    as_user, customer_user, customer_profile, category, settings
):
    settings.MAX_OPEN_REQUESTS_PER_CUSTOMER = 0
    client = as_user(customer_user)
    for _ in range(4):
        assert client.post(REQUESTS_URL, _request_payload(category), format="json").status_code == 201
