"""
Test / CI settings — fast password hashing, eager Celery.

By default uses SQLite in-memory (no external Postgres). Set ``USE_POSTGRES_TESTS=1``
to run against PostgreSQL with the same config as development (e.g. CI).
"""
import os
from datetime import timedelta

from .development import *  # noqa: F403, F405

DEBUG = True

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
