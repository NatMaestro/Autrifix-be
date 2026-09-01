"""Passwordless signup must not invent a role — SPEC-001 REQ-9.

`role` is read-only after signup (ADR-013), so a role assigned by default is permanent. Both
passwordless paths used to fall back to `customer` when the client sent none, which meant a
provider signing in with Google silently became a customer with no error and no way out.

These tests pin the rule: **signing in to an existing account is unaffected; creating one
requires the client to have asked.**
"""

from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.accounts.models import User, UserRole
from apps.accounts.otp_service import issue_otp

pytestmark = pytest.mark.django_db

GOOGLE_URL = reverse("auth-google")
VERIFY_OTP_URL = reverse("auth-verify-otp")

GOOGLE_IDINFO = {
    "iss": "https://accounts.google.com",
    "email": "new.provider@example.com",
    "email_verified": True,
}


def _google(api, settings, payload):
    settings.GOOGLE_OAUTH_CLIENT_ID = "test-client-id"
    with patch(
        "google.oauth2.id_token.verify_oauth2_token", return_value=GOOGLE_IDINFO
    ):
        return api.post(GOOGLE_URL, payload, format="json")


# --- Google -------------------------------------------------------------------------


def test_google_signup_without_a_role_is_refused(api, settings):
    response = _google(api, settings, {"id_token": "tok"})

    assert response.status_code == 400
    assert response.data["code"] == "signup_role_required"
    assert set(response.data["choices"]) == {"customer", "provider"}
    assert not User.objects.filter(email__iexact=GOOGLE_IDINFO["email"]).exists()


def test_google_signup_with_a_role_creates_that_role(api, settings):
    response = _google(api, settings, {"id_token": "tok", "role": "provider"})

    assert response.status_code == 200
    assert "access" in response.data
    user = User.objects.get(email__iexact=GOOGLE_IDINFO["email"])
    assert user.role == UserRole.PROVIDER


def test_google_signin_to_an_existing_account_needs_no_role(api, settings, make_user):
    """The role question only arises when an account would be created."""
    existing = make_user(role=UserRole.PROVIDER, email=GOOGLE_IDINFO["email"], phone=None)

    response = _google(api, settings, {"id_token": "tok"})

    assert response.status_code == 200
    existing.refresh_from_db()
    assert existing.role == UserRole.PROVIDER


def test_google_signin_cannot_change_an_existing_role(api, settings, make_user):
    """A supplied role applies at creation only — it is not a back door around ADR-013."""
    existing = make_user(role=UserRole.CUSTOMER, email=GOOGLE_IDINFO["email"], phone=None)

    response = _google(api, settings, {"id_token": "tok", "role": "provider"})

    assert response.status_code == 200
    existing.refresh_from_db()
    assert existing.role == UserRole.CUSTOMER


# --- OTP ----------------------------------------------------------------------------


def test_otp_signup_without_a_role_is_refused(api):
    phone = "+233200000123"
    code = issue_otp(phone)

    response = api.post(VERIFY_OTP_URL, {"phone": phone, "code": code}, format="json")

    assert response.status_code == 400
    assert response.data["code"] == "signup_role_required"
    assert not User.objects.filter(phone=phone).exists()


def test_otp_signup_with_a_role_creates_that_role(api):
    phone = "+233200000124"
    code = issue_otp(phone)

    response = api.post(
        VERIFY_OTP_URL, {"phone": phone, "code": code, "role": "provider"}, format="json"
    )

    assert response.status_code == 200
    assert User.objects.get(phone=phone).role == UserRole.PROVIDER


def test_otp_signin_to_an_existing_account_needs_no_role(api, make_user):
    phone = "+233200000125"
    make_user(role=UserRole.PROVIDER, phone=phone)
    code = issue_otp(phone)

    response = api.post(VERIFY_OTP_URL, {"phone": phone, "code": code}, format="json")

    assert response.status_code == 200
    assert User.objects.get(phone=phone).role == UserRole.PROVIDER


def test_a_refused_signup_does_not_consume_nothing_silently(api):
    """The caller can retry with a role — the refusal must be recoverable, not a dead end."""
    phone = "+233200000126"
    code = issue_otp(phone)

    first = api.post(VERIFY_OTP_URL, {"phone": phone, "code": code}, format="json")
    assert first.status_code == 400

    second = api.post(
        VERIFY_OTP_URL, {"phone": phone, "code": code, "role": "provider"}, format="json"
    )
    assert second.status_code == 200
    assert User.objects.get(phone=phone).role == UserRole.PROVIDER
