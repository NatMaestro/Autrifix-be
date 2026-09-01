"""
Test / CI settings — fast password hashing, eager Celery.

By default uses SQLite in-memory (no external Postgres). Set ``USE_POSTGRES_TESTS=1``
to run against PostgreSQL with the same config as development (e.g. CI).
"""
import os
import tempfile
from datetime import timedelta

from .development import *  # noqa: F403, F405

DEBUG = True

# Keep the issue-router training file out of the working tree: creating a service request
# trains the model synchronously, which would otherwise dirty the tracked
# ``var/issue_router_model.json`` on every test run.
ISSUE_ROUTER_MODEL_PATH = os.path.join(tempfile.gettempdir(), "autrifix-test-issue-router.json")

# Pin the transports rather than inheriting whatever ``USE_REDIS`` happens to be, so a
# developer with USE_REDIS=true does not silently run the suite against a live Redis.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "autrifix-test-cache",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"] = timedelta(minutes=60)

if os.environ.get("USE_POSTGRES_TESTS") == "1":
    DATABASES["default"]["TEST"] = {
        "NAME": env("POSTGRES_TEST_NAME", default="test_autrifix"),
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
