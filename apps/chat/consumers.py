from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.chat.models import ChatMessage, ChatRoom


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
            return
        payload = await self._create_message_payload(body)
        await self.channel_layer.group_send(self.group, {"type": "chat.message", "message": payload})

    async def chat_message(self, event):
        await self.send_json(event["message"])

    @sync_to_async
    def _get_room_for_user(self):
        user = self.scope["user"]
        try:
            room = ChatRoom.objects.select_related(
                "job__mechanic__user",
                "job__service_request__driver__user",
            ).get(job_id=self.job_id)
        except ChatRoom.DoesNotExist:
            return None
        is_driver = room.job.service_request.driver.user_id == user.id
        is_mechanic = room.job.mechanic.user_id == user.id
        return room if (is_driver or is_mechanic) else None

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
