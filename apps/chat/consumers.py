from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.chat.models import ChatMessage
from apps.chat.selectors import get_participant_room

MAX_BODY_LENGTH = 4000


class JobChatConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket: join group `job_{job_id}` for real-time chat."""

    async def connect(self):
        self.job_id = self.scope["url_route"]["kwargs"]["job_id"]
        self.group = f"job_{self.job_id}"
        if self.scope["user"].is_anonymous:
            await self.close()
            return
        self.room = await self._get_room_for_user()
        if not self.room:
            await self.close()
            return
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        kind = str(content.get("kind") or "").strip().lower()
        if kind == "typing":
            await self.channel_layer.group_send(
                self.group,
                {
                    "type": "chat.message",
                    "message": {
                        "kind": "typing",
                        "sender": str(self.scope["user"].id),
                        "is_typing": bool(content.get("is_typing")),
                    },
                },
            )
            return
        body = str(content.get("body") or "").strip()
        if not body:
            await self.send_json({"kind": "error", "detail": "body is required"})
            return
        if len(body) > MAX_BODY_LENGTH:
            await self.send_json(
                {"kind": "error", "detail": f"body must be {MAX_BODY_LENGTH} characters or fewer"}
            )
            return
        payload = await self._create_message_payload(body)
        # Same envelope the REST path publishes, so clients parse one shape.
        await self.channel_layer.group_send(
            self.group,
            {"type": "chat.message", "message": {"kind": "chat.message", "data": payload}},
        )

    async def chat_message(self, event):
        await self.send_json(event["message"])

    @sync_to_async
    def _get_room_for_user(self):
        return get_participant_room(self.scope["user"], self.job_id)

    @sync_to_async
    def _create_message_payload(self, body: str):
        message = ChatMessage.objects.create(
            room=self.room,
            sender=self.scope["user"],
            body=body,
        )
        return {
            "id": str(message.id),
            "sender": str(message.sender_id),
            "body": message.body,
            "image": message.image.url if message.image else None,
            "created_at": message.created_at.isoformat(),
        }
