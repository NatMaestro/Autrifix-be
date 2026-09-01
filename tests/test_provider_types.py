"""Provider trades and the customer/provider vocabulary — SPEC-014 / ADR-020."""

import pytest
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.jobs.models import ServiceCategory
from apps.providers.verification import ProviderType
from tests.conftest import ACCRA_LAT, ACCRA_LNG

pytestmark = pytest.mark.django_db

NEARBY_SERVICES = reverse("services-nearby")
NEARBY_REQUESTS = reverse("service-requests-nearby")


def services_url(**extra):
    params = {"lat": ACCRA_LAT, "lng": ACCRA_LNG, **extra}
    return NEARBY_SERVICES + "?" + "&".join(f"{k}={v}" for k, v in params.items())


@pytest.fixture
def tow_category(db):
    return ServiceCategory.objects.get_or_create(
        slug="tow-recovery", defaults={"name": "Towing / Recovery", "is_active": True}
    )[0]


# --- vocabulary ---------------------------------------------------------------------


def test_roles_are_customer_and_provider():
    """ADR-020: 'driver' collided with rideshare and with tow operators, who *are* drivers."""
    assert UserRole.CUSTOMER == "customer"
    assert UserRole.PROVIDER == "provider"
    assert "driver" not in UserRole.values
    assert "mechanic" not in UserRole.values


def test_signup_offers_customer_and_provider_only():
    from apps.accounts.models import SIGNUP_ROLE_CHOICES

    assert {value for value, _label in SIGNUP_ROLE_CHOICES} == {"customer", "provider"}


def test_registration_accepts_the_new_roles(api):
    response = api.post(
        reverse("register"),
        {
            "phone": "+233540000501",
            "email": "towco@example.com",
            "password": "TestPass123!",
            "password_confirm": "TestPass123!",
            "role": "provider",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["role"] == UserRole.PROVIDER


def test_registration_rejects_the_retired_role_names(api):
    response = api.post(
        reverse("register"),
        {
            "phone": "+233540000502",
            "email": "old@example.com",
            "password": "TestPass123!",
            "password_confirm": "TestPass123!",
            "role": "driver",
        },
        format="json",
    )
    assert response.status_code == 400


# --- provider type ------------------------------------------------------------------


def test_provider_defaults_to_mechanic(provider_profile):
    assert provider_profile.provider_type == ProviderType.MECHANIC


def test_provider_can_declare_its_trade(as_user, provider_user, provider_profile):
    response = as_user(provider_user).patch(
        reverse("provider-profile"), {"provider_type": "tow"}, format="json"
    )
    assert response.status_code == 200
    provider_profile.refresh_from_db()
    assert provider_profile.provider_type == ProviderType.TOW


def test_invalid_trade_is_rejected(as_user, provider_user, provider_profile):
    response = as_user(provider_user).patch(
        reverse("provider-profile"), {"provider_type": "helicopter"}, format="json"
    )
    assert response.status_code == 400


# --- discovery filtering ------------------------------------------------------------


def test_discovery_can_filter_to_tow_operators(
    as_user, customer_user, provider_user, make_provider_profile
):
    make_provider_profile(provider_user, name="Kofi Auto Works")  # mechanic
    response = as_user(customer_user).get(services_url(provider_type="tow"))
    assert response.data["nearby_providers_count"] == 0


def test_a_both_provider_matches_either_trade(
    as_user, customer_user, provider_user, make_provider_profile
):
    profile = make_provider_profile(provider_user)
    profile.provider_type = ProviderType.BOTH
    profile.save(update_fields=["provider_type"])

    for trade in ("tow", "mechanic"):
        response = as_user(customer_user).get(services_url(provider_type=trade))
        assert response.data["nearby_providers_count"] == 1, trade


def test_unfiltered_discovery_returns_every_trade(
    as_user, customer_user, provider_profile
):
    response = as_user(customer_user).get(services_url())
    assert response.data["nearby_providers_count"] == 1
    assert response.data["providers"][0]["provider_type"] == ProviderType.MECHANIC


def test_unknown_trade_filter_is_400(as_user, customer_user, provider_profile):
    assert as_user(customer_user).get(services_url(provider_type="boat")).status_code == 400


# --- capability filtering on the work feed ------------------------------------------


def test_repair_only_provider_does_not_see_tow_work(
    as_user, provider_user, provider_profile, customer_profile, make_service_request, tow_category
):
    """A mechanic without a truck physically cannot serve this; showing it is noise."""
    make_service_request(customer_profile, category=tow_category)
    rows = as_user(provider_user).get(
        f"{NEARBY_REQUESTS}?lat={ACCRA_LAT}&lng={ACCRA_LNG}"
    ).data
    assert rows == []


def test_tow_operator_sees_tow_work(
    as_user, provider_user, provider_profile, customer_profile, make_service_request, tow_category
):
    provider_profile.provider_type = ProviderType.TOW
    provider_profile.save(update_fields=["provider_type"])
    make_service_request(customer_profile, category=tow_category)

    rows = as_user(provider_user).get(
        f"{NEARBY_REQUESTS}?lat={ACCRA_LAT}&lng={ACCRA_LNG}"
    ).data
    assert len(rows) == 1


def test_repair_work_is_still_visible_to_everyone(
    as_user, provider_user, provider_profile, service_request
):
    """ADR-009 stands: non-tow work is not filtered by declared offerings."""
    provider_profile.provider_type = ProviderType.TOW
    provider_profile.save(update_fields=["provider_type"])

    rows = as_user(provider_user).get(
        f"{NEARBY_REQUESTS}?lat={ACCRA_LAT}&lng={ACCRA_LNG}"
    ).data
    assert len(rows) == 1
