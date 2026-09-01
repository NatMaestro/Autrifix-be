"""Service request creation, ownership, and customer cancellation — SPEC-005."""

import uuid

import pytest
from django.urls import reverse

from apps.customers.models import Vehicle
from apps.jobs.models import JobStatus, ServiceRequest, ServiceRequestStatus
from apps.notifications.models import Notification, NotificationKind
from tests.conftest import ACCRA_LAT, ACCRA_LNG

pytestmark = pytest.mark.django_db

LIST_URL = reverse("service-requests")


def body(category, **overrides):
    data = {
        "category": str(category.id),
        "description": "Battery is dead outside Osu",
        "latitude": ACCRA_LAT,
        "longitude": ACCRA_LNG,
    }
    data.update(overrides)
    return data


def detail_url(request):
    return reverse("service-request-detail", kwargs={"id": request.id})


def cancel_url(request):
    return reverse("service-request-cancel", kwargs={"id": request.id})


# --- creation ---------------------------------------------------------------------


def test_customer_creates_request(as_user, customer_user, category):
    response = as_user(customer_user).post(LIST_URL, body(category), format="json")
    assert response.status_code == 201
    assert response.data["status"] == ServiceRequestStatus.OPEN
    assert response.data["category"]["slug"] == category.slug
    assert ServiceRequest.objects.get().customer.user_id == customer_user.id


def test_alias_endpoint_behaves_identically(as_user, customer_user, category):
    response = as_user(customer_user).post(reverse("request-create"), body(category), format="json")
    assert response.status_code == 201


def test_provider_cannot_create_request(as_user, provider_user, category):
    assert as_user(provider_user).post(LIST_URL, body(category), format="json").status_code == 403


def test_anonymous_cannot_create_request(api, category):
    assert api.post(LIST_URL, body(category), format="json").status_code == 401


def test_status_is_not_client_writable(as_user, customer_user, category):
    response = as_user(customer_user).post(
        LIST_URL, body(category, status="completed"), format="json"
    )
    assert response.status_code == 201
    assert response.data["status"] == ServiceRequestStatus.OPEN


@pytest.mark.parametrize("missing", ["latitude", "longitude"])
def test_coordinates_are_required(as_user, customer_user, category, missing):
    data = body(category)
    data.pop(missing)
    assert as_user(customer_user).post(LIST_URL, data, format="json").status_code == 400


@pytest.mark.parametrize(
    ("field", "value"),
    [("latitude", 999), ("latitude", -91), ("longitude", 181), ("longitude", -181)],
)
def test_out_of_range_coordinates_are_rejected(as_user, customer_user, category, field, value):
    """SEC-GAP-24: these were previously persisted and later crashed geopy."""
    response = as_user(customer_user).post(LIST_URL, body(category, **{field: value}), format="json")
    assert response.status_code == 400


def test_description_is_length_limited(as_user, customer_user, category):
    response = as_user(customer_user).post(
        LIST_URL, body(category, description="x" * 2001), format="json"
    )
    assert response.status_code == 400


def test_inactive_category_is_rejected(as_user, customer_user, category):
    category.is_active = False
    category.save(update_fields=["is_active"])
    assert as_user(customer_user).post(LIST_URL, body(category), format="json").status_code == 400


# --- preferred vehicle ------------------------------------------------------------


def test_own_vehicle_can_be_attached(as_user, customer_user, category, vehicle):
    response = as_user(customer_user).post(
        LIST_URL, body(category, preferred_vehicle=str(vehicle.id)), format="json"
    )
    assert response.status_code == 201
    assert response.data["vehicle_summary"] == "2014 Toyota Corolla · Silver"


def test_another_customers_vehicle_is_rejected(
    as_user, customer_user, category, other_customer_profile
):
    """CONFLICT-004-A: a foreign vehicle used to be accepted and read back."""
    foreign = Vehicle.objects.create(customer=other_customer_profile, make="Honda", model="Civic")
    response = as_user(customer_user).post(
        LIST_URL, body(category, preferred_vehicle=str(foreign.id)), format="json"
    )
    assert response.status_code == 400
    assert "preferred_vehicle" in response.data


# --- ownership --------------------------------------------------------------------


def test_list_is_scoped_to_owner(as_user, customer_user, other_customer_user, service_request):
    assert as_user(customer_user).get(LIST_URL).data["count"] == 1
    assert as_user(other_customer_user).get(LIST_URL).data["count"] == 0


def test_foreign_request_detail_is_404(as_user, other_customer_user, service_request):
    assert as_user(other_customer_user).get(detail_url(service_request)).status_code == 404


def test_customer_name_does_not_leak_phone_number(as_user, customer_user, category, customer_profile):
    """SEC-GAP-15: the fallback used to expose the customer's phone number."""
    customer_profile.display_name = ""
    customer_profile.save(update_fields=["display_name"])
    response = as_user(customer_user).post(LIST_URL, body(category), format="json")
    assert response.data["customer_name"] == "Customer"


# --- cancellation (REQ-7, previously NOT_IMPLEMENTED) -----------------------------


def test_customer_cancels_open_request(as_user, customer_user, service_request):
    response = as_user(customer_user).post(cancel_url(service_request))
    assert response.status_code == 200
    service_request.refresh_from_db()
    assert service_request.status == ServiceRequestStatus.CANCELLED


def test_cancelling_matched_request_cancels_the_job(as_user, customer_user, job, provider_user):
    response = as_user(customer_user).post(cancel_url(job.service_request))
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.status == JobStatus.CANCELLED
    assert Notification.objects.filter(
        user=provider_user, kind=NotificationKind.REQUEST_CANCELLED
    ).exists()


def test_cancelling_a_completed_request_is_409(as_user, customer_user, make_service_request, customer_profile):
    request = make_service_request(customer_profile, status=ServiceRequestStatus.COMPLETED)
    assert as_user(customer_user).post(cancel_url(request)).status_code == 409


def test_cancelling_twice_is_409(as_user, customer_user, service_request):
    client = as_user(customer_user)
    assert client.post(cancel_url(service_request)).status_code == 200
    assert client.post(cancel_url(service_request)).status_code == 409


def test_customer_cannot_cancel_another_customers_request(as_user, other_customer_user, service_request):
    assert as_user(other_customer_user).post(cancel_url(service_request)).status_code == 404


def test_provider_cannot_cancel_a_request(as_user, provider_user, service_request):
    assert as_user(provider_user).post(cancel_url(service_request)).status_code == 403


def test_cancelling_unknown_request_is_404(as_user, customer_user):
    url = reverse("service-request-cancel", kwargs={"id": uuid.uuid4()})
    assert as_user(customer_user).post(url).status_code == 404
