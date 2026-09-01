from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.notifications.services import user_group_name


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """Per-user notification stream.

    Subscribes the connection to the caller's own group only — the group name is derived
    from the authenticated user, never from client input.
    """

    async def connect(self):
        user = self.scope["user"]
        if user.is_anonymous:
            await self.close()
            return
        self.group = user_group_name(user.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def notification_message(self, event):
        await self.send_json(event["message"])
