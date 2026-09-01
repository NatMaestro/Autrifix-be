import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditAction(models.TextChoices):
    """Auditable actions.

    Deliberately narrow: state changes and authentication failures only. Reads are not
    audited — they are orders of magnitude more voluminous and rarely answer a question
    that request logs cannot. See ``docs/DECISIONS.md`` ADR-016.
    """

    JOB_ACCEPTED = "job.accepted", _("Job accepted")
    JOB_TRANSITIONED = "job.transitioned", _("Job status changed")
    REQUEST_CANCELLED = "request.cancelled", _("Service request cancelled")
    QUOTE_SUBMITTED = "quote.submitted", _("Quote submitted")
    QUOTE_RESPONDED = "quote.responded", _("Quote accepted or declined")
    #: Written by the sweep with no actor. Kept distinct from `job.transitioned` so a
    #: dispute can tell a customer's confirmation from the platform's timeout.
    JOB_AUTO_CONFIRMED = "job.auto_confirmed", _("Job auto-confirmed after timeout")
    REQUEST_EXPIRED = "request.expired", _("Service request expired unclaimed")
    LOGIN_FAILED = "auth.login_failed", _("Failed login attempt")
    VERIFICATION_SUBMITTED = "provider.verification_submitted", _("Verification submitted")
    VERIFICATION_REVIEWED = "provider.verification_reviewed", _("Verification reviewed")
    AGENCY_CREATED = "agency.created", _("Agency created")
    AGENCY_MEMBER_INVITED = "agency.member_invited", _("Agency member invited")
    #: Joined, declined, left, removed, or re-roled. Membership changes a provider's
    #: *effective verification level* (SPEC-014 REQ-7), so each one is worth a row.
    AGENCY_MEMBERSHIP_CHANGED = "agency.membership_changed", _("Agency membership changed")


class AuditEvent(models.Model):
    """An append-only record of a security- or dispute-relevant action.

    **Never cascade-delete an audit row.** Every other foreign key in this codebase uses
    ``CASCADE``; a trail that disappears when a provider deletes their profile is worthless
    precisely when it is needed. ``actor`` is therefore ``SET_NULL`` and ``actor_label``
    denormalises who it was, so the row survives the actor.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.CharField(max_length=64, choices=AuditAction.choices, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    #: Who the actor was, captured at write time so the row outlives the account.
    actor_label = models.CharField(max_length=255, blank=True)
    #: Free-form type name ("job", "service_request", "user") — no content type, so a
    #: deleted model class cannot orphan the row.
    target_type = models.CharField(max_length=64, blank=True, db_index=True)
    target_id = models.CharField(max_length=64, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["target_type", "target_id", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]
        verbose_name = _("audit event")
        verbose_name_plural = _("audit events")

    def __str__(self):
        return f"{self.action} by {self.actor_label or 'system'} at {self.created_at:%Y-%m-%d %H:%M}"
