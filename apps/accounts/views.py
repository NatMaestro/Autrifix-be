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
from apps.accounts.serializers import RegisterSerializer, SendOTPSerializer, UserSerializer, VerifyOTPSerializer
from apps.accounts.sms import send_otp_sms

logger = logging.getLogger(__name__)


@extend_schema(
    summary="Login (password)",
    description=(
        "Authenticate with **username** = phone (E.164) and **password**. "
        "Returns JWT **access** and **refresh**."
    ),
    tags=["auth"],
)
class LoginView(TokenObtainPairView):
    throttle_scope = "auth"


@extend_schema(exclude=True)
class TokenObtainPairAliasView(TokenObtainPairView):
    throttle_scope = "auth"


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


class RegisterView(generics.CreateAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer
    throttle_scope = "auth"


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
