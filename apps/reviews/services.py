"""Rating aggregation.

``ProviderProfile.rating_avg`` / ``rating_count`` are denormalised: they are read on
every discovery payload and presence broadcast, so recomputing them per read would be
expensive. Before this module nothing wrote them at all and every provider showed
``0.00 (0)`` forever (``specs/011-ratings-reviews.md`` CONFLICT-011-A).
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Avg, Count

from apps.providers.models import ProviderProfile
from apps.reviews.models import Review


def recalculate_provider_rating(provider_id) -> None:
    """Recompute the cached rating summary for one provider.

    Uses ``queryset.update`` so the write does not re-fire the ``ProviderProfile``
    ``post_save`` presence broadcast for every review.
    """
    if provider_id is None:
        return

    aggregate = Review.objects.filter(job__provider_id=provider_id).aggregate(
        average=Avg("rating"),
        total=Count("id"),
    )
    average = aggregate["average"] or 0
    ProviderProfile.objects.filter(pk=provider_id).update(
        rating_avg=Decimal(average).quantize(Decimal("0.01")),
        rating_count=aggregate["total"] or 0,
    )
