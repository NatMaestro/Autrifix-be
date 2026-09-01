"""Sweeps for state nothing else will ever move — SPEC-016.

Two lifecycle states can be entered and then never left by any user action:

- a job sits in ``awaiting_confirmation`` because the customer never answered;
- a request sits ``open`` because no provider ever claimed it.

Neither has an actor who is motivated to resolve it — the customer who stops replying has
no reason to come back, and nobody owns an unclaimed request. Left alone they accumulate:
providers cannot be reviewed or move on, and a customer's own request list fills with work
that will never happen.

**Run from cron, not Celery.** These are periodic and idempotent; a worker process to run
two queries would be more moving parts than the problem needs, and ADR-012 deliberately
keeps Celery out of the request path. See ``manage.py sweep_stale_state``.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import AuditAction
from apps.jobs.models import Job, JobStatus, ServiceRequest, ServiceRequestStatus
from apps.notifications import services as notifications

logger = logging.getLogger(__name__)


def auto_confirm_stale_jobs(*, now=None, dry_run: bool = False) -> list[Job]:
    """Close jobs the customer never confirmed — SPEC-016 REQ-2.

    Silence becomes agreement after ``JOB_AUTO_CONFIRM_AFTER_HOURS``. That is a real
    transfer of risk onto the customer, so it is recorded as what it is: ``auto_confirmed``
    is set on the job, the audit action is distinct from a customer confirmation, and the
    customer is told it happened. A review or dispute must be able to tell "the customer
    agreed" from "the customer went quiet".
    """
    now = now or timezone.now()
    cutoff = now - settings.JOB_AUTO_CONFIRM_AFTER
    stale = (
        Job.objects.filter(
            status=JobStatus.AWAITING_CONFIRMATION, work_finished_at__lt=cutoff
        )
        .select_related("service_request__customer__user", "provider__user")
        .order_by("work_finished_at")
    )

    if dry_run:
        return list(stale)

    confirmed: list[Job] = []
    for job in stale:
        try:
            confirmed.append(_auto_confirm(job.pk, now))
        except Job.DoesNotExist:  # pragma: no cover - raced with a real confirmation
            continue
    if confirmed:
        logger.info("sweep.auto_confirmed count=%d", len(confirmed))
    return confirmed


@transaction.atomic
def _auto_confirm(job_pk, now) -> Job:
    # Re-read under a lock: the customer may have confirmed between the query and here, and
    # a second confirmation would re-stamp `completed_at` and re-notify.
    job = (
        Job.objects.select_for_update()
        .select_related("service_request__customer__user", "provider__user")
        .get(pk=job_pk, status=JobStatus.AWAITING_CONFIRMATION)
    )

    job.status = JobStatus.COMPLETED
    job.auto_confirmed = True
    job.completed_at = now
    job.save(update_fields=["status", "auto_confirmed", "completed_at", "updated_at"])

    service_request = job.service_request
    service_request.status = ServiceRequestStatus.COMPLETED
    service_request.save(update_fields=["status", "updated_at"])

    audit.record(
        AuditAction.JOB_AUTO_CONFIRMED,
        actor=None,
        target_type="job",
        target_id=job.id,
        metadata={
            "service_request_id": str(job.service_request_id),
            "final_amount": str(job.final_amount) if job.final_amount is not None else None,
            "currency": job.currency,
            "automatic": True,
            "reason": "customer did not confirm within the confirmation window",
        },
    )
    notifications.notify_job_auto_confirmed(job)
    notifications.notify_job_completed(job)
    return job


def expire_stale_requests(*, now=None, dry_run: bool = False) -> list[ServiceRequest]:
    """Retire requests no provider ever claimed — SPEC-016 REQ-3.

    Only ``open`` requests expire. A ``matching`` request has a provider looking at it, and
    pulling it out from under them mid-decision would be worse than leaving it.
    """
    now = now or timezone.now()
    cutoff = now - settings.REQUEST_EXPIRES_AFTER
    stale = (
        ServiceRequest.objects.filter(
            status=ServiceRequestStatus.OPEN, updated_at__lt=cutoff
        )
        .select_related("customer__user")
        .order_by("updated_at")
    )

    if dry_run:
        return list(stale)

    expired: list[ServiceRequest] = []
    for service_request in stale:
        try:
            expired.append(_expire(service_request.pk))
        except ServiceRequest.DoesNotExist:  # pragma: no cover - raced with an acceptance
            continue
    if expired:
        logger.info("sweep.expired_requests count=%d", len(expired))
    return expired


@transaction.atomic
def _expire(request_pk) -> ServiceRequest:
    service_request = (
        ServiceRequest.objects.select_for_update()
        .select_related("customer__user")
        .get(pk=request_pk, status=ServiceRequestStatus.OPEN)
    )

    service_request.status = ServiceRequestStatus.EXPIRED
    service_request.save(update_fields=["status", "updated_at"])

    audit.record(
        AuditAction.REQUEST_EXPIRED,
        actor=None,
        target_type="service_request",
        target_id=service_request.id,
        metadata={"automatic": True, "reason": "no provider claimed the request in time"},
    )
    notifications.notify_request_expired(service_request)
    return service_request
