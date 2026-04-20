"""
Base settings — shared across environments.
"""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load `.env` into the process environment (otherwise DATABASE_URL / POSTGRES_* in .env are ignored).
_env_file = BASE_DIR / ".env"
if _env_file.is_file():
    environ.Env.read_env(_env_file)

env = environ.Env(
    DEBUG=(bool, False),
)

SECRET_KEY = env("SECRET_KEY", default="dev-only-change-in-production")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="AutriFix <noreply@localhost>")

# Phone OTP (SMS) — codes hashed in DB; TTL 5 minutes by default
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=300)
OTP_SEND_MAX_PER_HOUR = env.int("OTP_SEND_MAX_PER_HOUR", default=5)
SMS_PROVIDER = env("SMS_PROVIDER", default="console")  # console | twilio | termii

# Twilio
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", default="")
TWILIO_FROM_NUMBER = env("TWILIO_FROM_NUMBER", default="")

# Termii
TERMII_API_KEY = env("TERMII_API_KEY", default="")
TERMII_SENDER_ID = env("TERMII_SENDER_ID", default="")
TERMII_CHANNEL = env("TERMII_CHANNEL", default="generic")  # generic | dnd | whatsapp
TERMII_SMS_TYPE = env("TERMII_SMS_TYPE", default="plain")

_CLOUDINARY_APPS = []
if env("CLOUDINARY_CLOUD_NAME", default=None):
    _CLOUDINARY_APPS = ["cloudinary_storage", "cloudinary"]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "channels",
    *_CLOUDINARY_APPS,
    "apps.core",
    "apps.accounts",
    "apps.drivers",
    "apps.mechanics",
    "apps.jobs",
    "apps.reviews",
    "apps.payments",
    "apps.notifications",
    "apps.chat",
    "apps.ai",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "autrifix.urls"
WSGI_APPLICATION = "autrifix.wsgi.application"
ASGI_APPLICATION = "autrifix.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# --- Redis / cache ---
REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
# When sharing one Redis instance with other apps, namespace keys (Redis Cloud often = single DB).
_redis_key_prefix_raw = env("REDIS_KEY_PREFIX", default="autrifix").strip()
REDIS_KEY_PREFIX = f"{_redis_key_prefix_raw}:" if _redis_key_prefix_raw else ""

_cache_options = {"CLIENT_CLASS": "django_redis.client.DefaultClient"}
if REDIS_KEY_PREFIX:
    _cache_options["KEY_PREFIX"] = REDIS_KEY_PREFIX

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": _cache_options,
    }
}

# --- Celery ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
if REDIS_KEY_PREFIX:
    # Isolate Celery broker + result keys from other apps on the same Redis.
    CELERY_BROKER_TRANSPORT_OPTIONS = {"global_keyprefix": REDIS_KEY_PREFIX}
    CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = {"global_keyprefix": REDIS_KEY_PREFIX}

# --- Channels ---
_channel_config = {"hosts": [env("CHANNEL_REDIS_URL", default=REDIS_URL)]}
if REDIS_KEY_PREFIX:
    _channel_config["prefix"] = f"{REDIS_KEY_PREFIX}asgi"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": _channel_config,
    },
}

# --- DRF ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        "auth": "30/minute",
        "ai": "20/minute",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.custom_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AutriFix API",
    "DESCRIPTION": "Roadside assistance marketplace: drivers, mechanics, real-time jobs. "
    "Primary auth: `POST /api/v1/auth/send-otp` + `POST /api/v1/auth/verify-otp` (phone + SMS). "
    "Optional password login: `POST /api/v1/auth/login/` with **username** = phone (E.164).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "PREPROCESSING_HOOKS": ["autrifix.openapi.preprocessing_filter_api_v1"],
    "COMPONENT_SPLIT_REQUEST": True,
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "displayOperationId": False,
        "persistAuthorization": True,
        "tryItOutEnabled": True,
        "filter": True,
    },
    "REDOC_UI_SETTINGS": {
        "hideDownloadButton": False,
        "expandResponses": "200,201",
    },
}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=True)
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Cloudinary (optional — only when apps are installed)
if env("CLOUDINARY_CLOUD_NAME", default=None):
    CLOUDINARY = {
        "cloud_name": env("CLOUDINARY_CLOUD_NAME"),
        "api_key": env("CLOUDINARY_API_KEY", default=""),
        "api_secret": env("CLOUDINARY_API_SECRET", default=""),
    }
    DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}
