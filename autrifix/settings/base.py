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

DEBUG = env.bool("DEBUG", default=False)

# No usable default outside DEBUG. Production additionally enforces a 32-character minimum;
# this stops a non-DEBUG deployment that merely forgot to set the variable from booting with
# a publicly known key (docs/SECURITY.md SEC-GAP-02).
_secret_key = env("SECRET_KEY", default="")
if not _secret_key:
    if DEBUG:
        _secret_key = "dev-only-insecure-key-do-not-use-outside-debug"
    else:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "SECRET_KEY must be set when DEBUG is False. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )
SECRET_KEY = _secret_key
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

# Google Sign-In (OAuth 2.0 client ID for Web — same value as NEXT_PUBLIC_GOOGLE_CLIENT_ID on the frontend)
GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", default="")

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
    "apps.administration",
    "apps.accounts",
    "apps.customers",
    "apps.providers",
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

# Ghana cedi. Money is recorded, never processed — settlement is cash between the two
# parties (ADR-022). The payment *rail* is deliberately unchosen; see SPEC-015.
PLATFORM_CURRENCY = env("PLATFORM_CURRENCY", default="GHS")

# --- Lifecycle sweeps and volume limits (SPEC-016) ---
# How long a customer has to confirm the amount before silence is treated as agreement.
# Long enough that a distracted customer is not surprised; short enough that a provider is
# not held hostage by one. Run `manage.py sweep_stale_state` from cron to apply it.
JOB_AUTO_CONFIRM_AFTER = timedelta(hours=env.int("JOB_AUTO_CONFIRM_AFTER_HOURS", default=72))

# How long an unclaimed request stays open. Note the tension with the 30-minute provider
# feed window: a request is *discoverable* for 30 minutes but stays open far longer, so a
# customer can be waiting on a request no provider can still see (SPEC-016 OQ-016-B).
REQUEST_EXPIRES_AFTER = timedelta(hours=env.int("REQUEST_EXPIRES_AFTER_HOURS", default=6))

# Abuse ceilings, not product rules (SEC-GAP-28). Set to 0 to disable either.
MAX_OPEN_REQUESTS_PER_CUSTOMER = env.int("MAX_OPEN_REQUESTS_PER_CUSTOMER", default=3)
MAX_CONCURRENT_JOBS_PER_PROVIDER = env.int("MAX_CONCURRENT_JOBS_PER_PROVIDER", default=3)

# Verification level at which a provider sees exact customer coordinates while browsing
# (SPEC-013 REQ-2). A setting, so the supply-versus-privacy trade can be retuned without a
# code change: "phone" is more permissive, "documents" is the default.
PROVIDER_EXACT_LOCATION_MIN_LEVEL = env("PROVIDER_EXACT_LOCATION_MIN_LEVEL", default="documents")

# Verification level required to ACCEPT work (SPEC-013 REQ-3). Unverified providers may still
# browse — seeing the work they cannot yet take is the intended nudge toward completing
# verification. This is the marketplace's cold-start dial: "documents" is a hard quality gate
# but nobody can work until reviewed; "phone" is self-service and instant.
PROVIDER_MIN_ACCEPT_LEVEL = env("PROVIDER_MIN_ACCEPT_LEVEL", default="documents")

# Issue-router ML model. Local-filesystem persistence is not durable on ephemeral hosts
# and is not shared between processes — see docs/DECISIONS.md ADR-010.
ISSUE_ROUTER_MODEL_PATH = env(
    "ISSUE_ROUTER_MODEL_PATH",
    default=str(BASE_DIR / "var" / "issue_router_model.json"),
)

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
        # Per-targeted-account login limit, independent of the IP-keyed "auth" scope.
        "login_identifier": "10/minute",
        # Agency invitations are addressed by phone number and report whether one belongs to
        # a provider, which makes the endpoint an enumeration oracle for an authenticated
        # agency admin. Throttled rather than redesigned — see SPEC-017 OQ-017-A.
        "agency_invite": "20/hour",
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
    # Default JWT obtain serializer (USERNAME_FIELD=phone would otherwise require "phone" + "password").
    "TOKEN_OBTAIN_SERIALIZER": "apps.accounts.serializers.IdentifierTokenObtainPairSerializer",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AutriFix API",
    "DESCRIPTION": "Roadside assistance marketplace: customers, providers, real-time jobs. "
    "MVP auth: `POST /api/v1/auth/register/` with **email** + **phone** + **password**; `POST /api/v1/auth/login/` with **identifier** (email or E.164 phone) + **password**; "
    "`POST /api/v1/auth/google/` with Google **id_token**. "
    "Legacy SMS OTP endpoints remain for future use.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "PREPROCESSING_HOOKS": ["autrifix.openapi.preprocessing_filter_api_v1"],
    "COMPONENT_SPLIT_REQUEST": True,
    # ``role`` appears with different choice sets (full UserRole vs. the customer/provider
    # subset offered at signup); name them explicitly so generated clients get stable types.
    "ENUM_NAME_OVERRIDES": {
        "UserRoleEnum": "apps.accounts.models.UserRole.choices",
        "SignupRoleEnum": "apps.accounts.models.SIGNUP_ROLE_CHOICES",
        "VerificationLevelEnum": "apps.providers.verification.VerificationLevel.choices",
        # Two `role` fields with different choice sets: `owner` is reachable by promotion
        # but never by invitation, so the invite enum is deliberately the smaller one.
        "AgencyRoleEnum": "apps.providers.agencies.AgencyRole.choices",
        "AgencyInviteRoleEnum": "apps.providers.agency_serializers.INVITABLE_ROLES",
        # Three different `status` fields now reach the schema (job, service request,
        # verification submission). Named explicitly so a client gets `JobStatusEnum` rather
        # than a hash-suffixed placeholder that changes whenever the set does.
        "JobStatusEnum": "apps.jobs.models.JobStatus.choices",
        "ServiceRequestStatusEnum": "apps.jobs.models.ServiceRequestStatus.choices",
        "VerificationSubmissionStatusEnum": "apps.providers.verification.VerificationStatus.choices",
    },
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
