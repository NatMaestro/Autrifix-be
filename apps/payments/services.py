"""Escrow hooks — **stubs with no caller**.

These are kept as a shape to fill in, not as working code. The platform does not move
money: a provider records an amount, the customer confirms it, and the two settle in cash
(ADR-022). Whether Autrifix ever takes a cut, and how, is deliberately unanswered until
there is real price data to answer it with — see ``specs/015-money-model.md`` OQ-015-B.

Do not wire these up without first choosing a rail. The previous version of this file
assumed Stripe, which does not serve the launch market.
"""

from decimal import Decimal


def to_minor_units(amount: Decimal) -> int:
    """Convert a decimal amount to whole minor units (pesewas for GHS).

    Money is stored as an integer count of the smallest unit everywhere it is *moved*,
    even though ``Job.final_amount`` is a ``Decimal`` — the decimal is a human-facing
    record, this is what a processor would be handed.
    """
    return int((Decimal(amount) * 100).to_integral_value())


def hold_payment_for_job(job, amount: Decimal, currency: str | None = None):
    """Create a provider-side hold. **Stub** — records intent, moves nothing."""
    from django.conf import settings

    from apps.payments.models import EscrowStatus, Payment

    payment, _ = Payment.objects.update_or_create(
        job=job,
        defaults={
            "amount_minor": to_minor_units(amount),
            "currency": currency or settings.PLATFORM_CURRENCY,
            "escrow_status": EscrowStatus.HELD,
            "metadata": {"stub": True},
        },
    )
    return payment


def release_to_provider(payment) -> None:
    """**Stub** — flips a status; no funds are transferred."""
    from apps.payments.models import EscrowStatus

    payment.escrow_status = EscrowStatus.RELEASED
    payment.save(update_fields=["escrow_status", "updated_at"])
