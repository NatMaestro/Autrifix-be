# SPEC-002 — Customer Profiles

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

The customer of the platform is modelled as a **customer**. `CustomerProfile` is a thin record
attached one-to-one to a `User`: a display name, an optional home location, and the owning side
of the customer's vehicles and service requests.

**CONFLICT-002-A (naming) — RESOLVED 2026-08-18.** The documentation said "Customer" while the
code said `driver` everywhere. ADR-020 settled it in the documentation's favour: the role value,
model, URL prefix, and permission class are all `customer` now. (The Django *app label* is still
`drivers` for migration-history reasons — see ADR-020.)

## 2. Problem

A service request needs a stable owner with contact identity, a reusable garage of vehicles,
and optionally a default location so a customer does not re-enter their address each time.

## 3. Actors

- Customer — owns and edits their own profile.
- Provider — reads a derived `customer_name` on requests and jobs, never the profile itself.
- Administrator — read/write via Django admin.

## 4. Goals

- One profile per customer account, created without an explicit onboarding step.
- Own the customer's vehicles (SPEC-004) and service requests (SPEC-005).

## 5. Non-Goals

- Customer verification, KYC, or document upload.
- Saved addresses beyond a single home coordinate.
- Publicly visible profile pages for other users.

## 6. Requirements

### REQ-1 — Implicit profile creation
**ID:** PROD-002-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

A customer never explicitly creates a profile. It is created on first touch of any customer
endpoint via `get_or_create`.

`PARTIAL` — creation is lazy and duplicated across three call sites rather than happening once
at registration:

| Call site | File |
|---|---|
| `CustomerProfileDetailView.get_object` | [apps/customers/views.py](apps/customers/views.py) |
| `CustomerVehicleQuerysetMixin.get_queryset` | [apps/customers/views.py](apps/customers/views.py) |
| `CustomerScopedRequestMixin` | [apps/jobs/views.py](apps/jobs/views.py) |
| Google sign-in (eager) | [apps/accounts/views.py](apps/accounts/views.py) |

All four now route through the single helper in
[apps/customers/selectors.py](apps/customers/selectors.py).

**RESOLVED (2026-08-17):** the two divergent `ensure_customer_profile` helpers — one returning
`None` for a non-customer, the other silently creating a `CustomerProfile` for *any* user including
a provider — were replaced by a single implementation in
[apps/customers/selectors.py](apps/customers/selectors.py). It raises `Conflict` (409) for a
non-customer account rather than creating a profile for them, so the behavior no longer depends on
`IsCustomer` happening to guard every caller.

### REQ-2 — Read and update own profile
**ID:** API-002-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A customer may `GET`, `PUT`, or `PATCH` `/customers/profile/` and receives their own profile with
their vehicles embedded.

Evidence: [apps/customers/views.py:9-23](apps/customers/views.py#L9-L23)

### REQ-3 — Optional home location
**ID:** PROD-002-003 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** PARTIAL

A customer may store a home coordinate, exposed at the API as `latitude` / `longitude` and
persisted as `home_latitude` / `home_longitude`.

`PARTIAL` — the stored value is written and echoed back but **never read** by any other code
path. Service requests carry their own coordinates (SPEC-005 REQ-2); nothing defaults from the
home location.

Evidence: [apps/customers/serializers.py:49-78](apps/customers/serializers.py#L49-L78); no other reader — grep of `home_latitude` finds only the model, migration, and serializer.

**OPEN QUESTION (OQ-002-A):** What is home location for? Prefilling a request, a map default, or
dead weight from an earlier design?

### REQ-4 — Customer identity shown to a matched provider
**ID:** PROD-002-004 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Where a provider legitimately sees a request or job, the customer appears as a single
`customer_name` string resolved in this order: `display_name` → `first_name last_name` →
`phone` → `email`.

Evidence: [apps/jobs/serializers.py:79-91](apps/jobs/serializers.py#L79-L91), [apps/jobs/serializers.py:122-135](apps/jobs/serializers.py#L122-L135)

**IMPLEMENTATION NOTE:** the fallback chain ends at raw `phone` or `email`. A customer who fills in
no name discloses their phone number to every provider who can see the request — including, via
`/jobs/requests/nearby/`, providers who have not yet been matched. See SPEC-008 SECGAP-008-2.

### REQ-5 — Ownership isolation
**ID:** SEC-002-005 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

No endpoint accepts a customer-profile id. The profile is always resolved from `request.user`, so
one customer cannot address another's profile.

Evidence: [apps/customers/views.py:14-23](apps/customers/views.py#L14-L23)

## 7. User Flow

1. User registers or signs in with `role = customer`.
2. Client calls `GET /customers/profile/`; the profile is created on the spot and returned.
3. Customer optionally sets `display_name` and a home coordinate.
4. Customer adds vehicles (SPEC-004) and creates requests (SPEC-005).

## 8. Business Rules

- Exactly one `CustomerProfile` per `User` (`OneToOneField`).
- Deleting the user cascades to the profile, its vehicles, and its service requests.
- `display_name` is free text, ≤120 chars, and may be blank.
- Latitude and longitude are only persisted when **both** are supplied in the same request.
- Profiles are ordered `-created_at`.

## 9. State Model

None. `CustomerProfile` has no status field and no lifecycle.

## 10. API Contract

`GET | PUT | PATCH /api/v1/customers/profile/`

Authentication: required (JWT).
Permissions: `IsAuthenticated` **and** `IsCustomer`.

Response `200`:

```json
{
  "id": "uuid",
  "display_name": "Ama K.",
  "latitude": 5.6037,
  "longitude": -0.187,
  "vehicles": [ { "id": "uuid", "make": "Toyota", "model": "Corolla", "…": "…" } ],
  "created_at": "…",
  "updated_at": "…"
}
```

`latitude` / `longitude` are declared `write_only` on the serializer and re-inserted in
`to_representation` only when both are set — so they are absent from the response for a customer
who has never set a home location.

Errors:
- `401` — no or invalid token
- `403` — authenticated as provider or admin (`IsCustomer` fails)

Pagination: not applicable (single object). Filtering/search: none.

## 11. Data Model

`customers.CustomerProfile`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `user` | OneToOne → `accounts.User` | `related_name="customer_profile"`, CASCADE |
| `display_name` | char(120), blank | |
| `home_latitude` | float, null | exposed as `latitude` |
| `home_longitude` | float, null | exposed as `longitude` |
| `created_at` / `updated_at` | datetime | |

Relationships:
- `CustomerProfile 1—* drivers.Vehicle` (`related_name="vehicles"`, CASCADE)
- `CustomerProfile 1—* jobs.ServiceRequest` (`related_name="service_requests"`, CASCADE)

Migrations: `drivers/0001_initial`, `drivers/0002_vehicle_specs` (vehicles only).

## 12. Security

- **Authentication:** JWT required.
- **Authorization:** role gate `IsCustomer` plus implicit self-scoping.
- **Object-level access:** structural — no id is ever accepted from the client.
- **Sensitive data:** home coordinates and the `customer_name` fallback to phone/email. See REQ-4 note.
- **Abuse/rate limiting:** default `user` scope only.
- **Auditability:** none.

### Security gaps — current status

| ID | Finding | Severity | Status |
|---|---|---|---|
| SECGAP-002-1 | A user who flipped `role` to `provider` kept an orphaned `CustomerProfile` | Medium | **RESOLVED** — `role` is no longer self-assignable (SPEC-001 REQ-9), so the scenario cannot arise from the API |
| SECGAP-002-2 | `customer_name` fell back to a raw phone number, disclosed to unmatched providers | Medium | **RESOLVED** — `_person_name` falls back to the literal `"Customer"`; phone and email are never used |
| SECGAP-002-3 | A lone `latitude` or `longitude` was silently discarded with a `200` | Low | **RESOLVED** — now `400` |

## 13. Edge Cases

- Provider calls `/customers/profile/` → `403`, even if they previously held a customer profile.
- `PATCH` with only `latitude` → silently ignored; the value is dropped unless `longitude` is present in the same payload. **IMPLEMENTATION NOTE:** no validation error is raised, so a client cannot tell the write was discarded.
- Customer with no vehicles → `vehicles: []`.
- `CustomerProfile.__str__` renders `Customer(None)` for phone-only accounts because it formats `self.user.email`. Cosmetic; visible in Django admin.
- Concurrent first requests could race in `get_or_create`; the `OneToOneField` unique constraint would surface as an `IntegrityError` (500) rather than a handled conflict. Unobserved in practice.

## 14. Acceptance Criteria

- [x] A customer's first `GET /customers/profile/` returns `200` and creates the profile.
- [x] A provider receives `403`.
- [x] An unauthenticated caller receives `401`.
- [x] `PUT`/`PATCH` updates `display_name`.
- [x] Vehicles are embedded read-only in the profile response.
- [x] Partial coordinate updates are rejected rather than silently dropped.
- [x] Coordinates are range-validated.
- [ ] Home location has a defined consumer — **blocked on OQ-002-A**. It is still written, read
      back, and used by nothing.

## 15. Tests

### Existing — in `tests/test_profiles.py` (5 customer-profile tests)
- Profile auto-created on first GET; provider receives `403`; home location round-trips;
  a lone `latitude` or `longitude` is rejected (parametrized); out-of-range coordinate rejected.

Ownership isolation is covered by the vehicle and service-request suites, which share the same
profile-resolution helper.

### Still missing (gap)
- **Integration:** `401` for anonymous on `/customers/profile/` specifically.

## 16. Observability

- Logs: none specific to customer profiles.
- Metrics: none.
- Errors: via the shared DRF exception handler.
- Audit events: none.

## 17. Dependencies

- SPEC-001 (identity and `role`).
- SPEC-004 (vehicles are embedded here).
- SPEC-005 / SPEC-007 consume `customer_name`.

## 18. Open Questions

- **OQ-002-A** — What consumes `home_latitude` / `home_longitude`?
- **OQ-002-B** — ~~Should "Customer" or "Driver" be the canonical term?~~ **RESOLVED 2026-08-18:**
  `customer` (ADR-020). `driver` also collided with rideshare apps and, once tow operators joined
  the platform, with providers who literally drive.
- **OQ-002-C** — When a user changes role, what happens to the profile of the abandoned role?
- **OQ-002-D** — Should a customer be able to suppress their phone number from `customer_name`?

## 19. Implementation Notes

- `CustomerProfileDetailView` declares both a class-level `queryset` and a `get_queryset`, but
  `get_object` ignores both and calls `get_or_create` directly. The queryset exists only to keep
  drf-spectacular schema generation happy.
- Every customer view carries a `swagger_fake_view` guard so schema generation does not hit the
  database with an anonymous user.
- `CustomerProfile` is created lazily on read. A customer who has authenticated but never called a
  customer endpoint has no row, so admin user counts and profile counts will not agree.

## 20. Verification Evidence

- Files: [apps/customers/models.py](apps/customers/models.py), [apps/customers/views.py](apps/customers/views.py), [apps/customers/serializers.py](apps/customers/serializers.py), [apps/customers/selectors.py](apps/customers/selectors.py)
- Route: [autrifix/api_urls.py](autrifix/api_urls.py)
- Tests: 5 customer-profile tests in `tests/test_profiles.py`. All passing.
- Commands: `pytest -q` → 169 passed; `manage.py makemigrations --check --dry-run` → no changes.
- Migration: `drivers/0003`.
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
