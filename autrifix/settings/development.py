from datetime import timedelta
import logging

from .base import *  # noqa: F403
from .database import get_databases

DEBUG = env.bool("DEBUG", default=True)
USE_REDIS = env.bool("USE_REDIS", default=False)

DATABASES = get_databases(conn_max_age=0, connect_timeout=10)

SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"] = timedelta(minutes=60)
SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"] = timedelta(days=14)

# Dev convenience: allow running API without local Redis.
if not USE_REDIS:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "autrifix-dev-cache",
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

_storage_mode = "cloudinary" if env("CLOUDINARY_CLOUD_NAME", default=None) else "local-media"
logging.getLogger("django").info("Development storage mode: %s", _storage_mode)
