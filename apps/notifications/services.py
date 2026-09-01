"""Notification production.

Every notification in the system is created here. Rows are persisted for the pull API
(``GET /notifications/``) and pushed to the recipient's personal Channels group so a
connected client sees them without polling.

Delivery is best-effort: a channel-layer failure must never roll back or fail the
domain operation that triggered the notification.
"""

from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from apps.notifications.models import Notification, NotificationKind

logger = logging.getLogger(__name__)


def user_group_name(user_id) -> str:
    """Channels group carrying one user's notifications."""
    return f"user_{user_id}"


def _broadcast(notification: Notification) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    payload = {
        "kind": "notification",
        "data": {
            "id": str(notification.id),
            "kind": notification.kind,
            "title": notification.title,
            "body": notification.body,
            "payload": notification.payload,
            "read_at": None,
            "created_at": notification.created_at.isoformat(),
        },
    }
    try:
        async_to_sync(layer.group_send)(
            user_group_name(notification.user_id),
            {"type": "notification.message", "message": payload},
        )
    except Exception:  # pragma: no cover - transport failure must not break the caller
        logger.exception("notification broadcast failed for %s", notification.id)


def notify(user, *, kind: str, title: str, body: str = "", payload: dict | None = None) -> Notification:
    """Create a notification for ``user`` and push it to their live clients.

    The broadcast is deferred until the surrounding transaction commits, so a client
    can never be told about a state change that then rolls back.
    """
    notification = Notification.objects.create(
        user=user,
        kind=kind,
        title=title,
        body=body,
        payload=payload or {},
    )
    transaction.on_commit(lambda: _broadcast(notification))
    logger.info("notification.created kind=%s user=%s", kind, user.pk)
    return notification


def job_payload(job) -> dict:
    """Correlation ids attached to every job-related notification.

    ``Notification`` has no foreign key to its subject, so this is the contract clients
    use to navigate from a notification to the thing it is about.
    """
    return {
        "job_id": str(job.id),
        "service_request_id": str(job.service_request_id),
    }


def quote_payload(quote) -> dict:
    return {
        "quote_id": str(quote.id),
        "amount": str(quote.amount),
        "currency": quote.currency,
        "quote_status": quote.status,
    }


def notify_request_accepted(job) -> None:
    notify(
        job.service_request.customer.user,
        kind=NotificationKind.REQUEST_ACCEPTED,
        title="A provider accepted your request",
        body=f"{job.provider.business_name} is reviewing your request.",
        payload=job_payload(job),
    )


def notify_job_active(job) -> None:
    notify(
        job.service_request.customer.user,
        kind=NotificationKind.JOB_ACTIVE,
        title="Your provider has started",
        body=f"{job.provider.business_name} has started work on your request.",
        payload=job_payload(job),
    )


def notify_quote_submitted(quote) -> None:
    job = quote.job
    notify(
        job.service_request.customer.user,
        kind=NotificationKind.QUOTE_SUBMITTED,
        title="You received a price quote",
        body=(
            f"{job.provider.business_name} quoted "
            f"{quote.currency} {quote.amount} for this job."
        ),
        payload={**job_payload(job), **quote_payload(quote)},
    )


def notify_quote_responded(quote) -> None:
    """Tell the provider how the customer answered."""
    from apps.jobs.models import QuoteStatus

    job = quote.job
    accepted = quote.status == QuoteStatus.ACCEPTED
    notify(
        job.provider.user,
        kind=(
            NotificationKind.QUOTE_ACCEPTED if accepted else NotificationKind.QUOTE_DECLINED
        ),
        title="Quote accepted" if accepted else "Quote declined",
        body=(
            f"The customer accepted your quote of {quote.currency} {quote.amount}."
            if accepted
            else "The customer declined your quote. You can submit a revised one."
        ),
        payload={**job_payload(job), **quote_payload(quote)},
    )


def notify_job_awaiting_confirmation(job) -> None:
    """Ask the customer to agree to the amount the provider recorded."""
    notify(
        job.service_request.customer.user,
        kind=NotificationKind.JOB_AWAITING_CONFIRMATION,
        title="Confirm the work and amount",
        body=(
            f"{job.provider.business_name} finished and recorded "
            f"{job.currency} {job.final_amount}. Confirm to close the job."
        ),
        payload={
            **job_payload(job),
            "final_amount": str(job.final_amount),
            "currency": job.currency,
        },
    )


def notify_job_completed(job) -> None:
    """Sent to the provider: the customer agreed and the job is closed."""
    notify(
        job.provider.user,
        kind=NotificationKind.JOB_COMPLETED,
        title="Job completed",
        body=(
            f"The customer confirmed the work and {job.currency} {job.final_amount}. "
            "Collect payment directly from the customer."
        ),
        payload={
            **job_payload(job),
            "final_amount": str(job.final_amount),
            "currency": job.currency,
        },
    )


def notify_job_cancelled(job, *, cancelled_by_role: str) -> None:
    """Tell the counterparty — never the actor — that the job was cancelled."""
    from apps.accounts.models import UserRole

    if cancelled_by_role == UserRole.PROVIDER:
        recipient = job.service_request.customer.user
        body = f"{job.provider.business_name} cancelled this job."
    else:
        recipient = job.provider.user
        body = "The customer cancelled this job."
    notify(
        recipient,
        kind=NotificationKind.JOB_CANCELLED,
        title="Job cancelled",
        body=body,
        payload=job_payload(job),
    )


def notify_job_auto_confirmed(job) -> None:
    """Tell the customer their silence closed the job.

    Sent *because* they did not act. Saying so plainly is the point — an amount that became
    binding by timeout should never be a surprise discovered later.
    """
    notify(
        job.service_request.customer.user,
        kind=NotificationKind.JOB_AUTO_CONFIRMED,
        title="Job closed automatically",
        body=(
            f"You did not confirm {job.currency} {job.final_amount} for this job, so it was "
            "closed automatically. Contact support if the amount is wrong."
        ),
        payload={
            **job_payload(job),
            "final_amount": str(job.final_amount),
            "currency": job.currency,
            "auto_confirmed": True,
        },
    )


def notify_request_expired(service_request) -> None:
    """Tell the customer nobody took the job, rather than leaving them waiting."""
    notify(
        service_request.customer.user,
        kind=NotificationKind.REQUEST_EXPIRED,
        title="Request expired",
        body="No provider accepted your request in time. You can create a new one.",
        payload={"service_request_id": str(service_request.id)},
    )


def notify_request_cancelled(service_request, provider_user) -> None:
    notify(
        provider_user,
        kind=NotificationKind.REQUEST_CANCELLED,
        title="Request cancelled",
        body="The customer cancelled this request.",
        payload={"service_request_id": str(service_request.id)},
    )


def notify_review_received(review) -> None:
    notify(
        review.job.provider.user,
        kind=NotificationKind.REVIEW_RECEIVED,
        title="You received a review",
        body=f"You were rated {review.rating} out of 5.",
        payload={
            "job_id": str(review.job_id),
            "review_id": str(review.id),
            "rating": review.rating,
        },
    )


# --- agencies -----------------------------------------------------------------------


def _agency_payload(membership) -> dict:
    return {
        "membership_id": str(membership.id),
        "agency_id": str(membership.agency_id),
        "agency_name": membership.agency.name,
        "role": membership.role,
        "membership_status": membership.status,
    }


def notify_agency_invitation(membership) -> None:
    notify(
        membership.provider.user,
        kind=NotificationKind.AGENCY_INVITED,
        title="You were invited to an agency",
        body=(
            f"{membership.agency.name} invited you to join as {membership.get_role_display().lower()}."
        ),
        payload=_agency_payload(membership),
    )


def notify_agency_invitation_answered(membership, *, accepted: bool) -> None:
    """Tell the agency's owners how the invitation was answered.

    Sent to owners rather than the inviting manager: the invite may be answered days later,
    and the person who sent it may no longer be the one who needs to know.
    """
    from apps.providers.agencies import AgencyRole, MembershipStatus

    owners = membership.agency.memberships.filter(
        status=MembershipStatus.ACTIVE, role=AgencyRole.OWNER
    ).select_related("provider__user")

    name = membership.provider.business_name or "A provider"
    for owner in owners:
        notify(
            owner.provider.user,
            kind=NotificationKind.AGENCY_INVITATION_ANSWERED,
            title="Agency invitation answered",
            body=f"{name} {'joined' if accepted else 'declined to join'} {membership.agency.name}.",
            payload={**_agency_payload(membership), "accepted": accepted},
        )


def notify_agency_membership_ended(membership) -> None:
    """A removal can lower the provider's effective verification level, so say so."""
    notify(
        membership.provider.user,
        kind=NotificationKind.AGENCY_MEMBERSHIP_ENDED,
        title="You were removed from an agency",
        body=(
            f"You are no longer a member of {membership.agency.name}. Any verification "
            "level inherited from the agency no longer applies."
        ),
        payload=_agency_payload(membership),
    )
