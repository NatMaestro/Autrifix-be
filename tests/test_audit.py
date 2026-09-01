"""Audit trail — SPEC-012 REQ-7 / ADR-016.

Scope is deliberately narrow: state changes and failed logins. Reads are not audited.
"""

import pytest
from django.urls import reverse

from apps.core.models import AuditAction, AuditEvent
from apps.jobs.models import JobStatus

pytestmark = pytest.mark.django_db


def job_url(job):
    return reverse("job-detail", kwargs={"id": job.id})


# --- what is audited ---------------------------------------------------------------


def test_acceptance_is_audited(as_user, provider_user, provider_profile, service_request):
    as_user(provider_user).post(reverse("job-accept", kwargs={"request_id": service_request.id}))

    event = AuditEvent.objects.get(action=AuditAction.JOB_ACCEPTED)
    assert event.actor_id == provider_user.id
    assert event.target_type == "job"
    assert event.metadata["service_request_id"] == str(service_request.id)


def test_each_transition_is_audited_with_from_and_to(
    as_user, provider_user, customer_user, job
):
    provider = as_user(provider_user)
    provider.patch(job_url(job), {"status": "active"}, format="json")
    provider.patch(
        job_url(job),
        {"status": "awaiting_confirmation", "final_amount": "250.00"},
        format="json",
    )
    as_user(customer_user).patch(job_url(job), {"status": "completed"}, format="json")

    events = list(
        AuditEvent.objects.filter(action=AuditAction.JOB_TRANSITIONED).order_by("created_at", "id")
    )
    pairs = {(e.metadata["from"], e.metadata["to"]) for e in events}
    assert pairs == {
        (JobStatus.PENDING_ACCEPT, JobStatus.ACTIVE),
        (JobStatus.ACTIVE, JobStatus.AWAITING_CONFIRMATION),
        (JobStatus.AWAITING_CONFIRMATION, JobStatus.COMPLETED),
    }
    # Completion is the customer's act; everything before it is the provider's.
    actors = {(e.metadata["to"], e.actor_id) for e in events}
    assert (JobStatus.COMPLETED, customer_user.id) in actors
    assert (JobStatus.ACTIVE, provider_user.id) in actors


def test_transition_audit_records_the_acting_role(as_user, customer_user, job):
    as_user(customer_user).patch(job_url(job), {"status": "cancelled"}, format="json")

    event = AuditEvent.objects.get(action=AuditAction.JOB_TRANSITIONED)
    assert event.metadata["actor_role"] == "customer"
    assert event.actor_id == customer_user.id


def test_request_cancellation_is_audited(as_user, customer_user, job):
    url = reverse("service-request-cancel", kwargs={"id": job.service_request_id})
    as_user(customer_user).post(url)

    event = AuditEvent.objects.get(action=AuditAction.REQUEST_CANCELLED)
    assert event.actor_id == customer_user.id
    assert event.target_id == str(job.service_request_id)
    assert str(job.id) in event.metadata["cancelled_job_ids"]


def test_failed_login_is_audited(api, make_user):
    make_user(email="audited@example.com", phone="+233540000030")
    api.post(
        reverse("login"),
        {"identifier": "audited@example.com", "password": "WrongPassword1!"},
        format="json",
    )

    event = AuditEvent.objects.get(action=AuditAction.LOGIN_FAILED)
    assert event.metadata["identifier"] == "audited@example.com"
    assert event.metadata["reason"] == "bad_credentials"
    assert event.metadata["account_exists"] is True
    # The attempt is unauthenticated, so there is no actor to attribute it to.
    assert event.actor is None


def test_failed_login_for_unknown_account_is_audited(api):
    api.post(
        reverse("login"),
        {"identifier": "ghost@example.com", "password": "WrongPassword1!"},
        format="json",
    )

    event = AuditEvent.objects.get(action=AuditAction.LOGIN_FAILED)
    assert event.metadata["account_exists"] is False


def test_inactive_account_login_is_audited_distinctly(api, make_user):
    user = make_user(email="disabled@example.com", phone="+233540000031")
    user.is_active = False
    user.save(update_fields=["is_active"])

    api.post(
        reverse("login"),
        {"identifier": "disabled@example.com", "password": "TestPass123!"},
        format="json",
    )

    event = AuditEvent.objects.get(action=AuditAction.LOGIN_FAILED)
    # The API response is identical for both reasons; only the audit trail distinguishes them.
    assert event.metadata["reason"] == "inactive_account"


# --- what is deliberately not audited ----------------------------------------------


def test_successful_login_is_not_audited(api, make_user):
    make_user(email="fine@example.com", phone="+233540000032")
    response = api.post(
        reverse("login"),
        {"identifier": "fine@example.com", "password": "TestPass123!"},
        format="json",
    )
    assert response.status_code == 200
    assert not AuditEvent.objects.filter(action=AuditAction.LOGIN_FAILED).exists()


def test_reads_are_not_audited(as_user, provider_user, provider_profile, service_request):
    """ADR-016: reads are high-volume and low-value; request logs cover them."""
    client = as_user(provider_user)
    client.get(reverse("services-nearby") + "?lat=5.6037&lng=-0.187")
    client.get(reverse("service-requests-nearby") + "?lat=5.6037&lng=-0.187")

    assert AuditEvent.objects.count() == 0


# --- durability --------------------------------------------------------------------


def test_audit_row_survives_deletion_of_the_actor(
    as_user, provider_user, provider_profile, service_request
):
    """The whole point: a trail that cascades away with the actor is worthless."""
    as_user(provider_user).post(reverse("job-accept", kwargs={"request_id": service_request.id}))
    event_id = AuditEvent.objects.get(action=AuditAction.JOB_ACCEPTED).id
    label_before = AuditEvent.objects.get(pk=event_id).actor_label
    assert label_before

    provider_user.delete()

    event = AuditEvent.objects.get(pk=event_id)
    assert event.actor is None
    assert event.actor_label == label_before
    assert event.metadata["service_request_id"] == str(service_request.id)


def test_audit_write_failure_does_not_break_the_audited_action(
    as_user, provider_user, provider_profile, service_request, monkeypatch
):
    """Losing an audit row must not fail a transition two people are waiting on."""

    def explode(*args, **kwargs):
        raise RuntimeError("audit backend down")

    monkeypatch.setattr(AuditEvent.objects, "create", explode)

    response = as_user(provider_user).post(
        reverse("job-accept", kwargs={"request_id": service_request.id})
    )
    assert response.status_code == 201
