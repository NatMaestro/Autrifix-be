from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.auth_utils import user_for_identifier
from apps.accounts.models import SIGNUP_ROLE_CHOICES, User, UserRole
from apps.accounts.phone import normalize_phone


class SendOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, help_text="E.164 or local GH number, e.g. +233XXXXXXXXX")


class VerifyOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)
    code = serializers.CharField(min_length=6, max_length=6, trim_whitespace=True)
    role = serializers.ChoiceField(
        choices=SIGNUP_ROLE_CHOICES,
        required=False,
        help_text="Set on first login when the account is created (default: customer).",
    )


class IdentifierTokenObtainPairSerializer(serializers.Serializer):
    """JWT from **identifier** (email or E.164 phone) + **password**.

    Accepts **identifier** and/or legacy **email** / **phone** keys — first non-empty wins.
    """

    identifier = serializers.CharField(required=False, allow_blank=True)
    email = serializers.CharField(required=False, allow_blank=True, max_length=254)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=32)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    #: Deliberately identical for "no such user", "wrong password", and "inactive", so
    #: the endpoint cannot be used to enumerate accounts.
    NO_ACTIVE_ACCOUNT = "No active account found with the given credentials"

    def _audit_failure(self, identifier: str, user, *, reason: str) -> None:
        """Record the attempt. The response stays identical either way — only the audit
        trail distinguishes 'no such account' from 'wrong password'."""
        from apps.core import audit
        from apps.core.models import AuditAction

        request = self.context.get("request")
        audit.record(
            AuditAction.LOGIN_FAILED,
            actor=None,  # the attempt is unauthenticated by definition
            target_type="user",
            target_id=getattr(user, "pk", "") or "",
            metadata={
                "identifier": identifier[:254],
                "reason": reason,
                "account_exists": user is not None,
                "ip": audit.client_ip(request),
            },
        )

    def validate(self, attrs):
        ident = (
            (attrs.get("identifier") or "").strip()
            or (attrs.get("email") or "").strip()
            or (attrs.get("phone") or "").strip()
        )
        if not ident:
            raise serializers.ValidationError(
                {"non_field_errors": ["Enter your email or phone number with your password."]},
                code="missing_identifier",
            )
        user = user_for_identifier(ident)
        if user is None or not user.has_usable_password() or not user.check_password(attrs["password"]):
            self._audit_failure(ident, user, reason="bad_credentials")
            raise AuthenticationFailed(self.NO_ACTIVE_ACCOUNT, code="no_active_account")
        if not user.is_active:
            self._audit_failure(ident, user, reason="inactive_account")
            raise AuthenticationFailed(self.NO_ACTIVE_ACCOUNT, code="no_active_account")

        refresh = RefreshToken.for_user(user)
        return {"refresh": str(refresh), "access": str(refresh.access_token)}


class RegisterSerializer(serializers.Serializer):
    """Password sign-up: **email** and **phone** are both required (no email OTP in MVP)."""

    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=32)
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)
    role = serializers.ChoiceField(choices=SIGNUP_ROLE_CHOICES, default=UserRole.CUSTOMER)

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_email(self, value):
        raw = (value or "").strip().lower()
        if User.objects.filter(email__iexact=raw).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return raw

    def validate_phone(self, value):
        try:
            return normalize_phone(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        if attrs.get("role") == UserRole.ADMIN:
            raise serializers.ValidationError({"role": "Cannot self-register as admin."})
        phone = attrs["phone"]
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError({"phone": "An account with this phone number already exists."})
        return attrs

    def create(self, validated_data):
        pwd = validated_data["password"]
        role = validated_data.get("role", UserRole.CUSTOMER)
        user = User(
            email=validated_data["email"],
            phone=validated_data["phone"],
            role=role,
        )
        user.set_password(pwd)
        user.save()
        return user


class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField()
    role = serializers.ChoiceField(
        choices=SIGNUP_ROLE_CHOICES,
        required=False,
        help_text="Optional role for first-time Google signup (customer or provider).",
    )


class UserSerializer(serializers.ModelSerializer):
    """Profile updates — identifier and role used at signup stay read-only here.

    ``role`` is deliberately read-only: it decides which endpoints the account may reach
    (including accepting jobs), so it is not a self-service field. Changing it requires
    an administrator. See ``specs/001-authentication.md`` REQ-9.
    """

    class Meta:
        model = User
        fields = (
            "id",
            "phone",
            "email",
            "role",
            "first_name",
            "last_name",
            "avatar",
            "is_email_verified",
            "date_joined",
        )
        read_only_fields = ("id", "phone", "role", "is_email_verified", "date_joined")

    def validate_email(self, value):
        """Match the case-insensitive lookup used by login (``auth_utils``)."""
        raw = (value or "").strip().lower()
        if not raw:
            return None
        qs = User.objects.filter(email__iexact=raw)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return raw
