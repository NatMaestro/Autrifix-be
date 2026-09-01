import logging

from django.core.exceptions import ValidationError
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, inline_serializer

from apps.ai.issue_router import route_issue
from apps.ai.matching import score_providers_for_request

logger = logging.getLogger(__name__)

_DIAG_REQUEST = inline_serializer(
    name="DiagnosticsRequest",
    fields={
        "symptoms": serializers.CharField(help_text="Problem description"),
        "vehicle": serializers.DictField(required=False, help_text='Optional e.g. {"make":"...","model":"..."}'),
    },
)


@extend_schema(
    request=_DIAG_REQUEST,
    responses={
        200: inline_serializer(
            name="DiagnosticsResponse",
            fields={
                "symptoms_received": serializers.CharField(),
                "suggestions": serializers.ListField(child=serializers.DictField()),
                "matching_hook": serializers.CharField(),
            },
        )
    },
    tags=["ai"],
)
class DiagnosticsView(APIView):
    """
    POST body: { "symptoms": "...", "vehicle": { "make": "...", "model": "..." } }
    Returns heuristic diagnostics (replace with LLM + RAG in production).
    """

    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "ai"

    MAX_SYMPTOMS = 2000

    def post(self, request):
        symptoms = (request.data.get("symptoms") or "").strip()
        if not symptoms:
            return Response(
                {"detail": "symptoms is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(symptoms) > self.MAX_SYMPTOMS:
            return Response(
                {"detail": f"symptoms must be {self.MAX_SYMPTOMS} characters or fewer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Placeholder — wire OpenAI / Vertex here
        suggestions = [
            {
                "label": "Possible flat tire or low pressure",
                "confidence": 0.42,
                "next_steps": "Pull over safely; inspect tires; call assistance if needed.",
            },
            {
                "label": "Battery or starter issue",
                "confidence": 0.31,
                "next_steps": "Check lights/dash; try jump-start if safe.",
            },
        ]
        logger.info("diagnostics.request user=%s len=%s", request.user.id, len(symptoms))
        return Response(
            {
                "symptoms_received": symptoms[:2000],
                "suggestions": suggestions,
                "matching_hook": "Use POST /api/v1/jobs/requests/ with category + location.",
            }
        )


_MATCH_PREVIEW_REQUEST = inline_serializer(
    name="MatchingPreviewRequest",
    fields={"service_request_id": serializers.UUIDField()},
)


@extend_schema(
    request=_MATCH_PREVIEW_REQUEST,
    responses={
        200: inline_serializer(
            name="MatchingPreviewResponse",
            fields={
                "service_request_id": serializers.CharField(),
                "ranked_providers": serializers.ListField(child=serializers.DictField()),
            },
        )
    },
    tags=["ai"],
)
class MatchingPreviewView(APIView):
    """Rank providers for a service request.

    Scoped to the request's own customer (or staff). It previously accepted any
    ``service_request_id`` from any authenticated user and returned nearby providers for
    it (``specs/006-matching-discovery.md`` SECGAP-006-3).
    """

    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "ai"

    def post(self, request):
        from apps.jobs.models import ServiceRequest

        rid = request.data.get("service_request_id")
        qs = ServiceRequest.objects.select_related("category")
        if not request.user.is_staff:
            qs = qs.filter(customer__user=request.user)
        try:
            sr = qs.get(id=rid)
        except (ServiceRequest.DoesNotExist, TypeError, ValueError, ValidationError):
            # Same response whether the id is malformed, absent, or not the caller's.
            return Response({"detail": "Invalid service_request_id."}, status=400)
        ranked = score_providers_for_request(sr)
        return Response({"service_request_id": str(sr.id), "ranked_providers": ranked})


_ISSUE_ROUTE_REQUEST = inline_serializer(
    name="IssueRouteRequest",
    fields={"issue_text": serializers.CharField()},
)


@extend_schema(
    request=_ISSUE_ROUTE_REQUEST,
    responses={
        200: inline_serializer(
            name="IssueRouteResponse",
            fields={
                "category_id": serializers.UUIDField(allow_null=True),
                "category_slug": serializers.CharField(allow_null=True),
                "confidence": serializers.FloatField(),
                "method": serializers.CharField(),
                "reason": serializers.CharField(),
            },
        )
    },
    tags=["ai"],
)
class IssueRouteView(APIView):
    """Hybrid issue routing (rules + incremental ML)."""

    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "ai"

    MAX_ISSUE_TEXT = 2000

    def post(self, request):
        issue_text = (request.data.get("issue_text") or "").strip()
        if not issue_text:
            return Response({"detail": "issue_text is required."}, status=status.HTTP_400_BAD_REQUEST)
        if len(issue_text) > self.MAX_ISSUE_TEXT:
            return Response(
                {"detail": f"issue_text must be {self.MAX_ISSUE_TEXT} characters or fewer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(route_issue(issue_text))
