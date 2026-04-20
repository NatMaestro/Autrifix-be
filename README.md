# AutriFix API (Django + DRF)

Production-oriented backend: JWT auth, PostgreSQL, lat/lng + **geopy** distances, Channels (WebSockets), Celery, Redis cache, Swagger. Maps live in the client (Google Maps, Mapbox, etc.).

## Database (Neon)

Use **[Neon](https://neon.tech)** (serverless PostgreSQL): create a project, copy **Connection string** (URI) into **`DATABASE_URL`** in `.env`. The app sets **`sslmode=require`** automatically for `*.neon.tech` / `*.neon.build` hosts if the URL omits it.

For **local Docker Compose** with the bundled `postgres` service, leave **`DATABASE_URL` unset** and use the **`POSTGRES_*`** variables from `.env.example`.

## Quick start (Docker)

1. Copy `.env.example` to `.env` and adjust secrets (set **`DATABASE_URL`** for Neon, or **`POSTGRES_*`** for the local `db` container).
2. From this directory, generate migrations and start services:

```bash
docker compose build
docker compose run --rm web python manage.py makemigrations
docker compose up
```

3. Create an admin user:

```bash
docker compose exec web python manage.py createsuperuser
```

- API: `http://localhost:8000/api/v1/`
- **Login**: `POST /api/v1/auth/login/` (JSON: `username` = email, `password`) → JWT `access` / `refresh`; **Logout**: `POST /api/v1/auth/logout/` with `{"refresh": "<refresh token>"}` (blacklists refresh)
- **Swagger UI**: `http://localhost:8000/api/docs/` (alias: `/swagger/`)
- **ReDoc**: `http://localhost:8000/api/redoc/`
- **OpenAPI JSON**: `http://localhost:8000/api/schema/` (add `?format=json` or `Accept: application/json`)
- Admin: `http://localhost:8000/admin/`
- Health: `GET /api/v1/health/`

WebSocket chat (after auth wiring in your client): `ws://localhost:8000/ws/jobs/<job-uuid>/chat/?token=<access_jwt>`

Driver live nearby mechanics (JWT query param, driver role only): `ws://localhost:8000/ws/mechanics/nearby/?token=<access_jwt>` — after connect, send `{"kind":"subscribe","lat":...,"lng":...,"radius_km":25}` to receive a `snapshot` plus `mechanic_update` events when any mechanic profile changes (availability or workshop coordinates).

## Local (without Docker)

Requires **PostgreSQL** (Neon via **`DATABASE_URL`**, or local), **Redis**, and Python deps (`pip install -r requirements.txt` includes **geopy** for geodesic distance). No GDAL/OSGeo4W.

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
export DJANGO_SETTINGS_MODULE=autrifix.settings.development
export DEBUG=True
export SECRET_KEY=dev-secret
python manage.py migrate
python manage.py runserver
```

Use `daphne -b 127.0.0.1 -p 8000 autrifix.asgi:application` for WebSockets.

## Media storage modes (avatars/files)

By default, development uses **local media files**:

- `MEDIA_ROOT = <repo>/autrifix-be/media`
- `MEDIA_URL = /media/`
- In `DEBUG=True`, Django serves media directly.

To enable **Cloudinary** (recommended for staging/production), set:

- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

When `CLOUDINARY_CLOUD_NAME` is present, the app switches to `MediaCloudinaryStorage`.
In development startup logs, you will see: `Development storage mode: local-media` or `cloudinary`.

## Celery

```bash
celery -A autrifix worker -l info
```

## Production

Set `DJANGO_SETTINGS_MODULE=autrifix.settings.production` and see `.env.production.example` for required variables (`SECRET_KEY`, `ALLOWED_HOSTS`, Postgres, Redis, CORS). TLS-related flags default on; adjust `USE_TLS` / `SECURE_*` if your host terminates SSL differently.

Run with Gunicorn (HTTP only) or **Daphne** / **Uvicorn** for HTTP + WebSockets:

```bash
daphne -b 0.0.0.0 -p 8000 autrifix.asgi:application
```

## Tests

```bash
pip install -r requirements-dev.txt
# Postgres + Redis must match `autrifix.settings.test` (see `pytest.ini`)
export DJANGO_SETTINGS_MODULE=autrifix.settings.test
export SECRET_KEY=test-secret-min-32-characters-long!!
export DEBUG=True
export POSTGRES_HOST=localhost
# ... other vars from `.env.example`
python manage.py migrate
pytest -v
```

## CI (GitHub Actions)

Workflow: `.github/workflows/ci.yml`. It assumes this backend lives at **`autrifix-be/`** in the repo root (monorepo). If your repo **is** only the API at the root, change `defaults.run.working-directory` to `.` and fix `cache-dependency-path` to `requirements-dev.txt`.

Commit migration files (`python manage.py makemigrations`) so `migrate` in CI succeeds. Optionally run `python manage.py makemigrations --check` locally before pushing.

## Project layout

- `apps/accounts` — custom `User` (roles: driver / mechanic / admin), JWT
- `apps/drivers` — `DriverProfile`, `Vehicle`
- `apps/mechanics` — `MechanicProfile`, availability, geo base
- `apps/jobs` — `ServiceCategory`, `ServiceRequest`, `Job` + Celery task stub
- `apps/reviews`, `apps/payments`, `apps/notifications`, `apps/chat`
- `apps/ai` — diagnostics + matching preview hooks

## Security notes

- Set a strong `SECRET_KEY` in production.
- Configure `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, HTTPS, and optional Cloudinary env vars.
- Replace payment stubs in `apps/payments/services.py` with Stripe Connect / PaymentIntents.
# Autrifix-be
