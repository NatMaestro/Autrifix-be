# Autrifix Backend Conventions

**Last synchronized with code:** 2026-08-18.

Follow the conventions already established in the repository before introducing new patterns.
The sections below record what the codebase actually does, so "the existing convention" is
unambiguous — and flag the few places where the code departs from its own norm.

## Project structure

- Domain code lives under `apps/<domain>/`, one Django app per bounded concern, with an explicit
  `AppConfig` declaring both `name` and a short `label`.
- Cross-cutting helpers live in `apps/core/` (currently `geo.py` and `exceptions.py`).
- All URLs are declared in the single flat module `autrifix/api_urls.py`. Do not add per-app
  `urls.py` files without a reason — the flat list is the current convention, and route ordering
  in it is load-bearing.
- Settings are layered: `base` → `development` → `test`, and `base` → `production`.

## Naming

Use domain names, not generic ones. The codebase is consistent here: `ServiceRequest`, `Job`,
`ProviderProfile`, `ChatRoom`, `issue_router`, `nearby_presence`.

Note the customer/customer vocabulary split: the code says **customer** everywhere, the product
docs say "Customer". Use `customer` in code (SPEC-002 OQ-002-B).

## Models

- **UUID primary keys everywhere**: `models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`.
- `created_at = auto_now_add`, `updated_at = auto_now`.
- Enumerations are `models.TextChoices` subclasses with `gettext_lazy` labels
  (`UserRole`, `ServiceRequestStatus`, `JobStatus`, `EscrowStatus`).
- Declare `Meta.ordering` explicitly; every model in the codebase does.
- Push invariants to the database where possible — the codebase already uses
  `CheckConstraint` (user phone-or-email), `UniqueConstraint` (one review per job per author),
  `unique_together` (offerings), and named `Index` entries on hot query paths.
- Foreign keys are `CASCADE` by default; use `PROTECT` for reference data (`ServiceCategory`) and
  `SET_NULL` where history must survive (`preferred_vehicle`).

**Gap to close:** there is no `full_clean()` call anywhere and no model-level coordinate
validation. Validators currently appear only on `rating` and `rating_avg`.

## Serializers

- One serializer per representation; add a `Mini` variant rather than overloading one serializer
  (`ServiceCategorySerializer` / `ServiceCategoryMiniSerializer`).
- **Always declare `fields` explicitly.** No serializer in this codebase uses `__all__`, and none
  should.
- **Always declare `read_only_fields`.** Server-assigned values — `id`, timestamps, `status`,
  `author`, `sender`, `accepted_at`, `completed_at`, `rating_avg` — must never be client-writable.
- Assign ownership in the view (`perform_create`), never from client input.
- Narrow related-field querysets: `PrimaryKeyRelatedField(queryset=ServiceCategory.objects.filter(is_active=True))`
  is the established pattern. **Apply it to ownership too** — the two places that skipped it
  (`preferred_vehicle`, `Review.job`) are both open defects.

**Anti-patterns present in the code — do not copy:**

- `VehicleSerializer.validate()` performs database writes (demoting other primary vehicles).
  Validation must not mutate. It also reads a context key the list view never sets, so
  `is_primary: true` on create raises `KeyError`.
- `ServiceRequestSerializer.create()` performs synchronous blocking disk I/O (ML training).
- `ServiceRequestSerializer.to_representation()` swaps a UUID field for a nested object, making
  the read and write contracts asymmetric.

## Views

- Prefer DRF generic views; use `APIView` only for genuinely non-CRUD actions
  (`JobAcceptView`, `ServicesNearbyView`, the auth views).
- **Scope by queryset, not by post-hoc checks.** `get_queryset()` filtering on
  `request.user` is the dominant authorization pattern and the one to reach for first; it yields
  `404` for a non-owned object, which is also the correct disclosure behavior.
- Declare `permission_classes` explicitly on every view, even when it matches the project
  default. Combine a role class with `IsAuthenticated`:
  `permission_classes = (permissions.IsAuthenticated, IsCustomer)`.
- Guard schema generation: `if getattr(self, "swagger_fake_view", False): return Model.objects.none()`.
- Annotate non-obvious endpoints with `@extend_schema` — query parameters, response shapes for
  `APIView`s, and `tags`.

**Gap to close:** business workflows currently live in view methods.
`JobDetailView.perform_update` holds the entire job state machine as a chain of `if` statements
with no transition table. This is the first place a service layer would earn its keep.

**Never** use `Model.objects.get(...)` on a user's own profile without handling `DoesNotExist` —
four call sites do, and each is a 500 waiting for a provider who has not yet opened their profile.

## Permissions

Role classes live in `apps/accounts/permissions.py`: `IsAdmin`, `IsCustomer`, `IsProvider`,
`IsCustomerOrProvider`, `ReadOnlyUnlessAdmin`. Reuse them; do not re-implement role checks inline.

Where an object-level check genuinely cannot be expressed as a queryset filter, write it
explicitly — `JobChatConsumer._get_room_for_user` is the reference implementation.

## Transactions

**Rule:** use transactions around multi-write operations that must succeed or fail atomically.

**There is currently no `transaction.atomic()` anywhere in the codebase.** Job acceptance
performs three writes (create job, create chat room, update request) with no transaction and no
`select_for_update()`. Any new multi-write workflow must not follow this example.

## State transitions

For stateful workflows, define valid transitions rather than allowing arbitrary status updates
(`CLAUDE.md`). Concretely:

- Keep the status field read-only on the serializer and expose named actions, **or** validate the
  requested transition against an explicit table.
- Gate transitions on the acting role, not just on authentication.
- Return `409` for an invalid transition. The API currently never returns `409`; it should.

## Errors

- Predictable errors, no internal detail. `apps.core.exceptions.custom_exception_handler` logs
  and returns `{"detail": "An unexpected error occurred."}` for anything unhandled.
- Use DRF's default error shape (`{"detail": …}` / `{"<field>": [...]}`); there is no error
  envelope or error-code taxonomy, and adding one is a breaking change for clients.
- Convert expected database integrity failures into `400`/`409` at the serializer. Two do not
  today: duplicate reviews (`UniqueConstraint`) and missing provider profiles.

## Async & realtime

- Celery tasks go in `apps/<app>/tasks.py` as `@shared_task`; import models **inside** the task
  body to avoid import cycles (see `apps/jobs/tasks.py`).
- Channels consumers go in `apps/<app>/consumers.py`; routes are collected centrally in
  `apps/chat/routing.py`.
- Wrap ORM access in consumers with `sync_to_async` / `database_sync_to_async`.
- Signals go in `apps/<app>/signals.py` and are imported from `AppConfig.ready()`.
- **Do not put durable state on the local filesystem.** `var/issue_router_model.json` does, and
  it is not durable on any of the project's deployment targets.

## Logging

`logger = logging.getLogger(__name__)` at module level. `apps.*` loggers are DEBUG in
development and INFO in production. Never log a credential or an OTP code — the console SMS
provider does, and is development-only for that reason.

Most domain events are currently unlogged. New workflow code should log state transitions.

## Tests

Prefer tests that verify business behavior and API contracts rather than implementation details.

Setup in place: `pytest` + `pytest-django`, `pytest.ini` pointing at `autrifix.settings.test`,
SQLite in-memory by default, MD5 password hashing, eager Celery, and `factory-boy` available
(currently unused). Tests live in the top-level `tests/` package.

**Only two tests exist** (`test_register_creates_customer`, `test_health_returns_ok`). Coverage is
reported in CI but `--cov-fail-under=0`, so it never fails a build.

Important scenarios, none of which is currently covered:

- permissions and role gates;
- object-level ownership (foreign id → 404);
- invalid state transitions;
- concurrent acceptance;
- cancellation and completion side effects;
- duplicate requests and duplicate reviews;
- missing resources;
- WebSocket authorization.

Run: `pytest -v`, or `pytest --cov=apps --cov-report=term-missing` as CI does.

## Validation commands

```bash
python manage.py makemigrations --check --dry-run   # migration drift (currently clean)
python manage.py migrate --noinput
pytest -v
```

Commit migration files; CI runs `migrate` and will fail on drift.
