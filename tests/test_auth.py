import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_register_creates_driver(api):
    url = reverse("register")
    payload = {
        "phone": "+233540000001",
        "email": "newdriver@example.com",
        "password": "TestPass123!",
        "password_confirm": "TestPass123!",
        "role": "driver",
    }
    response = api.post(url, payload, format="json")
    assert response.status_code == 201
    data = response.data
    assert data["phone"] == "+233540000001"
    assert data["email"] == "newdriver@example.com"
    assert data["role"] == "driver"
