import logging

from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from apps.accounts.models import SIGNUP_ROLE_CHOICES, User, UserRole
from apps.accounts.otp_service import check_otp, issue_otp, verify_otp as verify_otp_code
from apps.accounts.phone import normalize_phone
from apps.accounts.serializers import (
    GoogleAuthSerializer,
    IdentifierTokenObtainPairSerializer,
    RegisterSerializer,
    SendOTPSerializer,
    UserSerializer,
    VerifyOTPSerializer,
)
from apps.accounts.sms import send_otp_sms
from apps.accounts.throttling import LoginIdentifierRateThrottle
from apps.core.exceptions import Conflict
from apps.customers.models import CustomerProfile
from apps.providers.models import ProviderProfile
from apps.providers.verification import evaluate_automatic_level

logger = logging.getLogger(__name__)

#: Overriding ``throttle_classes`` replaces the project defaults, so the scoped and
#: anonymous throttles are re-listed alongside the per-identifier one.
LOGIN_THROTTLES = (LoginIdentifierRateThrottle, ScopedRateThrottle, AnonRateThrottle)

_LOGIN_REQ = inline_serializer(
    name="LoginIdentifierRequest",
    fields={
        "identifier": serializers.CharField(
            required=False,
            allow_blank=True,
            help_text="Email or E.164 phone (preferred single field)",
        ),
        "email": serializers.CharField(required=False, allow_blank=True, help_text="Optional alias of identifier"),
        "phone": serializers.CharField(required=False, allow_blank=True, help_text="Optional alias of identifier"),
        "password": serializers.CharField(),
    },
)


@extend_schema(
    summary="Login (password)",
    description=(
        "Authenticate with **identifier** (email or E.164 phone) and **password**. "
        "You may send **email** or **phone** instead of **identifier** if exactly one is non-empty. "
        "Returns JWT **access** and **refresh**."
    ),
    request=_LOGIN_REQ,
    tags=["auth"],
)
class LoginView(TokenObtainPairView):
    """Always use identifier-based serializer (not SimpleJWT default ``phone`` + password).

    Throttled twice over: the IP-keyed ``auth`` scope, and a per-identifier limit so an
    attacker cannot grind one account from many addresses (``docs/SECURITY.md`` SEC-GAP-01).
    """

    serializer_class = IdentifierTokenObtainPairSerializer
    throttle_scope = "auth"
    throttle_classes = LOGIN_THROTTLES

    def get_serializer_class(self):
        return IdentifierTokenObtainPairSerializer


@extend_schema(exclude=True)
class TokenObtainPairAliasView(TokenObtainPairView):
    serializer_class = IdentifierTokenObtainPairSerializer
    throttle_scope = "auth"
    throttle_classes = LOGIN_THROTTLES

    def get_serializer_class(self):
        return IdentifierTokenObtainPairSerializer


@extend_schema(
    summary="Refresh token",
    description="Body: `{\"refresh\": \"<refresh token>\"}` — returns new **access** (and optionally rotated **refresh**).",
    tags=["auth"],
)
class RefreshTokenAliasView(TokenRefreshView):
    throttle_scope = "auth"


@extend_schema(exclude=True)
class TokenRefreshLegacyView(TokenRefreshView):
    """Legacy path ``/auth/token/refresh/`` — same as ``/auth/refresh-token/``."""

    throttle_scope = "auth"


@extend_schema(
    summary="Logout",
    description="Blacklist the **refresh** token. Send `{\"refresh\": \"...\"}` in the body.",
    tags=["auth"],
)
class LogoutView(TokenBlacklistView):
    pass


_OTP_SENT = inline_serializer(
    name="OTPSentResponse",
    fields={"detail": serializers.CharField()},
)


@extend_schema(
    summary="Send OTP (SMS)",
    description="Sends a 6-digit code via SMS (console/log in dev). Rate-limited; code expires in 5 minutes.",
    request=SendOTPSerializer,
    responses={200: _OTP_SENT},
    tags=["auth"],
)
class SendOTPView(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_scope = "auth"

    def post(self, request):
        ser = SendOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            phone = normalize_phone(ser.validated_data["phone"])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.cache import cache

        rate_key = f"otp_send_rate:{phone}"
        n = cache.get(rate_key, 0)
        if n >= getattr(settings, "OTP_SEND_MAX_PER_HOUR", 5):
            return Response(
                {"detail": "Too many SMS requests for this number. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        cache.set(rate_key, n + 1, 3600)

        code = issue_otp(phone)
        try:
            send_otp_sms(phone, code)
        except RuntimeError as exc:
            logger.exception("SMS failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(
            {"detail": "If this number can receive SMS, a login code was sent."},
            status=status.HTTP_200_OK,
        )


#: Machine-readable marker for "this would create an account, but no role was chosen".
#: Deliberately **not** a 409: clients already treat 409 as "someone got there first"
#: (job taken, request expired, cap reached), and this is a retryable missing-input case.
SIGNUP_ROLE_REQUIRED = "signup_role_required"


def signup_role_required_response():
    """Ask the client to choose a role and retry, rather than choosing one for them."""
    return Response(
        {
            "detail": "No account exists for this identity. Choose a role to finish signing up.",
            "code": SIGNUP_ROLE_REQUIRED,
            "choices": [value for value, _label in SIGNUP_ROLE_CHOICES],
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


@extend_schema(
    summary="Verify OTP",
    description=(
        "Verify the SMS code. **Creates** a user on first success (passwordless) or logs in an existing user. "
        "Optional **role** (`customer` | `provider`) applies only when the account is created."
    ),
    request=VerifyOTPSerializer,
    responses={
        200: inline_serializer(
            name="OTPVerifyTokens",
            fields={
                "access": serializers.CharField(),
                "refresh": serializers.CharField(),
            },
        )
    },
    tags=["auth"],
)
class VerifyOTPView(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_scope = "auth"

    def post(self, request):
        ser = VerifyOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            phone = normalize_phone(ser.validated_data["phone"])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        code = ser.validated_data["code"]
        role_raw = ser.validated_data.get("role")

        # Checked before anything that depends on whether the account exists, so this
        # endpoint never confirms a phone number to someone without a valid code.
        if not check_otp(phone, code):
            return Response(
                {"detail": "Invalid or expired code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(phone=phone).first()
        if user is None and not role_raw:
            # Same rule as Google: never invent a permanent role for a new account. The
            # code is deliberately still unconsumed, so retrying with a role works.
            return signup_role_required_response()

        if not verify_otp_code(phone, code):
            # Lost a race with a concurrent use of the same code.
            return Response(
                {"detail": "Invalid or expired code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = False
        if user is None:
            user = User.objects.create(
                phone=phone,
                email=None,
                role=UserRole.PROVIDER if role_raw == "provider" else UserRole.CUSTOMER,
                is_phone_verified=True,
            )
            created = True
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        elif not user.is_phone_verified:
            # Consuming a code proves control of the number, however the account was made.
            user.is_phone_verified = True
            user.save(update_fields=["is_phone_verified"])

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )


_GOOGLE_REQ = inline_serializer(
    name="GoogleAuthRequest",
    fields={
        "id_token": serializers.CharField(help_text="Credential JWT from Google Identity Services"),
        "role": serializers.ChoiceField(choices=SIGNUP_ROLE_CHOICES, required=False),
    },
)
_GOOGLE_OK = inline_serializer(
    name="GoogleAuthTokens",
    fields={
        "access": serializers.CharField(),
        "refresh": serializers.CharField(),
    },
)


@extend_schema(
    summary="Sign in with Google",
    description="Verify a Google **id_token** (GIS credential) and return JWT **access** / **refresh**.",
    request=_GOOGLE_REQ,
    responses={200: _GOOGLE_OK},
    tags=["auth"],
)
class GoogleAuthView(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_scope = "auth"

    def post(self, request):
        client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or ""
        if not client_id:
            return Response(
                {"detail": "Google sign-in is not configured on the server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        ser = GoogleAuthSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        raw = ser.validated_data["id_token"]
        selected_role = ser.validated_data.get("role")
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token
        except ImportError:
            return Response(
                {
                    "detail": "Google auth dependency is missing. Install with: pip install google-auth "
                    "(or pip install -r requirements.txt).",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            idinfo = google_id_token.verify_oauth2_token(raw, google_requests.Request(), client_id)
        except ValueError:
            return Response({"detail": "Invalid Google token."}, status=status.HTTP_400_BAD_REQUEST)

        if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            return Response({"detail": "Invalid token issuer."}, status=status.HTTP_400_BAD_REQUEST)

        email = (idinfo.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "Google account has no email."}, status=status.HTTP_400_BAD_REQUEST)

        verified = bool(idinfo.get("email_verified"))
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            # Creating an account requires an explicit role. Defaulting here would decide
            # something permanent (ADR-013) on the user's behalf, which is how providers
            # ended up stranded in the customer app (SPEC-001 REQ-9).
            if not selected_role:
                return signup_role_required_response()
            user = User.objects.create_user(
                phone=None,
                password=None,
                email=email,
                role=selected_role,
                is_email_verified=verified,
            )
        elif verified and not user.is_email_verified:
            user.is_email_verified = True
            user.save(update_fields=["is_email_verified"])

        if user.role == UserRole.CUSTOMER:
            CustomerProfile.objects.get_or_create(user=user)
        elif user.role == UserRole.PROVIDER:
            ProviderProfile.objects.get_or_create(
                user=user,
                defaults={"business_name": user.email or "AutriFix Provider"},
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {"access": str(refresh.access_token), "refresh": str(refresh)},
            status=status.HTTP_200_OK,
        )


_REG_REQ = inline_serializer(
    name="RegisterEmailPhoneRequest",
    fields={
        "email": serializers.EmailField(),
        "phone": serializers.CharField(help_text="E.164 or local GH number"),
        "password": serializers.CharField(),
        "password_confirm": serializers.CharField(),
        "role": serializers.ChoiceField(choices=SIGNUP_ROLE_CHOICES, required=False),
    },
)


@extend_schema(
    summary="Register (password)",
    description=(
        "Create an account with **email**, **phone**, and **password**. "
        "Both email and phone are required; you can sign in later with either plus password. "
        "Returns profile fields and JWT tokens."
    ),
    request=_REG_REQ,
    tags=["auth"],
)
class RegisterView(generics.CreateAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer
    throttle_scope = "auth"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        data = UserSerializer(user, context={"request": request}).data
        data["access"] = str(refresh.access_token)
        data["refresh"] = str(refresh)
        headers = self.get_success_headers(data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


@extend_schema(
    summary="Verify my phone number",
    description=(
        "Confirm the code sent by `POST /auth/send-otp/` for this account's phone number. "
        "Registration collects a phone but does not verify it."
    ),
    request=inline_serializer(
        name="VerifyPhoneRequest", fields={"code": serializers.CharField(min_length=6, max_length=6)}
    ),
    responses={
        200: inline_serializer(
            name="VerifyPhoneResponse", fields={"is_phone_verified": serializers.BooleanField()}
        )
    },
    tags=["auth"],
)
class VerifyMyPhoneView(APIView):
    """Self-service phone verification for an already-authenticated user (SPEC-013 REQ-5)."""

    throttle_scope = "auth"

    def post(self, request):
        user = request.user
        if not user.phone:
            raise Conflict("This account has no phone number to verify.")
        if user.is_phone_verified:
            return Response({"is_phone_verified": True}, status=status.HTTP_200_OK)

        code = str(request.data.get("code") or "").strip()
        if not code:
            return Response({"detail": "code is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not verify_otp_code(user.phone, code):
            raise Conflict("Invalid or expired code.")

        user.is_phone_verified = True
        user.save(update_fields=["is_phone_verified"])

        # A provider may now qualify for the `phone` level (SPEC-013 REQ-1).
        provider = ProviderProfile.objects.filter(user=user).first()
        if provider is not None:
            evaluate_automatic_level(provider)

        return Response({"is_phone_verified": True}, status=status.HTTP_200_OK)


@extend_schema(
    responses={
        200: inline_serializer(
            name="HealthResponse",
            fields={
                "status": serializers.CharField(),
                "service": serializers.CharField(),
            },
        )
    },
    tags=["health"],
)
class HealthView(APIView):
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        return Response({"status": "ok", "service": "autrifix-be"})
