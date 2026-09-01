from django.db import transaction
from rest_framework import serializers

from apps.core.validators import (
    LATITUDE_MAX,
    LATITUDE_MIN,
    LONGITUDE_MAX,
    LONGITUDE_MIN,
)
from apps.customers.models import CustomerProfile, Vehicle


class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = (
            "id",
            "label",
            "make",
            "model",
            "year",
            "trim",
            "color",
            "engine",
            "license_plate",
            "vin",
            "tire_size",
            "battery_group",
            "belt_part_number",
            "oil_spec",
            "coolant_type",
            "notes",
            "extra",
            "is_primary",
            "photo",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_year(self, value):
        if value is not None and not (1900 <= value <= 2100):
            raise serializers.ValidationError("Enter a year between 1900 and 2100.")
        return value

    def validate_extra(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("extra must be a JSON object.")
        return value

    def _demote_other_primaries(self, customer, *, exclude_pk=None) -> None:
        qs = Vehicle.objects.filter(customer=customer, is_primary=True)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        qs.update(is_primary=False)

    @transaction.atomic
    def create(self, validated_data):
        # Demotion happens here, not in ``validate``: validation must not write, and the
        # previous implementation also read a context key this view never sets, which
        # made ``is_primary: true`` a 500 (``specs/004-vehicles.md`` CONFLICT-004-B).
        instance = super().create(validated_data)
        if instance.is_primary:
            self._demote_other_primaries(instance.customer, exclude_pk=instance.pk)
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        if instance.is_primary:
            self._demote_other_primaries(instance.customer, exclude_pk=instance.pk)
        return instance


class CustomerProfileSerializer(serializers.ModelSerializer):
    vehicles = VehicleSerializer(many=True, read_only=True)
    # Declared explicitly, so the model validators on ``home_latitude`` / ``home_longitude``
    # do not apply — the bounds are repeated here deliberately.
    # `source` maps both directions, so DRF reads and writes `home_latitude` itself. These
    # were `write_only` with a `to_representation` override that returned them anyway — the
    # value was readable in practice while the schema said it was not, so no generated client
    # knew the saved location existed. Same failure as `ServiceRequest.category`.
    latitude = serializers.FloatField(
        source="home_latitude",
        required=False,
        allow_null=True,
        min_value=LATITUDE_MIN,
        max_value=LATITUDE_MAX,
    )
    longitude = serializers.FloatField(
        source="home_longitude",
        required=False,
        allow_null=True,
        min_value=LONGITUDE_MIN,
        max_value=LONGITUDE_MAX,
    )

    class Meta:
        model = CustomerProfile
        fields = (
            "id",
            "display_name",
            "latitude",
            "longitude",
            "vehicles",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        # `source` means these arrive under their model names by this point.
        supplied = {k for k in ("home_latitude", "home_longitude") if k in attrs}
        if len(supplied) == 1:
            missing = ({"home_latitude", "home_longitude"} - supplied).pop()
            # Previously a lone coordinate was silently discarded with a 200.
            field = "latitude" if missing == "home_latitude" else "longitude"
            raise serializers.ValidationError({field: "Send latitude and longitude together."})
        return attrs
