# Autrifix Backend Architecture

**Last synchronized with code:** 2026-08-18.

## Stack (as built)

| Concern | Technology | Pinned |
|---|---|---|
| Language | Python 3.11 (`.python-version`; CI runs 3.12; Dockerfile 3.11-slim) | — |
| Framework | Django 5.1.6 | `requirements.txt` |
| API | Django REST Framework 3.15.2 | |
| Auth | `djangorestframework-simplejwt` 5.4.0 (+ `token_blacklist`) | |
| Database | PostgreSQL via `psycopg2-binary` (Neon serverless or local Docker) | |
| Realtime | Django Channels 4.2.0 + `channels-redis` 4.2.1, served by Daphne 4.1.2 | |
| Async tasks | Celery 5.4.0 with Redis broker/result backend | |
| Cache | `django-redis` 5.4.0 (LocMem in development when `USE_REDIS=false`) | |
| Geo | `geopy` 2.4.1 — **no GDAL, no PostGIS** | |
| Media | local `MEDIA_ROOT`, or Cloudinary when `CLOUDINARY_CLOUD_NAME` is set | |
| Static | Whitenoise 6.9.0, `CompressedManifestStaticFilesStorage` in production | |
| Schema | `drf-spectacular` 0.28.0 (Swagger UI + ReDoc) | |
| Filtering | `django-filter` 24.3 — installed as the default backend, **no filterset is declared anywhere** | |
| Logging | `python-json-logger` (JSON in production when `LOG_JSON=true`) | |
| Servers | Daphne (ASGI, required for WebSockets); Gunicorn present but unused by any start command | |

## Project layout

```text
autrifix/                 project package
  settings/               base → development → test;  base → production
    base.py               shared config, DRF, JWT, Celery, Channels, logging
    database.py           DATABASE_URL or POSTGRES_*; auto sslmode for Neon hosts
    development.py        DEBUG default on; USE_REDIS=false → LocMem + InMemoryChannelLayer
    test.py               SQLite in-memory by default; MD5 hashing; eager Celery
    production.py         enforces SECRET_KEY ≥32 chars and ALLOWED_HOSTS; TLS/HSTS; stricter throttles
  api_urls.py             every /api/v1/ route, in one flat list
  urls.py                 admin, api/v1, OpenAPI schema + UIs
  asgi.py                 ProtocolTypeRouter: HTTP → Django, WS → JWT middleware → chat routing
  celery.py               Celery app, autodiscovery
  openapi.py              spectacular hook restricting the schema to /api/v1/

apps/
  core/        geo.py (geodesic distance), exceptions.py (DRF exception handler)
  accounts/    User, PhoneOTP, JWT views, Google auth, OTP service, SMS providers, permissions
  customers/     CustomerProfile, Vehicle
  providers/   ProviderProfile, ProviderServiceOffering, presence consumer + signal
  jobs/        ServiceCategory, ServiceRequest, Job, Celery task (unused)
  chat/        ChatRoom, ChatMessage, consumer, routing, WebSocket JWT middleware
  reviews/     Review
  notifications/ Notification  (no producer)
  payments/    Payment + escrow service stubs  (no endpoint)
  ai/          issue router (rules + naive Bayes), matching score, diagnostics stub
```

`apps.core` and `apps.ai` have no models and therefore no migrations.

## Layering (as built)

```text
URLconf (autrifix/api_urls.py — one flat module)
   |
DRF generic views / APIView   ← business logic lives here
   |
Serializers                   ← validation, and in two places also writes
   |
Django models                 ← invariants: constraints, unique keys, choices
   |
PostgreSQL / Redis / external services
```

A **service layer** was introduced on 2026-08-17 for the workflows that outgrew views:

| Module | Owns |
|---|---|
| `apps/jobs/services.py` | The job state machine — `JOB_TRANSITIONS`, acceptance, transitions, cancellation. All `@transaction.atomic`. |
| `apps/notifications/services.py` | The single entry point for producing notifications |
| `apps/reviews/services.py` | Rating aggregation |
| `apps/payments/services.py` | Escrow stubs — still uncalled |

Alongside it, **selector modules** own read-side scoping shared between transports:
`apps/chat/selectors.py` (participant rooms, used by both REST and the consumer),
`apps/customers/selectors.py`, `apps/providers/selectors.py`.

Views now coordinate HTTP and delegate. `JobDetailView.perform_update` extracts the requested
status and hands it to `transition_job`; it contains no domain logic.

One layering violation remains: `ServiceRequestSerializer.create()` triggers synchronous ML
training with blocking disk I/O (`DECISIONS.md` ADR-010, recommended for reversal). The
`VehicleSerializer.validate()` write has been moved into `create()`/`update()` under a
transaction.

## API surface

- Single version prefix `/api/v1/`, declared by URL path, with no DRF versioning scheme
  configured. `drf-spectacular` is configured with `SCHEMA_PATH_PREFIX = "/api/v1"` and a
  preprocessing hook that drops every non-`/api/v1/` path from the published document.
- All routes are hand-declared in `autrifix/api_urls.py`; no `DefaultRouter`, no ViewSets.
  Every view is a DRF generic view or `APIView`.
- Defaults: `JWTAuthentication`, `IsAuthenticated`, `PageNumberPagination` (page size 20),
  `DjangoFilterBackend`, three throttle classes, and a custom exception handler.

See `API.md` for the full endpoint inventory and contract conventions.

## Realtime

Two WebSocket endpoints, routed in `apps/chat/routing.py` and mounted in `autrifix/asgi.py`:

| Route | Consumer | Group | Authorization |
|---|---|---|---|
| `ws/jobs/<job_id>/chat/` | `JobChatConsumer` | `job_{job_id}` | participant check — correct |
| `ws/providers/nearby/` | `CustomerNearbyProvidersConsumer` | `provider_presence` | customer role only |

Authentication is by JWT in the **query string** (`?token=`), via a custom
`JwtQueryAuthMiddleware` — browsers cannot set an `Authorization` header on a WebSocket. Note
that query strings are commonly logged by proxies (`SECURITY.md`).

Channel layer: `RedisChannelLayer` normally; `InMemoryChannelLayer` in development when
`USE_REDIS=false`. **With the in-memory layer, cross-process fan-out silently does not work** —
a message posted over REST will not reach a WebSocket client in another process.

Fan-out sources: `ChatMessageCreateView` (REST → group), `JobChatConsumer` (WS → group), and a
`post_save` signal on `ProviderProfile` (any profile save → the whole presence group).

Note that the REST and WebSocket chat paths broadcast **different frame envelopes** for the same
event (`specs/009-messaging.md` §10).

## Asynchronous work

Celery is fully configured (broker, result backend, key prefixing, eager mode in tests) and a
worker is defined in `docker-compose.yml`. There is exactly **one task**,
`apps.jobs.tasks.match_service_request_async`, which sets a cache key, logs, and returns — and
**it is never called**.

So: async infrastructure exists; no asynchronous work is actually performed. Notifications,
which are the archetypal candidate, do not exist either (`specs/010-notifications.md`).

## State outside PostgreSQL

Worth flagging explicitly, because it affects deployment:

| State | Where | Risk |
|---|---|---|
| OTP send rate counter | Django cache | LocMem in development → per-process only |
| Issue-router ML model | `var/issue_router_model.json` on local disk | **not durable** on Render/Docker; not shared between web and worker; guarded only by a per-process `threading.Lock` |
| Channel groups | Redis | fine, provided `USE_REDIS=true` |
| Uploaded media | `MEDIA_ROOT` or Cloudinary | local media is ephemeral in production containers |

The ML model file is the most serious of these: it is written synchronously on every service
request creation and effectively resets on every deploy.

## Integrations

| Integration | Configuration | Failure handling | Timeout / retry | Tests |
|---|---|---|---|---|
| Google Sign-In | `GOOGLE_OAUTH_CLIENT_ID` | 503 when unconfigured or `google-auth` missing; 400 on invalid token; explicit issuer check | library defaults | none |
| Twilio SMS | `TWILIO_*` | `RuntimeError` → 503 | SDK defaults | none |
| Termii SMS | `TERMII_*` | `RuntimeError` → 503; **silently falls back to console in DEBUG** | 15s timeout, **no retry** | none |
| Cloudinary | `CLOUDINARY_*` | apps only installed when configured | library defaults | none |
| Redis | `REDIS_URL`, `CHANNEL_REDIS_URL`, `CELERY_*` | none — failures surface as 500s | client defaults | none |
| Neon PostgreSQL | `DATABASE_URL` | `sslmode=require` auto-set for `*.neon.tech` / `*.neon.build` | `connect_timeout` 10s | none |

`ARCHITECTURE.md` has always asked for "tests around integration boundaries". There are none for
any integration. Termii is called with `urllib` rather than a client library, so it has no retry,
no backoff, and no circuit breaker.

## Configuration

`django-environ`, reading `.env` from `BASE_DIR` when present. Settings modules are selected by
`DJANGO_SETTINGS_MODULE`; `development` is the fallback default hard-coded in `manage.py`,
`asgi.py`, and `celery.py`.

`REDIS_KEY_PREFIX` namespaces cache, Celery broker/result, and Channels keys so one Redis
instance can be shared with other applications.

Production settings fail fast: they raise `ImproperlyConfigured` unless `SECRET_KEY` is at least
32 characters and `ALLOWED_HOSTS` is non-empty.

## Deployment

| Target | Definition | Notes |
|---|---|---|
| Render | `render.yaml` | Daphne on `$PORT`; `preDeployCommand` runs `migrate`; managed Postgres + Key Value; build via `scripts/render-build.sh` |
| Docker | `Dockerfile` + `docker-compose.yml` | Postgres 16, Redis 7, web (Daphne), and a Celery worker |
| CI | `.github/workflows/ci.yml` | Postgres + Redis services, `migrate`, then `pytest --cov=apps`; `--cov-fail-under=0` so coverage never fails the build |

**No Celery worker is deployed on Render** — `render.yaml` defines only the web service. Since
nothing enqueues tasks today this is currently harmless, and it becomes a blocker the moment
async work is introduced.

`scripts/render-build.sh` exports a hardcoded placeholder `SECRET_KEY` so `collectstatic` can
import production settings at build time; this is safe only because the runtime injects a real
generated value.

## Architectural goals — current standing

| Goal | Standing (2026-08-17, post-remediation) |
|---|---|
| Modular domain organization | **Good.** Nine focused apps, now with service and selector layers where warranted. |
| Explicit API contracts | **Good.** OpenAPI generates with 0 warnings; `409` semantics documented; enums named. The asymmetric `category` field remains. |
| Strong authorization | **Good.** Every endpoint uses one of three scoping patterns; all blocking gaps closed and covered by tests. Pre-acceptance location disclosure remains, pending a product decision. |
| Transactional integrity | **Good.** `@transaction.atomic` on every multi-write workflow; acceptance takes a row lock and is backed by a partial unique constraint. |
| Testable business rules | **Good.** The state machine is a data structure that tests assert against directly. 169 tests, 77% coverage. |
| Maintainable integrations | **Partial.** Configuration is clean; failure handling is thin and still untested. Unchanged. |
