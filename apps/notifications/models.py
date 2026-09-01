import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class NotificationKind(models.TextChoices):
    """Event catalogue.

    Every value is produced by ``apps.notifications.services.notify``; clients may
    switch on ``kind`` safely. See ``specs/010-notifications.md`` for the payload
    contract attached to each kind.
    """

    REQUEST_ACCEPTED = "request.accepted", _("A provider accepted your request")
    JOB_ACTIVE = "job.active", _("Your provider has started")
    QUOTE_SUBMITTED = "quote.submitted", _("You received a price quote")
    QUOTE_ACCEPTED = "quote.accepted", _("Your quote was accepted")
    QUOTE_DECLINED = "quote.declined", _("Your quote was declined")
    JOB_AWAITING_CONFIRMATION = (
        "job.awaiting_confirmation",
        _("Confirm the work and amount"),
    )
    #: Sent to the *provider* once the customer confirms — the customer performed that
    #: action themselves and learns the outcome from the response (SPEC-015 REQ-9).
    JOB_COMPLETED = "job.completed", _("Job completed")
    JOB_CANCELLED = "job.cancelled", _("Job cancelled")
    JOB_AUTO_CONFIRMED = "job.auto_confirmed", _("Job closed automatically")
    REQUEST_CANCELLED = "request.cancelled", _("Request cancelled")
    REQUEST_EXPIRED = "request.expired", _("Request expired")
    REVIEW_RECEIVED = "review.received", _("You received a review")
    AGENCY_INVITED = "agency.invited", _("You were invited to an agency")
    AGENCY_INVITATION_ANSWERED = "agency.invitation_answered", _("An invitation was answered")
    AGENCY_MEMBERSHIP_ENDED = "agency.membership_ended", _("You were removed from an agency")


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(max_length=64, choices=NotificationKind.choices, db_index=True)
    title = models.CharField(max_length=255, blank=True)
    body = models.TextField(max_length=2000, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # ``id`` breaks ties: several notifications can share a timestamp (one job
        # transition can emit more than one), and an unstable sort duplicates or drops
        # rows across paginated requests.
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.kind} → {self.user}"
