from django.contrib import admin

from .models import MechanicProfile, MechanicServiceOffering


@admin.register(MechanicProfile)
class MechanicProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "user", "is_available", "rating_avg", "created_at")
    list_filter = ("is_available",)
    search_fields = ("business_name", "user__email")


@admin.register(MechanicServiceOffering)
class MechanicServiceOfferingAdmin(admin.ModelAdmin):
    list_display = ("mechanic", "category", "title", "hourly_rate", "is_active", "created_at")
    list_filter = ("is_active", "category")
    search_fields = ("mechanic__business_name", "title", "category__name")
