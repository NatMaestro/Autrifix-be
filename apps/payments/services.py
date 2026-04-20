"""
Escrow hooks — integrate Stripe Connect / PaymentIntents here.
"""


def hold_payment_for_job(job, amount_cents: int, currency: str = "USD"):
    """Create provider-side hold; return Payment instance (stub)."""
    from apps.payments.models import EscrowStatus, Payment

    payment, _ = Payment.objects.update_or_create(
        job=job,
        defaults={
            "amount_cents": amount_cents,
            "currency": currency,
            "escrow_status": EscrowStatus.HELD,
            "metadata": {"stub": True},
        },
    )
    return payment


def release_to_mechanic(payment) -> None:
    from apps.payments.models import EscrowStatus

    payment.escrow_status = EscrowStatus.RELEASED
    payment.save(update_fields=["escrow_status", "updated_at"])
