from django.shortcuts import get_object_or_404
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions

from apps.accounts.models import UserRole
from apps.accounts.permissions import IsDriverOrMechanic
from apps.chat.models import ChatMessage, ChatRoom
from apps.chat.serializers import ChatMessageSerializer, ChatRoomListSerializer, ChatRoomSerializer


@extend_schema(
    summary="List my chat rooms",
    responses={200: ChatRoomListSerializer(many=True)},
    tags=["chat"],
)
class ChatRoomListView(generics.ListAPIView):
    """Chat rooms for jobs where the user is the driver or the assigned mechanic."""

    serializer_class = ChatRoomListSerializer
    permission_classes = (permissions.IsAuthenticated, IsDriverOrMechanic)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ChatRoom.objects.none()
        user = self.request.user
        if user.role == UserRole.DRIVER:
            return (
                ChatRoom.objects.filter(job__service_request__driver__user=user)
                .select_related("job", "job__mechanic__user", "job__service_request__driver__user")
                .prefetch_related("messages")
                .order_by("-created_at")
            )
        if user.role == UserRole.MECHANIC:
            return (
                ChatRoom.objects.filter(job__mechanic__user=user)
                .select_related("job", "job__mechanic__user", "job__service_request__driver__user")
                .prefetch_related("messages")
                .order_by("-created_at")
            )
        return ChatRoom.objects.none()


class ChatRoomDetailView(generics.RetrieveAPIView):
    serializer_class = ChatRoomSerializer
    permission_classes = (permissions.IsAuthenticated,)
    lookup_field = "job_id"
    lookup_url_kwarg = "job_id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ChatRoom.objects.none()
        return ChatRoom.objects.select_related("job").prefetch_related("messages")


class ChatMessageCreateView(generics.CreateAPIView):
    serializer_class = ChatMessageSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def perform_create(self, serializer):
        room = get_object_or_404(ChatRoom, job_id=self.kwargs["job_id"])
        message = serializer.save(room=room, sender=self.request.user)
        payload = ChatMessageSerializer(message).data
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"job_{room.job_id}",
            {
                "type": "chat.message",
                "message": {"kind": "chat.message", "data": payload},
            },
        )
