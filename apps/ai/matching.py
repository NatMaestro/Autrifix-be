"""
Matching optimization hooks — extend with ML / OR-Tools / distance + rating blend.
"""
from apps.core.geo import distance_meters
from apps.jobs.models import ServiceRequest
from apps.mechanics.models import MechanicProfile


def score_mechanics_for_request(sr: ServiceRequest, limit: int = 20) -> list[dict]:
    """Return list of { mechanic_id, score, distance_m } for nearby available mechanics."""
    if sr.latitude is None or sr.longitude is None:
        return []
    mechanics = MechanicProfile.objects.filter(
        is_available=True,
        base_latitude__isnull=False,
        base_longitude__isnull=False,
    )
    out: list[dict] = []
    for m in mechanics:
        dist_m = distance_meters(sr.latitude, sr.longitude, m.base_latitude, m.base_longitude)
        score = max(0.0, 1.0 - (dist_m / 50000.0)) * 0.7 + float(m.rating_avg or 0) / 5.0 * 0.3
        out.append(
            {
                "mechanic_id": str(m.id),
                "business_name": m.business_name,
                "score": round(score, 4),
                "distance_m": round(dist_m, 1),
            }
        )
    out.sort(key=lambda x: x["distance_m"])
    return out[:limit]
