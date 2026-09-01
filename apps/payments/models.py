"""Payment scaffolding — **not a live capability**.

Nothing in the running system writes a ``Payment``. Money in Autrifix today is *recorded*
on the job and settled in cash directly between customer and provider (ADR-022); this
module is the placeholder for the day the platform moves money itself.

Two market assumptions were baked into this stub before the launch market was settled, and
both were wrong: ``USD`` and ``stripe``. They are corrected here rather than left to be
copied by the first real integration. See ``specs/015-money-model.md`` OQ-015-A.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


def default_currency() -> str:
    """Callable, not a literal, so the platform currency has exactly one definition."""
    return settings.PLATFORM_CURRENCY


class EscrowStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    HELD = "held", _("Held")
    RELEASED = "released", _("Released to provider")
    REFUNDED = "refunded", _("Refunded to customer")
    FAILED = "failed", _("Failed")


class PaymentRail(models.TextChoices):
    """How the money would actually move.

    **Undecided.** Ghana is mobile-money-first — MTN MoMo dominant, with Telecel and
    AirtelTigo behind it — and the aggregators that front those rails (Hubtel, Paystack,
    Flutterwave, expressPay) are a different integration from a card processor. Card
    penetration is low enough that a card-only rail would exclude most of the market.

    ``UNSET`` is the default on purpose: a row that claims a rail nobody chose is worse
    than one that admits it does not know.
    """

    UNSET = "", _("Undecided")
    MOBILE_MONEY = "mobile_money", _("Mobile money")
    CARD = "card", _("Card")
    BANK_TRANSFER = "bank_transfer", _("Bank transfer")
    CASH = "cash", _("Cash, settled off-platform")


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        "jobs.Job",
        on_delete=models.CASCADE,
        related_name="payment",
    )
    #: Minor units — pesewas for GHS. Integers, because binary floats and money do not mix.
    amount_minor = models.PositiveIntegerField(
        help_text="Amount in minor units (pesewas for GHS)."
    )
    currency = models.CharField(max_length=3, default=default_currency)
    escrow_status = models.CharField(
        max_length=20,
        choices=EscrowStatus.choices,
        default=EscrowStatus.PENDING,
        db_index=True,
    )
    rail = models.CharField(
        max_length=32,
        choices=PaymentRail.choices,
        default=PaymentRail.UNSET,
        blank=True,
    )
    #: Aggregator or PSP identifier, once one is chosen.
    processor = models.CharField(max_length=32, blank=True)
    external_intent_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.id} ({self.escrow_status})"
