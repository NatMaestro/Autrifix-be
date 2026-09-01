import pytest
from django.urls import reverse

from apps.accounts.models import User, UserRole

pytestmark = pytest.mark.django_db


def test_register_creates_customer(api):
    response = api.post(
        reverse("register"),
        {
            "phone": "+233540000001",
            "email": "newdriver@example.com",
            "password": "TestPass123!",
            "password_confirm": "TestPass123!",
            "role": "customer",
        },
        format="json",
    )
    assert response.status_code == 201
    data = response.data
    assert data["phone"] == "+233540000001"
    assert data["email"] == "newdriver@example.com"
    assert data["role"] == "customer"
    assert data["access"] and data["refresh"]


def test_register_rejects_admin_role(api):
    response = api.post(
        reverse("register"),
        {
            "phone": "+233540000002",
            "email": "sneaky@example.com",
            "password": "TestPass123!",
            "password_confirm": "TestPass123!",
            "role": "admin",
        },
        format="json",
    )
    assert response.status_code == 400


def test_register_rejects_mismatched_passwords(api):
    response = api.post(
        reverse("register"),
        {
            "phone": "+233540000003",
            "email": "mismatch@example.com",
            "password": "TestPass123!",
            "password_confirm": "Different123!",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "password_confirm" in response.data


def test_register_rejects_duplicate_email_case_insensitively(api, make_user):
    make_user(email="taken@example.com")
    response = api.post(
        reverse("register"),
        {
            "phone": "+233540000099",
            "email": "TAKEN@example.com",
            "password": "TestPass123!",
            "password_confirm": "TestPass123!",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "email" in response.data


@pytest.mark.parametrize("identifier_field", ["identifier", "email", "phone"])
def test_login_by_email_or_phone(api, make_user, identifier_field):
    user = make_user(email="login@example.com", phone="+233540000010")
    identifier = "+233540000010" if identifier_field == "phone" else "login@example.com"
    response = api.post(
        reverse("login"),
        {identifier_field: identifier, "password": "TestPass123!"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["access"] and response.data["refresh"]
    assert User.objects.get(pk=user.pk).is_active


def test_login_with_wrong_password_is_401(api, make_user):
    make_user(email="wrong@example.com")
    response = api.post(
        reverse("login"),
        {"identifier": "wrong@example.com", "password": "NotMyPassword1!"},
        format="json",
    )
    assert response.status_code == 401


def test_login_for_inactive_user_is_401(api, make_user):
    user = make_user(email="inactive@example.com")
    user.is_active = False
    user.save(update_fields=["is_active"])
    response = api.post(
        reverse("login"),
        {"identifier": "inactive@example.com", "password": "TestPass123!"},
        format="json",
    )
    assert response.status_code == 401


def test_login_without_identifier_is_400(api):
    response = api.post(reverse("login"), {"password": "TestPass123!"}, format="json")
    assert response.status_code == 400


def test_me_requires_authentication(api):
    assert api.get(reverse("me")).status_code == 401


def test_me_returns_own_profile(as_user, customer_user):
    response = as_user(customer_user).get(reverse("me"))
    assert response.status_code == 200
    assert response.data["id"] == str(customer_user.id)


def test_me_can_update_name(as_user, customer_user):
    response = as_user(customer_user).patch(reverse("me"), {"first_name": "Ama"}, format="json")
    assert response.status_code == 200
    customer_user.refresh_from_db()
    assert customer_user.first_name == "Ama"


def test_me_cannot_change_role(as_user, customer_user):
    """SEC-GAP-09: role self-assignment previously granted provider-only endpoints."""
    response = as_user(customer_user).patch(reverse("me"), {"role": "provider"}, format="json")
    assert response.status_code == 200
    customer_user.refresh_from_db()
    assert customer_user.role == UserRole.CUSTOMER


def test_me_cannot_take_another_users_email(as_user, customer_user, make_user):
    make_user(email="occupied@example.com")
    response = as_user(customer_user).patch(
        reverse("me"), {"email": "OCCUPIED@example.com"}, format="json"
    )
    assert response.status_code == 400


def test_refresh_rotates_token(api, make_user):
    make_user(email="rotate@example.com", phone="+233540000011")
    tokens = api.post(
        reverse("login"),
        {"identifier": "rotate@example.com", "password": "TestPass123!"},
        format="json",
    ).data
    response = api.post(reverse("refresh-token"), {"refresh": tokens["refresh"]}, format="json")
    assert response.status_code == 200
    assert response.data["access"]
    # ROTATE_REFRESH_TOKENS is on, so a fresh refresh token comes back.
    assert response.data["refresh"] != tokens["refresh"]


def test_repeated_failed_logins_for_one_identifier_are_throttled(api, make_user):
    """SEC-GAP-01: the IP-keyed `auth` scope alone let one account be ground down."""
    make_user(email="target@example.com", phone="+233540000020")
    body = {"identifier": "target@example.com", "password": "WrongPassword1!"}

    statuses = [api.post(reverse("login"), body, format="json").status_code for _ in range(12)]

    assert 429 in statuses, statuses
    # The limit is per identifier, not global: the first attempts were genuine 401s.
    assert statuses[0] == 401


def test_throttling_one_identifier_does_not_lock_out_another(api, make_user):
    make_user(email="victim@example.com", phone="+233540000021")
    make_user(email="bystander@example.com", phone="+233540000022")

    for _ in range(12):
        api.post(
            reverse("login"),
            {"identifier": "victim@example.com", "password": "WrongPassword1!"},
            format="json",
        )

    response = api.post(
        reverse("login"),
        {"identifier": "bystander@example.com", "password": "TestPass123!"},
        format="json",
    )
    assert response.status_code == 200, response.data


def test_logout_blacklists_refresh_token(api, make_user):
    make_user(email="logout@example.com", phone="+233540000012")
    tokens = api.post(
        reverse("login"),
        {"identifier": "logout@example.com", "password": "TestPass123!"},
        format="json",
    ).data
    assert api.post(reverse("logout"), {"refresh": tokens["refresh"]}, format="json").status_code == 200
    reused = api.post(reverse("refresh-token"), {"refresh": tokens["refresh"]}, format="json")
    assert reused.status_code == 401
