import math
from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import UserRole
from apps.accounts.permissions import IsCustomer, IsCustomerOrProvider, IsProvider
from apps.core.exceptions import Conflict
from apps.core.geo import coarsen_coordinate, distance_meters
from apps.core.validators import parse_coordinate_params
from apps.customers.selectors import ensure_customer_profile
from apps.jobs import services as job_services
from apps.jobs.limits import assert_can_open_request
from apps.jobs.models import Job, Quote, ServiceCategory, ServiceRequest, ServiceRequestStatus
from apps.jobs.serializers import (
    JobSerializer,
    QuoteCreateSerializer,
    QuoteRespondSerializer,
    QuoteSerializer,
    ServiceCategoryMiniSerializer,
    ServiceRequestSerializer,
)
from apps.providers.nearby_presence import list_nearby_provider_previews
from apps.providers.selectors import get_provider_profile
from apps.providers.verification import (
    TOW_CAPABLE_TYPES,
    ProviderType,
    can_see_exact_locations,
)

#: How long an open request stays visible in the provider feed. Measured against
#: ``updated_at`` so a request returned to the pool by a declining provider becomes
#: discoverable again. See ``specs/006-matching-discovery.md`` REQ-3.
OPEN_REQUEST_FEED_WINDOW = timedelta(minutes=30)

#: Maximum rows returned by either discovery endpoint.
DISCOVERY_RESULT_LIMIT = 50


_JOB_SELECT_RELATED = (
    "service_request",
    "service_request__category",
    "service_request__customer__user",
    "provider",
    "provider__user",
)


@extend_schema(
    parameters=[
        OpenApiParameter("lat", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
        OpenApiParameter("lng", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
        OpenApiParameter(
            "radius_km",
            OpenApiTypes.FLOAT,
            OpenApiParameter.QUERY,
            description="Radius in km for counting nearby available providers (max 500)",
            default=50,
        ),
        OpenApiParameter(
            "provider_type",
            OpenApiTypes.STR,
            OpenApiParameter.QUERY,
            description="Restrict to a trade: mechanic | tow. Providers of type 'both' always match.",
            required=False,
        ),
    ],
    responses={
        200: inline_serializer(
            name="ServicesNearbyResponse",
            fields={
                "categories": serializers.ListField(child=serializers.DictField()),
                "nearby_providers_count": serializers.IntegerField(),
                "radius_km": serializers.FloatField(),
                "truncated": serializers.BooleanField(),
                "providers": serializers.ListField(child=serializers.DictField()),
            },
        )
    },
    tags=["services"],
)
class ServicesNearbyView(APIView):
    """Active service categories plus available providers within radius of ``lat``/``lng``.

    Authentication is required: the response contains providers' exact workshop
    coordinates, which must not be enumerable by anonymous callers
    (``specs/008-location.md`` SECGAP-008-1).
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        lat, lng, radius_km = parse_coordinate_params(request.query_params, default_radius_km=50)

        categories = list(
            ServiceCategory.objects.filter(is_active=True)
            .only("id", "name", "slug", "description")
            .order_by("name")
        )
        provider_type = (request.query_params.get("provider_type") or "").strip() or None
        if provider_type and provider_type not in ProviderType.values:
            raise ValidationError(
                {"provider_type": f"Must be one of: {', '.join(ProviderType.values)}."}
            )
        nearby_providers = list_nearby_provider_previews(
            lat, lng, radius_km, provider_type=provider_type
        )

        return Response(
            {
                "categories": ServiceCategoryMiniSerializer(categories, many=True).data,
                "nearby_providers_count": len(nearby_providers),
                "radius_km": radius_km,
                "truncated": len(nearby_providers) >= DISCOVERY_RESULT_LIMIT,
                "providers": nearby_providers,
            }
        )


class CustomerScopedRequestMixin:
    """Resolves the caller's customer profile once and shares it with the serializer."""

    def get_customer_profile(self):
        return ensure_customer_profile(self.request.user)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return ctx
        ctx["customer_profile"] = self.get_customer_profile()
        return ctx

    def perform_create(self, serializer):
        assert_can_open_request(self.get_customer_profile())
        serializer.save()


@extend_schema(
    summary="Create service request",
    request=ServiceRequestSerializer,
    responses={201: ServiceRequestSerializer},
    tags=["requests"],
)
class RequestCreateView(CustomerScopedRequestMixin, generics.CreateAPIView):
    """Alias for creating a service request (same as ``POST /jobs/requests/``)."""

    serializer_class = ServiceRequestSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomer)


@extend_schema(
    summary="List my jobs",
    responses={200: JobSerializer(many=True)},
    tags=["jobs"],
)
class JobListView(generics.ListAPIView):
    """Jobs where the current user is the customer (via request) or assigned provider."""

    serializer_class = JobSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomerOrProvider)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Job.objects.none()
        return participant_jobs(self.request.user).order_by("-created_at")


def participant_jobs(user):
    """Jobs the user takes part in, as customer or as assigned provider."""
    return (
        Job.objects.filter(
            Q(service_request__customer__user=user) | Q(provider__user=user)
        )
        .select_related(*_JOB_SELECT_RELATED)
        .distinct()
    )


@extend_schema(tags=["jobs"])
class JobDetailView(generics.RetrieveUpdateAPIView):
    """Read a job, or request a state transition by sending a new ``status``.

    Transitions are validated against the table in ``apps.jobs.services``; an illegal
    move returns ``409``.
    """

    serializer_class = JobSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomerOrProvider)
    lookup_field = "id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Job.objects.none()
        return participant_jobs(self.request.user)

    def perform_update(self, serializer):
        job = self.get_object()
        target_status = serializer.validated_data.pop("status", None)
        final_amount = serializer.validated_data.pop("final_amount", None)

        # An amount is a property of finishing, not an editable field. Accepting it on its
        # own would let a provider revise the bill after the customer had already agreed.
        if final_amount is not None and target_status is None:
            raise Conflict("An amount can only be recorded while finishing the job.")

        # Persist any non-status edits (currently only ``notes``, provider-only) first.
        if serializer.validated_data:
            serializer.save()

        if target_status is not None and target_status != job.status:
            job = job_services.transition_job(
                job=job,
                target_status=target_status,
                actor=self.request.user,
                final_amount=final_amount,
            )
            serializer.instance = job


class ServiceCategoryListView(generics.ListAPIView):
    queryset = ServiceCategory.objects.filter(is_active=True)
    serializer_class = ServiceCategoryMiniSerializer
    permission_classes = (permissions.IsAuthenticated,)


class ServiceRequestListCreateView(CustomerScopedRequestMixin, generics.ListCreateAPIView):
    serializer_class = ServiceRequestSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomer)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ServiceRequest.objects.none()
        return (
            ServiceRequest.objects.filter(customer=self.get_customer_profile())
            .select_related("category", "customer__user", "preferred_vehicle")
        )


class ServiceRequestDetailView(CustomerScopedRequestMixin, generics.RetrieveUpdateAPIView):
    serializer_class = ServiceRequestSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomer)
    lookup_field = "id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ServiceRequest.objects.none()
        return ServiceRequest.objects.filter(customer=self.get_customer_profile()).select_related(
            "category", "customer__user", "preferred_vehicle"
        )


@extend_schema(
    summary="Cancel my service request",
    request=None,
    responses={200: ServiceRequestSerializer, 409: OpenApiTypes.OBJECT},
    tags=["requests"],
)
class ServiceRequestCancelView(CustomerScopedRequestMixin, generics.GenericAPIView):
    """Customer-initiated cancellation. Also cancels any live job on the request."""

    serializer_class = ServiceRequestSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomer)
    lookup_field = "id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ServiceRequest.objects.none()
        return ServiceRequest.objects.filter(customer=self.get_customer_profile())

    def post(self, request, *args, **kwargs):
        service_request = job_services.cancel_service_request(
            service_request=self.get_object(), actor=request.user
        )
        return Response(self.get_serializer(service_request).data, status=status.HTTP_200_OK)


class NearbyOpenRequestsView(generics.ListAPIView):
    """Open requests near a provider, nearest first.

    Restricted to requests touched within :data:`OPEN_REQUEST_FEED_WINDOW`, capped at
    :data:`DISCOVERY_RESULT_LIMIT`.
    """

    serializer_class = ServiceRequestSerializer
    permission_classes = (permissions.IsAuthenticated, IsProvider)
    queryset = ServiceRequest.objects.filter(status=ServiceRequestStatus.OPEN)
    pagination_class = None

    @extend_schema(
        parameters=[
            OpenApiParameter("lat", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("lng", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter(
                "radius_km",
                OpenApiTypes.FLOAT,
                OpenApiParameter.QUERY,
                description="Search radius in kilometers (max 500)",
                default=50,
            ),
        ],
        responses={200: ServiceRequestSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        provider = get_provider_profile(request.user)
        show_exact = can_see_exact_locations(provider)
        lat, lng, radius_km = parse_coordinate_params(request.query_params, default_radius_km=50)
        radius_m = radius_km * 1000

        lat_pad = radius_km / 111.0
        lng_pad = radius_km / max(111.0 * math.cos(math.radians(lat)), 0.01)

        qs = (
            ServiceRequest.objects.filter(status=ServiceRequestStatus.OPEN)
            .filter(updated_at__gte=timezone.now() - OPEN_REQUEST_FEED_WINDOW)
            .select_related("category", "customer__user", "preferred_vehicle")
            .filter(
                latitude__gte=lat - lat_pad,
                latitude__lte=lat + lat_pad,
                longitude__gte=lng - lng_pad,
                longitude__lte=lng + lng_pad,
            )
        )
        # Still not filtered by service offerings (ADR-009) — but trade capability is a
        # different thing from a declared preference. A repair-only provider cannot tow a
        # vehicle, so showing them tow work is noise, not opportunity (SPEC-014 REQ-3).
        if provider.provider_type not in TOW_CAPABLE_TYPES:
            qs = qs.exclude(category__requires_destination=True)
        scored: list[tuple[float, ServiceRequest]] = []
        for sr in qs:
            # Radius filtering always uses the true position, so an unverified provider
            # still sees the right set of jobs — only the precision they are shown differs.
            true_distance_m = distance_meters(lat, lng, sr.latitude, sr.longitude)
            if true_distance_m > radius_m:
                continue

            if show_exact:
                sr._distance_m = true_distance_m
            else:
                # Coarsen once, then derive everything from the coarsened point. Publishing
                # an exact distance next to a snapped coordinate would let the true point be
                # recovered by trilateration (SPEC-013 REQ-2).
                snapped_lat, snapped_lng = coarsen_coordinate(sr.latitude, sr.longitude)
                sr.latitude = snapped_lat
                sr.longitude = snapped_lng
                sr._distance_m = distance_meters(lat, lng, snapped_lat, snapped_lng)

            scored.append((true_distance_m, sr))

        scored.sort(key=lambda x: x[0])
        page = [x[1] for x in scored[:DISCOVERY_RESULT_LIMIT]]
        return Response(self.get_serializer(page, many=True).data)


@extend_schema(
    parameters=[
        OpenApiParameter("request_id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="Open service request id"),
    ],
    request=None,
    responses={201: JobSerializer, 404: OpenApiTypes.OBJECT, 409: OpenApiTypes.OBJECT},
    tags=["jobs"],
)
class JobAcceptView(APIView):
    """Claim an open request. Returns ``409`` if another provider won the race."""

    permission_classes = (permissions.IsAuthenticated, IsProvider)

    def post(self, request, request_id):
        provider = get_provider_profile(request.user)
        job = job_services.accept_service_request(
            service_request_id=request_id,
            provider=provider,
        )
        return Response(
            JobSerializer(job, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


def _participant_job_or_404(user, job_id):
    """A job the caller is a party to, or 404 — never 403, so job ids stay unguessable."""
    return get_object_or_404(participant_jobs(user), id=job_id)


@extend_schema(
    tags=["jobs"],
    summary="List or submit price quotes for a job",
    request=QuoteCreateSerializer,
    responses={200: QuoteSerializer(many=True), 201: QuoteSerializer},
)
class JobQuoteListCreateView(generics.ListCreateAPIView):
    """Both parties read the price thread; only the assigned provider adds to it.

    Quoting is optional — a tow price is computable from distance up front, and a trivial
    repair may not be worth the round trip. Where it earns its keep is a repair whose cost
    is unknowable until someone looks (SPEC-015 REQ-5).
    """

    permission_classes = (permissions.IsAuthenticated, IsCustomerOrProvider)

    def get_serializer_class(self):
        return QuoteCreateSerializer if self.request.method == "POST" else QuoteSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Quote.objects.none()
        job = _participant_job_or_404(self.request.user, self.kwargs["job_id"])
        return job.quotes.all()

    def create(self, request, *args, **kwargs):
        # Checked before the profile lookup: without this a customer would fall through to
        # `get_provider_profile` and get a 409 about a missing provider profile, which
        # describes the wrong problem.
        if request.user.role != UserRole.PROVIDER:
            raise PermissionDenied("Only a provider can quote on a job.")

        job = _participant_job_or_404(request.user, self.kwargs["job_id"])
        provider = get_provider_profile(request.user)

        serializer = QuoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quote = job_services.submit_quote(
            job=job,
            provider=provider,
            amount=serializer.validated_data["amount"],
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(QuoteSerializer(quote).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["jobs"],
    summary="Accept or decline a price quote",
    request=QuoteRespondSerializer,
    responses={200: QuoteSerializer},
)
class QuoteRespondView(APIView):
    """Customer-only. Declining is not a cancellation — it invites a revised quote."""

    permission_classes = (permissions.IsAuthenticated, IsCustomerOrProvider)

    def post(self, request, job_id, quote_id):
        # Guarded before `ensure_customer_profile`, which would otherwise create a customer
        # profile for a provider as a side effect of them calling the wrong endpoint.
        if request.user.role != UserRole.CUSTOMER:
            raise PermissionDenied("Only the customer can respond to a quote.")

        job = _participant_job_or_404(request.user, job_id)
        quote = get_object_or_404(Quote, id=quote_id, job=job)
        customer = ensure_customer_profile(request.user)

        serializer = QuoteRespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quote = job_services.respond_to_quote(
            quote=quote,
            customer=customer,
            accept=serializer.validated_data["accept"],
        )
        return Response(QuoteSerializer(quote).data, status=status.HTTP_200_OK)
