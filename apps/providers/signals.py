from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.providers.models import ProviderProfile
from apps.providers.nearby_presence import provider_preview_from_instance


@receiver(post_save, sender=ProviderProfile)
def broadcast_provider_presence(sender, instance: ProviderProfile, **kwargs):
    layer = get_channel_layer()
    if not layer:
        return
    payload = {
        "kind": "provider_update",
        "provider": provider_preview_from_instance(instance),
    }
    async_to_sync(layer.group_send)(
        "provider_presence",
        {
            "type": "provider.presence",
            "message": payload,
        },
    )
