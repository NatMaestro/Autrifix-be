import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class ServiceCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, max_length=140)
    description = models.TextField(blank=True)
    keywords = models.TextField(
        blank=True,
        help_text="Comma-separated synonyms used by the issue router (e.g. battery,jump start,alternator).",
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


class JobStatus(models.TextChoices):
    PENDING_ACCEPT = "pending_accept", _("Pending accept")
    ACTIVE = "active", _("Active")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class ServiceRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(
        "drivers.DriverProfile",
        on_delete=models.CASCADE,
        related_name="service_requests",
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="requests",
    )
    description = models.TextField()
    latitude = models.FloatField()
    longitude = models.FloatField()
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
    mechanic = models.ForeignKey(
        "mechanics.MechanicProfile",
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    status = models.CharField(
        max_length=20,
        choices=JobStatus.choices,
        default=JobStatus.PENDING_ACCEPT,
        db_index=True,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Job {self.id}"
