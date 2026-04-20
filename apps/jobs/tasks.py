import logging

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def match_service_request_async(self, service_request_id: str):
    """Background match — notify mechanics, push to Channels (stub)."""
    from apps.jobs.models import ServiceRequest

    try:
        sr = ServiceRequest.objects.get(id=service_request_id)
    except ServiceRequest.DoesNotExist:
        logger.warning("match: missing request %s", service_request_id)
        return
    cache_key = f"match:queued:{service_request_id}"
    cache.set(cache_key, "processing", timeout=300)
    # Integrate: push notification, WebSocket broadcast
    logger.info("match: processed %s", service_request_id)
    return {"status": "ok", "id": service_request_id}
