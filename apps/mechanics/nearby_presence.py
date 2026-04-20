"""Shared logic for nearby mechanic previews (HTTP + WebSocket)."""

from __future__ import annotations

import math

from apps.core.geo import distance_meters
from apps.mechanics.models import MechanicProfile


def list_nearby_mechanic_previews(lat: float, lng: float, radius_km: float = 25) -> list[dict]:
    """
    Return mechanics with coordinates within ``radius_km`` of ``lat``/``lng``.
    Each dict matches the shape used by ``ServicesNearbyView`` / driver map.
    """
    radius_m = radius_km * 1000
    lat_pad = radius_km / 111.0
    lng_pad = radius_km / max(111.0 * math.cos(math.radians(lat)), 0.01)

    qs = MechanicProfile.objects.filter(
        is_available=True,
        base_latitude__isnull=False,
        base_longitude__isnull=False,
    ).filter(
        base_latitude__gte=lat - lat_pad,
        base_latitude__lte=lat + lat_pad,
        base_longitude__gte=lng - lng_pad,
        base_longitude__lte=lng + lng_pad,
    )
    nearby: list[dict] = []
    for m in qs:
        d_m = distance_meters(lat, lng, m.base_latitude, m.base_longitude)
        if d_m <= radius_m:
            nearby.append(
                {
                    "id": str(m.id),
                    "business_name": m.business_name,
                    "latitude": float(m.base_latitude),
                    "longitude": float(m.base_longitude),
                    "rating_avg": float(m.rating_avg or 0),
                    "rating_count": int(m.rating_count or 0),
                    "distance_km": round(d_m / 1000.0, 2),
                }
            )
    nearby.sort(key=lambda item: item["distance_km"])
    return nearby[:50]


def mechanic_preview_from_instance(m: MechanicProfile) -> dict:
    """Minimal mechanic payload for presence broadcasts (client filters by radius)."""
    lat = m.base_latitude
    lng = m.base_longitude
    return {
        "id": str(m.id),
        "business_name": m.business_name,
        "latitude": float(lat) if lat is not None else None,
        "longitude": float(lng) if lng is not None else None,
        "is_available": bool(m.is_available),
        "rating_avg": float(m.rating_avg or 0),
        "rating_count": int(m.rating_count or 0),
    }
