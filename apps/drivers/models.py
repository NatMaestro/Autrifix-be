import uuid

from django.conf import settings
from django.db import models


class DriverProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="driver_profile",
    )
    display_name = models.CharField(max_length=120, blank=True)
    home_latitude = models.FloatField(null=True, blank=True)
    home_longitude = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Driver({self.user.email})"


class Vehicle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(
        DriverProfile,
        on_delete=models.CASCADE,
        related_name="vehicles",
    )
    label = models.CharField(max_length=120, blank=True)
    make = models.CharField(max_length=80)
    model = models.CharField(max_length=80)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    trim = models.CharField(max_length=120, blank=True)
    color = models.CharField(max_length=64, blank=True)
    engine = models.CharField(max_length=120, blank=True)
    license_plate = models.CharField(max_length=32, blank=True)
    vin = models.CharField(max_length=32, blank=True)
    tire_size = models.CharField(max_length=64, blank=True)
    battery_group = models.CharField(max_length=64, blank=True)
    belt_part_number = models.CharField(max_length=64, blank=True)
    oil_spec = models.CharField(max_length=64, blank=True)
    coolant_type = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    extra = models.JSONField(default=dict, blank=True)
    is_primary = models.BooleanField(default=False)
    photo = models.ImageField(upload_to="vehicles/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.make} {self.model}"
