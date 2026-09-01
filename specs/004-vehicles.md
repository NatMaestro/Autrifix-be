# SPEC-004 — Vehicles

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

A customer keeps a garage of vehicles. Each vehicle carries identification (make, model, year,
plate, VIN), service-relevant specifications (tire size, battery group, belt part number, oil
spec, coolant type), a free-form `extra` JSON bag, an optional photo, and a primary flag. A
service request may reference one vehicle.

## 2. Problem

A provider responding to a roadside call needs to know what they are coming to — and which
parts to bring — before arriving. Re-typing that per request is error-prone.

## 3. Actors

- Customer — full CRUD over their own vehicles.
- Provider — reads only a derived `vehicle_summary` string on a request they can see.
- Administrator — full read/write via Django admin.

## 4. Goals

- Reusable vehicle records owned by the customer.
- Enough parts detail to make a roadside visit useful on the first trip.
- One designated primary vehicle for fast request creation.

## 5. Non-Goals

- VIN decoding, plate lookup, or any external vehicle-data integration.
- Service history per vehicle.
- Vehicle sharing between customers.

## 6. Requirements

### REQ-1 — Vehicle CRUD scoped to the owner
**ID:** PROD-004-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A customer may list, create, retrieve, update, and delete vehicles. Every queryset is filtered to
the caller's own `CustomerProfile`, so an unowned vehicle id returns `404`.

Evidence: [apps/customers/views.py:26-50](apps/customers/views.py#L26-L50)

### REQ-2 — Minimum required data
**ID:** DOM-004-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Only `make` and `model` are required. Every other field is optional or blank-defaulted.

Evidence: [apps/customers/models.py:34-51](apps/customers/models.py#L34-L51)

### REQ-3 — Service-relevant specifications
**ID:** PROD-004-003 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A vehicle may record `trim`, `color`, `engine`, `tire_size`, `battery_group`,
`belt_part_number`, `oil_spec`, `coolant_type`, free-text `notes`, and an arbitrary `extra`
JSON object.

Evidence: [apps/customers/models.py:38-49](apps/customers/models.py#L38-L49), migration [apps/customers/migrations/0002_vehicle_specs.py](apps/customers/migrations/0002_vehicle_specs.py)

**OPEN QUESTION (OQ-004-A):** These fields exist and are stored, but the provider-facing
`vehicle_summary` exposes only year/make/model/colour. Are the parts specs intended to reach the
provider, or are they a customer-side memo?

### REQ-4 — At most one primary vehicle
**ID:** DOM-004-004 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** PARTIAL

Setting `is_primary = true` on a vehicle clears the flag on that customer's other vehicles.

`PARTIAL` — enforced only in serializer code, with no database constraint, and the demotion is
performed inside `validate()` as a side effect rather than in `create`/`update`. Two concurrent
requests can leave zero or two primaries; a direct ORM or admin write bypasses it entirely.

Evidence: [apps/customers/serializers.py:7-17](apps/customers/serializers.py#L7-L17)

### REQ-5 — Vehicle attached to a service request
**ID:** PROD-004-005 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** PARTIAL

A service request may reference a `preferred_vehicle`. Where a provider can see the request,
the vehicle renders as `vehicle_summary`: `"{year} {make} {model}"`, suffixed with `" · {color}"`
when a colour is set.

`PARTIAL` — see CONFLICT-004-A: the referenced vehicle is not validated as belonging to the
requesting customer.

Evidence: [apps/jobs/models.py:65-71](apps/jobs/models.py#L65-L71), [apps/jobs/serializers.py:93-100](apps/jobs/serializers.py#L93-L100)

### REQ-6 — Vehicles are visible on the customer profile
**ID:** API-004-006 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`GET /customers/profile/` embeds the customer's full vehicle list read-only.

Evidence: [apps/customers/serializers.py:48](apps/customers/serializers.py#L48)

## 7. User Flow

1. Customer adds a vehicle with make and model, optionally marking it primary.
2. Customer enriches it with plate, VIN, and parts specs.
3. When creating a request, the customer may set `preferred_vehicle`.
4. The matched provider sees `vehicle_summary` on the request.

## 8. Business Rules

- A vehicle belongs to exactly one `CustomerProfile`; deleting the customer (or the user) cascades.
- `year` is a positive small integer with **no range validation** — `year: 1` or `year: 65535`
  is accepted.
- `license_plate` and `vin` are plain char fields: not unique, not validated, not normalized.
- `extra` defaults to `{}` and accepts any JSON object with no schema.
- Vehicles are ordered `-created_at`.
- A vehicle referenced by a service request uses `on_delete=SET_NULL`, so deleting a vehicle
  leaves historical requests intact with a null vehicle.

## 9. State Model

None. A vehicle has no status field; `is_primary` is a flag, not a state.

## 10. API Contract

`GET | POST /api/v1/customers/vehicles/`
`GET | PUT | PATCH | DELETE /api/v1/customers/vehicles/{id}/`

Authentication: required (JWT).
Permissions: `IsAuthenticated` **and** `IsCustomer`.
Lookup: `id` (UUID) in the path.
Pagination: list uses the global `PageNumberPagination`, page size 20.
Filtering/search: none.

Request (`POST`):

```json
{ "label": "Daily", "make": "Toyota", "model": "Corolla", "year": 2014,
  "trim": "LE", "color": "Silver", "engine": "1.8L", "license_plate": "GR 1234-20",
  "vin": "…", "tire_size": "195/65R15", "battery_group": "35", "belt_part_number": "6PK1750",
  "oil_spec": "5W-30", "coolant_type": "Pink OAT", "notes": "", "extra": {},
  "is_primary": true, "photo": null }
```

Response `201`: the same fields plus `id`, `created_at`, `updated_at` (all read-only).

Errors:
- `400` — missing `make` or `model`; malformed `extra`; unparseable `photo`
- `401` — unauthenticated
- `403` — caller is not a customer
- `404` — vehicle id not owned by the caller

**IMPLEMENTATION NOTE:** `customer` is never accepted from the client; it is injected in
`perform_create`. There is no way to create a vehicle under another customer.

## 11. Data Model

`drivers.Vehicle`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `customer` | FK → `customers.CustomerProfile` | `related_name="vehicles"`, CASCADE |
| `label` | char(120), blank | |
| `make` / `model` | char(80) | **required** |
| `year` | positive small int, null | unvalidated range |
| `trim` | char(120), blank | |
| `color` | char(64), blank | |
| `engine` | char(120), blank | |
| `license_plate` | char(32), blank | not unique |
| `vin` | char(32), blank | not unique |
| `tire_size` / `battery_group` / `belt_part_number` / `oil_spec` / `coolant_type` | char, blank | |
| `notes` | text, blank | |
| `extra` | JSON | default `{}` |
| `is_primary` | bool | default `False` |
| `photo` | image, null | `vehicles/` |
| `created_at` / `updated_at` | datetime | |

Relationships:
- `Vehicle *—1 CustomerProfile` (CASCADE)
- `Vehicle 1—* jobs.ServiceRequest` via `preferred_vehicle` (`related_name="service_requests"`, SET_NULL)

Migrations: `drivers/0001_initial` (core fields), `drivers/0002_vehicle_specs` (specs, `extra`, `photo`).

## 12. Security

- **Authentication:** JWT.
- **Authorization:** `IsCustomer` plus owner-scoped querysets.
- **Object-level access:** enforced by `Vehicle.objects.filter(customer=<caller's profile>)`;
  a foreign id yields `404`, which also avoids confirming existence.
- **Sensitive data:** plate and VIN are identifying vehicle data (`docs/SECURITY.md` names
  vehicle information as protected). They are never exposed to providers — only the derived
  `vehicle_summary` is.
- **Abuse/rate limiting:** default `user` scope. No cap on vehicles per customer and no upload
  size/type restriction on `photo` beyond Pillow's image validation.
- **Auditability:** none.

### CONFLICT-004-A — `preferred_vehicle` was not ownership-validated
**Status:** RESOLVED (2026-08-17) · **Severity was:** Medium

`ServiceRequestSerializer` left `preferred_vehicle` as a generated
`PrimaryKeyRelatedField(queryset=Vehicle.objects.all())`, so a customer could reference **any**
vehicle UUID — including another customer's — and read its year, make, model, and colour back.

**Fix:** the field is declared explicitly and its queryset is narrowed in
`ServiceRequestSerializer.__init__` to `Vehicle.objects.filter(customer=<context customer_profile>)`,
falling back to `Vehicle.objects.none()` when no customer profile is in context. A foreign id now
returns `400` on the `preferred_vehicle` field.

Verified by: `tests/test_service_requests.py::test_another_customers_vehicle_is_rejected`.

### CONFLICT-004-B — `is_primary` on create raised a 500
**Status:** RESOLVED (2026-08-17) · **Severity was:** High

`VehicleSerializer.validate()` performed database writes (demoting other primaries) and read
`self.context["customer_profile"]`, a key `VehicleListCreateView` never set — so
`POST /customers/vehicles/ {"is_primary": true}` raised `KeyError` → `500`.

**Fix:** the demotion moved out of `validate()` into `create()` and `update()`, both wrapped in
`@transaction.atomic`, and it now derives the customer from the saved instance rather than from
serializer context. Validation no longer writes, satisfying `docs/CONVENTIONS.md`.

Verified by: `tests/test_profiles.py::test_creating_primary_vehicle_does_not_500`,
`test_marking_primary_demotes_the_previous_one`.

### Security gaps — current status

| ID | Finding | Severity | Status |
|---|---|---|---|
| SECGAP-004-1 | `preferred_vehicle` cross-customer reference and readback | Medium | **RESOLVED** |
| SECGAP-004-2 | No image size limit on `photo` | Low | **RESOLVED** — 5 MB cap. A per-customer vehicle count limit is still OPEN. |
| SECGAP-004-3 | Media has no access control — the URL is the only secret | Low | OPEN |

## 13. Edge Cases

- `POST` with only `make` → `400` (model required); with make and model → `201`.
- First vehicle created with `is_primary: true` → no other vehicle to demote; succeeds.
- Setting a second vehicle primary → the first is demoted (REQ-4), inside a transaction.
- Deleting the primary vehicle → the customer is left with **no** primary; nothing promotes another.
- Deleting a vehicle referenced by a past request → request survives with `preferred_vehicle: null`
  and `vehicle_summary: null`.
- Duplicate VIN or plate across two customers → accepted; no uniqueness.
- `PATCH` on another customer's vehicle → `404`.
- `extra` given a JSON array or scalar instead of an object → now `400`; the object shape is
  enforced by `validate_extra`, though no schema inside it is.

## 14. Acceptance Criteria

- [x] A customer can create, list, update, and delete their own vehicles.
- [x] A foreign vehicle id returns `404`.
- [x] `make` and `model` are required.
- [x] Marking a vehicle primary demotes the previous primary.
- [x] Vehicles appear embedded on the customer profile.
- [x] Deleting a vehicle preserves historical requests.
- [x] `preferred_vehicle` must belong to the requesting customer.
- [x] `is_primary` on create succeeds and demotes the previous primary.
- [x] `year` is range-validated (1900–2100).
- [x] `extra` must be a JSON object.
- [x] `photo` uploads are size-capped.
- [ ] Exactly one primary is guaranteed at the **database** level — still **PARTIAL** (REQ-4):
      enforced in the serializer inside a transaction, but a direct ORM or admin write can still
      produce two. Needs a partial unique constraint; deferred because existing data may already
      violate it.

## 15. Tests

### Existing — in `tests/test_profiles.py` (11 vehicle tests)
- **CRUD:** create; owner-scoped list; foreign detail `404`; vehicles embedded in the profile.
- **Primary flag:** create with `is_primary` (the former 500); demotion of the previous primary,
  with a count assertion that exactly one remains.
- **Validation:** `make`/`model` required; `year` range; `extra` must be an object.
- **Cascade:** deleting a vehicle leaves the historical request with `preferred_vehicle: null`.

Cross-customer rejection is covered in `tests/test_service_requests.py`.

### Still missing (gap)
- **Unit:** `vehicle_summary` formatting without a year or colour.
- **Upload:** an oversized image is rejected (needs a fixture image).

## 16. Observability

- Logs: none.
- Metrics: none.
- Errors: shared DRF exception handler.
- Audit events: none.

## 17. Dependencies

- SPEC-002 (owning customer profile), SPEC-005 (`preferred_vehicle`).
- Pillow for `ImageField`; optional Cloudinary storage when `CLOUDINARY_CLOUD_NAME` is set,
  otherwise local `MEDIA_ROOT`.

## 18. Open Questions

- **OQ-004-A** — Should parts specs (tire size, battery group, belt, oil, coolant) be surfaced to the assigned provider? They are captured but never sent.
- **OQ-004-B** — Should plate or VIN be unique or validated? Today neither is.
- **OQ-004-C** — Is a primary vehicle meant to auto-populate `preferred_vehicle` on request creation? Nothing does this today.
- **OQ-004-D** — What is `extra` for? It is an unschema'd escape hatch with no writer or reader in the codebase.
- **OQ-004-E** — Should deleting the primary vehicle promote another automatically?

## 19. Implementation Notes

- Primary-vehicle demotion now lives in `create()` / `update()` under `@transaction.atomic`,
  keyed off the saved instance's own customer. Validation performs no writes.
- `photo` and `avatar` share the storage backend selection: Cloudinary when configured,
  otherwise local media served by Django only in `DEBUG`. Both now carry a 5 MB size validator
  from `apps.core.validators`.
- Vehicle querysets are scoped through the shared `CustomerVehicleQuerysetMixin`, which resolves
  the profile via `apps.customers.selectors.ensure_customer_profile` — the single helper that
  replaced the two divergent `ensure_customer_profile` functions.

## 20. Verification Evidence

- Files: [apps/customers/models.py](apps/customers/models.py), [apps/customers/serializers.py](apps/customers/serializers.py), [apps/customers/views.py](apps/customers/views.py), [apps/customers/selectors.py](apps/customers/selectors.py)
- Routes: [autrifix/api_urls.py](autrifix/api_urls.py)
- Tests: 11 vehicle tests in `tests/test_profiles.py`, plus cross-customer rejection in
  `tests/test_service_requests.py`. All passing.
- Commands: `pytest -q` → 169 passed; `manage.py makemigrations --check --dry-run` → no changes.
- Migration: `drivers/0003` (coordinate validators, notes cap, photo size validator).
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
