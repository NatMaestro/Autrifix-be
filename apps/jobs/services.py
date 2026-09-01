"""Job and service-request workflow.

All state changes for ``Job`` and ``ServiceRequest`` go through this module. Views must
not mutate ``status`` directly — the transition table below is the only definition of
what is legal, and it is what the tests assert against.

See ``specs/007-job-lifecycle.md`` §9.
"""

from __future__ import annotations

from dataclasses import dataclass

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import UserRole
from apps.core import audit
from apps.core.exceptions import Conflict, VerificationRequired
from apps.core.models import AuditAction
from apps.jobs.models import (
    CANCELLABLE_REQUEST_STATUSES,
    Job,
    JobStatus,
    Quote,
    QuoteStatus,
    ServiceRequest,
    ServiceRequestStatus,
)
from apps.notifications import services as notifications


@dataclass(frozen=True)
class Transition:
    """One legal move in the job state machine."""

    source: str
    target: str
    actor: str
    #: ``ServiceRequest.status`` to apply as a side effect, or ``None`` to leave it alone.
    request_status: str | None
    #: ``Job`` timestamp field to stamp with the current time, if not already set.
    stamp: str | None = None
    #: This move records money, so ``final_amount`` is mandatory.
    requires_amount: bool = False


#: Upper bound on any recorded amount. Not a business rule — a typo guard, so a slipped
#: decimal point cannot record an absurd figure against a customer.
MAX_AMOUNT = Decimal("1000000.00")


#: The complete set of legal job transitions. Anything not listed here is a 409.
JOB_TRANSITIONS: tuple[Transition, ...] = (
    # Provider starts the work they accepted.
    Transition(
        JobStatus.PENDING_ACCEPT,
        JobStatus.ACTIVE,
        UserRole.PROVIDER,
        ServiceRequestStatus.ASSIGNED,
        stamp="accepted_at",
    ),
    # Provider declines before starting — the request returns to the open pool.
    Transition(
        JobStatus.PENDING_ACCEPT,
        JobStatus.CANCELLED,
        UserRole.PROVIDER,
        ServiceRequestStatus.OPEN,
    ),
    # Provider abandons work already started — the request is dead.
    Transition(
        JobStatus.ACTIVE,
        JobStatus.CANCELLED,
        UserRole.PROVIDER,
        ServiceRequestStatus.CANCELLED,
    ),
    # Provider finishes and records what the customer owes. The request stays `assigned`:
    # nothing is closed until the customer agrees (SPEC-015 REQ-7).
    Transition(
        JobStatus.ACTIVE,
        JobStatus.AWAITING_CONFIRMATION,
        UserRole.PROVIDER,
        None,
        stamp="work_finished_at",
        requires_amount=True,
    ),
    # Only the customer can close a job. A provider cannot mark their own work agreed —
    # that is the entire point of two-sided completion (ADR-022).
    Transition(
        JobStatus.AWAITING_CONFIRMATION,
        JobStatus.COMPLETED,
        UserRole.CUSTOMER,
        ServiceRequestStatus.COMPLETED,
        stamp="completed_at",
    ),
    # Customer changes their mind, before or after the provider started.
    Transition(
        JobStatus.PENDING_ACCEPT,
        JobStatus.CANCELLED,
        UserRole.CUSTOMER,
        ServiceRequestStatus.CANCELLED,
    ),
    Transition(
        JobStatus.ACTIVE,
        JobStatus.CANCELLED,
        UserRole.CUSTOMER,
        ServiceRequestStatus.CANCELLED,
    ),
)


def _find_transition(source: str, target: str, actor_role: str) -> Transition | None:
    for candidate in JOB_TRANSITIONS:
        if candidate.source == source and candidate.target == target and candidate.actor == actor_role:
            return candidate
    return None


def allowed_targets(source: str, actor_role: str) -> list[str]:
    """Targets ``actor_role`` may move a job to from ``source``. Used in error detail."""
    return sorted({t.target for t in JOB_TRANSITIONS if t.source == source and t.actor == actor_role})


@transaction.atomic
def accept_service_request(*, service_request_id, provider) -> Job:
    """Claim an open service request.

    Locks the request row so two providers cannot both read it as ``open``. The
    ``unique_live_job_per_service_request`` constraint is the second line of defence if
    the lock is ever bypassed.
    """
    from apps.chat.models import ChatRoom
    from apps.jobs.limits import assert_can_accept_job
    from apps.providers.verification import accept_min_level, can_accept_jobs

    # Checked here rather than in the view so the gate holds for every caller — admin
    # actions and future background dispatch included (SPEC-013 REQ-3).
    if not can_accept_jobs(provider):
        raise VerificationRequired(
            current_level=provider.verification_level,
            required_level=accept_min_level(),
        )

    assert_can_accept_job(provider)

    try:
        service_request = ServiceRequest.objects.select_for_update().get(id=service_request_id)
    except ServiceRequest.DoesNotExist as exc:
        raise NotFound("Request not found.") from exc

    if service_request.status != ServiceRequestStatus.OPEN:
        raise Conflict("This request is no longer open.")

    try:
        job = Job.objects.create(
            service_request=service_request,
            provider=provider,
            status=JobStatus.PENDING_ACCEPT,
        )
    except IntegrityError as exc:
        raise Conflict("This request has already been accepted by another provider.") from exc

    ChatRoom.objects.get_or_create(job=job)

    service_request.status = ServiceRequestStatus.MATCHING
    service_request.save(update_fields=["status", "updated_at"])

    audit.record(
        AuditAction.JOB_ACCEPTED,
        actor=provider.user,
        target_type="job",
        target_id=job.id,
        metadata={
            "service_request_id": str(service_request.id),
            "provider_id": str(provider.id),
        },
    )
    notifications.notify_request_accepted(job)
    return job


@transaction.atomic
def transition_job(*, job: Job, target_status: str, actor, final_amount=None) -> Job:
    """Move ``job`` to ``target_status`` on behalf of ``actor``.

    Raises ``Conflict`` (409) if the move is not in :data:`JOB_TRANSITIONS` for the
    actor's role. ``final_amount`` is required by, and only accepted for, transitions
    marked ``requires_amount``.
    """
    job = Job.objects.select_for_update().select_related("service_request", "provider").get(pk=job.pk)
    actor_role = getattr(actor, "role", None)

    if target_status == job.status:
        # Idempotent: re-sending the current status is a no-op, not a conflict.
        return job

    transition = _find_transition(job.status, target_status, actor_role)
    if transition is None:
        permitted = allowed_targets(job.status, actor_role)
        detail = (
            f"Cannot move a job from '{job.status}' to '{target_status}'. "
            + (f"Allowed: {', '.join(permitted)}." if permitted else "No transitions are available to you.")
        )
        raise Conflict(detail)

    source_status = job.status
    update_fields = ["status", "updated_at"]
    if transition.requires_amount:
        job.final_amount = _clean_amount(final_amount)
        job.currency = settings.PLATFORM_CURRENCY
        update_fields += ["final_amount", "currency"]
    elif final_amount is not None:
        raise Conflict(f"An amount cannot be recorded when moving to '{target_status}'.")
    job.status = transition.target
    if transition.stamp and getattr(job, transition.stamp) is None:
        setattr(job, transition.stamp, timezone.now())
        update_fields.append(transition.stamp)
    job.save(update_fields=update_fields)

    if transition.request_status is not None:
        service_request = job.service_request
        service_request.status = transition.request_status
        service_request.save(update_fields=["status", "updated_at"])

    audit.record(
        AuditAction.JOB_TRANSITIONED,
        actor=actor,
        target_type="job",
        target_id=job.id,
        metadata={
            "from": source_status,
            "to": transition.target,
            "actor_role": transition.actor,
            "service_request_id": str(job.service_request_id),
            "service_request_status": transition.request_status,
        },
    )
    _notify_for_transition(job, transition)
    return job


def _clean_amount(value):
    """Coerce and bounds-check a recorded amount.

    Validation lives here rather than only in the serializer so the invariant holds for
    every caller of :func:`transition_job`, the admin and future dispatch included.
    """
    if value is None:
        raise ValidationError({"final_amount": "An amount is required to finish a job."})
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValidationError({"final_amount": "Enter a valid amount."}) from exc
    if amount < 0:
        raise ValidationError({"final_amount": "An amount cannot be negative."})
    if amount > MAX_AMOUNT:
        raise ValidationError({"final_amount": f"An amount cannot exceed {MAX_AMOUNT}."})
    return amount.quantize(Decimal("0.01"))


def _notify_for_transition(job: Job, transition: Transition) -> None:
    if transition.target == JobStatus.ACTIVE:
        notifications.notify_job_active(job)
    elif transition.target == JobStatus.AWAITING_CONFIRMATION:
        notifications.notify_job_awaiting_confirmation(job)
    elif transition.target == JobStatus.COMPLETED:
        notifications.notify_job_completed(job)
    elif transition.target == JobStatus.CANCELLED:
        notifications.notify_job_cancelled(job, cancelled_by_role=transition.actor)


@transaction.atomic
def cancel_service_request(*, service_request: ServiceRequest, actor=None) -> ServiceRequest:
    """Customer-initiated cancellation of their own request.

    Cancels any live job on the request and notifies the assigned provider.
    """
    service_request = ServiceRequest.objects.select_for_update().get(pk=service_request.pk)

    if service_request.status not in CANCELLABLE_REQUEST_STATUSES:
        raise Conflict(f"A request that is '{service_request.status}' can no longer be cancelled.")

    # `assigned` covers both "provider is working" and "provider has finished and is waiting
    # on the customer". Cancelling in the second case would be a way to walk away from work
    # already done, so it is refused (SPEC-015 REQ-8).
    if Job.objects.filter(
        service_request=service_request, status=JobStatus.AWAITING_CONFIRMATION
    ).exists():
        raise Conflict(
            "The work on this request is finished. Confirm the amount instead of cancelling."
        )

    live_jobs = list(
        Job.objects.select_for_update()
        .filter(service_request=service_request)
        .exclude(status__in=JobStatus.terminal())
        .select_related("provider__user")
    )
    for job in live_jobs:
        job.status = JobStatus.CANCELLED
        job.save(update_fields=["status", "updated_at"])
        notifications.notify_request_cancelled(service_request, job.provider.user)

    previous_status = service_request.status
    service_request.status = ServiceRequestStatus.CANCELLED
    service_request.save(update_fields=["status", "updated_at"])

    audit.record(
        AuditAction.REQUEST_CANCELLED,
        actor=actor if actor is not None else service_request.customer.user,
        target_type="service_request",
        target_id=service_request.id,
        metadata={
            "from": previous_status,
            "cancelled_job_ids": [str(job.id) for job in live_jobs],
        },
    )
    return service_request


# --------------------------------------------------------------------------------------
# Quotes
# --------------------------------------------------------------------------------------


@transaction.atomic
def submit_quote(*, job: Job, provider, amount, notes: str = "") -> Quote:
    """Provider proposes a price for work not yet done.

    Submitting a second quote supersedes the outstanding one rather than erroring: a
    provider who opens the engine and finds more wrong needs to revise, and forcing a
    withdraw-then-resubmit dance would leave the customer looking at a price nobody
    intends to honour.
    """
    job = (
        Job.objects.select_for_update()
        .select_related("service_request", "provider")
        .get(pk=job.pk)
    )

    if job.provider_id != provider.id:
        raise PermissionDenied("Only the assigned provider can quote on this job.")
    if job.status not in {JobStatus.PENDING_ACCEPT, JobStatus.ACTIVE}:
        raise Conflict(f"A job that is '{job.status}' can no longer be quoted on.")

    Quote.objects.filter(job=job, status=QuoteStatus.PENDING).update(
        status=QuoteStatus.SUPERSEDED, responded_at=timezone.now()
    )

    quote = Quote.objects.create(
        job=job,
        amount=_clean_quote_amount(amount),
        currency=settings.PLATFORM_CURRENCY,
        notes=notes,
    )

    audit.record(
        AuditAction.QUOTE_SUBMITTED,
        actor=provider.user,
        target_type="quote",
        target_id=quote.id,
        metadata={
            "job_id": str(job.id),
            "amount": str(quote.amount),
            "currency": quote.currency,
        },
    )
    notifications.notify_quote_submitted(quote)
    return quote


@transaction.atomic
def respond_to_quote(*, quote: Quote, customer, accept: bool) -> Quote:
    """Customer accepts or declines a pending quote."""
    quote = (
        Quote.objects.select_for_update()
        .select_related("job__service_request__customer__user", "job__provider__user")
        .get(pk=quote.pk)
    )

    if quote.job.service_request.customer_id != customer.id:
        raise PermissionDenied("Only the customer on this job can respond to its quotes.")
    if quote.status != QuoteStatus.PENDING:
        raise Conflict(f"This quote is already '{quote.status}'.")

    quote.status = QuoteStatus.ACCEPTED if accept else QuoteStatus.DECLINED
    quote.responded_at = timezone.now()
    quote.save(update_fields=["status", "responded_at"])

    audit.record(
        AuditAction.QUOTE_RESPONDED,
        actor=customer.user,
        target_type="quote",
        target_id=quote.id,
        metadata={"job_id": str(quote.job_id), "response": quote.status},
    )
    notifications.notify_quote_responded(quote)
    return quote


def _clean_quote_amount(value):
    if value is None:
        raise ValidationError({"amount": "An amount is required."})
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValidationError({"amount": "Enter a valid amount."}) from exc
    if amount <= 0:
        raise ValidationError({"amount": "A quote must be greater than zero."})
    if amount > MAX_AMOUNT:
        raise ValidationError({"amount": f"An amount cannot exceed {MAX_AMOUNT}."})
    return amount.quantize(Decimal("0.01"))


def accepted_quote(job: Job) -> Quote | None:
    """The price the customer agreed to, if any.

    Used to surface the gap between what was agreed and what was charged (SPEC-015 REQ-6).
    """
    return job.quotes.filter(status=QuoteStatus.ACCEPTED).order_by("-responded_at").first()
