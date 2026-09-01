# SPEC-005 — Service Requests

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

> **AMENDED by [SPEC-015](015-money-model.md) (ADR-022, 2026-08-18).** Cancellation is refused
> while any job on the request is `awaiting_confirmation` — the request stays `assigned` while the
> provider waits on confirmation, and without the guard cancelling would be a way to walk away
> from work already done.

> **AMENDED by [SPEC-016](016-lifecycle-sweeps.md) (2026-08-18).** Requests now expire:
> `open` gains a terminal `expired` after `REQUEST_EXPIRES_AFTER`, written by the sweep, and a
> customer's open requests are capped. Closes OQ-005-C.

## 1. Summary

A service request is a customer's call for help: a service category, a free-text description, a
coordinate, and optionally the vehicle involved. It is created directly in the `open` state and
becomes visible to nearby providers (SPEC-006). Accepting it creates a `Job` (SPEC-007); the
request itself then follows the job's outcome.

## 2. Problem

A stranded or servicing customer needs to state what is wrong and where they are, once, and have
that reach providers who can act on it.

## 3. Actors

- Customer — creates, lists, reads, and updates their own requests.
- Service Provider — reads open nearby requests; accepts one (SPEC-006/007).
- Administrator — read/write via Django admin.

## 4. Goals

- Low-friction creation: category + description + location.
- Categorized so that routing and (future) matching have a signal.
- Scoped strictly to the owning customer for read and write.

## 5. Non-Goals

- Scheduled or future-dated requests.
- Quotes, estimates, or price negotiation.
- Multi-vehicle or fleet requests.
- Customer-chosen provider (the provider self-selects — see SPEC-006).

## 6. Requirements

### REQ-1 — Create a service request
**ID:** PROD-005-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A customer may create a request with `category` (active category id), `description`, `latitude`,
`longitude`, and optional `preferred_vehicle`. The owning customer profile is injected server-side.

Evidence: [apps/jobs/views.py:97-112](apps/jobs/views.py#L97-L112), [apps/jobs/views.py:204-223](apps/jobs/views.py#L204-L223), [apps/jobs/serializers.py:59-72](apps/jobs/serializers.py#L59-L72)

### REQ-2 — Location is mandatory and range-validated at creation
**ID:** DOM-005-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`latitude` and `longitude` are required to create a request and must be within
[-90, 90] / [-180, 180]. Validators live on the model fields, so `ModelSerializer` inherits them
automatically and out-of-range values return `400` instead of being persisted and later crashing
`geopy` during distance scoring.

Evidence: [apps/jobs/models.py](apps/jobs/models.py) using [apps/core/validators.py](apps/core/validators.py); verified by `test_out_of_range_coordinates_are_rejected`.

### REQ-3 — Requests start open
**ID:** DOM-005-003 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** CONFLICT

A new request is created with status `open` and is immediately visible to nearby providers.

**CONFLICT-005-A:** `docs/DOMAIN.md` proposes a lifecycle beginning `DRAFT -> SUBMITTED`. The
implementation defines a `draft` value on `ServiceRequestStatus` but **never assigns or accepts
it**; the model default is `open`. There is no submit step.

Evidence: [apps/jobs/models.py:28-35](apps/jobs/models.py#L28-L35) (default `OPEN`); grep for `DRAFT` finds only the enum declaration.

### REQ-4 — Status is server-controlled
**ID:** SEC-005-004 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`status` is read-only on `ServiceRequestSerializer`. A customer cannot set or change it through
the service-request endpoints.

Evidence: [apps/jobs/serializers.py:57](apps/jobs/serializers.py#L57)

### REQ-5 — A customer sees only their own requests
**ID:** SEC-005-005 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

List and detail querysets filter on the caller's customer profile; a foreign request id returns `404`.

Evidence: [apps/jobs/views.py:208-235](apps/jobs/views.py#L208-L235)

### REQ-6 — Category is required and must be active
**ID:** DOM-005-006 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`category` is a required FK limited to `ServiceCategory.objects.filter(is_active=True)`.
Categories are seeded by migration, not created at runtime by any endpoint.

Evidence: [apps/jobs/serializers.py:36-38](apps/jobs/serializers.py#L36-L38), [apps/jobs/migrations/0002_seed_service_categories.py](apps/jobs/migrations/0002_seed_service_categories.py)

### REQ-7 — Cancellation by the customer
**ID:** PROD-005-007 · **Priority:** Must · **Provenance:** PROPOSED (accepted 2026-08-17) · **Status:** IMPLEMENTED

A customer may cancel their own request via `POST /jobs/requests/{id}/cancel/` while it is `open`,
`matching`, or `assigned`. Cancelling from a terminal state returns `409`.

Cancellation is atomic: it locks the request, cancels every non-terminal job on it, notifies each
affected provider (`request.cancelled`), and sets the request to `cancelled`.

Evidence: [apps/jobs/services.py](apps/jobs/services.py) `cancel_service_request()`, [apps/jobs/views.py](apps/jobs/views.py) `ServiceRequestCancelView`

### REQ-8 — Online training on create
**ID:** DOM-005-008 · **Priority:** Could · **Provenance:** OBSERVED · **Status:** PARTIAL

Creating a request trains the issue-routing model with `(description, category.slug)`.

`PARTIAL` / risky — training is synchronous, inside the create call, and writes a JSON file on
local disk. See §19 and SPEC-006.

Evidence: [apps/jobs/serializers.py:67-72](apps/jobs/serializers.py#L67-L72), [apps/ai/issue_router.py:252-273](apps/ai/issue_router.py#L252-L273)

## 7. User Flow

1. Customer picks a category (from `/jobs/categories/` or `/services/nearby/`) or gets one suggested by `/ai/route-issue/`.
2. Customer describes the problem, and the client supplies the device coordinate.
3. `POST /jobs/requests/` → status `open`.
4. Nearby online providers see it for **30 minutes** (SPEC-006).
5. A provider accepts → a `Job` is created, request → `matching`.
6. The provider completes the job → request → `completed`.

## 8. Business Rules

- Ownership is the customer profile derived from `request.user`; the client never supplies it.
- `description` is required and unbounded (`TextField`, no max length).
- A request carries at most one `preferred_vehicle`; ownership of that vehicle is **not**
  validated (SPEC-004 CONFLICT-004-A).
- A request may have **many** `Job` rows (`ForeignKey`, not `OneToOne`) — see SPEC-007 CONFLICT-007-B.
- Requests are ordered `-created_at`; indexed on `(status, -created_at)`.
- Deleting a customer profile cascades and deletes their requests and, transitively, jobs, chat
  rooms, messages, reviews, and payments.
- `category` uses `on_delete=PROTECT`.

## 9. State Model

Declared values (`ServiceRequestStatus`): `draft`, `open`, `matching`, `assigned`, `cancelled`, `completed`.

**Reachable** states and the only transitions any code performs:

```text
open ──(provider accepts)──> matching ──(provider starts)──> assigned ──(completes)──> completed
  ▲                             │                               │
  └──(provider declines)────────┘                               │
                                └──(either party cancels)───────┴──────────────────> cancelled
```

Every transition below is a declared side effect of a `JOB_TRANSITIONS` entry, or of
`cancel_service_request` — none is written ad hoc. See [apps/jobs/services.py](apps/jobs/services.py).

| From | Action | To | Actor |
|---|---|---|---|
| — | create | `open` | Customer (model default) |
| `open` | accept request | `matching` | Provider |
| `matching` | job → `active` | `assigned` | Assigned provider |
| `assigned` | job → `completed` | `completed` | Assigned provider |
| `matching` | job → `cancelled` (decline, job was `pending_accept`) | `open` | Assigned provider |
| `assigned` | job → `cancelled` (abandon) | `cancelled` | Assigned provider |
| `matching` / `assigned` | job → `cancelled` | `cancelled` | Customer |
| `open` / `matching` / `assigned` | cancel request | `cancelled` | Customer |

**`assigned` is now reachable** (2026-08-17): it means a provider is actively working, which
`matching` previously had to cover. `draft` remains declared and unwritten — see OQ-005-A.

**CONFLICT-005-B:** `docs/DOMAIN.md`'s proposed lifecycle (`DRAFT → SUBMITTED → MATCHING →
ACCEPTED → EN_ROUTE → IN_PROGRESS → COMPLETED`) shares only `MATCHING` and `COMPLETED` with the
implementation. The baseline document already labels those states "a baseline proposal, not
proof that the current backend implements them", so this is a documented divergence rather than
a regression — but the two vocabularies must be reconciled before clients depend on either.

**CONFLICT-005-C — RESOLVED (2026-08-17):** request-status changes are no longer inline in a
view. They are side effects declared on each entry of `JOB_TRANSITIONS` in
[apps/jobs/services.py](apps/jobs/services.py), plus `cancel_service_request()` for the customer
path. Both run inside `transaction.atomic()`.

**`assigned` is now reachable:** a provider moving their job to `active` moves the request from
`matching` to `assigned`, so "a provider is on their way / working" is finally distinguishable
from "a provider has claimed this". This is a **client-visible change** — a request that is being
worked on now reports `assigned` where it previously reported `matching`. The value was already
in the model's choices and therefore already in the published OpenAPI enum.

`draft` remains declared and unreachable (OQ-005-A).

## 10. API Contract

| Method | Path | Auth | Permission |
|---|---|---|---|
| GET, POST | `/api/v1/jobs/requests/` | JWT | `IsAuthenticated` + `IsCustomer` |
| GET, PUT, PATCH | `/api/v1/jobs/requests/{id}/` | JWT | `IsAuthenticated` + `IsCustomer` |
| POST | `/api/v1/requests/create/` | JWT | `IsAuthenticated` + `IsCustomer` |
| GET | `/api/v1/jobs/categories/` | JWT | `IsAuthenticated` |

**IMPLEMENTATION NOTE:** `/requests/create/` is a duplicate alias of `POST /jobs/requests/`
with identical behavior. Both are published in the OpenAPI schema.

Request (`POST`):

```json
{ "category": "uuid", "description": "Car won't start at Osu", 
  "latitude": 5.6037, "longitude": -0.187, "preferred_vehicle": "uuid|null" }
```

Response `201`:

```json
{
  "id": "uuid",
  "category": { "id": "uuid", "name": "Auto Electrical (Battery / Starter)",
                "slug": "battery-electrical", "description": "…", "keywords": "…",
                "default_radius_km": 25, "priority": 20, "is_active": true },
  "description": "…", "latitude": 5.6037, "longitude": -0.187,
  "status": "open", "preferred_vehicle": "uuid|null",
  "customer_name": "Ama K.", "vehicle_summary": "2014 Toyota Corolla · Silver",
  "created_at": "…", "updated_at": "…"
}
```

**IMPLEMENTATION NOTE — asymmetric contract:** `category` is written as a UUID but read back as
a nested object (`to_representation` replaces it). A client cannot round-trip a GET response
straight back into a PUT.

Errors:
- `400` — missing/blank `description`; missing coordinates on create; inactive or unknown `category`
- `401` — unauthenticated
- `403` — caller is not a customer
- `404` — request id not owned by the caller

Pagination: `PageNumberPagination`, page size 20 (list only).
Filtering/search: none on the customer's own list. `django_filters` is the default backend but no
`filterset_fields` are declared anywhere.

## 11. Data Model

`jobs.ServiceCategory`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `name` | char(120) | |
| `slug` | slug(140) unique | used by the issue router |
| `description` | text, blank | |
| `keywords` | text, blank | comma-separated router synonyms |
| `default_radius_km` | positive small int | default 25; returned by `/ai/route-issue/`, not enforced |
| `priority` | positive small int | default 100; ordering only |
| `is_active` | bool | default true |

Seeded categories (`jobs/0002`, keywords/priorities in `jobs/0004`):
`general-mechanic` (10), `battery-electrical` (20), `engine-overheat` (30), `tire-flat` (40),
`tow-recovery` (50), `brake-pads` (60).

`jobs.ServiceRequest`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `customer` | FK → `customers.CustomerProfile` | CASCADE, `related_name="service_requests"` |
| `category` | FK → `ServiceCategory` | PROTECT, `related_name="requests"` |
| `description` | text | required |
| `latitude` / `longitude` | float | required, unvalidated range |
| `status` | char(20), indexed | default `open` |
| `preferred_vehicle` | FK → `drivers.Vehicle`, null | SET_NULL |
| `created_at` / `updated_at` | datetime | |

Index: `(status, -created_at)`.

Migrations: `jobs/0001_initial`, `0002_seed_service_categories`, `0003_servicecategory_routing_fields`,
`0004_seed_servicecategory_keywords`, `0005_alter_servicecategory_options`.

## 12. Security

- **Authentication:** JWT for every request endpoint.
- **Authorization:** `IsCustomer` plus owner-scoped querysets for the customer's own view;
  `IsProvider` for the discovery view (SPEC-006).
- **Object-level access:** enforced by queryset filtering. A customer cannot read another customer's
  request.
- **Sensitive data:** the request carries a precise coordinate, a free-text description, the
  customer's name-or-phone, and a vehicle summary. Everything except `status` and timestamps is
  disclosed to any online provider within radius **before** any relationship is established
  (SPEC-006, SPEC-008 SECGAP-008-2).
- **Abuse/rate limiting:** default `user` scope (1000/h dev, 500/h prod). Nothing limits how many
  open requests one customer may create, and there is no duplicate-request detection —
  `docs/CONVENTIONS.md` names "duplicate requests" as a scenario to cover.
- **Auditability:** none. Status changes are not recorded anywhere; `updated_at` is the only trace.

### Observed security gaps

| ID | Finding | Severity |
|---|---|---|
| SECGAP-005-1 | No cap on open requests per customer; no duplicate detection | Medium |
| SECGAP-005-2 | `preferred_vehicle` accepts any customer's vehicle and reads it back (SPEC-004 CONFLICT-004-A) | Medium |
| SECGAP-005-3 | Coordinates are unvalidated, so out-of-range values reach `geopy` in the scoring loop | Low |
| SECGAP-005-4 | `description` is unbounded; `docs/SECURITY.md` asks for input size limits | Low |

## 13. Edge Cases

- Create with `latitude: 0, longitude: 0` → accepted; the validator only rejects `None`, and
  `NearbyOpenRequestsView` also defaults missing query coordinates to `0`, so null-island
  requests and null-island searches match each other.
- Create with an inactive category → `400`.
- `PATCH` a request that is already `matching` → allowed; description, coordinates, and vehicle
  can still be edited under a provider who has already accepted. No guard exists.
  **OPEN QUESTION (OQ-005-B).**
- Customer deletes the referenced vehicle → `preferred_vehicle` becomes null on the request.
- A request older than 30 minutes disappears from the provider feed but stays `open` forever.
  There is no expiry job, so `open` requests accumulate indefinitely. **OPEN QUESTION (OQ-005-C).**
- Provider declines (cancels a `pending_accept` job) → request returns to `open`, but its
  `created_at` is unchanged, so if 30 minutes have passed it is already invisible to everyone.
- Two providers accept the same request nearly simultaneously → both may succeed (SPEC-007 CONFLICT-007-A).

## 14. Acceptance Criteria

- [x] A customer can create a request with category, description, and coordinates.
- [x] A request is created `open`.
- [x] A customer cannot set `status` directly.
- [x] A customer sees only their own requests; a foreign id is `404`.
- [x] A provider cannot use the customer request endpoints (`403`).
- [x] An inactive category is rejected.
- [x] A customer can cancel an open or matched request (REQ-7).
- [x] Coordinates are range-validated.
- [x] `description` is length-limited (2000 chars).
- [x] `preferred_vehicle` must belong to the requesting customer.
- [x] `customer_name` never discloses a phone number.
- [x] Request status transitions run through the explicit table in `apps.jobs.services`.
- [ ] Editing is blocked once a provider has accepted — **still open** (OQ-005-B).
- [ ] An unaccepted request eventually expires — **NOT_IMPLEMENTED** (OQ-005-C).

## 15. Tests

### Existing — `tests/test_service_requests.py` (24 tests)
- **Creation:** happy path; alias endpoint parity; provider `403`; anonymous `401`; `status` not
  client-writable; missing coordinates parametrized; out-of-range coordinates parametrized over
  four cases; oversized description; inactive category.
- **Vehicle:** own vehicle attaches and renders a summary; another customer's vehicle rejected.
- **Ownership:** list scoped; foreign detail `404`; `customer_name` privacy.
- **Cancellation:** open request; matched request also cancels the job and notifies the provider;
  completed request `409`; double-cancel `409`; another customer's request `404`; provider `403`;
  unknown id `404`.

### Still missing (gap)
- **E2E:** create → provider feed → accept → complete → review, as one test. The pieces are
  covered across `test_discovery.py`, `test_job_lifecycle.py`, and `test_reviews.py`.

## 16. Observability

- Logs: none for request creation or status changes. The Celery task
  `match_service_request_async` logs, but nothing calls it (SPEC-006).
- Metrics: none — no open-request gauge, no time-to-accept.
- Errors: shared DRF exception handler.
- Audit events: none.

## 17. Dependencies

- SPEC-002 (owning customer), SPEC-004 (`preferred_vehicle`), SPEC-006 (discovery + routing),
  SPEC-007 (jobs), SPEC-008 (geo).
- `apps.ai.issue_router` is imported at module load by `apps/jobs/serializers.py`, coupling
  request creation to the AI module.

## 18. Open Questions

- **OQ-005-A** — Should requests have a `draft` state and an explicit submit step, as `docs/DOMAIN.md` proposes? The state exists in code but is unreachable.
- **OQ-005-B** — May a customer edit a request after a provider has accepted it?
- **OQ-005-C** — What should happen to an `open` request nobody accepts? There is no expiry, timeout, or escalation.
- **OQ-005-D** — Should a request that reaches `matching` have a distinct state for "provider en route" and "work in progress"? `assigned` is declared but unused, and the job's `active` state is the only signal.
- **OQ-005-E** — Is the `/requests/create/` alias intentional and supported, or a legacy route to retire?
- **OQ-005-F** — Should `default_radius_km` on the category actually constrain discovery? It is returned by `/ai/route-issue/` and otherwise ignored.

## 19. Implementation Notes

- `ServiceRequestSerializer.create` calls `train_from_service_request` **synchronously**. That
  function acquires a process-local `threading.Lock`, reads `var/issue_router_model.json`,
  rewrites the whole file, and returns. Consequences: request creation performs blocking disk
  I/O; the lock is per-process, so multiple workers can interleave and lose writes; and on
  ephemeral/containerised hosts (the Render and Docker deployments both rebuild the filesystem)
  the model is not durable and is not shared between the web and Celery containers.
  See SPEC-006 for the routing side of this.
- `ServiceRequestListCreateView` and `RequestCreateView` both set `customer_profile` into the
  serializer context *and* pass `customer=` to `serializer.save()`, while `create()` overwrites
  `validated_data["customer"]` from the context. Three mechanisms for the same assignment.
- URL ordering: `jobs/requests/<uuid:id>/` is registered before `jobs/requests/nearby/`.
  This is safe only because the `uuid` path converter cannot match the literal `nearby`.
- `ServiceRequest.jobs` is a reverse FK (plural) even though the workflow assumes one job.

## 20. Verification Evidence

- Files: [apps/jobs/models.py](apps/jobs/models.py), [apps/jobs/serializers.py](apps/jobs/serializers.py), [apps/jobs/views.py](apps/jobs/views.py), [apps/jobs/services.py](apps/jobs/services.py)
- Routes: [autrifix/api_urls.py](autrifix/api_urls.py)
- Tests: `tests/test_service_requests.py` — 24 tests, all passing.
- Commands: `pytest -q` → 169 passed; `manage.py makemigrations --check --dry-run` → no changes.
- Migration: `jobs/0006` (coordinate validators, description cap, live-job constraint).
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
