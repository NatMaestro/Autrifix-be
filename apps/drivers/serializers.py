from rest_framework import serializers

from apps.drivers.models import DriverProfile, Vehicle


class VehicleSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        primary = attrs.get("is_primary", getattr(self.instance, "is_primary", False))
        if primary and self.instance is None:
            driver = self.context["driver_profile"]
            Vehicle.objects.filter(driver=driver, is_primary=True).update(is_primary=False)
        if primary and self.instance is not None:
            driver = self.instance.driver
            Vehicle.objects.filter(driver=driver, is_primary=True).exclude(id=self.instance.id).update(
                is_primary=False
            )
        return attrs

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


class DriverProfileSerializer(serializers.ModelSerializer):
    vehicles = VehicleSerializer(many=True, read_only=True)
    latitude = serializers.FloatField(write_only=True, required=False)
    longitude = serializers.FloatField(write_only=True, required=False)

    class Meta:
        model = DriverProfile
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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.home_latitude is not None and instance.home_longitude is not None:
            data["latitude"] = instance.home_latitude
            data["longitude"] = instance.home_longitude
        return data

    def update(self, instance, validated_data):
        lat = validated_data.pop("latitude", None)
        lng = validated_data.pop("longitude", None)
        if lat is not None and lng is not None:
            instance.home_latitude = lat
            instance.home_longitude = lng
        return super().update(instance, validated_data)
