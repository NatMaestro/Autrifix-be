from rest_framework import serializers

from apps.ai.issue_router import train_from_service_request
from apps.jobs.models import Job, ServiceCategory, ServiceRequest


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "keywords",
            "default_radius_km",
            "priority",
            "is_active",
        )


class ServiceCategoryMiniSerializer(serializers.ModelSerializer):
    """
    Minimal fields for endpoints like `/services/nearby/`.

    Keeping this light reduces coupling to optional/advanced routing fields and
    prevents runtime failures if some DB columns haven't been migrated yet.
    """

    class Meta:
        model = ServiceCategory
        fields = ("id", "name", "slug")


class ServiceRequestSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=ServiceCategory.objects.filter(is_active=True),
    )
    driver_name = serializers.SerializerMethodField(read_only=True)
    vehicle_summary = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ServiceRequest
        fields = (
            "id",
            "category",
            "description",
            "latitude",
            "longitude",
            "status",
            "preferred_vehicle",
            "driver_name",
            "vehicle_summary",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "status", "created_at", "updated_at")

    def validate(self, attrs):
        if self.instance is None:
            if attrs.get("latitude") is None or attrs.get("longitude") is None:
                raise serializers.ValidationError(
                    {"latitude": "latitude and longitude are required to create a request."}
                )
        return attrs

    def create(self, validated_data):
        validated_data["driver"] = self.context["driver_profile"]
        instance = super().create(validated_data)
        # Online training: every labeled request improves ML routing over time.
        train_from_service_request(instance)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["category"] = ServiceCategorySerializer(instance.category).data
        return data

    def get_driver_name(self, instance):
        driver = getattr(instance, "driver", None)
        if not driver:
            return None
        if driver.display_name:
            return driver.display_name
        user = getattr(driver, "user", None)
        if not user:
            return None
        full = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if full:
            return full
        return user.phone or user.email

    def get_vehicle_summary(self, instance):
        vehicle = getattr(instance, "preferred_vehicle", None)
        if not vehicle:
            return None
        title = f"{vehicle.year or ''} {vehicle.make} {vehicle.model}".strip()
        if vehicle.color:
            return f"{title} · {vehicle.color}"
        return title


class JobSerializer(serializers.ModelSerializer):
    mechanic_name = serializers.SerializerMethodField(read_only=True)
    driver_name = serializers.SerializerMethodField(read_only=True)
    service_category_name = serializers.SerializerMethodField(read_only=True)

    def get_mechanic_name(self, obj: Job):
        mechanic = getattr(obj, "mechanic", None)
        if not mechanic:
            return None
        if mechanic.business_name:
            return mechanic.business_name
        user = getattr(mechanic, "user", None)
        if not user:
            return None
        full = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if full:
            return full
        return user.phone or user.email

    def get_driver_name(self, obj: Job):
        service_request = getattr(obj, "service_request", None)
        driver = getattr(service_request, "driver", None) if service_request else None
        if not driver:
            return None
        if driver.display_name:
            return driver.display_name
        user = getattr(driver, "user", None)
        if not user:
            return None
        full = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if full:
            return full
        return user.phone or user.email

    def get_service_category_name(self, obj: Job):
        service_request = getattr(obj, "service_request", None)
        category = getattr(service_request, "category", None) if service_request else None
        return category.name if category else None

    class Meta:
        model = Job
        fields = (
            "id",
            "service_request",
            "mechanic",
            "mechanic_name",
            "driver_name",
            "service_category_name",
            "status",
            "accepted_at",
            "completed_at",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "service_request",
            "mechanic",
            "accepted_at",
            "completed_at",
            "created_at",
            "updated_at",
        )
