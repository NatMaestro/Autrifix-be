from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.accounts.models import UserRole
from apps.mechanics.nearby_presence import list_nearby_mechanic_previews


class DriverNearbyMechanicsConsumer(AsyncJsonWebsocketConsumer):
    """
    Drivers subscribe with lat/lng/radius; receive snapshot + live mechanic_update events.
    """

    GROUP = "mechanic_presence"

    async def connect(self):
        user = self.scope["user"]
        if user.is_anonymous or getattr(user, "role", None) != UserRole.DRIVER:
            await self.close()
            return
        self.subscribed = False
        self.driver_lat: float | None = None
        self.driver_lng: float | None = None
        self.radius_km = 25.0
        await self.channel_layer.group_add(self.GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP, self.channel_name)

    async def receive_json(self, content, **kwargs):
        kind = str(content.get("kind") or "").strip().lower()
        if kind != "subscribe":
            return
        try:
            lat = float(content["lat"])
            lng = float(content["lng"])
        except (KeyError, TypeError, ValueError):
            await self.send_json({"kind": "error", "detail": "subscribe requires numeric lat and lng"})
            return
        radius = float(content.get("radius_km") or 25)
        if not (radius > 0 and radius <= 500):
            radius = 25.0
        self.driver_lat = lat
        self.driver_lng = lng
        self.radius_km = radius
        self.subscribed = True
        mechanics = await sync_to_async(list_nearby_mechanic_previews)(lat, lng, radius)
        await self.send_json(
            {
                "kind": "snapshot",
                "mechanics": mechanics,
                "nearby_mechanics_count": len(mechanics),
                "radius_km": radius,
            }
        )

    async def mechanic_presence(self, event):
        if not self.subscribed or self.driver_lat is None or self.driver_lng is None:
            return
        await self.send_json(event["message"])
