"""Towing-specific request behaviour — SPEC-014 REQ-4/REQ-5.

A repair happens where the vehicle already is. A tow has *two* points, so the request
needs a destination — and only a tow-capable provider can serve it.
"""

import pytest
from django.urls import reverse

from apps.jobs.models import ServiceCategory
from apps.providers.verification import ProviderType
from tests.conftest import ACCRA_LAT, ACCRA_LNG, NEARBY_LAT, NEARBY_LNG

pytestmark = pytest.mark.django_db

REQUESTS_URL = reverse("service-requests")


@pytest.fixture
def tow_category(db):
    category, _ = ServiceCategory.objects.get_or_create(
        slug="tow-recovery", defaults={"name": "Towing / Recovery", "is_active": True}
    )
    category.requires_destination = True
    category.is_active = True
    category.save(update_fields=["requires_destination", "is_active"])
    return category


def body(category, **extra):
    payload = {
        "category": str(category.id),
        "description": "Collision on the Tema motorway",
        "latitude": ACCRA_LAT,
        "longitude": ACCRA_LNG,
    }
    payload.update(extra)
    return payload


# --- the category flag ---------------------------------------------------------------


def test_seeded_tow_category_requires_a_destination(tow_category):
    assert tow_category.requires_destination is True


def test_repair_categories_do_not(category):
    assert category.requires_destination is False


def test_flag_is_exposed_on_the_category_payload(as_user, customer_user, tow_category):
    response = as_user(customer_user).get(reverse("service-categories"))
    # The mini serializer stays lean; the flag rides on the nested category of a request.
    assert response.status_code == 200


# --- creating a tow request ----------------------------------------------------------


def test_tow_request_requires_a_destination(as_user, customer_user, tow_category):
    response = as_user(customer_user).post(REQUESTS_URL, body(tow_category), format="json")
    assert response.status_code == 400
    assert "destination_latitude" in response.data


def test_tow_request_with_a_destination_succeeds(as_user, customer_user, tow_category):
    response = as_user(customer_user).post(
        REQUESTS_URL,
        body(tow_category, destination_latitude=NEARBY_LAT, destination_longitude=NEARBY_LNG),
        format="json",
    )
    assert response.status_code == 201
    assert response.data["destination_latitude"] == NEARBY_LAT
    assert response.data["destination_longitude"] == NEARBY_LNG
    assert response.data["category"]["requires_destination"] is True


def test_repair_request_needs_no_destination(as_user, customer_user, category):
    response = as_user(customer_user).post(REQUESTS_URL, body(category), format="json")
    assert response.status_code == 201
    assert response.data["destination_latitude"] is None


def test_repair_request_may_still_carry_one(as_user, customer_user, category):
    """Harmless, and avoids a special case in the client."""
    response = as_user(customer_user).post(
        REQUESTS_URL,
        body(category, destination_latitude=NEARBY_LAT, destination_longitude=NEARBY_LNG),
        format="json",
    )
    assert response.status_code == 201


@pytest.mark.parametrize("field", ["destination_latitude", "destination_longitude"])
def test_half_a_destination_is_rejected(as_user, customer_user, tow_category, field):
    response = as_user(customer_user).post(
        REQUESTS_URL, body(tow_category, **{field: NEARBY_LAT}), format="json"
    )
    assert response.status_code == 400


def test_destination_is_range_validated(as_user, customer_user, tow_category):
    response = as_user(customer_user).post(
        REQUESTS_URL,
        body(tow_category, destination_latitude=999, destination_longitude=0),
        format="json",
    )
    assert response.status_code == 400


# --- capability routing ---------------------------------------------------------------


def test_tow_work_is_hidden_from_repair_only_providers(
    as_user, provider_user, provider_profile, customer_profile, make_service_request, tow_category
):
    make_service_request(
        customer_profile,
        category=tow_category,
        destination_latitude=NEARBY_LAT,
        destination_longitude=NEARBY_LNG,
    )
    rows = as_user(provider_user).get(
        reverse("service-requests-nearby") + f"?lat={ACCRA_LAT}&lng={ACCRA_LNG}"
    ).data
    assert rows == []


def test_tow_work_reaches_a_both_provider(
    as_user, provider_user, provider_profile, customer_profile, make_service_request, tow_category
):
    provider_profile.provider_type = ProviderType.BOTH
    provider_profile.save(update_fields=["provider_type"])
    make_service_request(
        customer_profile,
        category=tow_category,
        destination_latitude=NEARBY_LAT,
        destination_longitude=NEARBY_LNG,
    )
    rows = as_user(provider_user).get(
        reverse("service-requests-nearby") + f"?lat={ACCRA_LAT}&lng={ACCRA_LNG}"
    ).data
    assert len(rows) == 1


# --- pricing ---------------------------------------------------------------------------


def test_offering_can_carry_a_per_km_rate(as_user, provider_user, provider_profile, tow_category):
    response = as_user(provider_user).post(
        reverse("provider-services"),
        {"category": str(tow_category.id), "title": "Flatbed tow", "per_km_rate": "12.50"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["per_km_rate"] == "12.50"
    assert response.data["hourly_rate"] is None


# --- what the client needs to build a correct request --------------------------------


def test_category_list_exposes_requires_destination(as_user, customer_user, tow_category):
    """The web client cannot ask for a destination it does not know is needed.

    Added 2026-09-01: the flag was absent from `ServiceCategoryMiniSerializer`, so the client
    had no way to distinguish a tow from a repair and submitted every tow request without a
    destination — rejected every time, with a field error the customer could not act on.
    """
    response = as_user(customer_user).get(reverse("service-categories"))
    assert response.status_code == 200

    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    row = next(r for r in rows if r["id"] == str(tow_category.id))
    assert row["requires_destination"] is True

    others = [r for r in rows if r["id"] != str(tow_category.id)]
    assert any(r["requires_destination"] is False for r in others)
