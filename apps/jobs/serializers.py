from decimal import Decimal

from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.plumbing import build_basic_type
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import UserRole
from apps.ai.issue_router import train_from_service_request
from apps.customers.models import Vehicle
from apps.jobs import services as job_services
from apps.jobs.models import Job, Quote, ServiceCategory, ServiceRequest


def _person_name(user, fallback: str) -> str:
    """Display name for a counterparty.

    Deliberately does **not** fall back to a phone number or email address: this value
    is shown to providers who have not yet been matched. See ``specs/002`` REQ-4.
    """
    if user is None:
        return fallback
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full or fallback


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
            "requires_destination",
            "is_active",
        )


class ServiceCategoryMiniSerializer(serializers.ModelSerializer):
    """Minimal fields for endpoints like `/services/nearby/`.

    ``requires_destination`` is included because a client cannot build a correct request
    without it: these categories relocate the vehicle, so the request is rejected unless it
    says where to. Omitting the flag left clients guessing, and the web app guessed wrong —
    it never asked, so every tow request failed validation.
    """

    class Meta:
        model = ServiceCategory
        fields = ("id", "name", "slug", "requires_destination")


class CategoryRelatedField(serializers.PrimaryKeyRelatedField):
    """Accepts a category id on write, returns the whole category on read.

    Clients need the category's name to render a request, and a second round trip per row
    to resolve a UUID would be absurd. The nesting is declared here rather than applied in
    ``to_representation`` so the OpenAPI schema reflects it.
    """

    def use_pk_only_optimization(self) -> bool:
        # Serializing the full object requires the instance, not just its primary key.
        return False

    def to_representation(self, value):
        return ServiceCategorySerializer(value).data


class CategoryRelatedFieldExtension(OpenApiSerializerFieldExtension):
    """Teach the schema that this field is asymmetric.

    A plain ``extend_schema_field`` would document one shape for both directions, so a
    generated client would be wrong on either read or write. Splitting by ``direction``
    is the only way to describe the field as it actually behaves.
    """

    target_class = "apps.jobs.serializers.CategoryRelatedField"

    def map_serializer_field(self, auto_schema, direction):
        if direction == "request":
            return build_basic_type(OpenApiTypes.UUID)
        return auto_schema.resolve_serializer(ServiceCategorySerializer, direction).ref


class ServiceRequestSerializer(serializers.ModelSerializer):
    category = CategoryRelatedField(
        queryset=ServiceCategory.objects.filter(is_active=True),
    )
    preferred_vehicle = serializers.PrimaryKeyRelatedField(
        queryset=Vehicle.objects.all(),
        required=False,
        allow_null=True,
    )
    customer_name = serializers.SerializerMethodField(read_only=True)
    vehicle_summary = serializers.SerializerMethodField(read_only=True)
    distance_km = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ServiceRequest
        fields = (
            "id",
            "category",
            "description",
            "latitude",
            "longitude",
            "destination_latitude",
            "destination_longitude",
            "status",
            "preferred_vehicle",
            "customer_name",
            "vehicle_summary",
            "distance_km",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "status", "created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Restrict the selectable vehicles to the requesting customer's own garage, so a
        # foreign vehicle id can never be referenced or read back.
        customer_profile = self.context.get("customer_profile")
        field = self.fields.get("preferred_vehicle")
        if field is not None:
            field.queryset = (
                Vehicle.objects.filter(customer=customer_profile)
                if customer_profile is not None
                else Vehicle.objects.none()
            )

    def validate(self, attrs):
        if self.instance is None:
            if attrs.get("latitude") is None or attrs.get("longitude") is None:
                raise serializers.ValidationError(
                    {"latitude": "latitude and longitude are required to create a request."}
                )

        category = attrs.get("category", getattr(self.instance, "category", None))
        dest_lat = attrs.get(
            "destination_latitude", getattr(self.instance, "destination_latitude", None)
        )
        dest_lng = attrs.get(
            "destination_longitude", getattr(self.instance, "destination_longitude", None)
        )

        # A destination is a pair or it is nothing — half of one is unusable.
        supplied = {
            k for k in ("destination_latitude", "destination_longitude") if attrs.get(k) is not None
        }
        if len(supplied) == 1:
            missing = ({"destination_latitude", "destination_longitude"} - supplied).pop()
            raise serializers.ValidationError(
                {missing: "Send destination_latitude and destination_longitude together."}
            )

        if category is not None and category.requires_destination:
            if dest_lat is None or dest_lng is None:
                raise serializers.ValidationError(
                    {
                        "destination_latitude": (
                            f"'{category.name}' relocates the vehicle, so a destination is required."
                        )
                    }
                )
        return attrs

    def create(self, validated_data):
        validated_data["customer"] = self.context["customer_profile"]
        instance = super().create(validated_data)
        # Online training: every labeled request improves ML routing over time.
        train_from_service_request(instance)
        return instance

    def get_customer_name(self, instance) -> str:
        customer = getattr(instance, "customer", None)
        if not customer:
            return "Customer"
        return customer.display_name or _person_name(getattr(customer, "user", None), "Customer")

    def get_vehicle_summary(self, instance) -> str | None:
        vehicle = getattr(instance, "preferred_vehicle", None)
        if not vehicle:
            return None
        title = f"{vehicle.year or ''} {vehicle.make} {vehicle.model}".strip()
        if vehicle.color:
            return f"{title} · {vehicle.color}"
        return title

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_distance_km(self, instance):
        """Distance from the searching provider, when the view computed one.

        Present on the nearby-requests feed so a provider can judge whether a job is worth
        accepting (ADR-015); ``null`` on a customer's own request list, where there is no
        reference point.
        """
        distance_m = getattr(instance, "_distance_m", None)
        return round(distance_m / 1000.0, 2) if distance_m is not None else None


class QuoteSerializer(serializers.ModelSerializer):
    """A price proposal. Read-only over the wire — quotes are created and answered
    through their own endpoints so the state change goes through the service layer."""

    class Meta:
        model = Quote
        fields = (
            "id",
            "job",
            "amount",
            "currency",
            "notes",
            "status",
            "created_at",
            "responded_at",
        )
        read_only_fields = fields


class QuoteCreateSerializer(serializers.Serializer):
    """Provider input. ``currency`` is not accepted — it is the platform's, not the
    caller's, so a client cannot quote in a currency nobody settles in."""

    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class QuoteRespondSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class JobSerializer(serializers.ModelSerializer):
    provider_name = serializers.SerializerMethodField(read_only=True)
    provider_verification_level = serializers.SerializerMethodField(read_only=True)
    customer_name = serializers.SerializerMethodField(read_only=True)
    service_category_name = serializers.SerializerMethodField(read_only=True)
    latest_quote = serializers.SerializerMethodField(read_only=True)
    amount_variance = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Job
        fields = (
            "id",
            "service_request",
            "provider",
            "provider_name",
            "provider_verification_level",
            "customer_name",
            "service_category_name",
            "status",
            "accepted_at",
            "work_finished_at",
            "completed_at",
            "final_amount",
            "currency",
            "auto_confirmed",
            "latest_quote",
            "amount_variance",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "service_request",
            "provider",
            "accepted_at",
            "work_finished_at",
            "completed_at",
            # Written only as part of the `active -> awaiting_confirmation` transition,
            # never as a standalone edit (SPEC-015 REQ-7).
            "currency",
            # Set by the sweep, never by a client. Exposed so the UI can tell a job the
            # customer agreed to from one the timeout closed against them (SPEC-016 REQ-2).
            "auto_confirmed",
            "created_at",
            "updated_at",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ``notes`` is the provider's working record; a customer may read it but not edit it.
        request = self.context.get("request")
        actor_role = getattr(getattr(request, "user", None), "role", None)
        if actor_role == UserRole.CUSTOMER and "notes" in self.fields:
            self.fields["notes"].read_only = True

    @extend_schema_field(QuoteSerializer(allow_null=True))
    def get_latest_quote(self, obj: Job):
        """The most recent quote in any state, so a client can render the price thread
        without a second request."""
        quote = obj.quotes.first()  # Meta.ordering is -created_at
        return QuoteSerializer(quote).data if quote else None

    @extend_schema_field(serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True))
    def get_amount_variance(self, obj: Job):
        """How far the recorded amount landed from the price the customer agreed to.

        ``None`` when there is nothing to compare — no accepted quote, or work not yet
        finished. Positive means the customer is being asked for more than they agreed to;
        the client should say so plainly before the confirm button (SPEC-015 REQ-6).
        """
        if obj.final_amount is None:
            return None
        agreed = job_services.accepted_quote(obj)
        if agreed is None:
            return None
        return obj.final_amount - agreed.amount

    def get_provider_name(self, obj: Job) -> str:
        provider = getattr(obj, "provider", None)
        if not provider:
            return "Provider"
        return provider.business_name or _person_name(getattr(provider, "user", None), "Provider")

    @extend_schema_field(serializers.CharField())
    def get_provider_verification_level(self, obj: Job) -> str:
        """Trust badge shown to the customer (SPEC-013 REQ-4)."""
        provider = getattr(obj, "provider", None)
        return provider.verification_level if provider else "none"

    def get_customer_name(self, obj: Job) -> str:
        service_request = getattr(obj, "service_request", None)
        customer = getattr(service_request, "customer", None) if service_request else None
        if not customer:
            return "Customer"
        return customer.display_name or _person_name(getattr(customer, "user", None), "Customer")

    def get_service_category_name(self, obj: Job) -> str | None:
        service_request = getattr(obj, "service_request", None)
        category = getattr(service_request, "category", None) if service_request else None
        return category.name if category else None
