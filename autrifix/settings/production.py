"""
Production settings — deploy with DJANGO_SETTINGS_MODULE=autrifix.settings.production

Requires: SECRET_KEY, ALLOWED_HOSTS, database and Redis URLs.
Set USE_TLS=true behind HTTPS terminators (Netlify, Railway, etc.).
"""
from datetime import timedelta

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403, F405
from .database import get_databases

DEBUG = False

SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise ImproperlyConfigured("SECRET_KEY must be set to a long random value (32+ chars).")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must list at least one hostname.")

# Static files (Render / any PaaS without nginx serving /static)
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Neon: set DATABASE_URL from the dashboard. Otherwise set POSTGRES_* (see .env.production.example).
DATABASES = get_databases(conn_max_age=60, connect_timeout=10)

# HTTPS / cookies (reverse proxies: set USE_TLS=true and configure SECURE_PROXY_SSL_HEADER if needed)
USE_TLS = env.bool("USE_TLS", default=True)
if USE_TLS:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
    SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

SECURE_PROXY_SSL_HEADER = (
    env("SECURE_PROXY_SSL_HEADER_NAME", default="HTTP_X_FORWARDED_PROTO"),
    env("SECURE_PROXY_SSL_HEADER_VALUE", default="https"),
)

# Shorter access tokens in production (override via env if needed)
SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"] = timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15))
SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"] = timedelta(days=env.int("JWT_REFRESH_DAYS", default=7))

# Stricter API throttling defaults (override in env via custom settings if needed)
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "anon": env("THROTTLE_ANON", default="60/hour"),
    "user": env("THROTTLE_USER", default="500/hour"),
    "auth": env("THROTTLE_AUTH", default="20/minute"),
    "ai": env("THROTTLE_AI", default="10/minute"),
}

# JSON logs in production (optional: ship to Datadog / CloudWatch)
if env.bool("LOG_JSON", default=False):
    LOGGING["handlers"]["console"]["formatter"] = "json"
    LOGGING["root"]["level"] = "INFO"
    LOGGING["loggers"]["apps"]["level"] = "INFO"
