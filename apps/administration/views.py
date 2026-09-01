"""Operator API — SPEC-012 REQ-4.

Scope is deliberately narrow: **inspect, and intervene in the few places an operator must.**
Django admin already provides general-purpose editing; the point of this surface is that
verification review — the gate deciding who may attend a stranded customer — should not
require a staff credential over the whole database.

Two things are **not** here, on purpose:

- **Private conversations.** SEC-GAP-17/34 records that administrative reads of chat are
  unaudited. Not exposing them means this slice does not widen that gap.
- **Editing users or jobs.** Every intervention that exists goes through the same service
  layer the product uses, so an operator cannot reach a state the domain forbids.
"""

from django.db.models import Count, Q, Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User, UserRole
from apps.accounts.permissions import IsAdmin
from apps.administration.serializers import (
    AdminJobSerializer,
    AdminUserSerializer,
    AdminVerificationReviewSerializer,
    AdminVerificationSerializer,
)
from apps.core import audit
from apps.core.models import AuditAction
from apps.jobs.models import Job, JobStatus, ServiceRequest, ServiceRequestStatus
from apps.providers import services as provider_services
from apps.providers.models import ProviderVerification
from apps.providers.verification import VerificationStatus


@extend_schema(
    tags=["administration"],
    summary="Verification review queue",
    parameters=[
        OpenApiParameter(
            "status",
            str,
            description="Filter by submission status. Defaults to `pending`.",
        )
    ],
)
class AdminVerificationListView(generics.ListAPIView):
    """Submissions awaiting a decision, oldest first.

    Oldest first because this is a queue someone works through, and newest-first quietly
    starves the people who have waited longest — which is the complaint verification delays
    generate (SPEC-013 OQ-013-D).
    """

    serializer_class = AdminVerificationSerializer
    permission_classes = (permissions.IsAuthenticated, IsAdmin)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProviderVerification.objects.none()
        requested = (self.request.query_params.get("status") or "").strip().lower()
        allowed = {c[0] for c in VerificationStatus.choices}
        qs = ProviderVerification.objects.select_related(
            "provider__user", "reviewed_by"
        ).order_by("submitted_at")
        return qs.filter(status=requested if requested in allowed else VerificationStatus.PENDING)


@extend_schema(
    tags=["administration"],
    summary="Approve or decline a verification submission",
    request=AdminVerificationReviewSerializer,
    responses={200: AdminVerificationSerializer},
)
class AdminVerificationReviewView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsAdmin)
    serializer_class = AdminVerificationReviewSerializer

    def post(self, request, id):
        from rest_framework.generics import get_object_or_404

        submission = get_object_or_404(
            ProviderVerification.objects.select_related("provider__user"), id=id
        )
        serializer = AdminVerificationReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # The same service the rest of the product uses: approval never downgrades an existing
        # level, and documents are purged either way (SPEC-013 REQ-8).
        submission = provider_services.review_verification(
            submission=submission,
            approve=serializer.validated_data["approve"],
            reviewer=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(AdminVerificationSerializer(submission).data)


@extend_schema(
    tags=["administration"],
    summary="Search users",
    parameters=[
        OpenApiParameter("q", str, description="Match name, email, or phone."),
        OpenApiParameter("role", str, description="Filter by role."),
    ],
)
class AdminUserListView(generics.ListAPIView):
    serializer_class = AdminUserSerializer
    permission_classes = (permissions.IsAuthenticated, IsAdmin)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()

        qs = User.objects.select_related("provider_profile").order_by("-date_joined")

        role = (self.request.query_params.get("role") or "").strip().lower()
        if role in {c[0] for c in UserRole.choices}:
            qs = qs.filter(role=role)

        term = (self.request.query_params.get("q") or "").strip()
        if term:
            qs = qs.filter(
                Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
                | Q(email__icontains=term)
                | Q(phone__icontains=term)
            )
        return qs


@extend_schema(tags=["administration"], summary="Job history")
class AdminJobListView(generics.ListAPIView):
    """Every job, newest first — the operational view for answering "what happened here?"."""

    serializer_class = AdminJobSerializer
    permission_classes = (permissions.IsAuthenticated, IsAdmin)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Job.objects.none()

        qs = Job.objects.select_related(
            "service_request__customer__user", "service_request__category", "provider"
        ).order_by("-created_at")

        job_status = (self.request.query_params.get("status") or "").strip().lower()
        if job_status in {c[0] for c in JobStatus.choices}:
            qs = qs.filter(status=job_status)
        return qs


_STATS = inline_serializer(
    name="AdminStatsResponse",
    fields={
        "users_total": serializers.IntegerField(),
        "customers": serializers.IntegerField(),
        "providers": serializers.IntegerField(),
        "verifications_pending": serializers.IntegerField(),
        "requests_open": serializers.IntegerField(),
        "jobs_active": serializers.IntegerField(),
        "jobs_awaiting_confirmation": serializers.IntegerField(),
        "jobs_completed": serializers.IntegerField(),
        "jobs_auto_confirmed": serializers.IntegerField(),
        "confirmed_amount_total": serializers.CharField(allow_null=True),
        "currency": serializers.CharField(),
    },
)


@extend_schema(tags=["administration"], summary="Operational counts", responses={200: _STATS})
class AdminStatsView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsAdmin)
    serializer_class = _STATS

    def get(self, request):
        from django.conf import settings

        role_counts = User.objects.aggregate(
            total=Count("id"),
            customers=Count("id", filter=Q(role=UserRole.CUSTOMER)),
            providers=Count("id", filter=Q(role=UserRole.PROVIDER)),
        )
        job_counts = Job.objects.aggregate(
            active=Count("id", filter=Q(status=JobStatus.ACTIVE)),
            awaiting=Count("id", filter=Q(status=JobStatus.AWAITING_CONFIRMATION)),
            completed=Count("id", filter=Q(status=JobStatus.COMPLETED)),
            # Surfaced because a rising count means customers are being charged by timeout
            # rather than by agreement — the operational risk SPEC-016 REQ-2 accepted.
            auto_confirmed=Count("id", filter=Q(auto_confirmed=True)),
            confirmed_total=Sum("final_amount", filter=Q(status=JobStatus.COMPLETED)),
        )

        return Response(
            {
                "users_total": role_counts["total"],
                "customers": role_counts["customers"],
                "providers": role_counts["providers"],
                "verifications_pending": ProviderVerification.objects.filter(
                    status=VerificationStatus.PENDING
                ).count(),
                "requests_open": ServiceRequest.objects.filter(
                    status=ServiceRequestStatus.OPEN
                ).count(),
                "jobs_active": job_counts["active"],
                "jobs_awaiting_confirmation": job_counts["awaiting"],
                "jobs_completed": job_counts["completed"],
                "jobs_auto_confirmed": job_counts["auto_confirmed"],
                "confirmed_amount_total": (
                    str(job_counts["confirmed_total"])
                    if job_counts["confirmed_total"] is not None
                    else None
                ),
                "currency": settings.PLATFORM_CURRENCY,
            },
            status=status.HTTP_200_OK,
        )
