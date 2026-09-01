from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.accounts.models import UserRole
from apps.core.geo import distance_meters
from apps.core.validators import (
    LATITUDE_MAX,
    LATITUDE_MIN,
    LONGITUDE_MAX,
    LONGITUDE_MIN,
    clamp_radius_km,
)
from apps.providers.nearby_presence import list_nearby_provider_previews

DEFAULT_RADIUS_KM = 25.0


class CustomerNearbyProvidersConsumer(AsyncJsonWebsocketConsumer):
    """
    Customers subscribe with lat/lng/radius; receive snapshot + live provider_update events.

    Updates are filtered against the subscriber's own radius **server-side**. The previous
    implementation broadcast every provider's coordinates to every subscribed customer and
    left filtering to the client (``specs/008-location.md`` SECGAP-008-3).
    """

    GROUP = "provider_presence"

    async def connect(self):
        user = self.scope["user"]
        if user.is_anonymous or getattr(user, "role", None) != UserRole.CUSTOMER:
            await self.close()
            return
        self.subscribed = False
        self.customer_lat: float | None = None
        self.customer_lng: float | None = None
        self.radius_km = DEFAULT_RADIUS_KM
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
        if not (LATITUDE_MIN <= lat <= LATITUDE_MAX) or not (LONGITUDE_MIN <= lng <= LONGITUDE_MAX):
            await self.send_json({"kind": "error", "detail": "lat/lng out of range"})
            return

        radius = clamp_radius_km(content.get("radius_km"), default=DEFAULT_RADIUS_KM)
        self.customer_lat = lat
        self.customer_lng = lng
        self.radius_km = radius
        self.subscribed = True

        providers = await sync_to_async(list_nearby_provider_previews)(lat, lng, radius)
        await self.send_json(
            {
                "kind": "snapshot",
                "providers": providers,
                "nearby_providers_count": len(providers),
                "radius_km": radius,
            }
        )

    async def provider_presence(self, event):
        if not self.subscribed or self.customer_lat is None or self.customer_lng is None:
            return
        provider = (event.get("message") or {}).get("provider") or {}
        lat = provider.get("latitude")
        lng = provider.get("longitude")
        if lat is None or lng is None:
            # A provider with no coordinates is not discoverable; nothing to show.
            return
        distance_km = distance_meters(self.customer_lat, self.customer_lng, lat, lng) / 1000.0
        if distance_km > self.radius_km:
            return
        message = dict(event["message"])
        message["provider"] = {**provider, "distance_km": round(distance_km, 2)}
        await self.send_json(message)
