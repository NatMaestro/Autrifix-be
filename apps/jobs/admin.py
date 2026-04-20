from django.contrib import admin

from .models import Job, ServiceCategory, ServiceRequest


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "priority", "default_radius_km", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "description", "keywords")
    ordering = ("priority", "name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "driver", "category", "status", "created_at")
    list_filter = ("status", "category")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "service_request", "mechanic", "status", "created_at")
    list_filter = ("status",)
