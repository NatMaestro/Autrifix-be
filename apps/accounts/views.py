import logging

from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from apps.accounts.models import User, UserRole
from apps.accounts.otp_service import issue_otp, verify_otp as verify_otp_code
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

logger = logging.getLogger(__name__)

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
    """Always use identifier-based serializer (not SimpleJWT default ``phone`` + password)."""

    serializer_class = IdentifierTokenObtainPairSerializer
    throttle_scope = "auth"

    def get_serializer_class(self):
        return IdentifierTokenObtainPairSerializer


@extend_schema(exclude=True)
class TokenObtainPairAliasView(TokenObtainPairView):
    serializer_class = IdentifierTokenObtainPairSerializer
    throttle_scope = "auth"

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


@extend_schema(
    summary="Verify OTP",
    description=(
        "Verify the SMS code. **Creates** a user on first success (passwordless) or logs in an existing user. "
        "Optional **role** (`driver` | `mechanic`) applies only when the account is created."
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

        if not verify_otp_code(phone, code):
            return Response(
                {"detail": "Invalid or expired code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        role = UserRole.DRIVER
        if role_raw == "mechanic":
            role = UserRole.MECHANIC
        elif role_raw == "driver":
            role = UserRole.DRIVER

        user, created = User.objects.get_or_create(
            phone=phone,
            defaults={"email": None, "role": role},
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])

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
    fields={"id_token": serializers.CharField(help_text="Credential JWT from Google Identity Services")},
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
            user = User.objects.create_user(
                phone=None,
                password=None,
                email=email,
                role=UserRole.DRIVER,
                is_email_verified=verified,
            )
        elif verified and not user.is_email_verified:
            user.is_email_verified = True
            user.save(update_fields=["is_email_verified"])

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
        "role": serializers.ChoiceField(choices=["driver", "mechanic"], required=False),
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
