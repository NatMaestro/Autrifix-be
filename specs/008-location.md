# SPEC-008 — Location & Geospatial Behavior

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

Location is stored as plain float latitude/longitude pairs on three models, and distance is
computed in Python with `geopy` after a naive bounding-box prefilter. There is no PostGIS, no
`GeoDjango`, and no spatial index — a deliberate choice recorded in the README ("lat/lng +
**geopy** distances… No GDAL/OSGeo4W. Maps live in the client").

## 2. Problem

Roadside assistance is inherently local: a request must reach providers who can physically get
there, and a customer must see that such providers exist.

## 3. Actors

- Customer — supplies a request coordinate and a search coordinate; optionally stores a home coordinate.
- Service Provider — supplies a workshop coordinate and a search coordinate.
- Anonymous visitor — may currently search for providers (SECGAP-008-1).

## 4. Goals

- Capture where help is needed and where providers are based.
- Rank both directions of discovery by real-world distance.
- Keep the backend free of geospatial infrastructure dependencies.

## 5. Non-Goals

- Routing, ETA, or turn-by-turn (client-side, using the client's map provider).
- Live tracking of a provider en route.
- Reverse geocoding or address resolution — the platform stores no human-readable address.
- Polygonal service areas.

## 6. Requirements

### REQ-1 — Coordinate storage model
**ID:** DOM-008-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Coordinates are stored as two nullable/required `FloatField`s per entity, in WGS84 decimal
degrees.

| Model | Fields | Nullability | API name |
|---|---|---|---|
| `customers.CustomerProfile` | `home_latitude`, `home_longitude` | optional | `latitude`, `longitude` |
| `providers.ProviderProfile` | `base_latitude`, `base_longitude` | optional | same |
| `jobs.ServiceRequest` | `latitude`, `longitude` | **required** | same |

Evidence: [apps/customers/models.py:15-16](apps/customers/models.py#L15-L16), [apps/providers/models.py:17-18](apps/providers/models.py#L17-L18), [apps/jobs/models.py:57-58](apps/jobs/models.py#L57-L58)

### REQ-2 — Geodesic distance
**ID:** DOM-008-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Distance between two points is the WGS84 geodesic distance in metres, via `geopy.distance.geodesic`.

Evidence: [apps/core/geo.py:8-15](apps/core/geo.py#L8-L15)

### REQ-3 — Bounding-box prefilter before exact distance
**ID:** NFR-008-003 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

Candidates are narrowed in SQL with a lat/lng box, then filtered exactly in Python:

```text
lat_pad = radius_km / 111.0
lng_pad = radius_km / max(111.0 * cos(radians(lat)), 0.01)
```

`PARTIAL` — the arithmetic does not handle the antimeridian (a box spanning ±180° longitude
produces an empty range) and degrades near the poles. Both are acceptable for a Ghana-centred
launch and unsafe as a general rule.

Evidence: [apps/providers/nearby_presence.py:16-29](apps/providers/nearby_presence.py#L16-L29), [apps/jobs/views.py:269-282](apps/jobs/views.py#L269-L282)

### REQ-4 — Distance is disclosed to the searcher
**ID:** API-008-004 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Both directions of discovery return `distance_km`, rounded to two decimals:

- nearby providers (customer-facing), and live presence updates;
- nearby open requests (provider-facing) — added 2026-08-17 under ADR-015, since distance is the
  primary accept/decline input.

`distance_km` is `null` on a customer's own request list, where there is no reference point.

Evidence: [apps/providers/nearby_presence.py](apps/providers/nearby_presence.py), [apps/jobs/serializers.py](apps/jobs/serializers.py) `get_distance_km`, [apps/jobs/views.py](apps/jobs/views.py) `NearbyOpenRequestsView`

### REQ-5 — Coordinates gate provider availability
**ID:** DOM-008-005 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A provider cannot go online without both base coordinates (SPEC-003 REQ-3), and discovery
excludes null coordinates at the query level.

### REQ-6 — Coordinate validation
**ID:** DOM-008-006 · **Priority:** Must · **Provenance:** PROPOSED (accepted 2026-08-17) · **Status:** IMPLEMENTED

Latitude must be within [-90, 90] and longitude within [-180, 180], everywhere a coordinate
enters the system.

Enforced at three layers, all sourced from [apps/core/validators.py](apps/core/validators.py) so
the bounds are defined once:

| Entry point | Mechanism |
|---|---|
| `ServiceRequest`, `ProviderProfile`, `CustomerProfile` model fields | `latitude_validators` / `longitude_validators`, inherited automatically by `ModelSerializer` |
| `CustomerProfileSerializer.latitude` / `.longitude` | explicit `min_value` / `max_value` — these are declared fields, so model validators do **not** apply |
| `?lat=`, `?lng=`, `?radius_km=` query parameters | `parse_coordinate_params()` → `400` |
| WebSocket subscribe frame | explicit range check → error frame; radius via `clamp_radius_km` |

Out-of-range values can no longer be persisted or reach `geopy`.

**Not enforced at the database level:** adding `CheckConstraint`s was considered and deferred,
because the migration would fail on any pre-existing out-of-range row. See OQ-008-G.

### REQ-7 — Location privacy
**ID:** SEC-008-007 · **Priority:** Must · **Provenance:** PRODUCT · **Status:** IMPLEMENTED

`docs/SECURITY.md` states: "Precise service locations can be sensitive. Do not expose a user's
location to arbitrary users. Providers should receive only the location information necessary
for a legitimate job workflow."

Interpreted and settled as of 2026-08-17:

| Disclosure | Rule |
|---|---|
| Provider coordinates → anonymous callers | **Not permitted.** Discovery requires authentication (ADR-014). |
| Provider coordinates → arbitrary customers over WebSocket | **Not permitted.** Presence updates are filtered to the subscriber's own radius. |
| Customer coordinates → a **verified** provider browsing nearby open requests | **Permitted, by design** (ADR-015). Deciding whether to accept a job *is* the legitimate workflow, and it depends on where the job is. |
| Customer coordinates → an **unverified** provider browsing | **Coarsened** to a ~1 km grid (SPEC-013 REQ-2). Enough to judge the job; not enough to build a map. |
| Customer coordinates → the provider who accepted | Exact — navigation needs it, and acceptance is audited and identity-bound. |
| Customer coordinates → anyone else | Not permitted; requests are owner-scoped. |

**The assumption carried by ADR-015** — that an online provider is a plausible service provider
— is now *enforced by degree* rather than taken on trust. [SPEC-013](013-provider-verification.md)
grades disclosure by verification level: an unverified provider sees a ~1 km grid-snapped
coordinate (and a distance derived from it), a verified one sees the exact point. Both can still
judge and accept the job; only precision differs.

## 7. User Flow

**Customer:** client obtains a device coordinate → `GET /services/nearby/?lat&lng&radius_km` →
sees provider pins and distances → creates a request carrying the same coordinate.

**Provider:** sets a workshop coordinate once → goes online → polls
`GET /jobs/requests/nearby/?lat&lng&radius_km` with their *current* coordinate → sees requests
nearest-first.

**IMPLEMENTATION NOTE:** the provider's stored `base_*` is used for *being found*; the coordinate
they *search from* is whatever the client sends. Those can differ arbitrarily, and nothing
reconciles or records the difference.

## 8. Business Rules

- Distance is computed per candidate row in Python; there is no spatial index.
- Result sets are hard-capped at 50 after sorting, in both directions, with no pagination and no
  truncation signal.
- Radius defaults differ by entry point: `/services/nearby/` 50 km; `/jobs/requests/nearby/`
  50 km; `list_nearby_provider_previews` 25 km; the WebSocket subscribe 25 km, clamped to
  `(0, 500]`.
- Missing `lat`/`lng` on `/jobs/requests/nearby/` default to `0` rather than erroring.
- `ProviderProfile.service_radius_km` and `ServiceCategory.default_radius_km` are stored and
  returned but never applied server-side.
- The customer's home coordinate has no reader (SPEC-002 REQ-3).

## 9. State Model

None. Coordinates are values, not states. The only location-linked state transition is
provider availability, specified in SPEC-003.

## 10. API Contract

Location appears as:

| Surface | Shape |
|---|---|
| `GET /services/nearby/` | query `lat`, `lng`, `radius_km`; response includes `latitude`, `longitude`, `distance_km` per provider |
| `GET /jobs/requests/nearby/` | query `lat`, `lng`, `radius_km`; response includes each request's `latitude`, `longitude` (no distance) |
| `GET/PATCH /customers/profile/` | `latitude`, `longitude` (write-only fields re-injected on read, only when both are set) |
| `GET/PATCH /providers/profile/` | `base_latitude`, `base_longitude` |
| `POST/GET /jobs/requests/` | `latitude`, `longitude` (required on create) |
| `ws/providers/nearby/` | subscribe frame `{lat, lng, radius_km}`; snapshot + `provider_update` frames carry coordinates |

Errors:
- `400` — `lat`/`lng` missing or non-numeric on `/services/nearby/`; missing coordinates on request creation
- `500` — non-numeric `radius_km` on `/services/nearby/`; out-of-range latitude reaching `geopy`

No coordinate is ever rounded, fuzzed, or truncated before being returned.

## 11. Data Model

No location-specific model exists. See REQ-1 for the three carriers.

There is **no** location history, no breadcrumb trail, and no record of where a provider was when
they accepted or completed a job.

## 12. Security

- **Authentication:** required everywhere except `/services/nearby/`.
- **Authorization:** role gates; no location-specific authorization exists.
- **Object-level access:** a request's coordinate is readable by its owner, by any provider
  within radius during the 30-minute window, and by the accepting provider thereafter.
- **Sensitive data:** exact device coordinates, unrounded.
- **Abuse/rate limiting:** `anon` scope on the public endpoint; nothing prevents systematic
  coordinate sweeping within that budget.
- **Auditability:** none. No record of who queried what location, or of location disclosure.

### CONFLICT-008-A — Location handling contradicted the security baseline
**Status:** PARTIALLY RESOLVED (2026-08-17) · **Severity was:** High

| ID | Finding | Severity | Status |
|---|---|---|---|
| SECGAP-008-1 | `GET /services/nearby/` was `AllowAny`, so unauthenticated callers got exact provider coordinates and business names, and sweeping `lat`/`lng` enumerated the whole supply side | High | **RESOLVED** — `IsAuthenticated` (ADR-014) |
| SECGAP-008-2 | `GET /jobs/requests/nearby/` gives any online provider within radius the customer's exact coordinate, description, and vehicle summary before any relationship exists | High | **ACCEPTED BY DESIGN** (ADR-015) — not fixed. `customer_name` no longer discloses a phone number, and the exposure is bounded to `open` requests inside a 30-minute window and a capped radius. The compensating control is provider verification (OQ-003-A), still open. |
| SECGAP-008-3 | `provider_update` events were broadcast platform-wide with filtering left to the client | High | **RESOLVED** — the consumer filters by the subscriber's own radius before sending |
| SECGAP-008-4 | Coordinates are never coarsened, even where disclosure is legitimate | Medium | **CLOSED for the browse path** by ADR-015 (coarsening would degrade the accept/decline signal). Still open in principle for any future disclosure surface. |
| SECGAP-008-5 | No coordinate validation; out-of-range latitude was a `500` vector inside the discovery loop | Medium | **RESOLVED** — REQ-6 |

Evidence: [apps/jobs/views.py](apps/jobs/views.py), [apps/providers/consumers.py](apps/providers/consumers.py), [apps/jobs/serializers.py](apps/jobs/serializers.py) `_person_name`

## 13. Edge Cases

- `lat=0&lng=0` — a legitimate query in the Gulf of Guinea, and also the silent default for a
  provider feed called without parameters. Null-island requests and null-island searches match.
- Latitude beyond ±90 → stored fine, then `geopy` raises during scoring → `500`.
- Longitude near ±180 → the bounding box produces an impossible range and silently returns nothing.
- `cos(lat)` at the poles → clamped by `max(…, 0.01)`, producing a very wide longitude pad rather
  than a division by zero.
- `radius_km=0` on HTTP → matches only exact-coincident points; on the WebSocket it is clamped
  back to the 25 km default.
- `radius_km=100000` on HTTP → accepted; the bounding box degenerates to the whole world and the
  scan becomes a full table scan capped at 50 results. The WebSocket path clamps at 500.
- More than 50 results → silent truncation, so a dense city shows a partial map with no signal.
- A provider who moves physically but never updates `base_*` remains discoverable at their old
  workshop location.

## 14. Acceptance Criteria

- [x] Requests require coordinates; providers require coordinates to go online.
- [x] Distances are geodesic and returned to customers.
- [x] Both discovery directions sort nearest-first.
- [x] The backend has no GDAL/PostGIS dependency.
- [x] Coordinates are range-validated at every entry point (REQ-6).
- [x] Provider locations are not readable by unauthenticated callers.
- [x] Presence broadcasts respect the subscriber's radius.
- [x] Result truncation is signalled on `/services/nearby/` (`truncated`).
- [x] Bad query parameters return `400`, never `500`.
- [x] Customer locations reach only providers with a legitimate need — where "browsing to decide
      whether to accept" counts as legitimate (ADR-015).
- [x] Distance is returned on the provider request feed (REQ-4).
- [x] Verification level gates location precision — [SPEC-013](013-provider-verification.md) REQ-2.
- [ ] Bounds are enforced at the database level — **deferred** (OQ-008-G).

## 15. Tests

### Existing — across `tests/test_discovery.py`, `test_profiles.py`, `test_service_requests.py`
- **Radius behavior:** a provider just inside and just outside the radius; a request inside and
  outside; nearest-first ordering asserted with two requests at known distances.
- **Validation:** out-of-range latitude/longitude on request creation (parametrized over four
  cases), on the customer profile, and on query parameters; non-numeric and out-of-range
  `radius_km`; missing `lat`/`lng` on both discovery endpoints.
- **Pairing:** half-pair coordinate updates rejected on both customer and provider profiles.
- **Privacy:** `/services/nearby/` requires authentication; `customer_name` never yields a phone
  number.

### Still missing (gap)
- **Unit:** `distance_meters` against known coordinate pairs; bounding-box padding at 60°
  latitude and across the antimeridian; the 50-result cap with >50 candidates.
- **WebSocket:** radius clamping and per-subscriber filtering asserted through the consumer.

## 16. Observability

- Logs: none for location queries.
- Metrics: none — no query volume, radius distribution, or result-count distribution.
- Errors: `geopy` failures surface as unhandled `500`s through the shared handler.
- Audit events: none. Location disclosure is not recorded.

## 17. Dependencies

- `geopy==2.4.1`.
- SPEC-002/003 (stored coordinates), SPEC-005 (request coordinate), SPEC-006 (both discovery
  directions), SPEC-003 (presence broadcast).
- Client-side map providers are out of scope for the backend.

## 18. Open Questions

- **OQ-008-A** — ~~Should `/services/nearby/` stay public?~~ **RESOLVED 2026-08-17:** no, it
  requires authentication (ADR-014). If pre-signup supply visibility is later wanted for the
  landing page, revisit with a count-only or coarsened variant rather than reopening the
  endpoint.
- **OQ-008-G** — Should coordinate bounds be enforced by database `CheckConstraint`s as well as
  validators? Deferred: the migration would fail on any pre-existing out-of-range row, so it
  needs a data audit first.
- **OQ-008-B** — ~~At what point should a provider see the customer's exact coordinate?~~
  **RESOLVED 2026-08-17:** on browsing, before accepting (ADR-015). A provider decides whether to
  take a job largely on where it is, so the location travels with the request in the feed.
- **OQ-008-C** — Should the provider's stored `service_radius_km` be authoritative rather than the
  client-supplied radius?
- **OQ-008-D** — ~~Should coordinates be coarsened for pre-acceptance disclosure?~~
  **RESOLVED 2026-08-17:** no, for the browse path — coarsening degrades the accept/decline
  signal (ADR-015). Still worth asking for any *new* disclosure surface.
- **OQ-008-E** — Is live provider tracking during a job a product requirement? Nothing implements
  it; `docs/DOMAIN.md` mentions "communicate arrival/progress".
- **OQ-008-F** — ~~Should location disclosure be audited?~~ **RESOLVED 2026-08-17:** no
  (ADR-016) — reads are high-volume and low-value; request logs cover them.

## 19. Implementation Notes

- The bounding-box constant `111.0` is kilometres per degree of latitude. It is duplicated
  verbatim in [apps/providers/nearby_presence.py:17-18](apps/providers/nearby_presence.py#L17-L18) and [apps/jobs/views.py:269-270](apps/jobs/views.py#L269-L270) rather than living in `apps/core/geo.py`.
- `apps/core/geo.py` contains exactly one function; the module docstring records the
  no-GDAL decision, which belongs in `docs/DECISIONS.md` (added there as ADR-003).
- Every distance computation is O(candidates) in Python. With a large online provider pool this
  becomes the dominant cost of `/services/nearby/`, which is also the only unauthenticated
  endpoint — a combination worth noting for load.
- The customer presence consumer keeps `customer_lat`, `customer_lng`, and `radius_km` on the
  connection and checks only that they are non-`None` before forwarding. The values are captured
  but never used to filter, which reads as an unfinished implementation rather than a decision.

## 20. Verification Evidence

- Files: [apps/core/geo.py](apps/core/geo.py), [apps/core/validators.py](apps/core/validators.py), [apps/providers/nearby_presence.py](apps/providers/nearby_presence.py), [apps/jobs/views.py](apps/jobs/views.py), [apps/providers/consumers.py](apps/providers/consumers.py)
- Dependency: `geopy==2.4.1` ([requirements.txt](requirements.txt))
- Tests: coordinate and radius coverage across `tests/test_discovery.py`,
  `tests/test_profiles.py`, `tests/test_service_requests.py`. All passing.
- Commands: `pytest -q` → 169 passed; `manage.py makemigrations --check --dry-run` → no changes.
- Migrations: `jobs/0006`, `mechanics/0004`, `drivers/0003` (coordinate validators).
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
