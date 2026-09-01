# SPEC-006 — Provider Matching & Discovery

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

Discovery is **pull-based and provider-initiated**. Customers see which providers are nearby;
providers see which open requests are nearby and choose one to accept. There is no dispatch and
no assignment engine, and nothing tells a provider that work exists (ADR-005). Two ranking
helpers (`/ai/matching/preview/`, `/ai/route-issue/`) exist but neither is wired into the flow.

Both directions require authentication and validate their coordinates; the presence socket
filters updates by the subscriber's own radius.

**IMPLEMENTATION NOTE:** `docs/PRODUCT.md` says the platform "can facilitate discovery/matching".
What exists is discovery. Matching, in the sense of the platform choosing or proposing a
provider for a request, is `NOT_IMPLEMENTED`.

## 2. Problem

A customer wants to know help exists nearby before committing; a provider wants to see work they
can reach.

## 3. Actors

- Customer — sees nearby available providers.
- Service Provider — sees nearby open requests and accepts one.

Anonymous visitors have **no** discovery access as of ADR-014.

## 4. Goals

- Show a customer that supply exists near them, with distance.
- Show an online provider the open demand near them, nearest first.
- Let a provider claim a request.

## 5. Non-Goals (current implementation)

- Automatic assignment or broadcast-to-many dispatch.
- Bidding, quoting, or customer choice among providers.
- Respecting the provider's declared service radius or offerings (both stored, neither applied).

## 6. Requirements

### REQ-1 — Nearby providers for a customer
**ID:** PROD-006-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Given `lat`, `lng`, and an optional `radius_km`, the platform returns active service categories,
a count of available providers within radius, and a list of those providers with distance.

**Authentication is now required** (ADR-014). Query parameters are validated: missing or
non-numeric `lat`/`lng`, out-of-range coordinates, and a `radius_km` outside `(0, 500]` all
return `400` instead of a silent default or a `500`. The response carries a `truncated` boolean
so a client can tell when the 50-result cap has been hit.

Evidence: [apps/jobs/views.py](apps/jobs/views.py) `ServicesNearbyView`, [apps/core/validators.py](apps/core/validators.py) `parse_coordinate_params`

### REQ-2 — Provider eligibility for discovery
**ID:** DOM-006-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A provider appears in discovery only when `is_available = true` **and** both base coordinates are
set. Both conditions are enforced at query time and at the point of going online (SPEC-003 REQ-3).

Evidence: [apps/providers/nearby_presence.py:20-29](apps/providers/nearby_presence.py#L20-L29)

### REQ-3 — Nearby open requests for a provider
**ID:** PROD-006-003 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

A provider may fetch open requests near a coordinate, sorted nearest-first, capped at
`DISCOVERY_RESULT_LIMIT` (50).

`PARTIAL` — the feed works and its parameters are now validated (missing `lat`/`lng` returns
`400` instead of silently searching null island), but two constraints remain undocumented from
the caller's point of view:

1. Only requests **touched** within `OPEN_REQUEST_FEED_WINDOW` (30 minutes) are returned. The
   window now keys on `updated_at` rather than `created_at`, so a request returned to the pool
   by a declining provider becomes discoverable again — previously it could be stranded
   invisibly (SPEC-007 OQ-007-C, now resolved).
2. The provider's own `service_radius_km` is still ignored; radius comes from the query string
   (OQ-006-D).

Service offerings remain deliberately ignored (ADR-009).

Evidence: [apps/jobs/views.py](apps/jobs/views.py) `NearbyOpenRequestsView`

**OPEN QUESTION (OQ-006-A):** Is the 30-minute window a product rule (roadside urgency) or a
performance guard? Still unanswered; it is now at least a named constant.

### REQ-4 — Provider claims a request
**ID:** PROD-006-004 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A provider may accept an open request. This atomically creates a `Job` in `pending_accept`,
creates the chat room, moves the request to `matching`, and notifies the customer.

Concurrency-safe as of 2026-08-17: row lock plus a partial unique constraint, with `409` for the
losing provider. See SPEC-007 CONFLICT-007-A (resolved).

Evidence: [apps/jobs/services.py](apps/jobs/services.py) `accept_service_request`

### REQ-5 — Live provider presence over WebSocket
**ID:** PROD-006-005 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A customer may subscribe over WebSocket to receive an initial snapshot of nearby providers plus
live updates when any provider profile changes.

Both the snapshot **and** the live updates are now radius-filtered server-side: the consumer
computes the geodesic distance from the subscriber's own stored coordinate and drops events
beyond their radius, adding `distance_km` to the ones it forwards. The subscribe frame's
coordinates are range-checked and the radius clamped.

Evidence: [apps/providers/consumers.py](apps/providers/consumers.py), [apps/providers/signals.py](apps/providers/signals.py), [apps/chat/routing.py](apps/chat/routing.py)

### REQ-6 — Issue routing suggests a category
**ID:** PROD-006-006 · **Priority:** Could · **Provenance:** OBSERVED · **Status:** PARTIAL

Free text can be routed to a service category by a hybrid of keyword rules and an incremental
naive-Bayes model, falling back to `general-mechanic`.

`PARTIAL` — the endpoint exists and works, but nothing in the request-creation flow calls it;
the client must choose to. The model's persistence is not deployment-safe (§19).

Evidence: [apps/ai/issue_router.py:210-249](apps/ai/issue_router.py#L210-L249), [apps/ai/views.py:133-142](apps/ai/views.py#L133-L142)

### REQ-7 — Provider ranking preview
**ID:** PROD-006-007 · **Priority:** Could · **Provenance:** OBSERVED · **Status:** STUB

`POST /ai/matching/preview/` scores available providers for a request by distance (70%) and
rating (30%).

`STUB` for three reasons: nothing consumes the ranking; ratings are always `0` (SPEC-003 REQ-6),
so the rating term contributes nothing; and the results are then re-sorted by raw distance,
discarding the score entirely.

Evidence: [apps/ai/matching.py:9-31](apps/ai/matching.py#L9-L31) — note `out.sort(key=lambda x: x["distance_m"])` on line 30.

### REQ-8 — Background matching
**ID:** PROD-006-008 · **Priority:** Could · **Provenance:** OBSERVED · **Status:** STUB

`match_service_request_async` is a Celery task that sets a cache key and logs. It contains a
comment reading "Integrate: push notification, WebSocket broadcast" and **is never called**.

Evidence: [apps/jobs/tasks.py:9-23](apps/jobs/tasks.py#L9-L23); grep for the task name finds only its definition.

## 7. User Flow

**Customer:** open the app → `GET /services/nearby/?lat&lng` → see categories, provider count, and
pins → optionally subscribe over `ws/providers/nearby/` → create a request (SPEC-005) → wait.

**Provider:** go online (SPEC-003) → poll `GET /jobs/requests/nearby/?lat&lng&radius_km` →
pick one → `POST /jobs/requests/{id}/accept/` → job created (SPEC-007).

**IMPLEMENTATION NOTE:** nothing tells a **provider** that a new request exists — discovery in
that direction is polling only, per ADR-005. The **customer** side is now covered: acceptance
produces a `request.accepted` notification (SPEC-010 REQ-5), delivered live over
`ws/notifications/`.

## 8. Business Rules

- Distance is geodesic (WGS84) via `geopy`, computed **in Python**, not in the database.
- Candidate sets are pre-filtered with a bounding box before exact distance:
  `lat_pad = radius_km / 111.0`, `lng_pad = radius_km / max(111.0 · cos(lat), 0.01)`.
- Both discovery endpoints cap results at 50 after sorting by distance;
  `/services/nearby/` reports `truncated` when the cap is hit.
- `radius_km` defaults to 50 on both HTTP endpoints and must be within `(0, 500]`; the WebSocket
  subscribe defaults to 25 and clamps rather than erroring, because a frame cannot return `400`.
- `lat`/`lng` are **required** on both HTTP endpoints — neither silently defaults any more.
- Only `open` requests are returned to providers.
- Accepting is first-come-first-served; there is no queue, offer, or expiry.

## 9. State Model

Discovery itself is stateless. The state it depends on:

| Input | Owner | Effect |
|---|---|---|
| `ProviderProfile.is_available` | Provider | visibility in provider discovery |
| `ProviderProfile.base_*` | Provider | position and eligibility |
| `ServiceRequest.status == open` | System | visibility in the request feed |
| `ServiceRequest.created_at` within 30 min | System | visibility in the request feed |

The acceptance transition is specified in SPEC-007.

## 10. API Contract

### `GET /api/v1/services/nearby/`

Authentication: **none** (`AllowAny`). Throttle: `anon` (100/h dev, 60/h prod).

Query: `lat` (required, float), `lng` (required, float), `radius_km` (optional, default 50).

```json
{
  "categories": [ { "id": "uuid", "name": "Tire / Wheel Service", "slug": "tire-flat" } ],
  "nearby_providers_count": 3,
  "radius_km": 50.0,
  "providers": [
    { "id": "uuid", "business_name": "Kofi Auto Works",
      "latitude": 5.6037, "longitude": -0.187,
      "rating_avg": 0.0, "rating_count": 0, "distance_km": 1.24 }
  ]
}
```

Errors: `400` when `lat`/`lng` are missing or non-numeric.
**IMPLEMENTATION NOTE:** a non-numeric `radius_km` raises `ValueError` → `500`, because only
`lat`/`lng` are wrapped in the try block.

### `GET /api/v1/jobs/requests/nearby/`

Authentication: JWT. Permissions: `IsAuthenticated` + `IsProvider`.
Query: `lat`, `lng`, `radius_km` (default 50). Missing values silently become `0`.
Response: an **unpaginated** array of `ServiceRequestSerializer` objects (max 50).

Errors: `401`, `403`; `500` if the provider has no profile (SPEC-003 CONFLICT-003-A).

### `POST /api/v1/jobs/requests/{request_id}/accept/`

Specified in SPEC-007 REQ-2.

### `POST /api/v1/ai/route-issue/`

Authentication: JWT. Permissions: `IsAuthenticated`. **No `ai` throttle scope** (see SECGAP-006-4).

Request: `{ "issue_text": "battery is dead" }`

```json
{ "category_id": "uuid", "category_slug": "battery-electrical",
  "default_radius_km": 25, "confidence": 0.65, "method": "rules|ml|fallback",
  "reason": "rule:electrical" }
```

**IMPLEMENTATION NOTE:** `default_radius_km` is present on success responses but absent from the
`no_categories` response, and the documented `@extend_schema` response does not declare it at all.

### `POST /api/v1/ai/matching/preview/`

Authentication: JWT. Permissions: `IsAuthenticated` — **any authenticated user**, despite the
docstring saying "admin / internal". See SECGAP-006-3.

Request: `{ "service_request_id": "uuid" }` · Response: `{ "service_request_id": "…", "ranked_providers": [...] }`

### WebSocket `ws/providers/nearby/?token=<access_jwt>`

Authentication: JWT in the query string. Authorization: customer role only; others are closed.

Client → server: `{"kind": "subscribe", "lat": 5.6, "lng": -0.18, "radius_km": 25}`
Server → client (snapshot): `{"kind": "snapshot", "providers": [...], "nearby_providers_count": n, "radius_km": r}`
Server → client (update): `{"kind": "provider_update", "provider": { "id", "business_name", "latitude", "longitude", "is_available", "rating_avg", "rating_count" }}`

## 11. Data Model

No models are owned by this feature. It reads `providers.ProviderProfile`,
`jobs.ServiceRequest`, and `jobs.ServiceCategory`, and writes `jobs.Job` on acceptance.

The issue-router model is persisted **outside the database** at `var/issue_router_model.json`
(`BASE_DIR/var`), as `{"classes": {slug: {doc_count, token_total, tokens{}}}, "vocabulary": {}}`.

## 12. Security

- **Authentication:** JWT for the provider feed, acceptance, and both AI endpoints; **none** for `/services/nearby/`.
- **Authorization:** `IsProvider` on the request feed and acceptance; customer-only on the presence socket.
- **Object-level access:** acceptance re-reads the request with `status=OPEN`; the AI preview does not scope by owner.
- **Sensitive data:** provider coordinates and customer request coordinates + names are the payloads at issue.
- **Abuse/rate limiting:** `/services/nearby/` is anon-throttled only; the provider feed uses the `user` scope.
- **Auditability:** none. Who viewed which requests, and who accepted what and when, beyond `Job.created_at`, is not recorded.

### Security gaps — current status

| ID | Finding | Severity | Status |
|---|---|---|---|
| SECGAP-006-1 | `/services/nearby/` was `AllowAny`, letting anyone enumerate every provider's exact coordinates | High | **RESOLVED** — now `IsAuthenticated` (ADR-014) |
| SECGAP-006-2 | `provider_update` events broadcast platform-wide with no radius filter | High | **RESOLVED** — filtered server-side in the consumer |
| SECGAP-006-3 | `/ai/matching/preview/` accepted any `service_request_id` from any user | Medium | **RESOLVED** — scoped to the request's own customer, or staff; a foreign id returns the same `400` as a malformed one |
| SECGAP-006-4 | The `ai` throttle scope was applied only to `DiagnosticsView` | Low | **RESOLVED** — now on all three AI endpoints; `issue_text` and `symptoms` are also length-capped |
| SECGAP-006-5 | `/jobs/requests/nearby/` discloses customer identity and exact coordinates pre-acceptance | Medium | **PARTIALLY RESOLVED** — `customer_name` no longer falls back to a phone number, but the exact coordinate and description are still disclosed. Blocked on OQ-008-B. |

## 13. Edge Cases

- `lat`/`lng` omitted from the provider feed → both default to `0`, so the search runs at null island and returns nothing (or null-island requests).
- `radius_km=""` on `/services/nearby/` → falsy, so it falls back to 50; `radius_km=abc` → `500`.
- Longitude wrap-around: the bounding box is naive arithmetic. A search near ±180° longitude, or at very high latitude, will under-select candidates before the exact distance check.
- More than 50 providers or requests in range → silently truncated with no `has_more` signal.
- A provider with a huge `service_radius_km` still only sees what the client's `radius_km` asks for.
- Every provider profile save — including an unrelated `bio` edit — emits a presence broadcast.
- `route_issue` when no categories exist at all → `{"method": "none", "reason": "no_categories"}` with null ids.
- `route_issue` before the ML model file exists → `ml_untrained`, so the rules or the fallback decide.

## 14. Acceptance Criteria

- [x] A customer can retrieve nearby available providers with distances.
- [x] Unavailable or coordinate-less providers never appear.
- [x] A provider can retrieve nearby open requests, nearest first.
- [x] A provider can accept an open request and get a job.
- [x] A customer can subscribe over WebSocket and receive a radius-filtered snapshot.
- [x] Issue routing returns a category with a confidence and a method.
- [x] Provider locations require authentication.
- [x] Live presence updates respect the subscriber's radius.
- [x] Discovery query parameters are validated; bad input returns `400`, never `500`.
- [x] Result truncation is signalled (`truncated`) on `/services/nearby/`.
- [x] A missing provider profile returns `409`, not `500`.
- [x] `/ai/matching/preview/` is scoped to the request's owner.
- [x] Concurrent acceptance yields exactly one job.
- [ ] The 30-minute feed window is a documented, intentional **product** rule — **blocked on OQ-006-A**.
- [ ] The provider's own radius influences what they see — **NOT_IMPLEMENTED** (OQ-006-D).
- [ ] Offerings influence discovery — **deliberately not** (ADR-009); revisit per OQ-003-B.
- [ ] Ranking influences anything — **STUB** (REQ-7).
- [ ] A provider is informed that new work exists — **NOT_IMPLEMENTED** (REQ-8); notifications
      now exist (SPEC-010) but no producer targets providers, per ADR-005.

## 15. Tests

### Existing — `tests/test_discovery.py` (27 tests)
- **`/services/nearby/`:** anonymous `401`; available provider returned with distance; offline
  and coordinate-less providers excluded; radius boundary in both directions; missing params
  parametrized; non-numeric radius `400` (formerly `500`); out-of-range radius and coordinates.
- **`/jobs/requests/nearby/`:** provider sees a nearby open request; customer `403`; missing
  profile `409`; non-open requests omitted; stale requests omitted; a declined request becomes
  visible again; nearest-first ordering; missing coordinates `400` (formerly null island).
- **AI:** matching preview scoped to the owner and rejected for another user's request; issue
  routing returns a category; blank and oversized text rejected.

### Existing — `tests/test_websockets.py` (7 presence tests)
- Customer subscribes and receives a radius-filtered snapshot; provider and anonymous rejected.
- Out-of-range and non-numeric subscribe coordinates return an error frame.
- A **nearby** provider's profile change reaches the subscriber, carrying `distance_km`.
- A **distant** provider's profile change does **not** reach the subscriber — the direct
  regression test for SECGAP-006-2 / SECGAP-008-3.

### Still missing (gap)
- **Unit:** bounding-box padding at high latitude and across the antimeridian; the 50-item cap
  with more than 50 candidates.
- **Unit:** `_rule_pick` / `_ml_predict` / fallback selection paths in `route_issue` individually.

## 16. Observability

- Logs: `apps.ai.views` logs diagnostics calls only. Discovery and acceptance log nothing.
- Metrics: none. No supply/demand counters, no time-to-accept, no acceptance rate.
- Errors: shared DRF handler; the two `500` paths above are unlogged as domain events.
- Audit events: none.

## 17. Dependencies

- `geopy` (geodesic distance), Django Channels + `channels_redis` (presence), Celery (unused task).
- SPEC-003 (availability), SPEC-005 (requests), SPEC-007 (jobs), SPEC-008 (geo behavior and privacy).

## 18. Open Questions

- **OQ-006-A** — Is the 30-minute request-feed window a product rule?
- **OQ-006-B** — Who should be allowed to call `/ai/matching/preview/`? The docstring says admin/internal; the code says any authenticated user.
- **OQ-006-C** — Should matching stay pull-based (provider browses) or become push-based (platform offers to a ranked provider)? `match_service_request_async` suggests push was intended.
- **OQ-006-D** — Should `ProviderProfile.service_radius_km` be authoritative instead of the client-supplied radius?
- **OQ-006-E** — Should a customer ever choose among providers, or is first-come-first-served final?
- **OQ-006-F** — Is `/services/nearby/` intentionally public (pre-signup marketing value) and, if so, should provider coordinates be coarsened or reduced to a count?

## 19. Implementation Notes

- **Distance is computed in Python, per row.** Every candidate inside the bounding box costs one
  `geopy.geodesic` call. There is no spatial index, no PostGIS, and no `GeoDjango`; the README
  states this is deliberate ("No GDAL/OSGeo4W", "maps stay on the client"). This is adequate at
  MVP volume and will not scale to a large provider pool.
- **The ML routing model is not deployment-safe.** `var/issue_router_model.json` lives on local
  disk under `BASE_DIR`. The Render deployment and the Dockerfile both produce ephemeral
  filesystems, and the web and Celery containers do not share a volume. In production the model
  is effectively reset on every deploy and diverges per replica. Its `threading.Lock` protects
  only one process, so concurrent writers can lose updates.
- `ServicesNearbyView` deliberately selects only `id, name, slug, description` from
  `ServiceCategory` and `ServiceCategoryMiniSerializer` exposes only three fields, with comments
  explaining this guards against unmigrated optional columns. `apps/ai/issue_router.py` reads
  category attributes through `__dict__` and catches `ProgrammingError` for the same reason.
  These are defensive workarounds for schema drift; migrations are currently in sync, so the
  workarounds are no longer load-bearing.
- The presence consumer stores `customer_lat`/`customer_lng`/`radius_km` per connection and checks
  only that they are set before forwarding an update — the values are never used to filter.

## 20. Verification Evidence

- Files: [apps/jobs/views.py](apps/jobs/views.py), [apps/jobs/services.py](apps/jobs/services.py), [apps/providers/nearby_presence.py](apps/providers/nearby_presence.py), [apps/providers/consumers.py](apps/providers/consumers.py), [apps/ai/views.py](apps/ai/views.py), [apps/core/validators.py](apps/core/validators.py)
- Routes: [autrifix/api_urls.py](autrifix/api_urls.py), [apps/chat/routing.py](apps/chat/routing.py)
- Tests: `tests/test_discovery.py` — 27 tests, all passing.
- Commands: `pytest -q` → 169 passed; `manage.py spectacular` → 0 errors, 0 warnings.
- Still dead by grep: `match_service_request_async` has no caller (ADR-005).
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
