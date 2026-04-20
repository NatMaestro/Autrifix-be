from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import User, UserRole


class SendOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, help_text="E.164 or local GH number, e.g. +233XXXXXXXXX")


class VerifyOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)
    code = serializers.CharField(min_length=6, max_length=6, trim_whitespace=True)
    role = serializers.ChoiceField(
        choices=["driver", "mechanic"],
        required=False,
        help_text="Set on first login when the account is created (default: driver).",
    )


class UserSerializer(serializers.ModelSerializer):
    """Profile updates after OTP (name, role) — phone stays read-only."""

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
        read_only_fields = ("id", "phone", "is_email_verified", "date_joined")

    def validate_role(self, value):
        if value == UserRole.ADMIN:
            raise serializers.ValidationError("Cannot set role to admin.")
        return value


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, required=False)
    password_confirm = serializers.CharField(write_only=True, min_length=8, required=False)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = User
        fields = ("phone", "email", "password", "password_confirm", "role")

    def validate(self, attrs):
        pwd = attrs.get("password")
        pwd2 = attrs.pop("password_confirm", None)
        if pwd2 and not pwd:
            raise serializers.ValidationError({"password": "Required when confirming a password."})
        if pwd and pwd2 and pwd != pwd2:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        role = attrs.get("role", UserRole.DRIVER)
        if role == UserRole.ADMIN:
            raise serializers.ValidationError({"role": "Cannot self-register as admin."})
        return attrs

    def validate_password(self, value):
        if value:
            validate_password(value)
        return value

    def validate_email(self, value):
        if value == "":
            return None
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user
