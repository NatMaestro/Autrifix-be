from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response

from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return Notification.objects.filter(user=self.request.user)


_MARK_READ = inline_serializer(
    name="NotificationMarkReadResponse",
    fields={"updated": serializers.IntegerField(help_text="Rows marked read")},
)


@extend_schema(request=None, responses={200: _MARK_READ})
class NotificationMarkReadView(generics.GenericAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = NotificationSerializer

    def post(self, request, pk=None):
        updated = Notification.objects.filter(
            user=request.user,
            id=pk,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response({"updated": updated}, status=status.HTTP_200_OK)
