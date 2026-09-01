from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response

from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer


@extend_schema(
    parameters=[
        OpenApiParameter(
            "unread",
            OpenApiTypes.BOOL,
            OpenApiParameter.QUERY,
            description="Return only notifications that have not been marked read.",
        ),
    ],
    tags=["notifications"],
)
class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        qs = Notification.objects.filter(user=self.request.user)
        unread = str(self.request.query_params.get("unread") or "").strip().lower()
        if unread in ("1", "true", "yes"):
            qs = qs.filter(read_at__isnull=True)
        return qs


_MARK_READ = inline_serializer(
    name="NotificationMarkReadResponse",
    fields={
        "updated": serializers.IntegerField(help_text="Rows marked read"),
        "unread_count": serializers.IntegerField(help_text="Remaining unread notifications"),
    },
)


@extend_schema(request=None, responses={200: _MARK_READ}, tags=["notifications"])
class NotificationMarkReadView(generics.GenericAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = NotificationSerializer

    def post(self, request, pk=None):
        updated = Notification.objects.filter(
            user=request.user,
            id=pk,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        unread_count = Notification.objects.filter(user=request.user, read_at__isnull=True).count()
        return Response(
            {"updated": updated, "unread_count": unread_count},
            status=status.HTTP_200_OK,
        )


_UNREAD_COUNT = inline_serializer(
    name="NotificationUnreadCountResponse",
    fields={"unread_count": serializers.IntegerField()},
)


@extend_schema(responses={200: _UNREAD_COUNT}, tags=["notifications"])
class NotificationUnreadCountView(generics.GenericAPIView):
    """Badge count, so clients do not have to page the whole list."""

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = NotificationSerializer

    def get(self, request):
        count = Notification.objects.filter(user=request.user, read_at__isnull=True).count()
        return Response({"unread_count": count}, status=status.HTTP_200_OK)
