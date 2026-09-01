from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions
from rest_framework.exceptions import NotFound

from apps.accounts.permissions import IsCustomerOrProvider
from apps.chat.models import ChatMessage
from apps.chat.selectors import get_participant_room, participant_rooms
from apps.chat.serializers import ChatMessageSerializer, ChatRoomListSerializer, ChatRoomSerializer


@extend_schema(
    summary="List my chat rooms",
    responses={200: ChatRoomListSerializer(many=True)},
    tags=["chat"],
)
class ChatRoomListView(generics.ListAPIView):
    """Chat rooms for jobs where the user is the customer or the assigned provider."""

    serializer_class = ChatRoomListSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomerOrProvider)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return participant_rooms(None)
        return (
            participant_rooms(self.request.user)
            .prefetch_related("messages")
            .order_by("-created_at")
        )


@extend_schema(tags=["chat"])
class ChatRoomDetailView(generics.RetrieveAPIView):
    """Read a conversation. Restricted to the job's two participants."""

    serializer_class = ChatRoomSerializer
    permission_classes = (permissions.IsAuthenticated,)
    lookup_field = "job_id"
    lookup_url_kwarg = "job_id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return participant_rooms(None)
        return participant_rooms(self.request.user).prefetch_related("messages")


@extend_schema(tags=["chat"])
class ChatMessageCreateView(generics.CreateAPIView):
    """Post a message. Restricted to the job's two participants."""

    serializer_class = ChatMessageSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_room(self):
        room = get_participant_room(self.request.user, self.kwargs["job_id"])
        if room is None:
            # Same response whether the room is absent or simply not the caller's, so
            # membership is not disclosed.
            raise NotFound("Chat room not found.")
        return room

    def perform_create(self, serializer):
        room = self.get_room()
        message = serializer.save(room=room, sender=self.request.user)
        broadcast_message(room, message, context=self.get_serializer_context())


def broadcast_message(room, message: ChatMessage, *, context=None) -> None:
    """Fan a REST-created message out to the job's WebSocket group.

    The envelope matches the one used by ``JobChatConsumer`` so clients handle a single
    frame shape regardless of which transport produced the message.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    payload = ChatMessageSerializer(message, context=context or {}).data
    async_to_sync(channel_layer.group_send)(
        f"job_{room.job_id}",
        {"type": "chat.message", "message": {"kind": "chat.message", "data": payload}},
    )
