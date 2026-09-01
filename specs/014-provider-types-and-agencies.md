# SPEC-014 — Provider Types & Agencies

**Status:** READY
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

> **EXTENDED by [SPEC-017](017-agency-api.md) (2026-08-18).** The agency model specified
> here now has an HTTP surface — create, invite, respond, roles, leave and remove. The
> inheritance rule in REQ-7 is what SPEC-017 REQ-3 exists to protect.

## 1. Summary

The platform serves **mechanics, tow operators, and agencies**, not mechanics alone. This spec
covers the vocabulary change that made that expressible (`driver`→`customer`,
`mechanic`→`provider`), the `provider_type` discriminator, the towing-specific data a repair job
never needed, and the agency model.

## 2. Problem

Three problems with one root cause — the domain outgrew its vocabulary.

1. **"Sign up as driver" reads like a rideshare app** in a market where Uber, Bolt and Yango all
   operate. Worse, once tow operators exist, *a tow operator is a driver* — so `driver` meaning
   "the customer" became ambiguous inside the code, not only in signup copy.
2. **`mechanic` cannot describe a towing business.** The role name presumed a single trade.
3. **A tow is not a repair.** It has a destination, is priced per kilometre, and needs a truck.
   `ServiceRequest` carried exactly one coordinate.

## 3. Actors

- Customer — needs help; may want a specific trade.
- Provider — a mechanic, a tow operator, or both; may belong to an agency.
- Agency — a business fielding several providers.
- Administrator — verifies agencies and manages membership.

## 4. Goals

- Vocabulary that is unambiguous in signup copy *and* in the codebase.
- One provider path, with trade as data rather than as a second role.
- Enough towing structure for a tow job to be well-formed.
- Let a verified business onboard operators without re-verifying each one.

## 5. Non-Goals

- Dispatching to an agency which then assigns an operator (ADR-021).
- Agency-level ratings or payouts.
- Equipment modelling — flatbed vs hook, tonnage (OQ-014-C).
- An agency API; admin only for now.

## 6. Requirements

### REQ-1 — Provider trade is a type, not a role
**ID:** DOM-014-001 · **Priority:** Must · **Provenance:** PRODUCT (ADR-020) · **Status:** IMPLEMENTED

`ProviderProfile.provider_type` is one of `mechanic`, `tow`, `both`; default `mechanic`, writable
by the provider.

One role keeps verification, discovery, jobs, chat, reviews and ratings on a single path, and a
garage that also runs a tow truck is one record (`both`). Finer capability continues to live on
`ProviderServiceOffering`.

Evidence: [apps/providers/verification.py](apps/providers/verification.py) `ProviderType`, [apps/providers/models.py](apps/providers/models.py)

### REQ-2 — Customer / provider vocabulary
**ID:** DOM-014-002 · **Priority:** Must · **Provenance:** PRODUCT (ADR-020) · **Status:** IMPLEMENTED

Roles are `customer`, `provider`, `admin`. Routes are `/customers/*` and `/providers/*`. API
fields follow: `customer_name`, `provider_name`, `provider_verification_level`.

**Breaking, deliberately** — no aliases. Existing rows are migrated in place by
`accounts/0009_rename_roles_to_customer_provider`.

This also settles CONFLICT-002-A, where `PRODUCT.md` said "Customer" and the code said `driver`.

### REQ-3 — Trade-aware discovery
**ID:** PROD-014-003 · **Priority:** Must · **Provenance:** PROPOSED · **Status:** IMPLEMENTED

- `GET /services/nearby/?provider_type=tow` restricts to that trade; `both` always matches; an
  unknown value returns `400`.
- The provider work feed **excludes** requests whose category `requires_destination` from
  providers that are not tow-capable.

The second rule does not contradict ADR-009. That decision stopped filtering by a provider's
*declared preferences*, which hid work they could have done. This is *capability*: a provider
with no truck cannot tow a vehicle, so showing them the job is noise, not opportunity.

Evidence: [apps/providers/nearby_presence.py](apps/providers/nearby_presence.py), [apps/jobs/views.py](apps/jobs/views.py)

### REQ-4 — A tow request carries a destination
**ID:** DOM-014-004 · **Priority:** Must · **Provenance:** PROPOSED · **Status:** IMPLEMENTED

`ServiceCategory.requires_destination` marks a service that relocates the vehicle.
`ServiceRequest` gains nullable `destination_latitude` / `destination_longitude`: required when
the category demands it, range-validated, and rejected if only half a pair is sent.

**Category-driven, not slug-driven.** Hardcoding `"tow-recovery"` in view logic would break
silently the moment the catalogue is edited in admin. The seed names the slug exactly once, in
`jobs/0009`.

A repair request may still carry a destination; harmless, and it avoids a client special case.

### REQ-5 — Per-kilometre pricing
**ID:** DOM-014-005 · **Priority:** Should · **Provenance:** PROPOSED · **Status:** PARTIAL

`ProviderServiceOffering.per_km_rate` sits alongside `hourly_rate`.

`PARTIAL` — the fields are captured and returned, but **nothing computes a price**. There is no
quoting, estimate, or settlement anywhere in the platform. Currency also remains undecided
(ADR-006), so both rates are bare decimals.

### REQ-6 — Agencies
**ID:** DOM-014-006 · **Priority:** Must · **Provenance:** PRODUCT (ADR-021) · **Status:** IMPLEMENTED

`Agency` (name, slug, `provider_type`, `verification_level`, contact details, RGD
`registration_number`) and `AgencyMembership` (provider, role of owner/manager/operator, status
of invited/active/removed).

A provider holds at most one live membership, enforced by a partial unique constraint over
non-removed rows — so leaving and rejoining keeps history rather than overwriting it.

**The individual remains the unit of work.** They hold the profile, accept the job, and chat with
the customer. A customer needs to know which person is coming, and the audit trail needs a person
to attribute actions to.

### REQ-7 — Agency verification lifts its members
**ID:** SEC-014-007 · **Priority:** Must · **Provenance:** PRODUCT (ADR-021) · **Status:** IMPLEMENTED

`effective_verification_level(provider)` is the **higher** of the provider's own level and their
active agency's. It can lift a provider, never lower one. Every entitlement check
(`can_accept_jobs`, `can_see_exact_locations`) uses the effective level.

Losing membership immediately drops the inherited level.

**This makes verifying an agency the highest-leverage administrative action on the platform** —
one approval lifts every current *and future* member. The admin surface says so.

Evidence: [apps/providers/verification.py](apps/providers/verification.py) `effective_verification_level`

## 7. State Model

Membership: `invited → active → removed`. Only `active` confers agency identity or inherited
verification.

## 8. API Contract

| Method | Path | Access | Notes |
|---|---|---|---|
| GET/PUT/PATCH | `/providers/profile/` | Provider | `provider_type` writable; `verification_level` read-only |
| GET | `/services/nearby/` | Any | optional `provider_type` filter; payload carries `provider_type` |
| GET | `/jobs/requests/nearby/` | Provider | excludes destination-requiring work from non-tow-capable providers |
| POST | `/jobs/requests/` | Customer | `destination_latitude` / `destination_longitude`, required per category |
| GET/POST | `/providers/services/` | Provider | `per_km_rate` alongside `hourly_rate` |

Agencies are **admin-only**; there is no agency API yet.

## 9. Security

- `provider_type` is self-declared and unverified. A repair-only account can claim `tow`. The
  mitigation is verification (SPEC-013), not the type field.
- Agency verification is the highest-leverage administrative action: one approval lifts everyone
  in the agency, including operators added later.
- Membership changes are **not audited** — a real gap given REQ-7 (OQ-014-E).

## 10. Edge Cases

- `both` matches either discovery filter and sees all work.
- A tow request whose category flag is later turned off keeps its destination; harmless.
- A provider removed from a verified agency loses exact locations and the ability to accept on
  their next request. Jobs already accepted are unaffected.
- An agency at a *lower* level than a member never reduces that member.
- Two agencies cannot both claim a provider; the constraint rejects the second.

## 11. Acceptance Criteria

- [x] Roles are `customer` / `provider`; old values rejected at signup and migrated in place.
- [x] `provider_type` defaults to `mechanic`, is writable, and validates.
- [x] Discovery filters by trade; `both` matches either.
- [x] Non-tow-capable providers do not see destination-requiring work.
- [x] Repair work remains visible to every provider (ADR-009 intact).
- [x] A tow request without a destination is rejected; half a destination is rejected.
- [x] Destination coordinates are range-validated.
- [x] One live agency membership per provider, enforced in the database.
- [x] Agency verification lifts members and never lowers them; removal drops it.
- [x] The job belongs to the individual, not the agency.
- [ ] Prices are calculated from rates — **NOT_IMPLEMENTED** (REQ-5).
- [ ] Agency membership changes are audited — **NOT_IMPLEMENTED** (OQ-014-E).
- [ ] Agencies are manageable over the API — **NOT_IMPLEMENTED**, admin only.

## 12. Tests

- `tests/test_provider_types.py` (14) — vocabulary and role migration, trade declaration and
  validation, discovery filtering, `both` matching, capability filtering on the feed, and proof
  that repair work stays unfiltered.
- `tests/test_tow_requests.py` (13) — the category flag, destination required/optional per
  category, half-pair and range rejection, capability routing, per-km rate round-trip.
- `tests/test_agencies.py` (13) — membership resolution, invited ≠ member, the one-live-membership
  constraint, rejoin keeping history, inherited verification lifting but never lowering, loss on
  removal, and an end-to-end proof that an agency member accepts work without their own documents.

## 13. Open Questions

- **OQ-014-A** — Should `provider_type` be verifiable rather than self-declared? A claimed tow
  operator with no truck is only discovered at the job.
- **OQ-014-B** — Should agencies be dispatched jobs and assign internally (the ADR-021
  alternative)?
- **OQ-014-C** — Does towing need equipment modelling (flatbed vs hook, tonnage)? A truck that
  cannot lift an SUV is a wasted dispatch.
- **OQ-014-D** — Do ratings accrue to the operator, the agency, or both?
- **OQ-014-E** — Should membership changes be audited? Given REQ-7 they change entitlement, so
  probably yes; deferred with the rest of the audit scope.
- **OQ-014-F** — Should an agency owner see their members' jobs and earnings? Needs the operator
  roles deferred by ADR-017.
- **OQ-014-G** — Should the app *labels* eventually follow the package rename? Needs manual
  `django_migrations` SQL per deployment (ADR-020).

## 14. Verification Evidence

- Files: [apps/providers/](apps/providers/), [apps/customers/](apps/customers/), [apps/jobs/](apps/jobs/)
- Migrations: `accounts/0009` (role data), `drivers/0004-0005`, `mechanics/0006-0009`,
  `jobs/0007-0009`. Renames are hand-written so rows are preserved.
- Tests: 40 across three modules; full suite 283 passing on SQLite, 284 on PostgreSQL.
- Commands: `pytest -q`; `makemigrations --check` clean; `spectacular --fail-on-warn` clean.
- Review: to be reviewed by the project owner (`docs/REVIEW-GUIDE.md`).
