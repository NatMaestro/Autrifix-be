from rest_framework import serializers

from apps.jobs.models import ServiceCategory
from apps.mechanics.models import MechanicProfile, MechanicServiceOffering


class MechanicProfileSerializer(serializers.ModelSerializer):
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
