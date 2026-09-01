from rest_framework import serializers

from apps.jobs.models import ServiceCategory
from apps.providers.models import ProviderProfile, ProviderServiceOffering, ProviderVerification


class ProviderProfileSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        is_available = attrs.get("is_available", getattr(self.instance, "is_available", False))
        base_latitude = attrs.get("base_latitude", getattr(self.instance, "base_latitude", None))
        base_longitude = attrs.get("base_longitude", getattr(self.instance, "base_longitude", None))
        if is_available and (base_latitude is None or base_longitude is None):
            raise serializers.ValidationError(
                {"is_available": "Set your workshop location before going online."}
            )
        # A workshop location is a pair; accepting half of one leaves the profile in a
        # state discovery silently ignores.
        supplied = {k for k in ("base_latitude", "base_longitude") if k in attrs}
        if len(supplied) == 1:
            missing = ({"base_latitude", "base_longitude"} - supplied).pop()
            raise serializers.ValidationError(
                {missing: "Send base_latitude and base_longitude together."}
            )
        return attrs

    class Meta:
        model = ProviderProfile
        fields = (
            "id",
            "business_name",
            "provider_type",
            "bio",
            "base_latitude",
            "base_longitude",
            "service_radius_km",
            "is_available",
            "rating_avg",
            "rating_count",
            "verification_level",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "rating_avg",
            "rating_count",
            "verification_level",
            "created_at",
            "updated_at",
        )


class ProviderServiceOfferingSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    category = serializers.PrimaryKeyRelatedField(queryset=ServiceCategory.objects.filter(is_active=True))

    def validate(self, attrs):
        """Enforce ``unique_together`` in the serializer.

        DRF cannot generate a ``UniqueTogetherValidator`` here because ``provider`` is
        injected by the view rather than posted, so a duplicate previously reached the
        database and surfaced as a 500.
        """
        provider = self.context.get("provider")
        if provider is None:
            return attrs

        category = attrs.get("category", getattr(self.instance, "category", None))
        title = attrs.get("title", getattr(self.instance, "title", "") or "")
        clash = ProviderServiceOffering.objects.filter(
            provider=provider, category=category, title=title
        )
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                {"title": "You already offer this category under this title."}
            )
        return attrs

    class Meta:
        model = ProviderServiceOffering
        fields = (
            "id",
            "category",
            "category_name",
            "category_slug",
            "title",
            "description",
            "hourly_rate",
            "per_km_rate",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class ProviderVerificationSubmissionSerializer(serializers.ModelSerializer):
    """Status of a submission. Deliberately never exposes the uploaded images."""

    class Meta:
        model = ProviderVerification
        fields = (
            "id",
            "requested_level",
            "status",
            "submitted_at",
            "reviewed_at",
            "review_notes",
        )
        read_only_fields = fields


class ProviderVerificationCreateSerializer(serializers.ModelSerializer):
    id_document = serializers.ImageField(required=True)
    selfie = serializers.ImageField(required=True)
    workshop_photo = serializers.ImageField(required=True)

    class Meta:
        model = ProviderVerification
        fields = ("id_document", "selfie", "workshop_photo")


class ProviderVerificationStatusSerializer(serializers.Serializer):
    """Everything a provider needs to understand where they stand and what is missing."""

    verification_level = serializers.CharField()
    exact_location_unlocked = serializers.BooleanField()
    can_accept_jobs = serializers.BooleanField()
    accept_requires_level = serializers.CharField()
    profile_complete = serializers.BooleanField()
    phone_verified = serializers.BooleanField()
    missing_requirements = serializers.ListField(child=serializers.CharField())
    submission = ProviderVerificationSubmissionSerializer(allow_null=True)
