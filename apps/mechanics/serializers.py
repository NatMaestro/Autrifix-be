from rest_framework import serializers

from apps.jobs.models import ServiceCategory
from apps.mechanics.models import MechanicProfile, MechanicServiceOffering


class MechanicProfileSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        is_available = attrs.get("is_available", getattr(self.instance, "is_available", False))
        base_latitude = attrs.get("base_latitude", getattr(self.instance, "base_latitude", None))
        base_longitude = attrs.get("base_longitude", getattr(self.instance, "base_longitude", None))
        if is_available and (base_latitude is None or base_longitude is None):
            raise serializers.ValidationError(
                {"is_available": "Set your workshop location before going online."}
            )
        return attrs

    class Meta:
        model = MechanicProfile
        fields = (
            "id",
            "business_name",
            "bio",
            "base_latitude",
            "base_longitude",
            "service_radius_km",
            "is_available",
            "rating_avg",
            "rating_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "rating_avg", "rating_count", "created_at", "updated_at")


class MechanicServiceOfferingSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    category = serializers.PrimaryKeyRelatedField(queryset=ServiceCategory.objects.filter(is_active=True))

    class Meta:
        model = MechanicServiceOffering
        fields = (
            "id",
            "category",
            "category_name",
            "category_slug",
            "title",
            "description",
            "hourly_rate",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
