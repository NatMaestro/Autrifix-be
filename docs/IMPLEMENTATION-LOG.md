# Implementation Log

Records what actually shipped, in order, with the evidence. Complements
[`SYNC-REPORT.md`](SYNC-REPORT.md), which recorded what the code looked like beforehand.

> **Vocabulary note.** Entries dated before 2026-08-18 use the original `driver` /
> `mechanic` vocabulary. They are historical records and are deliberately **not**
> rewritten — see ADR-020 for the rename.

---

## 2026-08-17 — Remediation slice 1: authorization, lifecycle, reviews, notifications

**Scope:** `autrifix-be` only. Four product decisions taken up front (ADR-011 … ADR-014).

**Result:** 2 tests → **169 tests**, 77% statement coverage. All five blocking defects closed,
plus one high-severity bug the new tests uncovered. No API route removed; three added.

### Product decisions taken

| ADR | Decision |
|---|---|
| ADR-011 | Reviews are driver → mechanic, on completed jobs only |
| ADR-012 | In-app notifications only; synchronous production, `on_commit` delivery |
| ADR-013 | `role` is fixed at signup |
| ADR-014 | Mechanic discovery requires authentication |

### Defects closed

| Was | Now | Test |
|---|---|---|
| Any authenticated user could read any chat room | Participant-scoped; `404` otherwise | `test_unrelated_customer_cannot_read_room` |
| Any authenticated user could post into any chat room | Participant-scoped | `test_unrelated_provider_cannot_post_message` |
| Any authenticated user could review any job in any state | Driver of a **completed** job only | `test_provider_cannot_review_their_own_job` |
| `PATCH /me/ {"role":"mechanic"}` granted job acceptance | `role` read-only | `test_me_cannot_change_role` |
| Drivers could write job `status` and `notes` | Actor-aware transition table | `test_customer_cannot_complete_a_job` |
| Any job transition from any state was accepted | `JOB_TRANSITIONS`, `409` otherwise | `test_skipping_active_is_409` |
| Two mechanics could accept the same request | Row lock + partial unique constraint + `409` | `test_second_provider_accepting_gets_409` |
| Mechanic coordinates readable anonymously | Authenticated | `test_services_nearby_requires_authentication` |
| Presence broadcast every mechanic to every driver | Radius-filtered server-side | — (consumer logic; WebSocket test still owed) |
| `rating_avg` never written — always `0.00 (0)` | Recomputed on review save/delete | `test_review_updates_provider_rating` |
| Nothing ever created a notification | 6-event catalogue on every transition | `test_full_job_flow_produces_the_expected_notifications` |
| Missing mechanic profile → `500` | `409` with a usable message | `test_provider_without_profile_gets_409` |
| `is_primary` on vehicle create → `500` (`KeyError`) | Works; demotes previous primary | `test_creating_primary_vehicle_does_not_500` |
| Another driver's vehicle accepted on a request | Queryset narrowed to owner | `test_another_customers_vehicle_is_rejected` |
| Driver had no way to cancel anything | Cancels request and any live job | `test_cancelling_matched_request_cancels_the_job` |
| Out-of-range coordinates persisted, then crashed `geopy` | Validated at 4 layers | `test_out_of_range_coordinates_are_rejected` |
| `radius_km=abc` → `500` | `400` | `test_non_numeric_radius_is_400_not_500` |
| Mechanic feed defaulted missing `lat`/`lng` to null island | `400` | `test_feed_rejects_missing_coordinates` |
| Duplicate offering → `500` | `400` | `test_duplicate_offering_is_rejected` |
| Duplicate review → `500` | `409` | `test_duplicate_review_is_409` |
| `driver_name` fell back to a phone number | Falls back to `"Driver"` | `test_customer_name_does_not_leak_phone_number` |

### Found during remediation, not by the synchronization pass

**Every failed login returned `500`, not `401`.**
`IdentifierTokenObtainPairSerializer` raised
`AuthenticationFailed(jwt_api_settings.NO_ACTIVE_ACCOUNT_FOUND)`, but that attribute does not
exist on simplejwt 5.4.0's settings object, so every wrong password raised `AttributeError`
inside the serializer — and logged an exception each time. The line reads as correct, which is
exactly why the code-reading pass missed it and the first failed-login test caught it
immediately. Recorded as SEC-GAP-33.

### New modules

| File | Purpose |
|---|---|
| `apps/jobs/services.py` | The job state machine: `JOB_TRANSITIONS`, `accept_service_request`, `transition_job`, `cancel_service_request` |
| `apps/notifications/services.py` | Single entry point for producing notifications |
| `apps/reviews/services.py` + `signals.py` | Rating aggregation |
| `apps/chat/selectors.py` | Participant scoping shared by REST and WebSocket |
| `apps/drivers/selectors.py`, `apps/mechanics/selectors.py` | Profile resolution; replaced four unguarded `.get()` calls and two divergent helpers |
| `apps/core/validators.py` | Coordinate bounds, upload limits, query-parameter parsing |
| `apps/notifications/consumers.py` | Per-user notification socket |

`apps/jobs/services.py` is the first real service layer in the codebase — the answer to the
`ARCHITECTURE.md` note that business workflows were living in view methods.

### API changes

**Added:** `POST /jobs/requests/{id}/cancel/`, `GET /notifications/unread-count/`,
`ws/notifications/`.

**Client-visible behavior changes** — worth flagging to the web team:

| Change | Impact |
|---|---|
| `GET /services/nearby/` now requires authentication | Breaks any anonymous caller (ADR-014) |
| A request being worked on now reports `assigned`, not `matching` | The value was already in the OpenAPI enum |
| Invalid job transitions return `409` where they used to return `200` | Clients relying on the old permissiveness will break — deliberately |
| `role` is silently ignored on `PATCH /me/` instead of applied | |
| Driver-profile `latitude`/`longitude` are always present (null when unset), not omitted | |
| A lone `latitude` or `longitude` is now `400` instead of a silent `200` | |
| Chat messages fan out as `{"kind":"chat.message","data":{…}}` on **both** transports | Previously WebSocket sends were a bare object |
| `driver_name` returns `"Driver"` rather than a phone number when no name is set | |
| `POST /notifications/{id}/read/` also returns `unread_count` | Additive |
| `GET /services/nearby/` also returns `truncated` | Additive |
| `GET /chat/` rows also carry `job_status` | Additive |
| Review responses also carry `mechanic` and `mechanic_name` | Additive |

### Migrations (8)

All applied cleanly on a fresh database; `makemigrations --check` reports no drift.

- `accounts/0007`, `drivers/0003`, `mechanics/0004`, `chat/0002`, `reviews/0002`,
  `notifications/0002`, `notifications/0003` — validators, size caps, indexes, the
  `NotificationKind` enum, stable notification ordering.
- `jobs/0006` — adds `unique_live_job_per_service_request`. **Self-repairing:** a `RunPython`
  step first cancels pre-existing duplicate live jobs (keeping the earliest) so the constraint
  cannot fail on existing data.
- `reviews/0003` — backfills `rating_avg` / `rating_count` from existing reviews; reversible.

### Verification

```
pytest -q                                    → 169 passed
pytest --cov=apps                            → 77%
manage.py makemigrations --check --dry-run   → No changes detected
manage.py check                              → no issues
manage.py check --deploy (production)        → 2 advisory warnings only
manage.py spectacular                        → 0 errors, 0 warnings
```

`pytest`, `pytest-django`, `pytest-cov`, and `factory-boy` were installed into the existing
virtualenv at the versions already pinned in `requirements-dev.txt`. No runtime dependency was
added or changed.

### Housekeeping

- `ISSUE_ROUTER_MODEL_PATH` is now a setting (env-overridable). Test settings redirect it to a
  temp file — before this, **every test run dirtied the tracked `var/issue_router_model.json`**,
  because creating a service request trains the model synchronously. In production it can now be
  pointed at a mounted volume. The underlying ADR-010 problem is unchanged.
- `ENUM_NAME_OVERRIDES` added so `role` generates stable `UserRoleEnum` / `SignupRoleEnum`
  components instead of a hash-suffixed name that changes between builds.

### Known gaps carried forward (updated by slice 2 below)

- **No independent review.** `CLAUDE.md` §8 asks for a second reviewer; this slice was
  self-reviewed only.
- **No WebSocket tests.** Three consumers (chat, presence, notifications) are covered only
  indirectly. Needs `channels.testing.WebsocketCommunicator`.
- **No true concurrency test.** The acceptance race is closed by a lock *and* a database
  constraint, and the constraint is asserted directly, but no test runs two simultaneous
  transactions — that needs `TransactionTestCase` against PostgreSQL.
- **Still nothing is audited.** The transition table now provides a single hook point when
  SPEC-012 OQ-012-D is answered.
- **Pre-acceptance location disclosure** remains, blocked on OQ-008-B.
- **The ML routing model still writes to local disk** on every request creation (ADR-010).

---

## 2026-08-17 — Remediation slice 2: test-gap closure and auth hardening

Picks up the three "next" items from slice 1. **190 → 193 tests** (192 + 1 skipped on SQLite).

### WebSocket consumers are now tested

`tests/test_websockets.py` — 21 tests covering all three consumers, previously the largest
untested surface.

- **Chat:** participant (both roles) connects; non-participant, anonymous, invalid token, and
  unknown job all rejected; message persisted and fanned out to the counterparty with the
  `{"kind":"chat.message","data":{…}}` envelope; blank and oversized bodies return an error
  frame and persist nothing; typing frames fan out without persisting.
- **Presence:** driver subscribes and gets a radius-filtered snapshot; mechanic and anonymous
  rejected; out-of-range and non-numeric coordinates rejected; a nearby mechanic's update
  arrives with `distance_km`; **a distant mechanic's update does not arrive** — the direct test
  for SECGAP-008-3.
- **Notifications:** authenticated connect, anonymous rejected, owner receives the broadcast,
  and a second user does **not** receive another user's notification.

No new dependency: async consumers are driven from sync tests via `asyncio.run` rather than
adding `pytest-asyncio`. Tokens must be minted before entering the coroutine — `RefreshToken.for_user`
touches the database, which Django forbids from an async context.

### The test backend could not exercise locking — now CI does

`connection.features.has_select_for_update` is **False** on SQLite, so Django silently drops
`SELECT … FOR UPDATE`. Every prior run of the suite was therefore testing the acceptance race
with only the database constraint in play, never the lock.

- `test_concurrent_acceptance_yields_exactly_one_job` runs two real threads through
  `accept_service_request` against a shared barrier, and skips with an explicit reason on a
  backend without row locking.
- `.github/workflows/ci.yml` now runs a **matrix over `[sqlite, postgres]`**. The postgres leg
  sets `USE_POSTGRES_TESTS=1`, so the concurrency test actually executes, and the previously
  pointless `migrate` step now runs against a real PostgreSQL.
- CI also gained a missing-migration check, `spectacular --fail-on-warn`, and
  `--cov-fail-under=70` (was `0`, i.e. coverage could never fail a build).

**Verified locally against PostgreSQL 16 in Docker: 191 passed, nothing skipped** — including
the concurrency test, which confirms exactly one mechanic wins and the loser gets `Conflict`.

### Auth hardening

| Finding | Fix |
|---|---|
| SEC-GAP-01 — no per-account brute-force lockout | `LoginIdentifierRateThrottle` keys on the *targeted identifier* (SHA-256 hashed, so cache keys hold no PII), 10/min dev / 5/min prod, applied alongside the existing IP-keyed `auth` scope. Throttling one account provably does not lock out another. |
| SEC-GAP-02 — `SECRET_KEY` fell back to a known literal | The default now exists only under `DEBUG`. A non-DEBUG boot without `SECRET_KEY` raises `ImproperlyConfigured` with the command to generate one. Verified in both modes with the `.env` file mocked away. |
| SEC-GAP-03 — hardcoded build-time `SECRET_KEY` | `render-build.sh` generates an ephemeral key per build; never persisted, never reaches the running service. |

### Test isolation fix

Throttle counters live in the cache, which outlives a test. An autouse `clear_throttle_cache`
fixture now clears it around every test — without it, one test's login attempts count against
the next test's budget and the suite fails differently depending on execution order. This was
latent before the throttle work; the new tests would have made it visible.

### Verification

```
pytest -q                      (sqlite)    → 192 passed, 1 skipped
pytest -q                      (postgres)  → 191 passed, 0 skipped
manage.py check                (test)      → no issues
manage.py check                (production)→ no issues
manage.py spectacular --fail-on-warn       → clean
manage.py makemigrations --check --dry-run → No changes detected
bash -n scripts/render-build.sh            → syntax OK
```

No migrations in this slice — no model changed.

### Still carried forward

- **No independent review** (`CLAUDE.md` §8). Unchanged, and now the only Definition-of-Done item
  outstanding for the specs marked `VERIFIED`.
- **Pre-acceptance location disclosure** — blocked on OQ-008-B.
- **Nothing is audited** — blocked on OQ-012-D.
- **SPEC-012 (Administration) is still `DRAFT`** with no tests; it is the last untouched spec.
- **The ML routing model still writes to local disk** on request creation (ADR-010).

---

## 2026-08-17 — Slice 3: product decisions applied, audit trail

Four decisions answered; three encoded as ADRs and implemented. **192 → 206 tests.**

### Decisions

| ADR | Decision | Effect |
|---|---|---|
| ADR-015 | A mechanic sees the driver's exact location before accepting | SEC-GAP-22 **accepted by design**, not fixed; `distance_km` added to the feed |
| ADR-016 | Audit state changes and failed logins; **not** reads | New `core.AuditEvent` + hooks |
| ADR-017 | Administration deferred | SPEC-012 stays `DRAFT`; its gaps accepted for now |

Independent review: the project owner is reviewing. `docs/REVIEW-GUIDE.md` written to direct
attention by consequence-if-wrong rather than by diff size.

### ADR-015 — location disclosure accepted, and made useful

The mechanic feed now returns `distance_km` per request. Distance is what a mechanic actually
reasons about when deciding whether to accept, and it was previously computed for sorting and
then discarded — SPEC-008 REQ-4 had been `PARTIAL` for exactly this reason.

`distance_km` is `null` on a driver's own request list, where there is no reference point.

**The consequence worth restating:** this decision moves **mechanic verification** (SPEC-003
REQ-6 / OQ-003-A) from a quality feature to *the* compensating control for driver location
privacy. Anyone can register as a mechanic today, go online, and read every open request within
their radius. That is now the highest-priority security item in the backend, and
`SECURITY.md` leads with it.

### ADR-016 — audit trail

`core.AuditEvent` — the first model in `apps.core`, and its first migration.

| Action | Recorded when |
|---|---|
| `job.accepted` | a mechanic claims a request |
| `job.transitioned` | any job state change, with `from`, `to`, `actor_role` |
| `request.cancelled` | a driver cancels, with the jobs it killed |
| `auth.login_failed` | wrong credentials or inactive account, with `reason` and `ip` |

Three design points, each tested:

1. **The row outlives its actor.** `actor` is `SET_NULL` with a denormalised `actor_label` —
   the only non-cascading foreign key in the codebase. `test_audit_row_survives_deletion_of_the_actor`
   deletes the mechanic and asserts the row, its label, and its metadata all survive.
2. **Auditing never breaks the audited action.** `test_audit_write_failure_does_not_break_the_audited_action`
   patches `AuditEvent.objects.create` to raise and asserts acceptance still returns `201`.
3. **Reads are not audited.** `test_reads_are_not_audited` runs a discovery sweep and asserts
   zero rows.

Failed logins record `reason` and `account_exists`, so the trail distinguishes "no such account"
from "wrong password" even though the API response is deliberately identical for both — the
audit log is the only place that distinction exists.

Registered read-only in Django admin: no add, no change, no delete, every field read-only.

**Not audited, deferred with ADR-017:** administrative actions, including an operator reading a
private conversation — the one read that would be worth auditing.

**No retention policy.** Nothing prunes (SPEC-012 OQ-012-H).

### ADR-017 — administration deferred

SPEC-012 keeps `DRAFT` status with an explicit deferral banner so it does not read as neglect.
Its findings are marked **DEFERRED** rather than open, with two notes worth carrying:

- Since ADR-013 made `role` read-only over the API, **Django admin is now the only way to correct
  a user's role** — SECGAP-012-7 became load-bearing.
- Since SPEC-001 REQ-10 added per-identifier login throttling, **admin is the remaining
  unprotected login door** (SECGAP-012-4).

### Verification

```
pytest -q                                    → 206 passed, 1 skipped
manage.py check                              → no issues
manage.py spectacular --fail-on-warn         → clean
manage.py makemigrations --check --dry-run   → No changes detected
```

Migration: `core/0001_initial` (`AuditEvent`).

### Open questions closed this slice

OQ-008-B, OQ-008-D, OQ-008-F (ADR-015 / ADR-016), OQ-012-A, OQ-012-D (ADR-016 / ADR-017).
New: OQ-012-H (audit retention).

---

## 2026-08-17 — Slice 4: mechanic verification (SPEC-013 / ADR-018)

The compensating control ADR-015 was leaning on. **206 → 237 tests.**

Designed from a brainstorm across five tiers (friction-only → manual review → automated
documents → Ghana Card/NIA → full KYC). Shipped **Tier 0 + Tier 1**, with the model shaped so
Tiers 2–3 need no schema change.

### The design decision that mattered

The tension: ADR-015 says a mechanic needs the driver's location to decide whether to accept.
But *deciding* needs **distance**; *navigating* needs the **exact pin** — and those happen at
different moments.

So verification gates **precision**, not participation:

| Level | Browsing a nearby request | After accepting |
|---|---|---|
| below `documents` | coordinate snapped to a ~1 km grid | exact |
| `documents`+ | exact | exact |

An unverified mechanic can still judge and take any job. What they cannot do is build a map of
where drivers are without ever accepting one.

### The subtle part: trilateration

A mechanic chooses the `lat`/`lng` they search from. Publishing an **exact distance** beside a
**coarsened coordinate** would let the true point be recovered from three queries — the
coarsening would have been decorative.

Fix: coarsen once, then derive everything from the coarsened point, distance included. Every
vantage now agrees on the snapped point and none reveals the true one.
`test_trilateration_cannot_recover_the_true_coordinate` queries from three positions and asserts
exactly that. Radius filtering still uses the true position, so an unverified mechanic sees the
right *set* of jobs — only the precision differs.

### What shipped

| Piece | Detail |
|---|---|
| `VerificationLevel` | `none → phone → documents → ghana_card`, ordered in one place; comparisons via `level_at_least()` |
| Tier 0 | Phone OTP verification (`POST /me/verify-phone/`, reusing the existing `PhoneOTP`) + a completeness gate: business name, workshop coordinates, ≥1 active offering |
| Tier 1 | `MechanicVerification` submissions reviewed in Django admin, with inline image previews and approve/reject actions |
| Badge | `mechanic_verification_level` on job payloads; `verification_level` in nearby-mechanic discovery |
| Audit | `mechanic.verification_submitted` / `mechanic.verification_reviewed` |
| Setting | `MECHANIC_EXACT_LOCATION_MIN_LEVEL` — retune the supply-versus-privacy trade without a deploy |

**Documents are purged on decision.** Manual review needs a human to see them; a permanent store
of Ghana Card images is a breach liability out of proportion to its value. Only the outcome,
reviewer, timestamp, and notes survive — so a later dispute has notes, not images. Deliberate.

**`MechanicServiceOffering` does something again.** ADR-009 left it inert; it is now part of the
completeness gate.

### Client-visible changes

- `GET /jobs/requests/nearby/` returns coarsened `latitude`/`longitude` for unverified mechanics,
  with `distance_km` consistent with them.
- `mechanic_verification_level` added to job payloads; `verification_level` to mechanic profiles
  and discovery payloads (additive).
- New: `POST /me/verify-phone/`, `GET|POST /mechanics/verification/`.

### Verification

```
pytest -q              (sqlite)   → 236 passed, 1 skipped
pytest -q              (postgres) → 237 passed, 0 skipped
manage.py spectacular --fail-on-warn → clean
manage.py makemigrations --check     → No changes detected
```

Run against PostgreSQL 16 in Docker as well as SQLite, because this slice adds a second partial
unique constraint (`unique_pending_verification_per_mechanic`) and SQLite's constraint handling
is not the production one.

Migrations: `accounts/0008` (`is_phone_verified`), `mechanics/0005` (level + `MechanicVerification`),
`core/0002` (two new audit actions).

### One stale test, corrected

`test_feed_reports_distance_for_each_request` assumed exact coordinates. It predates coarsening
and its fixture mechanic is unverified, so it was asserting the old behaviour. Repointed at a new
`verified_mechanic_profile` fixture — the test was stale, not the code.

### Not closed

An unverified mechanic can still **accept** a job to reveal the exact location and then cancel,
repeatedly. Audited and throughput-limited by the single-live-job constraint, so it is
detectable via the accept-to-completion ratio — but not prevented. A daily accept cap would close
it; that is a business rule needing product input (SPEC-013 OQ-013-A).

---

## 2026-08-18 — Slice 5: unverified mechanics may browse but not accept (ADR-019)

A product reversal of ADR-018's participation clause. **236 → 243 tests.**

### The change

| | Before (ADR-018) | After (ADR-019) |
|---|---|---|
| Browse | coarsened | coarsened (unchanged) |
| Accept | allowed | **`403 verification_required`** below `MECHANIC_MIN_ACCEPT_LEVEL` |

The `403` carries `current_level`, `required_level`, and `verification_url`, so the client can
render an upsell instead of a dead end — which is the point: a mechanic who can see the work they
are missing has a reason to finish verification.

Enforced in `accept_service_request`, not the view, so admin actions and any future dispatch are
covered by the same gate.

### Why this is a better security posture, not just a growth lever

ADR-018 closed browse-harvesting but left **accept-then-cancel**: accept a job to reveal the
exact coordinate, cancel, repeat. That was tracked as OQ-013-A — detectable via audit, not
prevented. Gating acceptance closes it outright, and adds a stronger property: **nobody
unverified ever attends a customer.**

OQ-013-A is now closed as moot.

### The cost, stated plainly

**Cold start.** At `documents` — the default — nobody can work until manually reviewed. On day
one that means zero accepted jobs, with review turnaround as the critical path for the entire
marketplace, dependent on one person.

`MECHANIC_MIN_ACCEPT_LEVEL` is a setting for exactly this reason: run at `phone` (self-service,
instant) during launch, raise to `documents` once a mechanic base exists. **That choice is
OQ-013-G and should be made before go-live rather than discovered.** It is now the top item in
`SECURITY.md`, reclassified from a confidentiality risk to an availability one.

### Test-fixture change worth knowing about

`mechanic_profile` is now **verified by default** — most scenarios need a mechanic who can
actually work, and leaving it unverified would have made 8 lifecycle/audit tests fail for reasons
unrelated to what they test. `unverified_mechanic_profile` is the explicit opposite, used
throughout `test_verification.py`.

New coverage: browse-but-not-accept with the `403` body asserted; a refused accept leaves no job
and the request still `open`; `phone` alone does not unlock accepting; the threshold is
configurable; approval unlocks accepting end to end; demotion does not disturb a job already in
hand.

### Reviewer scaling (your second point)

Recorded as SPEC-013 §18b rather than built. The short version: the data model already supports
it — `reviewed_by` is a real FK, decisions are audited per actor, and everything goes through
`review_verification()` so a future queue UI or API inherits the level change, document purge,
and audit entry for free.

What is missing is a reviewer *role* (today it is all-or-nothing `is_staff`), claiming so two
reviewers do not collide, turnaround measurement, and an appeal path for rejections.

The recommended sequence is **not** "add reviewers" but **automate the common case** — a Tier 2
provider clears clean submissions instantly and routes only ambiguous ones to a human. That keeps
judgement where it helps and removes the cold-start pressure ADR-019 creates.

One gap that bites even at one reviewer: **there is no written standard for what "approved" means**
(OQ-013-I). Right now the bar is whatever you decide that day, which cannot be handed over or
used to defend a rejection.

### Verification

```
pytest -q                                    → 243 passed, 1 skipped
manage.py makemigrations --check --dry-run   → No changes detected
manage.py spectacular --fail-on-warn         → clean
```

No migration — the change is entitlement logic and a setting.

---

## 2026-08-18 — Slice 6: customer/provider vocabulary, provider types, towing, agencies

The largest change so far: ADR-020 (vocabulary + provider type), ADR-021 (agencies), and
SPEC-014. **243 → 284 tests.** Verified on both SQLite and PostgreSQL.

### Why the rename was more than cosmetic

"Sign up as driver" reads like a rideshare app in a market with Uber, Bolt and Yango. But the
sharper problem was internal: **once tow operators exist, a tow operator *is* a driver.**
`job.service_request.driver.user` meaning "the customer", next to providers who drive for a
living, is a bug waiting to be written.

`driver` → `customer` also settles CONFLICT-002-A, open since the first sync pass, where
`PRODUCT.md` said "Customer" and the code said `driver`.

### Scale

~518 identifier occurrences over 48 files, 7 routes, and role values stored as strings. Done as
a scripted pass with word-boundary matching, then repaired by hand where the boundaries lied.

**Three things the blanket pass got wrong, each caught by a check rather than by luck:**

1. It rewrote the `"general-mechanic"` **category slug** — a database value, not an identifier.
2. Underscores block a word boundary, so `get_mechanic_name` and ORM paths like
   `job__service_request__driver__user` were silently skipped. The former surfaced as
   `AttributeError: 'JobSerializer' object has no attribute 'get_provider_name'`.
3. It renamed the *import paths* too, which was the package rename I had explicitly deferred.

### The app-label decision

Packages renamed (`apps/drivers`→`apps/customers`, `apps/mechanics`→`apps/providers`), **app
labels deliberately preserved**. Changing a label orphans every applied row in
`django_migrations` and needs manual SQL on each deployment — real risk for the least valuable
half of the rename.

So tables stay `drivers_*` / `mechanics_*` and string model references keep the old prefix
(`"drivers.CustomerProfile"`). This is the one place the code reads inconsistently; it is a
deliberate trade, documented in both `AppConfig`s and ADR-020, and reversible later (OQ-014-G).

### Two migration hazards worth remembering

Renames were hand-written as `RenameModel`/`RenameField` so rows are preserved — `makemigrations`
non-interactively would have emitted drop-and-recreate instead.

1. **Historical data migrations resolve models by their old names.** `reviews/0003` calls
   `get_model("mechanics", "MechanicProfile")`; the graph was free to run the rename first, and
   did — `KeyError: 'mechanicprofile'`. Fixed by making the rename depend on it.
2. **`RenameField` does not rewrite `Meta.indexes` or `Meta.constraints`**, and SQLite rebuilds
   the whole table on any `AlterField` — at which point it recreates an index against a column
   that no longer exists. Fixed by dropping the dependent index and constraint first and
   recreating them after.

### What shipped

| Piece | Detail |
|---|---|
| Vocabulary | `customer` / `provider` roles, routes, fields; data migration for stored values |
| Provider type | `mechanic` / `tow` / `both` on the profile, writable, validated |
| Trade-aware discovery | `?provider_type=` filter; `both` matches either |
| Capability routing | Destination-requiring work is hidden from non-tow-capable providers |
| Tow destination | `requires_destination` on the category; destination coordinates on the request, required per category, pair-validated and range-validated |
| Per-km pricing | `per_km_rate` alongside `hourly_rate` |
| Agencies | `Agency` + `AgencyMembership`, one live membership per provider, admin-managed |
| Inherited verification | An agency's level lifts its active members, never lowers them |

**Capability filtering does not contradict ADR-009.** That decision stopped filtering by a
provider's *declared preferences*, which hid work they could have done. This is capability: a
provider with no truck cannot tow a vehicle.

**The tow rule is category-driven, not slug-driven.** Hardcoding `"tow-recovery"` in view logic
would break silently the moment the catalogue is edited in admin. The slug is named once, in a
seed migration.

### Agencies: what was deliberately *not* done

The individual provider stays the unit of work — they hold the profile, accept the job, and chat.
A customer needs to know which person is coming, and the audit trail needs a person to attribute
actions to. Dispatch-to-agency-then-assign was considered and rejected for now (ADR-021).

**Verifying an agency is now the highest-leverage administrative action on the platform**: one
approval lifts every current *and future* member. Worth internalising before approving the first
one.

### Client-visible changes — all breaking, by decision

- `role` values: `driver`→`customer`, `mechanic`→`provider`. Old values rejected at signup.
- Routes: `/drivers/*`→`/customers/*`, `/mechanics/*`→`/providers/*`. No aliases.
- Fields: `driver_name`→`customer_name`, `mechanic_name`→`provider_name`,
  `mechanic_verification_level`→`provider_verification_level`.
- WebSocket: `ws/mechanics/nearby/`→`ws/providers/nearby/`.
- Additive: `provider_type`, `requires_destination`, `destination_latitude/longitude`,
  `per_km_rate`, and `?provider_type=` on discovery.

`autrifix-web` will need a coordinated update; it was not inspected.

### Verification

```
pytest -q            (sqlite)   → 283 passed, 1 skipped
pytest -q            (postgres) → 284 passed, 0 skipped
manage.py check                 → no issues
makemigrations --check          → No changes detected
spectacular --fail-on-warn      → clean
```

Migrations: `accounts/0009`, `drivers/0004-0005`, `mechanics/0006-0009`, `jobs/0007-0009`.

### Left undone, deliberately

- **No price is ever calculated** from `hourly_rate` or `per_km_rate` — no quoting, estimate, or
  settlement exists anywhere. Currency is still undecided (ADR-006).
- **No agency API** — admin only. No invitation flow, agency ratings, or payouts.
- **Membership changes are not audited**, which matters because they change entitlement
  (OQ-014-E).
- **`provider_type` is self-declared**; a claimed tow operator with no truck is only discovered
  at the job (OQ-014-A).
- **No equipment modelling** — flatbed vs hook, tonnage (OQ-014-C).

---

## 2026-08-18 — Slice 7: specification resync after the rename

Mechanical in intent, but it surfaced a real problem. **283 tests still green**, no drift, schema
clean.

### Why this was not optional

The ADR-020 rename left ~900 stale references. `SPEC-013` described `MechanicProfile` and
`apps.mechanics`, neither of which exists. Specs that do not describe the code are worse than no
specs: they are confidently wrong, and the web app was about to be built from them.

### The finding worth recording

`DOMAIN.md` was not merely using retired words — it was **describing the system from before all
four remediation slices**, with five outright false claims:

- "the rating summary is **never written by any code**" — written since SPEC-011 REQ-5
- "**Nothing creates one**" (notifications) — six event kinds since SPEC-010 REQ-5
- "**No transition table exists in code**" — `JOB_TRANSITIONS` since SPEC-007
- "`draft` and `assigned` are declared but never written" — `assigned` reachable since ADR-019 work
- "No such field exists" (verification) — the whole of SPEC-013

…and it was missing four models entirely: `Agency`, `AgencyMembership`, `ProviderVerification`,
`AuditEvent`. Rewritten from the code.

**The lesson:** every slice updated the specs it touched, but `DOMAIN.md` is cross-cutting and
nothing owned it. Cross-cutting documents need an explicit check, not incidental updates.

### One inconsistency the resync caught in the *code*

The WebSocket presence frame still announced `"kind": "mechanic_update"` — the underscore blocked
the identifier rename in slice 6. Left alone it would have shipped retired vocabulary in a
contract we had deliberately broken cleanly. Renamed to `provider_update` in code, test, and spec.

### What was resynced, and what deliberately was not

**Resynced:** all 14 specs, plus `DOMAIN`, `API`, `SECURITY`, `ARCHITECTURE`, `CONVENTIONS`,
`FEATURE-MATRIX`, `PRODUCT`, `README`, `REVIEW-GUIDE`.

**Deliberately not:** `SYNC-REPORT.md`, `IMPLEMENTATION-LOG.md`, and the ADR bodies in
`DECISIONS.md`. These are dated historical records; rewriting them would falsify what was true at
the time. Each now carries a vocabulary note pointing at ADR-020.

**Judgement, not substitution.** `mechanic` survives wherever it means the *trade*
(`ProviderType.MECHANIC`, the `general-mechanic` category, SPEC-014's discussion of trades) and
wherever it names an app label or migration. A blind replace would have rewritten a database slug
— it did, on the first pass, and the check caught it.

### Also done

- Spec files renamed: `013-mechanic-verification.md` → `013-provider-verification.md`,
  `003-mechanic-profiles.md` → `003-provider-profiles.md`; every reference updated, including
  those in code docstrings.
- 71 test functions renamed so spec citations resolve.
- CONFLICT-002-A and OQ-002-B closed — the docs-vs-code naming divergence open since the first
  sync pass is settled by ADR-020.
- Two automated checks run over the result: every `apps/…` path cited in a spec exists on disk
  (0 broken), and every backticked identifier cited in a spec appears in the code (1 genuine
  error found and fixed — `DriverVehicleQuerysetMixin`).

### Verification

```
pytest -q                                    → 283 passed, 1 skipped
manage.py check                              → no issues
makemigrations --check                       → No changes detected
spectacular --fail-on-warn                   → clean
broken apps/… references in specs            → 0
```

---

## Slice — Money model: quotes and two-sided completion (2026-08-18)

**Spec:** [SPEC-015](../specs/015-money-model.md) · **Decision:** ADR-022

### What changed and why

The platform had no price on any job, and completion was one-sided: a provider PATCHed
`status: completed` and the job closed. Those are the same problem the moment money is attached —
an amount only the provider ever agreed to is an assertion, not a record.

**The state machine now ends in two hands:**

```
active ──> awaiting_confirmation ──> completed
        (provider records amount)   (customer confirms)
```

`active → completed` was **removed**. A provider can no longer close a job.

**Quotes are a first-class row, and optional.** A tow price is per-km × distance and a jump start
is a known number; forcing a quote there would push providers to enter placeholders, which look
like agreement and are not. Where an accepted quote exists, `amount_variance` discloses the gap to
the recorded amount — deliberately *not* clamped, because a repair needing an unforeseeable part
would otherwise have to be finished at a loss or abandoned.

**Money is recorded, never moved.** Settlement is cash between the two parties. `apps/payments/`
stays a stub, with its `USD`/`stripe` defaults corrected — not because anything reads them, but
because wrong scaffolding is what a first integration copies.

### Why now rather than after the web app

Two-sided completion is the expensive half. It changes the job state machine, the notification
catalogue, the request lifecycle, and every client that closes a job. Doing it before the web app
exists costs a migration. Doing it after costs a migration *plus* a client rewrite *plus* a window
where live jobs are stranded across two contracts.

### Guards worth naming

- `final_amount` is rejected on a PATCH with no transition (`409`) — otherwise a provider could
  revise the bill after the customer had already seen it.
- Cancellation is refused while a job is `awaiting_confirmation`. The request stays `assigned`
  through that state, which without the guard leaves cancelling open as a way to walk away from
  work already performed.
- Role checks precede the profile lookups on both quote endpoints. Without them a customer POSTing
  a quote got a `409` about a missing *provider* profile (wrong problem), and a provider hitting
  the respond endpoint would have had a customer profile created for them as a side effect.
- Amount validation lives in the service, not only the serializer, so it holds for the admin and
  any future non-HTTP caller — the same reasoning as the verification gate.

### Contract changes

- `job.completed` changes recipient, customer → **provider**. Completion is now the customer's own
  act, so they learn the outcome from the HTTP response.
- Four new notification kinds: `quote.submitted`, `quote.accepted`, `quote.declined`,
  `job.awaiting_confirmation`.
- `Payment.amount_cents` → `amount_minor` (pesewas are not cents), `provider` → `processor`
  (`provider` collided with the platform's word for a service provider).

### Known gap, flagged not fixed

**A job the customer never confirms strands.** `awaiting_confirmation` has no timeout; the request
stays `assigned`; the provider cannot be reviewed or move on. Every fix needs either a scheduler
(no Celery worker is deployed — ADR-010) or the admin surface (SPEC-012, deferred). Recorded as
SPEC-015 OQ-015-D rather than half-built.

### Verification

```
pytest -q                                    → 321 passed, 1 skipped
manage.py check                              → no issues
makemigrations --check                       → No changes detected
spectacular --fail-on-warn                   → clean
USE_POSTGRES_TESTS=1 pytest -q               → NOT RUN (Docker daemon not running)
```

The PostgreSQL leg is the only one that exercises `select_for_update`, so the row locking added to
`submit_quote` and `respond_to_quote` is **covered by the partial unique constraint and the status
guards but not yet by a locking test**. Re-run it before this slice is called VERIFIED.

---

## Slice — Lifecycle sweeps and volume limits (2026-08-18)

**Spec:** [SPEC-016](../specs/016-lifecycle-sweeps.md)

Two states could be entered and never left by any user action, because neither had a party
motivated to leave them: a job waiting on a customer who already knows the amount and has no
reason to return, and a request waiting on a provider who may never appear.

**Auto-confirmation records silence as silence.** `Job.auto_confirmed`, a distinct audit action
with a `NULL` actor, and a notification to the customer *because* they did not act. Once
"agreed to GHS 250" and "stopped replying" are the same database row, the difference is gone
for good — and that is exactly the difference a dispute turns on.

**`expired` is a new request status, not a reuse of `cancelled`.** Conflating them would lose
the difference between a customer changing their mind and the platform failing to find anyone,
which is the metric that says whether supply is adequate.

**Cron, not Celery.** ADR-012 keeps Celery out of the request path and its one configured task
has never been called; a worker plus broker to run two queries an hour is more infrastructure
than the problem justifies, and more that can fail silently.

### The subtle exclusion

`awaiting_confirmation` does **not** count against the provider's concurrent-job cap. If
finished-but-unconfirmed work occupied a slot, one unresponsive customer could idle a provider
for the whole 72-hour window — punishing the wrong party, and turning the auto-confirm timeout
into a denial of service on the provider's livelihood. Similarly `assigned` requests do not
count against the customer's cap, so a customer whose car is being fixed can still report a
second breakdown.

### Deployment dependency

**The sweep must be scheduled or REQ-2 and REQ-3 simply do not happen.** Everything else in
this slice fails loudly; an unscheduled sweep just quietly means the stuck states come back.
Hourly is ample — see SPEC-016 §7.

Closes SPEC-015 OQ-015-D, SPEC-005 OQ-005-C, and the two caps in SEC-GAP-28.

---

## Slice — Agency API (2026-08-18)

**Spec:** [SPEC-017](../specs/017-agency-api.md)

SPEC-014 built the agency model, memberships, and the verification inheritance that is the
whole point of the feature — and no endpoints. `effective_verification_level` already consulted
it on every job acceptance while no provider could reach any of it.

### The rule everything else protects

**`verification_level` is not writable through the API.** An agency's level lifts every active
member's effective level (SPEC-014 REQ-7), which governs exact-location visibility and job
acceptance (SPEC-013). An agency that could set its own level would let one signup mint
verified providers at will.

Input and output use separate serializer classes throughout for exactly this reason — a single
`ModelSerializer` with a growing `read_only_fields` tuple is one careless edit from that
outcome. Tested directly: `test_verification_level_cannot_be_set_through_the_api`.

### Shape decisions worth naming

- **Two resource families.** `/agencies/…` is the business from inside it; `/memberships/…` is
  the individual's own place in one. An invitee is not yet a member, so their invitation cannot
  live behind an agency-scoped lookup without punching a hole in that lookup.
- **Declining lands in `removed`.** The one-live-membership constraint counts `invited` and
  `active`; any other landing state would trap the provider, unable to join anywhere including
  the agency they just turned down.
- **An agency always keeps an owner.** Otherwise it can be left unadministrable, recoverable
  only from the Django admin — the escape hatch this slice exists to remove.
- **Removal is history.** An agency that could erase who worked for it would erase the
  attribution the audit trail depends on, and the incentive to do so peaks exactly when the
  record matters.
- **`owner` cannot be invited**, only promoted. An unaccepted owner is an agency with no live
  administrator.

### Accepted tradeoff

Invitation is by phone number, which lets an authenticated agency admin learn whether a number
belongs to a provider account. Throttled at `20/hour` rather than redesigned — the alternatives
are more machinery for the same result, and the attacker must already hold both a provider
account and an agency. Recorded as **SEC-GAP-36** / OQ-017-A rather than left unstated.

### Verification

```
pytest -q                                    → 382 passed, 1 skipped
manage.py check                              → no issues
makemigrations --check                       → No changes detected
spectacular --fail-on-warn                   → clean
USE_POSTGRES_TESTS=1 pytest -q               → NOT RUN (Docker daemon not running)
```

Two schema fixes were needed: `serializer_class` on the three `APIView`s, and
`ENUM_NAME_OVERRIDES` for the two differently-scoped `role` fields (`AgencyRoleEnum` for
promotion, `AgencyInviteRoleEnum` for the smaller invitable set).

The PostgreSQL leg remains unrun, so the row locking in the sweeps and in
`respond_to_invitation` is covered by status guards and the partial unique constraint but not
by a locking test.


---

## PostgreSQL verification of slices 015-017 (2026-08-31)

The PostgreSQL leg was outstanding across three slices because Docker was unavailable. Now run:

```
USE_POSTGRES_TESTS=1 pytest -q     -> 383 passed in 187s
```

This is the only leg that exercises `select_for_update` — SQLite reports
`has_select_for_update = False` and the locking test skips. The row locking added in
`accept_service_request`, `transition_job`, `submit_quote`, `respond_to_quote`,
`respond_to_invitation`, and both sweeps is now covered rather than assumed.

**Two environment traps worth recording**, because both cost time and neither is obvious:

1. A **native Windows PostgreSQL 16 service** (`postgresql-x64-16`) owns `0.0.0.0:5432`, so
   the compose `db` container is shadowed on the host. Connecting to `127.0.0.1:5432` reaches
   the native server, not the container, and fails with a password error that looks like a
   credentials bug. Run the test database on another port:

   ```
   docker run -d --name autrifix-testpg -e POSTGRES_USER=autrifix -e POSTGRES_PASSWORD=autrifix      -e POSTGRES_DB=autrifix -p 5433:5432 postgres:16-alpine
   USE_POSTGRES_TESTS=1 DATABASE_URL=postgres://autrifix:autrifix@127.0.0.1:5433/autrifix pytest -q
   ```

2. `DATABASE_URL` in `.env` points at **Neon**. Without an explicit override, `USE_POSTGRES_TESTS=1`
   would create and drop a test database on the hosted instance.


---

## CI was never able to run (2026-09-01)

`.github/workflows/ci.yml` set `working-directory: autrifix-be` — a path that does not exist
inside this repository's own checkout, because the root *is* the backend. The two projects sit
in sibling directories locally but are **separate GitHub repositories**
(`NatMaestro/Autrifix-be` and `NatMaestro/Autrifix-fe`). Every step would have failed before
running.

This predates the current work; it was inherited, not introduced. Found by tracing the
workflow's working directories rather than by a failing run, since a workflow that fails at
step one is easy to stop looking at.

Removed. The matrix, the PostgreSQL service, and the coverage gate were all correct — only the
path was wrong.

### Verified against the real thing

```
USE_POSTGRES_TESTS=1 pytest --cov=apps --cov-fail-under=70
  -> 424 passed, coverage 89.12%
```

424 rather than the 423 SQLite reports: `select_for_update` is a silent no-op on SQLite, so
the concurrent-acceptance test only runs on this leg. That is the whole reason the PostgreSQL
matrix entry exists.
