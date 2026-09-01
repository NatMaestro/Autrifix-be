"""Provider verification workflow — SPEC-013.

Submission and review both go through here, so the level change, the document purge, and
the audit entry can never drift apart.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import audit
from apps.core.exceptions import Conflict
from apps.core.models import AuditAction
from apps.providers.models import ProviderVerification
from apps.providers.verification import (
    VerificationLevel,
    VerificationStatus,
    level_at_least,
    missing_profile_requirements,
)

logger = logging.getLogger(__name__)


@transaction.atomic
def submit_verification(*, provider, documents: dict) -> ProviderVerification:
    """Open a verification submission for review."""
    if ProviderVerification.objects.filter(
        provider=provider, status=VerificationStatus.PENDING
    ).exists():
        raise Conflict("You already have a verification submission awaiting review.")

    try:
        submission = ProviderVerification.objects.create(
            provider=provider,
            requested_level=VerificationLevel.DOCUMENTS,
            **documents,
        )
    except IntegrityError as exc:  # lost race against the partial unique constraint
        raise Conflict("You already have a verification submission awaiting review.") from exc

    audit.record(
        AuditAction.VERIFICATION_SUBMITTED,
        actor=provider.user,
        target_type="provider_verification",
        target_id=submission.id,
        metadata={
            "provider_id": str(provider.id),
            "requested_level": submission.requested_level,
            "profile_gaps": missing_profile_requirements(provider),
        },
    )
    logger.info("verification.submitted provider=%s", provider.id)
    return submission


@transaction.atomic
def review_verification(
    *,
    submission: ProviderVerification,
    approve: bool,
    reviewer=None,
    notes: str = "",
) -> ProviderVerification:
    """Approve or reject a submission.

    Approval raises the provider's level; rejection leaves it untouched — a refusal must
    never *lower* a level already granted. Documents are purged either way (REQ-8).
    """
    if submission.status != VerificationStatus.PENDING:
        raise Conflict(f"This submission is already {submission.status}.")

    provider = submission.provider
    granted_level = None

    if approve:
        # Never downgrade: a provider already at a higher level keeps it.
        if not level_at_least(provider.verification_level, submission.requested_level):
            provider.verification_level = submission.requested_level
            provider.save(update_fields=["verification_level", "updated_at"])
        granted_level = provider.verification_level

    submission.status = VerificationStatus.APPROVED if approve else VerificationStatus.REJECTED
    submission.reviewed_at = timezone.now()
    submission.reviewed_by = reviewer
    submission.review_notes = notes or ""
    submission.purge_documents()
    submission.save()

    audit.record(
        AuditAction.VERIFICATION_REVIEWED,
        actor=reviewer,
        target_type="provider_verification",
        target_id=submission.id,
        metadata={
            "provider_id": str(provider.id),
            "outcome": submission.status,
            "granted_level": granted_level,
            "notes": (notes or "")[:500],
        },
    )
    logger.info(
        "verification.reviewed provider=%s outcome=%s", provider.id, submission.status
    )
    return submission
