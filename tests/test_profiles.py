"""Customer profiles, vehicles, and provider profiles — SPEC-002 / 003 / 004."""

import pytest
from django.urls import reverse

from apps.customers.models import CustomerProfile, Vehicle
from apps.providers.models import ProviderProfile, ProviderServiceOffering
from tests.conftest import ACCRA_LAT, ACCRA_LNG

pytestmark = pytest.mark.django_db

DRIVER_PROFILE = reverse("customer-profile")
VEHICLES = reverse("vehicle-list")
MECHANIC_PROFILE = reverse("provider-profile")
OFFERINGS = reverse("provider-services")


def vehicle_url(vehicle):
    return reverse("vehicle-detail", kwargs={"id": vehicle.id})


# --- customer profile ---------------------------------------------------------------


def test_profile_is_created_on_first_access(as_user, customer_user):
    assert not CustomerProfile.objects.filter(user=customer_user).exists()
    response = as_user(customer_user).get(DRIVER_PROFILE)
    assert response.status_code == 200
    assert CustomerProfile.objects.filter(user=customer_user).exists()


def test_provider_cannot_access_customer_profile(as_user, provider_user):
    assert as_user(provider_user).get(DRIVER_PROFILE).status_code == 403


def test_customer_can_set_home_location(as_user, customer_user):
    response = as_user(customer_user).patch(
        DRIVER_PROFILE, {"latitude": ACCRA_LAT, "longitude": ACCRA_LNG}, format="json"
    )
    assert response.status_code == 200
    assert response.data["latitude"] == ACCRA_LAT
    assert response.data["longitude"] == ACCRA_LNG


@pytest.mark.parametrize("field", ["latitude", "longitude"])
def test_partial_coordinate_is_rejected(as_user, customer_user, field):
    """Previously accepted with a 200 and silently discarded."""
    response = as_user(customer_user).patch(DRIVER_PROFILE, {field: 5.0}, format="json")
    assert response.status_code == 400


def test_out_of_range_home_coordinate_is_rejected(as_user, customer_user):
    response = as_user(customer_user).patch(
        DRIVER_PROFILE, {"latitude": 91, "longitude": 0}, format="json"
    )
    assert response.status_code == 400


# --- vehicles ---------------------------------------------------------------------


def test_customer_creates_vehicle(as_user, customer_user):
    response = as_user(customer_user).post(
        VEHICLES, {"make": "Toyota", "model": "Corolla", "year": 2014}, format="json"
    )
    assert response.status_code == 201
    assert Vehicle.objects.get().customer.user_id == customer_user.id


def test_creating_primary_vehicle_does_not_500(as_user, customer_user):
    """CONFLICT-004-B: is_primary on create raised KeyError -> 500."""
    response = as_user(customer_user).post(
        VEHICLES, {"make": "Toyota", "model": "Corolla", "is_primary": True}, format="json"
    )
    assert response.status_code == 201
    assert Vehicle.objects.get().is_primary is True


def test_marking_primary_demotes_the_previous_one(as_user, customer_user, customer_profile):
    first = Vehicle.objects.create(customer=customer_profile, make="Toyota", model="Corolla", is_primary=True)
    response = as_user(customer_user).post(
        VEHICLES, {"make": "Honda", "model": "Civic", "is_primary": True}, format="json"
    )
    assert response.status_code == 201
    first.refresh_from_db()
    assert first.is_primary is False
    assert Vehicle.objects.filter(customer=customer_profile, is_primary=True).count() == 1


def test_make_and_model_are_required(as_user, customer_user):
    assert as_user(customer_user).post(VEHICLES, {"make": "Toyota"}, format="json").status_code == 400


def test_year_is_range_validated(as_user, customer_user):
    response = as_user(customer_user).post(
        VEHICLES, {"make": "Toyota", "model": "Corolla", "year": 1}, format="json"
    )
    assert response.status_code == 400


def test_extra_must_be_an_object(as_user, customer_user):
    response = as_user(customer_user).post(
        VEHICLES, {"make": "Toyota", "model": "Corolla", "extra": [1, 2]}, format="json"
    )
    assert response.status_code == 400


def test_vehicle_list_is_owner_scoped(as_user, customer_user, other_customer_user, vehicle):
    assert as_user(customer_user).get(VEHICLES).data["count"] == 1
    assert as_user(other_customer_user).get(VEHICLES).data["count"] == 0


def test_foreign_vehicle_detail_is_404(as_user, other_customer_user, vehicle):
    assert as_user(other_customer_user).get(vehicle_url(vehicle)).status_code == 404


def test_vehicles_are_embedded_in_the_profile(as_user, customer_user, vehicle):
    response = as_user(customer_user).get(DRIVER_PROFILE)
    assert [v["id"] for v in response.data["vehicles"]] == [str(vehicle.id)]


def test_deleting_vehicle_preserves_history(as_user, customer_user, vehicle, make_service_request, customer_profile):
    request = make_service_request(customer_profile, preferred_vehicle=vehicle)
    assert as_user(customer_user).delete(vehicle_url(vehicle)).status_code == 204
    request.refresh_from_db()
    assert request.preferred_vehicle is None


# --- provider profile -------------------------------------------------------------


def test_provider_profile_created_on_first_access(as_user, provider_user):
    assert not ProviderProfile.objects.filter(user=provider_user).exists()
    response = as_user(provider_user).get(MECHANIC_PROFILE)
    assert response.status_code == 200
    assert ProviderProfile.objects.filter(user=provider_user).exists()
    assert response.data["is_available"] is False


def test_customer_cannot_access_provider_profile(as_user, customer_user):
    assert as_user(customer_user).get(MECHANIC_PROFILE).status_code == 403


def test_cannot_go_online_without_a_location(as_user, provider_user):
    as_user(provider_user).get(MECHANIC_PROFILE)
    response = as_user(provider_user).patch(MECHANIC_PROFILE, {"is_available": True}, format="json")
    assert response.status_code == 400
    assert "is_available" in response.data


def test_can_go_online_with_a_location(as_user, provider_user):
    as_user(provider_user).get(MECHANIC_PROFILE)
    response = as_user(provider_user).patch(
        MECHANIC_PROFILE,
        {"is_available": True, "base_latitude": ACCRA_LAT, "base_longitude": ACCRA_LNG},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["is_available"] is True


def test_partial_base_coordinate_is_rejected(as_user, provider_user, provider_profile):
    response = as_user(provider_user).patch(
        MECHANIC_PROFILE, {"base_latitude": 6.0}, format="json"
    )
    assert response.status_code == 400


def test_ratings_are_read_only(as_user, provider_user, provider_profile):
    as_user(provider_user).patch(MECHANIC_PROFILE, {"rating_avg": "5.00"}, format="json")
    provider_profile.refresh_from_db()
    assert float(provider_profile.rating_avg) == 0.0


# --- offerings --------------------------------------------------------------------


def test_offerings_before_profile_exists_do_not_500(as_user, provider_user, category):
    """CONFLICT-003-A: this raised ProviderProfile.DoesNotExist."""
    response = as_user(provider_user).get(OFFERINGS)
    assert response.status_code == 200


def test_provider_creates_offering(as_user, provider_user, provider_profile, category):
    response = as_user(provider_user).post(
        OFFERINGS, {"category": str(category.id), "title": "Jump start", "hourly_rate": "80.00"}, format="json"
    )
    assert response.status_code == 201
    assert response.data["category_slug"] == category.slug


def test_duplicate_offering_is_rejected(as_user, provider_user, provider_profile, category):
    client = as_user(provider_user)
    body = {"category": str(category.id), "title": "Jump start"}
    assert client.post(OFFERINGS, body, format="json").status_code == 201
    assert client.post(OFFERINGS, body, format="json").status_code == 400


def test_inactive_category_offering_is_rejected(as_user, provider_user, provider_profile, category):
    category.is_active = False
    category.save(update_fields=["is_active"])
    response = as_user(provider_user).post(OFFERINGS, {"category": str(category.id)}, format="json")
    assert response.status_code == 400


def test_offerings_are_owner_scoped(
    as_user, provider_user, provider_profile, other_provider_user, other_provider_profile, category
):
    offering = ProviderServiceOffering.objects.create(provider=provider_profile, category=category)
    url = reverse("provider-service-detail", kwargs={"id": offering.id})
    assert as_user(provider_user).get(url).status_code == 200
    assert as_user(other_provider_user).get(url).status_code == 404
