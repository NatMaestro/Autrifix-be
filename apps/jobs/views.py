import math
from datetime import timedelta

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.accounts.permissions import IsDriver, IsDriverOrMechanic, IsMechanic
from apps.core.geo import distance_meters
from apps.drivers.models import DriverProfile
from apps.jobs.models import Job, JobStatus, ServiceCategory, ServiceRequest, ServiceRequestStatus
from apps.jobs.serializers import (
    JobSerializer,
    ServiceCategoryMiniSerializer,
    ServiceCategorySerializer,
    ServiceRequestSerializer,
)
from apps.chat.models import ChatRoom
from apps.mechanics.models import MechanicProfile, MechanicServiceOffering
from apps.mechanics.nearby_presence import list_nearby_mechanic_previews


def ensure_driver_profile(user):
    profile, _ = DriverProfile.objects.get_or_create(user=user)
    return profile


@extend_schema(
    parameters=[
        OpenApiParameter("lat", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
        OpenApiParameter("lng", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
        OpenApiParameter(
            "radius_km",
            OpenApiTypes.FLOAT,
            OpenApiParameter.QUERY,
            description="Radius in km for counting nearby available mechanics",
            default=50,
        ),
    ],
    responses={
        200: inline_serializer(
            name="ServicesNearbyResponse",
            fields={
                "categories": serializers.ListField(child=serializers.DictField()),
                "nearby_mechanics_count": serializers.IntegerField(),
                "radius_km": serializers.FloatField(),
                "mechanics": serializers.ListField(child=serializers.DictField()),
            },
        )
    },
    tags=["services"],
)
class ServicesNearbyView(APIView):
    """Active service categories plus how many mechanics are within radius of ``lat``/``lng``."""

    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        try:
            lat = float(request.query_params["lat"])
            lng = float(request.query_params["lng"])
        except (KeyError, TypeError, ValueError):
            return Response(
                {"detail": "Query parameters lat and lng are required (numbers)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        radius_km = float(request.query_params.get("radius_km") or 50)

        # Only select stable/basic columns so this endpoint doesn't crash if optional
        # routing columns (e.g. `keywords`) haven't been migrated yet.
        categories_qs = ServiceCategory.objects.filter(is_active=True).only("id", "name", "slug", "description")
        categories = list(categories_qs.order_by("name"))
        cat_data = ServiceCategoryMiniSerializer(categories, many=True).data

        nearby_mechanics = list_nearby_mechanic_previews(lat, lng, radius_km)

        return Response(
            {
                "categories": cat_data,
                "nearby_mechanics_count": len(nearby_mechanics),
                "radius_km": radius_km,
                "mechanics": nearby_mechanics,
            }
        )


@extend_schema(
    summary="Create service request",
    request=ServiceRequestSerializer,
    responses={201: ServiceRequestSerializer},
    tags=["requests"],
)
class RequestCreateView(generics.CreateAPIView):
    """Alias for creating a service request (same as ``POST /jobs/requests/``)."""

    serializer_class = ServiceRequestSerializer
    permission_classes = (permissions.IsAuthenticated, IsDriver)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return ctx
        ctx["driver_profile"] = ensure_driver_profile(self.request.user)
        return ctx

    def perform_create(self, serializer):
        profile = ensure_driver_profile(self.request.user)
        serializer.save(driver=profile)


@extend_schema(
    summary="List my jobs",
    responses={200: JobSerializer(many=True)},
    tags=["jobs"],
)
class JobListView(generics.ListAPIView):
    """Jobs where the current user is the driver (via request) or assigned mechanic."""

    serializer_class = JobSerializer
    permission_classes = (permissions.IsAuthenticated, IsDriverOrMechanic)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Job.objects.none()
        user = self.request.user
        if user.role == UserRole.DRIVER:
            return (
                Job.objects.filter(service_request__driver__user=user)
                .select_related("service_request", "service_request__category", "service_request__driver__user", "mechanic")
                .order_by("-created_at")
            )
        if user.role == UserRole.MECHANIC:
            return (
                Job.objects.filter(mechanic__user=user)
                .select_related("service_request", "service_request__category", "service_request__driver__user", "mechanic")
                .order_by("-created_at")
            )
        return Job.objects.none()


class JobDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = JobSerializer
    permission_classes = (permissions.IsAuthenticated, IsDriverOrMechanic)
    lookup_field = "id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Job.objects.none()
        user = self.request.user
        if user.role == UserRole.DRIVER:
            return Job.objects.filter(service_request__driver__user=user).select_related(
                "service_request",
                "service_request__category",
                "service_request__driver__user",
                "mechanic",
            )
        if user.role == UserRole.MECHANIC:
            return Job.objects.filter(mechanic__user=user).select_related(
                "service_request",
                "service_request__category",
                "service_request__driver__user",
                "mechanic",
            )
        return Job.objects.none()

    def perform_update(self, serializer):
        job: Job = self.get_object()
        previous_status = job.status
        user = self.request.user
        next_status = serializer.validated_data.get("status")
        if next_status and user.role == UserRole.MECHANIC:
            if next_status == JobStatus.ACTIVE and not job.accepted_at:
                serializer.save(accepted_at=timezone.now())
                return
            if next_status == JobStatus.COMPLETED and not job.completed_at:
                serializer.save(completed_at=timezone.now())
                sr = job.service_request
                sr.status = ServiceRequestStatus.COMPLETED
                sr.save(update_fields=["status", "updated_at"])
                return
            if next_status == JobStatus.CANCELLED:
                serializer.save()
                sr = job.service_request
                # If mechanic declines before starting, put request back in the open pool.
                if previous_status == JobStatus.PENDING_ACCEPT:
                    sr.status = ServiceRequestStatus.OPEN
                else:
                    sr.status = ServiceRequestStatus.CANCELLED
                sr.save(update_fields=["status", "updated_at"])
                return
        serializer.save()


class ServiceCategoryListView(generics.ListAPIView):
    queryset = ServiceCategory.objects.filter(is_active=True)
    serializer_class = ServiceCategoryMiniSerializer
    permission_classes = (permissions.IsAuthenticated,)


class ServiceRequestListCreateView(generics.ListCreateAPIView):
    serializer_class = ServiceRequestSerializer
    permission_classes = (permissions.IsAuthenticated, IsDriver)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ServiceRequest.objects.none()
        profile = ensure_driver_profile(self.request.user)
        return ServiceRequest.objects.filter(driver=profile).select_related("category")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return ctx
        ctx["driver_profile"] = ensure_driver_profile(self.request.user)
        return ctx

    def perform_create(self, serializer):
        profile = ensure_driver_profile(self.request.user)
        serializer.save(driver=profile)


class ServiceRequestDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ServiceRequestSerializer
    permission_classes = (permissions.IsAuthenticated, IsDriver)
    lookup_field = "id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ServiceRequest.objects.none()
        profile = ensure_driver_profile(self.request.user)
        return ServiceRequest.objects.filter(driver=profile)


class NearbyOpenRequestsView(generics.ListAPIView):
    serializer_class = ServiceRequestSerializer
    permission_classes = (permissions.IsAuthenticated, IsMechanic)
    queryset = ServiceRequest.objects.filter(status=ServiceRequestStatus.OPEN)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ServiceRequest.objects.filter(status=ServiceRequestStatus.OPEN)
        return ServiceRequest.objects.filter(status=ServiceRequestStatus.OPEN)

    @extend_schema(
        parameters=[
            OpenApiParameter("lat", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("lng", OpenApiTypes.FLOAT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter(
                "radius_km",
                OpenApiTypes.FLOAT,
                OpenApiParameter.QUERY,
                description="Search radius in kilometers",
                default=50,
            ),
        ],
        responses={200: ServiceRequestSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        mechanic = MechanicProfile.objects.get(user=request.user)
        lat = float(request.query_params.get("lat") or 0)
        lng = float(request.query_params.get("lng") or 0)
        radius_km = float(request.query_params.get("radius_km") or 50)
        radius_m = radius_km * 1000

        lat_pad = radius_km / 111.0
        lng_pad = radius_km / max(111.0 * math.cos(math.radians(lat)), 0.01)

        qs = (
            ServiceRequest.objects.filter(status=ServiceRequestStatus.OPEN)
            .filter(created_at__gte=timezone.now() - timedelta(minutes=30))
            .select_related("category", "driver__user", "preferred_vehicle")
            .filter(
                latitude__gte=lat - lat_pad,
                latitude__lte=lat + lat_pad,
                longitude__gte=lng - lng_pad,
                longitude__lte=lng + lng_pad,
            )
        )
        offered_category_ids = list(
            MechanicServiceOffering.objects.filter(mechanic=mechanic, is_active=True).values_list("category_id", flat=True)
        )
        if offered_category_ids:
            qs = qs.filter(category_id__in=offered_category_ids)
        scored: list[tuple[float, ServiceRequest]] = []
        for sr in qs:
            d_m = distance_meters(lat, lng, sr.latitude, sr.longitude)
            if d_m <= radius_m:
                scored.append((d_m, sr))
        scored.sort(key=lambda x: x[0])
        page = [x[1] for x in scored[:50]]
        serializer = self.get_serializer(page, many=True)
        return Response(serializer.data)


@extend_schema(
    parameters=[
        OpenApiParameter("request_id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="Open service request id"),
    ],
    request=None,
    responses={201: JobSerializer, 404: OpenApiTypes.OBJECT},
    tags=["jobs"],
)
class JobAcceptView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsMechanic)

    def post(self, request, request_id):
        mechanic = MechanicProfile.objects.get(user=request.user)
        try:
            sr = ServiceRequest.objects.get(id=request_id, status=ServiceRequestStatus.OPEN)
        except ServiceRequest.DoesNotExist:
            return Response({"detail": "Request not found or not open."}, status=status.HTTP_404_NOT_FOUND)
        job = Job.objects.create(
            service_request=sr,
            mechanic=mechanic,
            status=JobStatus.PENDING_ACCEPT,
        )
        ChatRoom.objects.get_or_create(job=job)
        sr.status = ServiceRequestStatus.MATCHING
        sr.save(update_fields=["status", "updated_at"])
        return Response(JobSerializer(job).data, status=status.HTTP_201_CREATED)
