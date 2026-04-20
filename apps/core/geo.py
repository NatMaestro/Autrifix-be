"""Geodesic distance (WGS84) — no GDAL/PostGIS required; maps stay on the client."""

from __future__ import annotations

from geopy.distance import geodesic


def distance_meters(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return great-circle distance in meters between two WGS84 points."""
    return float(geodesic((lat1, lon1), (lat2, lon2)).meters)
