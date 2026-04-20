from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import PhoneOTP, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("phone", "email", "role", "is_staff", "is_active", "date_joined")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("phone", "email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Profile", {"fields": ("email", "role", "is_email_verified", "first_name", "last_name")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "email", "password1", "password2", "role"),
            },
        ),
    )
    filter_horizontal = ("groups", "user_permissions")
    readonly_fields = ("last_login", "date_joined")


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = ("phone", "expires_at", "consumed_at", "created_at")
    list_filter = ("expires_at",)
    search_fields = ("phone",)
    readonly_fields = ("code_hash", "expires_at", "consumed_at", "created_at")
