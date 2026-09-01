from django.contrib import admin

from .models import CustomerProfile, Vehicle


class VehicleInline(admin.TabularInline):
    model = Vehicle
    extra = 0


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "created_at")
    inlines = [VehicleInline]
    search_fields = ("user__email", "display_name")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("make", "model", "customer", "license_plate")
