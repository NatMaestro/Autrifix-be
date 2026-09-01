"""Geodesic distance (WGS84) — no GDAL/PostGIS required; maps stay on the client."""

from __future__ import annotations

import math

from geopy.distance import geodesic

#: Kilometres per degree of latitude. Duplicated historically in two view modules; this is
#: the canonical definition.
KM_PER_DEGREE_LAT = 111.0

#: Grid size used to coarsen a location for a caller not entitled to the exact point.
DEFAULT_COARSEN_GRID_KM = 1.0


def distance_meters(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return great-circle distance in meters between two WGS84 points."""
    return float(geodesic((lat1, lon1), (lat2, lon2)).meters)


def coarsen_coordinate(
    lat: float,
    lng: float,
    *,
    grid_km: float = DEFAULT_COARSEN_GRID_KM,
) -> tuple[float, float]:
    """Snap a point to a grid of roughly ``grid_km`` squares.

    Used to blunt location disclosure to callers who are not entitled to the exact point
    (``specs/013-provider-verification.md`` REQ-2).

    **Everything shown to such a caller must be derived from the snapped point, including
    distance.** A caller controls the coordinate they search from, so an exact distance
    published alongside a coarsened point would let the true point be recovered by
    trilateration from three queries.

    The longitude step is scaled by ``cos(latitude)`` so cells stay roughly square rather
    than stretching towards the equator.
    """
    lat_step = grid_km / KM_PER_DEGREE_LAT
    lng_step = grid_km / max(KM_PER_DEGREE_LAT * math.cos(math.radians(lat)), 0.01)

    snapped_lat = round(lat / lat_step) * lat_step
    snapped_lng = round(lng / lng_step) * lng_step
    # Round to a sane number of decimals so the value does not advertise its own grid via
    # floating-point noise.
    return round(snapped_lat, 6), round(snapped_lng, 6)
