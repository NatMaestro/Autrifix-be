import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.validators import latitude_validators, longitude_validators


class ServiceCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, max_length=140)
    description = models.TextField(blank=True)
    keywords = models.TextField(
        blank=True,
        help_text="Comma-separated synonyms used by the issue router (e.g. battery,jump start,alternator).",
    )
    requires_destination = models.BooleanField(
        default=False,
        help_text=(
            "This service relocates the vehicle, so a request must say where to. "
            "Implies the job needs a tow-capable provider (SPEC-014 REQ-3)."
        ),
    )
    default_radius_km = models.PositiveSmallIntegerField(default=25)
    priority = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority", "name"]
        verbose_name_plural = "service categories"

    def __str__(self):
        return self.name


class ServiceRequestStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    OPEN = "open", _("Open")
    MATCHING = "matching", _("Matching")
    ASSIGNED = "assigned", _("Assigned")
    CANCELLED = "cancelled", _("Cancelled")
    COMPLETED = "completed", _("Completed")
    #: Retired by the sweep because no provider ever claimed it. Distinct from `cancelled`,
    #: which is somebody's decision — conflating the two would lose the difference between
    #: "the customer changed their mind" and "the platform found nobody" (SPEC-016 REQ-3).
    EXPIRED = "expired", _("Expired")


class JobStatus(models.TextChoices):
    PENDING_ACCEPT = "pending_accept", _("Pending accept")
    ACTIVE = "active", _("Active")
    #: Work is finished and an amount recorded; waiting on the customer to agree.
    AWAITING_CONFIRMATION = "awaiting_confirmation", _("Awaiting customer confirmation")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")

    @classmethod
    def terminal(cls) -> set[str]:
        """States a job can never leave."""
        return {cls.COMPLETED, cls.CANCELLED}


class QuoteStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    ACCEPTED = "accepted", _("Accepted")
    DECLINED = "declined", _("Declined")
    #: Withdrawn because the provider issued a revised quote.
    SUPERSEDED = "superseded", _("Superseded")


#: Request states from which a customer may still cancel.
CANCELLABLE_REQUEST_STATUSES = frozenset(
    {ServiceRequestStatus.OPEN, ServiceRequestStatus.MATCHING, ServiceRequestStatus.ASSIGNED}
)


class ServiceRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        "drivers.CustomerProfile",
        on_delete=models.CASCADE,
        related_name="service_requests",
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="requests",
    )
    description = models.TextField(max_length=2000)
    latitude = models.FloatField(validators=latitude_validators)
    longitude = models.FloatField(validators=longitude_validators)
    #: Where the vehicle should end up. Required only for categories with
    #: ``requires_destination`` — a repair happens where the vehicle already is.
    destination_latitude = models.FloatField(
        null=True, blank=True, validators=latitude_validators
    )
    destination_longitude = models.FloatField(
        null=True, blank=True, validators=longitude_validators
    )
    status = models.CharField(
        max_length=20,
        choices=ServiceRequestStatus.choices,
        default=ServiceRequestStatus.OPEN,
        db_index=True,
    )
    preferred_vehicle = models.ForeignKey(
        "drivers.Vehicle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"Request {self.id} ({self.status})"


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    provider = models.ForeignKey(
        "mechanics.ProviderProfile",
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    status = models.CharField(
        max_length=25,
        choices=JobStatus.choices,
        default=JobStatus.PENDING_ACCEPT,
        db_index=True,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    #: When the provider finished and recorded an amount.
    work_finished_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    #: What the customer is actually asked to agree to. Recorded, never charged —
    #: settlement happens in cash between the two parties (ADR-022).
    final_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField(max_length=3, blank=True)
    #: True when the sweep closed this job because the customer never answered. A review or
    #: dispute must be able to tell agreement from silence (SPEC-016 REQ-2).
    auto_confirmed = models.BooleanField(default=False)
    notes = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # A request may accumulate several jobs over time (a provider declines, another
            # accepts), but only one may be live at once. This is what makes concurrent
            # acceptance safe at the database level rather than by timing.
            models.UniqueConstraint(
                fields=["service_request"],
                condition=~models.Q(status=JobStatus.CANCELLED),
                name="unique_live_job_per_service_request",
            ),
        ]

    def __str__(self):
        return f"Job {self.id}"

    @property
    def is_terminal(self) -> bool:
        return self.status in JobStatus.terminal()


class Quote(models.Model):
    """A provider's price proposal for a job, before the work is done.

    Quoting is *optional*: a tow price is computable up front from distance, and a trivial
    repair may not warrant the round trip. What a quote buys is a price the customer agreed
    to in writing before anyone opened the bonnet — so when one exists, the amount recorded
    at completion is checked against it and any gap is shown to the customer (SPEC-015 REQ-6).

    A provider may revise: submitting a new quote supersedes the outstanding one. Only one
    may be ``pending`` at a time, by partial unique constraint.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="quotes")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    #: What the money is for. The customer is agreeing to this text as much as the number.
    notes = models.TextField(max_length=2000, blank=True)
    status = models.CharField(
        max_length=12,
        choices=QuoteStatus.choices,
        default=QuoteStatus.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    #: When the customer accepted or declined.
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job"],
                condition=models.Q(status=QuoteStatus.PENDING),
                name="unique_pending_quote_per_job",
            ),
        ]

    def __str__(self):
        return f"Quote {self.amount} {self.currency} on job {self.job_id}"
