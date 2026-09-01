"""Discovery in both directions — SPEC-006 / SPEC-008."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.jobs.models import ServiceRequest, ServiceRequestStatus
from tests.conftest import ACCRA_LAT, ACCRA_LNG, FAR_LAT, FAR_LNG, NEARBY_LAT, NEARBY_LNG

pytestmark = pytest.mark.django_db

NEARBY_SERVICES = reverse("services-nearby")
NEARBY_REQUESTS = reverse("service-requests-nearby")


def q(url, lat=ACCRA_LAT, lng=ACCRA_LNG, **extra):
    params = "&".join(f"{k}={v}" for k, v in {"lat": lat, "lng": lng, **extra}.items())
    return f"{url}?{params}"


# --- /services/nearby/ ------------------------------------------------------------


def test_services_nearby_requires_authentication(api):
    """SEC-GAP-20: provider coordinates used to be readable by anyone."""
    assert api.get(q(NEARBY_SERVICES)).status_code == 401


def test_services_nearby_returns_available_providers(as_user, customer_user, provider_profile):
    response = as_user(customer_user).get(q(NEARBY_SERVICES))
    assert response.status_code == 200
    assert response.data["nearby_providers_count"] == 1
    entry = response.data["providers"][0]
    assert entry["business_name"] == "Kofi Auto Works"
    assert entry["distance_km"] == 0.0
    assert response.data["truncated"] is False


def test_offline_provider_is_hidden(as_user, customer_user, provider_user, make_provider_profile):
    make_provider_profile(provider_user, available=False)
    assert as_user(customer_user).get(q(NEARBY_SERVICES)).data["nearby_providers_count"] == 0


def test_provider_without_coordinates_is_hidden(as_user, customer_user, provider_user, make_provider_profile):
    make_provider_profile(provider_user, lat=None, lng=None, available=False)
    assert as_user(customer_user).get(q(NEARBY_SERVICES)).data["nearby_providers_count"] == 0


def test_far_provider_is_outside_radius(as_user, customer_user, provider_user, make_provider_profile):
    make_provider_profile(provider_user, lat=FAR_LAT, lng=FAR_LNG)
    response = as_user(customer_user).get(q(NEARBY_SERVICES, radius_km=10))
    assert response.data["nearby_providers_count"] == 0


def test_far_provider_is_inside_a_wide_radius(as_user, customer_user, provider_user, make_provider_profile):
    make_provider_profile(provider_user, lat=FAR_LAT, lng=FAR_LNG)
    response = as_user(customer_user).get(q(NEARBY_SERVICES, radius_km=400))
    assert response.data["nearby_providers_count"] == 1


@pytest.mark.parametrize("params", [{}, {"lat": ACCRA_LAT}, {"lng": ACCRA_LNG}])
def test_missing_coordinates_are_400(as_user, customer_user, params):
    url = NEARBY_SERVICES + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
    assert as_user(customer_user).get(url).status_code == 400


def test_non_numeric_radius_is_400_not_500(as_user, customer_user):
    """Previously an unhandled ValueError."""
    assert as_user(customer_user).get(q(NEARBY_SERVICES, radius_km="abc")).status_code == 400


@pytest.mark.parametrize("radius", [0, -5, 100000])
def test_out_of_range_radius_is_400(as_user, customer_user, radius):
    assert as_user(customer_user).get(q(NEARBY_SERVICES, radius_km=radius)).status_code == 400


def test_out_of_range_coordinates_are_400(as_user, customer_user):
    assert as_user(customer_user).get(q(NEARBY_SERVICES, lat=999)).status_code == 400


# --- /jobs/requests/nearby/ -------------------------------------------------------


def test_provider_sees_nearby_open_request(as_user, provider_user, provider_profile, service_request):
    response = as_user(provider_user).get(q(NEARBY_REQUESTS))
    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [str(service_request.id)]


def test_customer_cannot_use_provider_feed(as_user, customer_user, service_request):
    assert as_user(customer_user).get(q(NEARBY_REQUESTS)).status_code == 403


def test_provider_without_profile_gets_409(as_user, provider_user):
    """CONFLICT-003-A: previously an unhandled 500."""
    assert as_user(provider_user).get(q(NEARBY_REQUESTS)).status_code == 409


def test_feed_omits_non_open_requests(
    as_user, provider_user, provider_profile, make_service_request, customer_profile
):
    make_service_request(customer_profile, status=ServiceRequestStatus.COMPLETED)
    assert as_user(provider_user).get(q(NEARBY_REQUESTS)) .data == []


def test_feed_omits_stale_requests(
    as_user, provider_user, provider_profile, service_request
):
    ServiceRequest.objects.filter(pk=service_request.pk).update(
        updated_at=timezone.now() - timedelta(minutes=31)
    )
    assert as_user(provider_user).get(q(NEARBY_REQUESTS)).data == []


def test_declined_request_becomes_visible_again(
    as_user, provider_user, job, other_provider_user, other_provider_profile
):
    """The feed window keys on updated_at, so returning work to the pool refreshes it."""
    ServiceRequest.objects.filter(pk=job.service_request_id).update(
        updated_at=timezone.now() - timedelta(minutes=45)
    )
    as_user(provider_user).patch(
        reverse("job-detail", kwargs={"id": job.id}), {"status": "cancelled"}, format="json"
    )
    response = as_user(other_provider_user).get(q(NEARBY_REQUESTS))
    assert [row["id"] for row in response.data] == [str(job.service_request_id)]


def test_feed_is_sorted_nearest_first(
    as_user, provider_user, provider_profile, customer_profile, make_service_request
):
    near = make_service_request(customer_profile, lat=ACCRA_LAT, lng=ACCRA_LNG)
    far = make_service_request(customer_profile, lat=NEARBY_LAT, lng=NEARBY_LNG)
    ids = [row["id"] for row in as_user(provider_user).get(q(NEARBY_REQUESTS)).data]
    assert ids == [str(near.id), str(far.id)]


def test_feed_rejects_missing_coordinates(as_user, provider_user, provider_profile):
    """Previously defaulted silently to lat=0, lng=0 (null island)."""
    assert as_user(provider_user).get(NEARBY_REQUESTS).status_code == 400


def test_feed_reports_distance_for_each_request(
    as_user, provider_user, verified_provider_profile, customer_profile, make_service_request
):
    """ADR-015: the provider decides whether to accept largely on distance.

    Uses a **verified** provider — an unverified one sees a coarsened location and a
    distance derived from it (SPEC-013 REQ-2, covered in `test_verification.py`).
    """
    make_service_request(customer_profile, lat=ACCRA_LAT, lng=ACCRA_LNG)
    rows = as_user(provider_user).get(q(NEARBY_REQUESTS)).data

    assert rows[0]["distance_km"] == 0.0
    assert rows[0]["latitude"] == ACCRA_LAT
    assert rows[0]["longitude"] == ACCRA_LNG


def test_feed_distance_grows_with_separation(
    as_user, provider_user, verified_provider_profile, customer_profile, make_service_request
):
    make_service_request(customer_profile, lat=NEARBY_LAT, lng=NEARBY_LNG)
    row = as_user(provider_user).get(q(NEARBY_REQUESTS)).data[0]
    # ~1.1 km north of the search point.
    assert 0.9 < row["distance_km"] < 1.3


def test_customer_own_request_list_has_no_distance(as_user, customer_user, service_request):
    """There is no reference point on a customer's own list, so the field is null."""
    row = as_user(customer_user).get(reverse("service-requests")).data["results"][0]
    assert row["distance_km"] is None


# --- AI matching preview ----------------------------------------------------------


def test_matching_preview_scoped_to_own_request(as_user, customer_user, service_request, provider_profile):
    response = as_user(customer_user).post(
        reverse("ai-matching-preview"), {"service_request_id": str(service_request.id)}, format="json"
    )
    assert response.status_code == 200
    assert len(response.data["ranked_providers"]) == 1


def test_matching_preview_rejects_other_users_request(as_user, other_customer_user, service_request):
    """SECGAP-006-3: any authenticated user could preview any request."""
    response = as_user(other_customer_user).post(
        reverse("ai-matching-preview"), {"service_request_id": str(service_request.id)}, format="json"
    )
    assert response.status_code == 400


def test_route_issue_returns_a_category(as_user, customer_user, category):
    response = as_user(customer_user).post(
        reverse("ai-route-issue"), {"issue_text": "my battery is dead, need a jump start"}, format="json"
    )
    assert response.status_code == 200
    assert response.data["category_slug"]
    assert response.data["method"] in {"rules", "ml", "fallback"}


def test_route_issue_rejects_blank_and_oversized_text(as_user, customer_user):
    client = as_user(customer_user)
    assert client.post(reverse("ai-route-issue"), {"issue_text": "  "}, format="json").status_code == 400
    assert (
        client.post(reverse("ai-route-issue"), {"issue_text": "x" * 2001}, format="json").status_code
        == 400
    )
