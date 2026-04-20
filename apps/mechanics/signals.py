from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.mechanics.models import MechanicProfile
from apps.mechanics.nearby_presence import mechanic_preview_from_instance


@receiver(post_save, sender=MechanicProfile)
def broadcast_mechanic_presence(sender, instance: MechanicProfile, **kwargs):
    layer = get_channel_layer()
    if not layer:
        return
    payload = {
        "kind": "mechanic_update",
        "mechanic": mechanic_preview_from_instance(instance),
    }
    async_to_sync(layer.group_send)(
        "mechanic_presence",
        {
            "type": "mechanic.presence",
            "message": payload,
        },
    )
