import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class MechanicProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mechanic_profile",
    )
    business_name = models.CharField(max_length=200)
    bio = models.TextField(blank=True)
    base_latitude = models.FloatField(null=True, blank=True)
    base_longitude = models.FloatField(null=True, blank=True)
    service_radius_km = models.PositiveIntegerField(default=25)
    is_available = models.BooleanField(default=False, db_index=True)
    rating_avg = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
    )
    rating_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-rating_avg", "-created_at"]
        indexes = [
            models.Index(fields=["is_available"]),
        ]

    def __str__(self):
        return self.business_name


class MechanicServiceOffering(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mechanic = models.ForeignKey(
        MechanicProfile,
        on_delete=models.CASCADE,
        related_name="service_offerings",
    )
    category = models.ForeignKey(
        "jobs.ServiceCategory",
        on_delete=models.PROTECT,
        related_name="mechanic_offerings",
    )
    title = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("mechanic", "category", "title")
        indexes = [
            models.Index(fields=["mechanic", "is_active"]),
        ]

    def __str__(self):
        return self.title or self.category.name
