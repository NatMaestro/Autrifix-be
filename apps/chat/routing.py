from django.urls import re_path

from apps.chat import consumers
from apps.providers import consumers as providers_consumers
from apps.notifications import consumers as notification_consumers

websocket_urlpatterns = [
    re_path(r"ws/jobs/(?P<job_id>[0-9a-f-]+)/chat/$", consumers.JobChatConsumer.as_asgi()),
    re_path(r"ws/providers/nearby/$", providers_consumers.CustomerNearbyProvidersConsumer.as_asgi()),
    re_path(r"ws/notifications/$", notification_consumers.NotificationConsumer.as_asgi()),
]
