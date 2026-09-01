"""Shared field validators and query-parameter parsing.

Coordinate bounds and upload limits were previously unenforced anywhere in the
codebase (see ``specs/008-location.md`` REQ-6). Keep the limits here so models,
serializers, and query parameters all agree.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

LATITUDE_MIN = -90.0
LATITUDE_MAX = 90.0
LONGITUDE_MIN = -180.0
LONGITUDE_MAX = 180.0

#: Largest accepted search radius, in kilometres.
MAX_RADIUS_KM = 500.0

#: Largest accepted image upload, in bytes.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

latitude_validators = [MinValueValidator(LATITUDE_MIN), MaxValueValidator(LATITUDE_MAX)]
longitude_validators = [MinValueValidator(LONGITUDE_MIN), MaxValueValidator(LONGITUDE_MAX)]


def validate_image_size(value) -> None:
    """Reject uploads larger than :data:`MAX_IMAGE_BYTES`."""
    size = getattr(value, "size", None)
    if size is not None and size > MAX_IMAGE_BYTES:
        raise DjangoValidationError(
            _("Image must be %(limit)s MB or smaller."),
            params={"limit": MAX_IMAGE_BYTES // (1024 * 1024)},
            code="image_too_large",
        )


def parse_coordinate_params(query_params, *, required: bool = True, default_radius_km: float = 50.0):
    """Parse and validate ``lat`` / ``lng`` / ``radius_km`` from a query string.

    Returns ``(lat, lng, radius_km)``. Raises DRF ``ValidationError`` (HTTP 400) on
    anything missing, non-numeric, or out of range — previously these produced either
    a silent ``0`` default or an unhandled ``500``.
    """
    errors: dict[str, list[str]] = {}

    def _number(name: str):
        raw = query_params.get(name)
        if raw in (None, ""):
            if required:
                errors[name] = ["This query parameter is required."]
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            errors[name] = ["Must be a number."]
            return None

    lat = _number("lat")
    lng = _number("lng")

    if lat is not None and not (LATITUDE_MIN <= lat <= LATITUDE_MAX):
        errors["lat"] = [f"Must be between {LATITUDE_MIN} and {LATITUDE_MAX}."]
    if lng is not None and not (LONGITUDE_MIN <= lng <= LONGITUDE_MAX):
        errors["lng"] = [f"Must be between {LONGITUDE_MIN} and {LONGITUDE_MAX}."]

    raw_radius = query_params.get("radius_km")
    radius_km = default_radius_km
    if raw_radius not in (None, ""):
        try:
            radius_km = float(raw_radius)
        except (TypeError, ValueError):
            errors["radius_km"] = ["Must be a number."]
        else:
            if not (0 < radius_km <= MAX_RADIUS_KM):
                errors["radius_km"] = [f"Must be greater than 0 and at most {MAX_RADIUS_KM}."]

    if errors:
        raise ValidationError(errors)

    return lat, lng, radius_km


def clamp_radius_km(raw, *, default: float = 25.0) -> float:
    """Best-effort radius for transports that cannot return a 400 (WebSocket frames)."""
    try:
        radius = float(raw)
    except (TypeError, ValueError):
        return default
    if not (0 < radius <= MAX_RADIUS_KM):
        return default
    return radius
