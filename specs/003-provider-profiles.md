# SPEC-003 — Provider Profiles

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

A provider is a service provider with a business identity, a workshop coordinate, a service
radius, an online/offline availability flag, a rating summary, and a list of service offerings
keyed to platform service categories. Availability plus workshop coordinate is what makes a
provider discoverable (SPEC-006).

## 2. Problem

Customers need to see who can help nearby, and providers need control over whether they are
currently accepting work.

## 3. Actors

- Service Provider — owns and edits their own profile and offerings.
- Customer — reads a **subset** of provider data through discovery endpoints.
- Administrator — full read/write via Django admin.

## 4. Goals

- Let a provider go online/offline deliberately.
- Publish a workshop location and a service radius.
- Declare which service categories the provider covers, with optional rates.

## 5. Non-Goals

- Verification and document review — a separate concern, see [SPEC-013](013-provider-verification.md).
- Multi-technician shops, staff, or opening hours.
- Live GPS tracking of the provider (only a static base coordinate exists).

## 6. Requirements

### REQ-1 — Implicit profile creation with a derived business name
**ID:** PROD-003-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

A provider's profile is created on first `GET`/`PUT`/`PATCH` of `/providers/profile/`, with
`business_name` defaulting to the email local-part, else the phone, else `"Workshop"`. Google
sign-in creates it eagerly with `business_name` set to the email.

`PARTIAL` — creation only happens on `/providers/profile/`. The other provider endpoints call
`ProviderProfile.objects.get(...)` and raise an unhandled `DoesNotExist` if the profile is
missing. See CONFLICT-003-A.

Evidence: [apps/providers/views.py:12-23](apps/providers/views.py#L12-L23), [apps/accounts/views.py:285-289](apps/accounts/views.py#L285-L289)

### REQ-2 — Read and update own profile
**ID:** API-003-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A provider may read and update `business_name`, `bio`, `base_latitude`, `base_longitude`,
`service_radius_km`, and `is_available`. Ratings are read-only.

Evidence: [apps/providers/serializers.py:18-33](apps/providers/serializers.py#L18-L33)

### REQ-3 — Cannot go online without a workshop location
**ID:** DOM-003-003 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Setting `is_available = true` is rejected with `400` unless both `base_latitude` and
`base_longitude` are present (existing or in the same payload).

Evidence: [apps/providers/serializers.py:8-16](apps/providers/serializers.py#L8-L16)

### REQ-4 — Availability defaults to offline
**ID:** DOM-003-004 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`is_available` defaults to `False`; a new provider is invisible to discovery until they opt in.

Evidence: [apps/providers/models.py:20](apps/providers/models.py#L20)

### REQ-5 — Service offerings
**ID:** PROD-003-005 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** PARTIAL

A provider may create, list, update, and delete offerings. Each references an **active**
`ServiceCategory` and carries an optional title, description, `hourly_rate`, and `is_active`.

`PARTIAL` — offerings are stored and editable but **no longer influence anything**. See
CONFLICT-003-B.

Evidence: [apps/providers/views.py:26-50](apps/providers/views.py#L26-L50), [apps/providers/models.py:41-68](apps/providers/models.py#L41-L68)

### REQ-6 — Rating summary
**ID:** DOM-003-006 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`rating_avg` and `rating_count` are read-only over the API and maintained by
`apps.reviews.services.recalculate_provider_rating`, wired to `post_save` / `post_delete` on
`Review` (SPEC-011 REQ-5). They now carry real values in the profile response, discovery
payloads, presence broadcasts, and the matching score, and the model's default ordering
`-rating_avg` is finally meaningful.

Cross-reference: SPEC-011 CONFLICT-011-A (resolved).

### REQ-7 — Ownership isolation
**ID:** SEC-003-007 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Profile and offering querysets are scoped to `request.user`; a provider cannot read or edit
another provider's offering even with a valid offering id.

Evidence: [apps/providers/views.py:30-50](apps/providers/views.py#L30-L50)

## 7. User Flow

1. Sign up with `role = provider`.
2. `GET /providers/profile/` → profile created with a derived business name.
3. `PATCH` workshop coordinates and radius.
4. `PATCH {"is_available": true}` → provider becomes discoverable and is broadcast to subscribed customers.
5. Optionally add offerings at `/providers/services/`.
6. Poll `/jobs/requests/nearby/` and accept work (SPEC-006, SPEC-007).

## 8. Business Rules

- One `ProviderProfile` per `User` (`OneToOneField`, CASCADE).
- `service_radius_km` defaults to 25 and is a positive integer.
- Offerings are unique on `(provider, category, title)`; a blank title participates in that key,
  so a provider may hold at most one untitled offering per category.
- `ProviderServiceOffering.category` uses `on_delete=PROTECT`: a category in use cannot be deleted.
- Default ordering is `-rating_avg, -created_at` — currently equivalent to `-created_at` (REQ-6).
- Any save of a `ProviderProfile` broadcasts a presence event (see §12 and SPEC-008).

## 9. State Model

Availability is the only state:

```text
OFFLINE (is_available=false)  <->  ONLINE (is_available=true)
```

| From | Action | To | Actor | Conditions |
|---|---|---|---|---|
| OFFLINE | `PATCH {"is_available": true}` | ONLINE | Provider (self) | `base_latitude` and `base_longitude` both set |
| ONLINE | `PATCH {"is_available": false}` | OFFLINE | Provider (self) | none |

**IMPLEMENTATION NOTE:** availability is not affected by job state. A provider with an active job
stays online and keeps appearing in discovery and in the nearby-requests feed. There is no
capacity or concurrency limit. See OQ-003-C.

**Verification is a second, independent axis** — see [SPEC-013](013-provider-verification.md).
`ProviderProfile.verification_level` moves `none → phone → documents → ghana_card` and controls
how precisely the provider sees customer locations. It deliberately does **not** gate availability:
an unverified provider can still go online and work.

## 10. API Contract

`GET | PUT | PATCH /api/v1/providers/profile/` — auth: JWT; permissions: `IsAuthenticated` + `IsProvider`.

```json
{
  "id": "uuid", "business_name": "Kofi Auto Works", "bio": "",
  "base_latitude": 5.6037, "base_longitude": -0.187,
  "service_radius_km": 25, "is_available": true,
  "rating_avg": "0.00", "rating_count": 0,
  "verification_level": "none",
  "created_at": "…", "updated_at": "…"
}
```

Read-only: `id`, `rating_avg`, `rating_count`, `verification_level`, `created_at`, `updated_at`.
`verification_level` is granted by SPEC-013, never set here.

`GET | POST /api/v1/providers/services/`
`GET | PUT | PATCH | DELETE /api/v1/providers/services/{id}/`
Auth: JWT; permissions: `IsAuthenticated` + `IsProvider`.

```json
{ "id": "uuid", "category": "uuid", "category_name": "Tire / Wheel Service",
  "category_slug": "tire-flat", "title": "Roadside tire change",
  "description": "", "hourly_rate": "80.00", "is_active": true,
  "created_at": "…", "updated_at": "…" }
```

Errors:
- `400` — `is_available` without coordinates; inactive/unknown `category`; duplicate `(provider, category, title)`
- `401` — unauthenticated
- `403` — not a provider
- `404` — offering id not owned by the caller
- `500` — see CONFLICT-003-A

Pagination: list endpoints use the global `PageNumberPagination`, page size 20.
Filtering/search: none.

## 11. Data Model

`providers.ProviderProfile`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `user` | OneToOne → `accounts.User` | `related_name="provider_profile"` |
| `business_name` | char(200) | required |
| `bio` | text, blank | |
| `base_latitude` / `base_longitude` | float, null | workshop coordinate |
| `service_radius_km` | positive int | default 25 |
| `is_available` | bool, indexed | default `False` |
| `rating_avg` | decimal(3,2) | validators 0–5; maintained by `apps.reviews.services` (REQ-6) |
| `rating_count` | positive int | maintained by `apps.reviews.services` (REQ-6) |
| `created_at` / `updated_at` | datetime | |

`providers.ProviderServiceOffering`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `provider` | FK → `ProviderProfile` | `related_name="service_offerings"`, CASCADE |
| `category` | FK → `jobs.ServiceCategory` | PROTECT, `related_name="provider_offerings"` |
| `title` | char(120), blank | part of the unique key |
| `description` | text, blank | |
| `hourly_rate` | decimal(10,2), null | currency undefined — see OQ-003-D |
| `is_active` | bool | default `True` |

Indexes: `is_available`; `(provider, is_active)`.
Relationship: `ProviderProfile 1—* jobs.Job` (`related_name="jobs"`, CASCADE).

Migrations: `providers/0001_initial`, `0002_mechanicserviceoffering`, `0003_rename_…_idx`.

## 12. Security

- **Authentication:** JWT.
- **Authorization:** `IsProvider` plus self-scoped querysets.
- **Object-level access:** enforced by queryset filtering on `provider__user`.
- **Sensitive data:** the workshop coordinate is business-address-grade data and is published
  broadly (below).
- **Abuse/rate limiting:** default `user` scope only.
- **Auditability:** none — availability changes are not recorded.

### CONFLICT-003-A — Missing profile caused a 500
**Status:** RESOLVED (2026-08-17) · **Severity was:** High

Four call sites used a bare `ProviderProfile.objects.get(user=request.user)`, so a provider who
registered and called `/providers/services/` before `/providers/profile/` got an unhandled
`DoesNotExist` → `500`.

**Fix:** [apps/providers/selectors.py](apps/providers/selectors.py) provides two helpers with
deliberately different semantics:

- `ensure_provider_profile(user)` — creates on first use. Used by the offering endpoints, so
  listing or creating an offering now works immediately after signup.
- `get_provider_profile(user)` — raises `Conflict` (409, "Set up your provider profile before
  using this endpoint"). Used where implicit creation would be wrong: browsing the request feed
  and accepting a job, both of which need a workshop location the provider must set deliberately.

Both reject a non-provider account with `409` rather than silently creating a profile for them.

Verified by: `test_offerings_before_profile_exists_do_not_500`,
`test_provider_without_profile_gets_409` (in both `test_job_lifecycle.py` and `test_discovery.py`).

### CONFLICT-003-B — Offerings no longer affect the work a provider is shown
**Status:** CONFLICT · **Severity:** Medium

`NearbyOpenRequestsView` previously filtered open requests to the provider's active offering
categories. That filter was **removed in the current working tree** (uncommitted change to
`apps/jobs/views.py`) with the rationale that "strict category matching can hide valid nearby
requests". Offerings are still collected from providers and still shown in the UI contract, but
they no longer influence discovery, matching, or acceptance.

Evidence: [apps/jobs/views.py:283-285](apps/jobs/views.py#L283-L285) and `git diff apps/jobs/views.py`.

**OPEN QUESTION (OQ-003-B):** Are offerings now purely informational, or should category
matching return as a ranking signal rather than a hard filter?

### Security gaps — current status

| ID | Finding | Severity | Status |
|---|---|---|---|
| SECGAP-003-1 | Presence broadcasts sent every provider's coordinates to every subscribed customer, with filtering left to the client | High | **RESOLVED** — `CustomerNearbyProvidersConsumer.provider_presence` now computes the geodesic distance from the subscriber's own stored `lat`/`lng` and drops the event if it exceeds their radius. The forwarded payload gains `distance_km`. |
| SECGAP-003-2 | `GET /services/nearby/` was `AllowAny` | High | **RESOLVED** — now `IsAuthenticated` (SPEC-008, ADR-014) |
| SECGAP-003-3 | A user could self-assign `role = provider` and immediately harvest customer locations | High | **RESOLVED** — role is no longer self-assignable (SPEC-001 REQ-9), and an unverified provider now sees only coarsened customer locations (SPEC-013 REQ-2). Registering as a provider is still unrestricted, by design (SPEC-013 REQ-3). |
| SECGAP-003-4 | `bio` was unbounded | Low | **RESOLVED** — capped at 2000 chars |
| SECGAP-003-5 | Base coordinates were unvalidated | Medium | **RESOLVED** — range validators, and a half-pair update is now rejected instead of silently applied |

Evidence: [apps/providers/consumers.py](apps/providers/consumers.py), [apps/providers/serializers.py](apps/providers/serializers.py)

## 13. Edge Cases

- Customer calls a `/providers/…` endpoint → `403`.
- `is_available: true` with no coordinates → `400` with a field error on `is_available`.
- Clearing coordinates while online: `PATCH {"base_latitude": null}` passes validation, because
  the validator reads the *incoming* value, which is `None`, and short-circuits on
  `is_available` being unchanged-true only when both coordinates resolve. **IMPLEMENTATION NOTE:**
  the effective result is a `400` (`is_available` true + a null coordinate), so an online
  provider cannot null out one coordinate. Untested.
- Duplicate offering `(category, title)` → `400` from the unique constraint.
- Offering referencing an inactive category → `400` (the queryset filters `is_active=True`).
- Deleting a `ServiceCategory` that any offering references → blocked by `PROTECT`.
- Provider goes offline mid-job → job is unaffected; no rule ties the two.

## 14. Acceptance Criteria

- [x] First `/providers/profile/` call creates the profile.
- [x] Going online requires both coordinates.
- [x] New providers start offline.
- [x] Offering CRUD is scoped to the owner.
- [x] Ratings are read-only over the API.
- [x] `rating_avg` / `rating_count` reflect real reviews (REQ-6).
- [x] A missing provider profile yields a handled `409`, not a `500`.
- [x] Provider coordinates require authentication, and presence updates are radius-filtered
      server-side.
- [x] A duplicate offering returns `400`, not `500`.
- [x] A half-pair coordinate update is rejected.
- [x] Verification status exists — see [SPEC-013](013-provider-verification.md).
- [ ] `service_radius_km` constrains what a provider is shown — **NOT_IMPLEMENTED** (OQ-003-E).

## 15. Tests

### Existing — in `tests/test_profiles.py` (11 provider tests)
- **Profile:** auto-created on first access and starts offline; customer `403`; cannot go online
  without a location; can go online with one; half-pair coordinate rejected; ratings read-only.
- **Offerings:** listing before the profile exists returns `200` (formerly `500`); create;
  duplicate `400`; inactive category `400`; owner-scoped detail with `404` for another provider.

Availability's effect on discovery is covered in `tests/test_discovery.py`; rating aggregation in
`tests/test_reviews.py`.

### Still missing (gap)
- **Unit:** `provider_preview_from_instance` with null coordinates.
- **WebSocket:** presence radius filtering asserted end to end through the consumer.

## 16. Observability

- Logs: none for availability changes or offering edits.
- Metrics: none (no count of online providers).
- Errors: shared DRF handler; `DoesNotExist` surfaces as an unhandled 500 (CONFLICT-003-A).
- Audit events: none.

## 17. Dependencies

- SPEC-001 (role), SPEC-005/006 (`ServiceCategory`), SPEC-008 (geo + presence transport), SPEC-011 (ratings).
- Django Channels + `channels_redis` for the presence broadcast.

## 18. Open Questions

- **OQ-003-A** — ~~Is provider verification a product requirement?~~ **RESOLVED 2026-08-17:**
  yes — specified and implemented to Tier 1 (manual document review) in
  [SPEC-013](013-provider-verification.md). Automated document checks and Ghana Card verification
  remain future tiers.
- **OQ-003-B** — Should service offerings gate or merely rank the requests a provider sees? (CONFLICT-003-B)
- **OQ-003-C** — May a provider hold several concurrent jobs? Nothing limits it today.
- **OQ-003-D** — What currency is `hourly_rate`? The field has no currency; `payments.Payment` defaults to `USD` while the launch market appears to be Ghana.
- **OQ-003-E** — Should `service_radius_km` constrain what a provider is shown? It is stored but never applied — `/jobs/requests/nearby/` uses a client-supplied radius instead.

## 19. Implementation Notes

- `ProvidersConfig.ready()` imports `apps.providers.signals`, so the presence broadcast is active
  in every process that loads the app, including management commands and the Celery worker.
- The broadcast is fired by `post_save` on **any** field change, including `updated_at` churn.
- `ProviderProfileSerializer.validate` reads pre-existing values via `getattr(self.instance, …)`,
  so a partial update is evaluated against the merged state rather than the payload alone.
- `service_radius_km` is stored but no server-side code reads it; radius always comes from the
  request's query parameters or the WebSocket subscribe frame.
- The default ordering `-rating_avg` is currently a no-op tiebreak (REQ-6) but will silently
  change list ordering the moment ratings start being written.

## 20. Verification Evidence

- Files: [apps/providers/selectors.py](apps/providers/selectors.py), [apps/providers/views.py](apps/providers/views.py), [apps/providers/serializers.py](apps/providers/serializers.py), [apps/providers/consumers.py](apps/providers/consumers.py)
- Routes: [autrifix/api_urls.py](autrifix/api_urls.py)
- Tests: 11 provider tests in `tests/test_profiles.py`, plus discovery and rating coverage
  elsewhere. All passing.
- Commands: `pytest -q` → 169 passed; `manage.py makemigrations --check --dry-run` → no changes.
- Migration: `mechanics/0004` (coordinate validators, bio cap).
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
