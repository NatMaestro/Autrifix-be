import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class EscrowStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    HELD = "held", _("Held")
    RELEASED = "released", _("Released to mechanic")
    REFUNDED = "refunded", _("Refunded to driver")
    FAILED = "failed", _("Failed")


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        "jobs.Job",
        on_delete=models.CASCADE,
        related_name="payment",
    )
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    escrow_status = models.CharField(
        max_length=20,
        choices=EscrowStatus.choices,
        default=EscrowStatus.PENDING,
        db_index=True,
    )
    provider = models.CharField(max_length=32, default="stripe", blank=True)
    external_intent_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.id} ({self.escrow_status})"
