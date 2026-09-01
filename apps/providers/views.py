from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import IsProvider
from apps.providers import services as provider_services
from apps.providers.models import ProviderServiceOffering
from apps.providers.selectors import ensure_provider_profile
from apps.providers.serializers import (
    ProviderProfileSerializer,
    ProviderServiceOfferingSerializer,
    ProviderVerificationCreateSerializer,
    ProviderVerificationStatusSerializer,
)
from apps.providers.verification import (
    accept_min_level,
    can_accept_jobs,
    can_see_exact_locations,
    evaluate_automatic_level,
    is_profile_complete,
    missing_profile_requirements,
)


class ProviderProfileDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ProviderProfileSerializer
    permission_classes = (permissions.IsAuthenticated, IsProvider)

    def get_object(self):
        return ensure_provider_profile(self.request.user)


class ProviderOfferingQuerysetMixin:
    """Offerings are always scoped to the calling provider's own profile."""

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProviderServiceOffering.objects.none()
        provider = ensure_provider_profile(self.request.user)
        return (
            ProviderServiceOffering.objects.filter(provider=provider)
            .select_related("category")
            .order_by("-created_at")
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return ctx
        # Needed by the serializer's uniqueness check, since ``provider`` is not posted.
        ctx["provider"] = ensure_provider_profile(self.request.user)
        return ctx


class ProviderServiceOfferingListCreateView(ProviderOfferingQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = ProviderServiceOfferingSerializer
    permission_classes = (permissions.IsAuthenticated, IsProvider)

    def perform_create(self, serializer):
        serializer.save(provider=ensure_provider_profile(self.request.user))


class ProviderServiceOfferingDetailView(ProviderOfferingQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProviderServiceOfferingSerializer
    permission_classes = (permissions.IsAuthenticated, IsProvider)
    lookup_field = "id"


@extend_schema(tags=["providers"])
class ProviderVerificationView(generics.GenericAPIView):
    """Read verification status, or submit documents for review — SPEC-013."""

    permission_classes = (permissions.IsAuthenticated, IsProvider)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ProviderVerificationCreateSerializer
        return ProviderVerificationStatusSerializer

    def _status_payload(self, provider):
        # Re-evaluated on read so a provider who has just completed their profile sees the
        # new level immediately, without a signal firing on every offering change.
        evaluate_automatic_level(provider)
        return {
            "verification_level": provider.verification_level,
            "exact_location_unlocked": can_see_exact_locations(provider),
            "can_accept_jobs": can_accept_jobs(provider),
            "accept_requires_level": accept_min_level(),
            "profile_complete": is_profile_complete(provider),
            "phone_verified": bool(provider.user.is_phone_verified),
            "missing_requirements": missing_profile_requirements(provider),
            "submission": provider.verifications.order_by("-submitted_at").first(),
        }

    @extend_schema(responses={200: ProviderVerificationStatusSerializer})
    def get(self, request):
        provider = ensure_provider_profile(request.user)
        return Response(ProviderVerificationStatusSerializer(self._status_payload(provider)).data)

    @extend_schema(
        request=ProviderVerificationCreateSerializer,
        responses={201: ProviderVerificationStatusSerializer, 409: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        provider = ensure_provider_profile(request.user)
        serializer = ProviderVerificationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider_services.submit_verification(
            provider=provider, documents=serializer.validated_data
        )
        return Response(
            ProviderVerificationStatusSerializer(self._status_payload(provider)).data,
            status=status.HTTP_201_CREATED,
        )
