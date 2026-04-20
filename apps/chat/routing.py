from django.urls import re_path

from apps.chat import consumers
from apps.mechanics import consumers as mechanics_consumers

websocket_urlpatterns = [
    re_path(r"ws/jobs/(?P<job_id>[0-9a-f-]+)/chat/$", consumers.JobChatConsumer.as_asgi()),
    re_path(r"ws/mechanics/nearby/$", mechanics_consumers.DriverNearbyMechanicsConsumer.as_asgi()),
]
