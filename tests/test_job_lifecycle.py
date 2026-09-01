"""Job acceptance and transitions — SPEC-007.

Covers the three conflicts closed in this slice: unvalidated transitions (CONFLICT-007-B),
customer-writable job state (CONFLICT-007-C), and non-atomic acceptance (CONFLICT-007-A).
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.jobs.models import Job, JobStatus, ServiceRequestStatus
from apps.jobs.services import JOB_TRANSITIONS, allowed_targets
from apps.providers.models import ProviderProfile
from apps.notifications.models import Notification, NotificationKind

pytestmark = pytest.mark.django_db


def accept_url(service_request):
    return reverse("job-accept", kwargs={"request_id": service_request.id})


def job_url(job):
    return reverse("job-detail", kwargs={"id": job.id})


# --- acceptance -------------------------------------------------------------------


def test_provider_accepts_open_request(as_user, provider_user, provider_profile, service_request):
    response = as_user(provider_user).post(accept_url(service_request))
    assert response.status_code == 201
    assert response.data["status"] == JobStatus.PENDING_ACCEPT

    job = Job.objects.get()
    assert job.provider_id == provider_profile.id
    assert hasattr(job, "chat_room")
    service_request.refresh_from_db()
    assert service_request.status == ServiceRequestStatus.MATCHING


def test_accepting_notifies_the_customer(as_user, provider_user, provider_profile, service_request):
    as_user(provider_user).post(accept_url(service_request))
    notification = Notification.objects.get(user=service_request.customer.user)
    assert notification.kind == NotificationKind.REQUEST_ACCEPTED
    assert notification.payload["service_request_id"] == str(service_request.id)


def test_second_provider_accepting_gets_409(
    as_user, provider_user, provider_profile, other_provider_user, other_provider_profile, service_request
):
    """CONFLICT-007-A: previously both providers created a job."""
    assert as_user(provider_user).post(accept_url(service_request)).status_code == 201
    response = as_user(other_provider_user).post(accept_url(service_request))
    assert response.status_code == 409
    assert Job.objects.count() == 1


def test_only_one_live_job_per_request_at_database_level(service_request, provider_profile, other_provider_profile):
    from django.db.utils import IntegrityError

    Job.objects.create(service_request=service_request, provider=provider_profile)
    with pytest.raises(IntegrityError):
        Job.objects.create(service_request=service_request, provider=other_provider_profile)


@pytest.mark.django_db(transaction=True)
def test_concurrent_acceptance_yields_exactly_one_job(
    service_request, provider_profile, other_provider_profile
):
    """Two providers accepting simultaneously — exactly one wins.

    Skipped on SQLite: ``has_select_for_update`` is False there, so Django silently drops
    the ``SELECT ... FOR UPDATE`` and this exercises only the database constraint, which
    ``test_only_one_live_job_per_service_request`` already covers directly. Run with
    ``USE_POSTGRES_TESTS=1`` to exercise the locking layer.
    """
    import threading

    from django.db import connection, connections

    from apps.core.exceptions import Conflict
    from apps.jobs.services import accept_service_request

    if not connection.features.has_select_for_update:
        pytest.skip("backend does not support SELECT ... FOR UPDATE (set USE_POSTGRES_TESTS=1)")

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(mechanic_pk):
        try:
            provider = ProviderProfile.objects.get(pk=mechanic_pk)
            barrier.wait(timeout=5)
            accept_service_request(service_request_id=service_request.id, provider=provider)
            outcome = "accepted"
        except Conflict:
            outcome = "conflict"
        except Exception as exc:  # surfaced in the assertion below
            outcome = f"error:{type(exc).__name__}"
        finally:
            connections.close_all()
        with lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=attempt, args=(provider_profile.pk,)),
        threading.Thread(target=attempt, args=(other_provider_profile.pk,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert sorted(outcomes) == ["accepted", "conflict"], outcomes
    assert Job.objects.count() == 1
    service_request.refresh_from_db()
    assert service_request.status == ServiceRequestStatus.MATCHING


def test_customer_cannot_accept(as_user, customer_user, service_request):
    assert as_user(customer_user).post(accept_url(service_request)).status_code == 403


def test_provider_without_profile_gets_409(as_user, provider_user, service_request):
    """CONFLICT-003-A: this was previously an unhandled 500."""
    response = as_user(provider_user).post(accept_url(service_request))
    assert response.status_code == 409


def test_accepting_unknown_request_is_404(as_user, provider_user, provider_profile):
    import uuid

    url = reverse("job-accept", kwargs={"request_id": uuid.uuid4()})
    assert as_user(provider_user).post(url).status_code == 404


def test_accepting_non_open_request_is_409(
    as_user, provider_user, provider_profile, make_service_request, customer_profile
):
    request = make_service_request(customer_profile, status=ServiceRequestStatus.COMPLETED)
    assert as_user(provider_user).post(accept_url(request)).status_code == 409


# --- transitions ------------------------------------------------------------------


def test_provider_starts_job(as_user, provider_user, job):
    response = as_user(provider_user).patch(job_url(job), {"status": "active"}, format="json")
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.status == JobStatus.ACTIVE
    assert job.accepted_at is not None
    job.service_request.refresh_from_db()
    assert job.service_request.status == ServiceRequestStatus.ASSIGNED


def test_provider_finishing_does_not_complete_the_job(as_user, provider_user, job):
    """SPEC-015 REQ-7: finishing is one half of completion, not the whole of it."""
    client = as_user(provider_user)
    client.patch(job_url(job), {"status": "active"}, format="json")
    response = client.patch(
        job_url(job),
        {"status": "awaiting_confirmation", "final_amount": "250.00"},
        format="json",
    )
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.status == JobStatus.AWAITING_CONFIRMATION
    assert job.work_finished_at is not None
    assert job.completed_at is None
    assert job.final_amount == Decimal("250.00")
    assert job.currency == "GHS"
    # The request is still `assigned` — nothing is closed until the customer agrees.
    job.service_request.refresh_from_db()
    assert job.service_request.status == ServiceRequestStatus.ASSIGNED


def test_customer_confirmation_completes_the_job(
    as_user, customer_user, awaiting_confirmation_job
):
    response = as_user(customer_user).patch(
        job_url(awaiting_confirmation_job), {"status": "completed"}, format="json"
    )
    assert response.status_code == 200
    awaiting_confirmation_job.refresh_from_db()
    assert awaiting_confirmation_job.status == JobStatus.COMPLETED
    assert awaiting_confirmation_job.completed_at is not None
    assert awaiting_confirmation_job.final_amount == Decimal("250.00")
    awaiting_confirmation_job.service_request.refresh_from_db()
    assert (
        awaiting_confirmation_job.service_request.status
        == ServiceRequestStatus.COMPLETED
    )


def test_provider_cannot_confirm_their_own_work(
    as_user, provider_user, awaiting_confirmation_job
):
    """The whole point of two-sided completion (ADR-022)."""
    response = as_user(provider_user).patch(
        job_url(awaiting_confirmation_job), {"status": "completed"}, format="json"
    )
    assert response.status_code == 409
    awaiting_confirmation_job.refresh_from_db()
    assert awaiting_confirmation_job.status == JobStatus.AWAITING_CONFIRMATION


def test_finishing_without_an_amount_is_rejected(as_user, provider_user, job):
    client = as_user(provider_user)
    client.patch(job_url(job), {"status": "active"}, format="json")
    response = client.patch(
        job_url(job), {"status": "awaiting_confirmation"}, format="json"
    )
    assert response.status_code == 400
    assert "final_amount" in response.data
    job.refresh_from_db()
    assert job.status == JobStatus.ACTIVE


def test_a_negative_amount_is_rejected(as_user, provider_user, job):
    client = as_user(provider_user)
    client.patch(job_url(job), {"status": "active"}, format="json")
    response = client.patch(
        job_url(job),
        {"status": "awaiting_confirmation", "final_amount": "-1.00"},
        format="json",
    )
    assert response.status_code == 400
    job.refresh_from_db()
    assert job.status == JobStatus.ACTIVE


def test_an_absurd_amount_is_rejected(as_user, provider_user, job):
    """Typo guard: a slipped decimal point must not become a bill."""
    client = as_user(provider_user)
    client.patch(job_url(job), {"status": "active"}, format="json")
    response = client.patch(
        job_url(job),
        {"status": "awaiting_confirmation", "final_amount": "99999999.00"},
        format="json",
    )
    assert response.status_code == 400


def test_amount_cannot_be_edited_without_a_transition(
    as_user, provider_user, awaiting_confirmation_job
):
    """A provider must not be able to revise the bill after the customer sees it."""
    response = as_user(provider_user).patch(
        job_url(awaiting_confirmation_job), {"final_amount": "900.00"}, format="json"
    )
    assert response.status_code == 409
    awaiting_confirmation_job.refresh_from_db()
    assert awaiting_confirmation_job.final_amount == Decimal("250.00")


def test_finished_work_cannot_be_cancelled_by_the_customer(
    as_user, customer_user, awaiting_confirmation_job
):
    """SPEC-015 REQ-8: cancelling must not be a way to walk away from work done."""
    url = reverse(
        "service-request-cancel",
        kwargs={"id": awaiting_confirmation_job.service_request_id},
    )
    response = as_user(customer_user).post(url)
    assert response.status_code == 409
    awaiting_confirmation_job.refresh_from_db()
    assert awaiting_confirmation_job.status == JobStatus.AWAITING_CONFIRMATION


def test_customer_cannot_cancel_the_job_directly_once_work_is_finished(
    as_user, customer_user, awaiting_confirmation_job
):
    response = as_user(customer_user).patch(
        job_url(awaiting_confirmation_job), {"status": "cancelled"}, format="json"
    )
    assert response.status_code == 409


def test_provider_declining_returns_request_to_pool(as_user, provider_user, job):
    response = as_user(provider_user).patch(job_url(job), {"status": "cancelled"}, format="json")
    assert response.status_code == 200
    job.service_request.refresh_from_db()
    assert job.service_request.status == ServiceRequestStatus.OPEN


def test_provider_abandoning_active_job_cancels_request(as_user, provider_user, job):
    client = as_user(provider_user)
    client.patch(job_url(job), {"status": "active"}, format="json")
    client.patch(job_url(job), {"status": "cancelled"}, format="json")
    job.service_request.refresh_from_db()
    assert job.service_request.status == ServiceRequestStatus.CANCELLED


def test_declined_request_can_be_accepted_by_another_provider(
    as_user, provider_user, job, other_provider_user, other_provider_profile
):
    as_user(provider_user).patch(job_url(job), {"status": "cancelled"}, format="json")
    response = as_user(other_provider_user).post(accept_url(job.service_request))
    assert response.status_code == 201
    assert Job.objects.count() == 2


def test_skipping_active_is_409(as_user, provider_user, job):
    """CONFLICT-007-B: pending_accept -> completed used to be accepted silently."""
    response = as_user(provider_user).patch(job_url(job), {"status": "completed"}, format="json")
    assert response.status_code == 409
    job.refresh_from_db()
    assert job.status == JobStatus.PENDING_ACCEPT
    assert job.completed_at is None
    job.service_request.refresh_from_db()
    assert job.service_request.status == ServiceRequestStatus.MATCHING


def test_resending_current_status_is_an_idempotent_noop(as_user, provider_user, job):
    response = as_user(provider_user).patch(job_url(job), {"status": "pending_accept"}, format="json")
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.status == JobStatus.PENDING_ACCEPT


def test_completed_job_cannot_regress(as_user, provider_user, completed_job):
    response = as_user(provider_user).patch(completed_job_url(completed_job), {"status": "active"}, format="json")
    assert response.status_code == 409
    completed_job.refresh_from_db()
    assert completed_job.status == JobStatus.COMPLETED


def completed_job_url(job):
    return reverse("job-detail", kwargs={"id": job.id})


def test_transition_notifies_the_counterparty_only(as_user, provider_user, job):
    as_user(provider_user).patch(job_url(job), {"status": "active"}, format="json")
    kinds = list(
        Notification.objects.filter(user=job.service_request.customer.user).values_list("kind", flat=True)
    )
    assert NotificationKind.JOB_ACTIVE in kinds
    assert not Notification.objects.filter(user=provider_user).exists()


# --- customer restrictions ----------------------------------------------------------


def test_customer_cannot_complete_a_job(as_user, customer_user, job):
    """CONFLICT-007-C: a customer PATCH used to write status with no side effects."""
    response = as_user(customer_user).patch(job_url(job), {"status": "completed"}, format="json")
    assert response.status_code == 409
    job.refresh_from_db()
    assert job.status == JobStatus.PENDING_ACCEPT


def test_customer_cannot_start_a_job(as_user, customer_user, job):
    response = as_user(customer_user).patch(job_url(job), {"status": "active"}, format="json")
    assert response.status_code == 409


def test_customer_may_cancel_their_job(as_user, customer_user, job):
    response = as_user(customer_user).patch(job_url(job), {"status": "cancelled"}, format="json")
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.status == JobStatus.CANCELLED
    job.service_request.refresh_from_db()
    assert job.service_request.status == ServiceRequestStatus.CANCELLED


def test_customer_cancelling_notifies_provider(as_user, customer_user, job, provider_user):
    as_user(customer_user).patch(job_url(job), {"status": "cancelled"}, format="json")
    assert Notification.objects.filter(
        user=provider_user, kind=NotificationKind.JOB_CANCELLED
    ).exists()


def test_customer_cannot_edit_notes(as_user, customer_user, job):
    job.notes = "provider's record"
    job.save(update_fields=["notes"])
    as_user(customer_user).patch(job_url(job), {"notes": "tampered"}, format="json")
    job.refresh_from_db()
    assert job.notes == "provider's record"


def test_provider_can_edit_notes(as_user, provider_user, job):
    response = as_user(provider_user).patch(job_url(job), {"notes": "Replaced battery"}, format="json")
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.notes == "Replaced battery"


# --- visibility -------------------------------------------------------------------


def test_non_participant_cannot_see_job(as_user, other_customer_user, job):
    assert as_user(other_customer_user).get(job_url(job)).status_code == 404


def test_job_list_is_participant_scoped(as_user, customer_user, other_customer_user, job):
    assert as_user(customer_user).get(reverse("job-list")).data["count"] == 1
    assert as_user(other_customer_user).get(reverse("job-list")).data["count"] == 0


# --- transition table -------------------------------------------------------------


def test_transition_table_has_no_moves_out_of_terminal_states():
    terminal = JobStatus.terminal()
    assert not [t for t in JOB_TRANSITIONS if t.source in terminal]


def test_allowed_targets_reports_role_specific_moves():
    assert set(allowed_targets(JobStatus.PENDING_ACCEPT, "provider")) == {"active", "cancelled"}
    assert set(allowed_targets(JobStatus.PENDING_ACCEPT, "customer")) == {"cancelled"}
    assert allowed_targets(JobStatus.COMPLETED, "provider") == []
