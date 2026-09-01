# Spec Synchronization Report — `autrifix-be`

**Date:** 2026-08-17
**Scope:** backend only (`autrifix-be`). Web, mobile, and landing were not inspected.
**Method:** full read of the source tree (~5,000 lines across 9 Django apps), settings,
migrations, URLs, ASGI/Channels wiring, tests, CI, and deployment configuration.
**Constraints honoured:** no application code changed, no migrations created, no dependencies
installed, no refactoring. Documentation only.

> **Vocabulary note.** This report uses the original `driver` / `mechanic` vocabulary, which was
> current on 2026-08-17. It is a historical record and is deliberately **not** rewritten — the
> rename to `customer` / `provider` is ADR-020.

**Baseline state:** all twelve specs were identical scaffolds containing no requirements and no
requirement IDs. All IDs introduced in this pass are therefore new and are now stable.

**Verification performed:**
- `python manage.py makemigrations --check --dry-run` → *No changes detected* (models and
  migrations are in sync).
- Test suite **not executed** — `pytest` is absent from the checked-in virtualenv and installing
  it was out of scope. CI command of record: `pytest --cov=apps`.
- Every CONFLICT below was derived by reading code. None was exploited or reproduced.

---

## 1. What is implemented

**Authentication and identity (SPEC-001)** — the most complete area. Three sign-in paths
(email/phone + password, Google ID token, phone OTP), JWT with 15-minute production access
tokens, rotating refresh tokens with blacklist-after-rotation, hashed OTP codes with TTL and a
per-phone hourly cap, Ghana-aware E.164 normalization, and admin self-assignment blocked at both
registration and profile update.

**Vehicles (SPEC-004)** — full owner-scoped CRUD with identification and service-specification
fields, a photo, and a primary flag; ownership isolation is structural.

**Core platform** — UUID primary keys throughout; database-level constraints where they matter
(phone-or-email check, one review per job per author, unique offering key); layered settings with
production fail-fast on `SECRET_KEY` and `ALLOWED_HOSTS`; TLS/HSTS/secure-cookie hardening;
allowlisted CORS; a custom exception handler that does not leak internals; generated OpenAPI with
Swagger UI and ReDoc; Redis-backed cache, Celery, and Channels with key namespacing; CI running
Postgres and Redis; Render and Docker deployment definitions.

**Working feature slices** — driver and mechanic profile self-service; mechanic availability
gated on having a workshop location; nearby-mechanic and nearby-request discovery with geodesic
distance; job creation on acceptance with automatic chat-room creation; real-time chat over
WebSocket with a correct participant check; notification read API; issue routing (rules + naive
Bayes) that works out of the box from seeded keywords.

---

## 2. What is partially implemented

| Area | What works | What does not |
|---|---|---|
| **Driver profiles (002)** | lazy creation, self-scoped read/update | home location is written and read back but consumed by nothing; creation logic duplicated across three call sites |
| **Mechanic profiles (003)** | availability, offerings CRUD, ownership isolation | `rating_avg`/`rating_count` are **never written**; `service_radius_km` never applied; no verification state; missing profile → 500 on four endpoints |
| **Service requests (005)** | create, list, read, server-controlled status | no driver cancellation; coordinates unvalidated; `draft` and `assigned` states unreachable; no expiry for unaccepted requests |
| **Discovery (006)** | both directions work, nearest-first | matching does not exist — no dispatch, no offers, no notification; ranking helper is inert; undocumented 30-minute feed window |
| **Job lifecycle (007)** | states, timestamps, participant scoping, request cascade | no transition validation, no atomicity, no locking, no driver cancellation, no audit |
| **Location (008)** | geodesic distance, bounding-box prefilter | no coordinate validation anywhere; results capped at 50 with no truncation signal; privacy conflicts (below) |
| **Messaging (009)** | REST + WebSocket, correct WS authorization, typing indicators | REST detail/send not participant-scoped; unpaginated history; two different frame envelopes for one event |
| **Reviews (011)** | rating bounds, unique constraint, server-assigned author | no eligibility checks at all; no aggregation; mechanics cannot see reviews about them; duplicates return 500 |
| **Administration (012)** | full Django admin over every model | no admin API; `role = admin` grants nothing; admin edits bypass all workflow side effects |
| **Issue routing (006)** | rules + ML classification | model persisted to local disk — not durable, not shared across processes, reset on every deploy |

---

## 3. What is missing

**Not implemented at all:**

- **Notification production (010)** — the model, list endpoint, and mark-read endpoint exist;
  **nothing anywhere creates a notification**. Every user's list is permanently empty. No push,
  no email, no SMS for notifications. This is the largest functional hole: a driver is never told
  their request was accepted, and a mechanic is never told work exists.
- **Rating aggregation (011/003)** — `rating_avg` and `rating_count` are read in four places and
  written in none.
- **Driver-initiated cancellation** of a request (005) or a job (007).
- **Mechanic verification / approval** (003) — no state, no gate.
- **Administrative API** (012) — `IsAdmin` and `ReadOnlyUnlessAdmin` exist and are imported by
  nothing.
- **Audit trail** — no audit model, no `created_by`/`updated_by`, no change history, no security
  event logging, anywhere.
- **Transactions** — no `transaction.atomic()` in the codebase.
- **Filtering** — `DjangoFilterBackend` is the configured default; no view declares a filterset.
- **Coordinate validation** — no range check on any model, serializer, or query parameter.
- **Payments** — `Payment` model and two escrow stubs, no endpoint, no caller. Correctly *not* a
  committed requirement.
- **Background work** — Celery fully configured; one task exists; it is never called. No Celery
  worker is deployed on Render.
- **Tests** — two exist in total (registration happy path, health check). Nothing covers
  permissions, ownership, transitions, concurrency, cancellation, completion, or WebSockets.
  CI reports coverage with `--cov-fail-under=0`, so it can never fail.

---

## 4. What conflicts with the baseline specs

Ordered by severity. Each is specified in full in its spec and summarized in `SECURITY.md`.

### Blockers

| ID | Conflict | Baseline it violates |
|---|---|---|
| **SPEC-009 CONFLICT-009-A** | `GET /chat/jobs/{job_id}/` and `POST /chat/jobs/{job_id}/messages/` have **no participant check**. Any authenticated user with a job UUID reads the whole conversation and can inject messages attributed to themselves, which are then broadcast to both real participants. A mechanic who cancels a job keeps this access. | `API.md` object-level authorization; `SECURITY.md` "protect private messages". The correct check already exists in `JobChatConsumer._get_room_for_user`. |
| **SPEC-011 CONFLICT-011-B** | `POST /reviews/` has **no participation, role, or job-status check**. Any authenticated user can review any job; a mechanic can review their own; a job that was never completed can be reviewed. | `API.md` object-level authorization; `CLAUDE.md` explicit permission checks. |

### High

| ID | Conflict | Baseline it violates |
|---|---|---|
| **SPEC-001 CONFLICT-001-A** | `role` is client-writable at `PATCH /me/`. A driver can become a mechanic instantly and accept jobs; only `admin` is blocked. | `SECURITY.md` authorization; no product rule permits role switching. |
| **SPEC-007 CONFLICT-007-C** | A **driver** can `PATCH` job `status` and `notes`. The side-effect branch is mechanic-gated, so a driver's write desynchronises the job from its request and stamps no timestamps. | `API.md` "a mechanic must not modify another mechanic's job" — and its converse. |
| **SPEC-007 CONFLICT-007-B** | Job status accepts **any** transition from any state, in either direction, any number of times. No transition table exists. | `CLAUDE.md` "define valid transitions rather than allowing arbitrary status updates"; `DOMAIN.md`. |
| **SPEC-007 CONFLICT-007-A** | Job acceptance is three writes with no transaction, no `select_for_update`, and no uniqueness constraint. Two mechanics can both accept the same request. `Job.service_request` is a plural FK. | `CONVENTIONS.md` transactions and "concurrent acceptance" test scenario; `CLAUDE.md` transactional integrity. |
| **SPEC-008 CONFLICT-008-A** | Three location-privacy violations: `/services/nearby/` is unauthenticated and returns exact mechanic coordinates; `mechanic_update` WebSocket events are broadcast platform-wide with no radius filter (filtering is left to the client); the nearby-requests feed discloses the driver's exact coordinate, description, and name-or-phone to any online mechanic before any relationship exists. | `SECURITY.md` "Do not expose a user's location to arbitrary users. Mechanics should receive only the location information necessary for a legitimate job workflow." |
| **SPEC-003 CONFLICT-003-A** | Four endpoints call `MechanicProfile.objects.get()` unguarded; a mechanic who has not opened their profile gets a 500 instead of a handled 4xx. | `CONVENTIONS.md` predictable API errors. |
| **SPEC-011 CONFLICT-011-A** | The mechanic rating summary is read in four places (profile, discovery payloads, presence broadcasts, matching score, default ordering) and written by nothing. Every mechanic shows `0.00 (0)` forever. | `DOMAIN.md` lists "rating summary" as mechanic information. |

### Medium and documentation-level

| ID | Conflict |
|---|---|
| **SPEC-004 CONFLICT-004-A** | `preferred_vehicle` is not ownership-validated — another driver's vehicle can be referenced and is read back. |
| **SPEC-004 CONFLICT-004-B** | `POST /drivers/vehicles/` with `is_primary: true` raises `KeyError` → 500, because the serializer reads a context key the list view never sets. |
| **SPEC-005 CONFLICT-005-B** | The implemented request lifecycle shares only `MATCHING` and `COMPLETED` with the `DOMAIN.md` proposal. `draft` and `assigned` are declared and unreachable. (The baseline labelled its states a proposal, so this is a divergence to reconcile, not a regression.) |
| **SPEC-002 CONFLICT-002-A** | Vocabulary: docs say "Customer", code says "driver" everywhere. |
| **SPEC-003 CONFLICT-003-B** | Category filtering was removed from the mechanic feed in an **uncommitted** working-tree change, leaving `MechanicServiceOffering` inert. |
| **SPEC-005 CONFLICT-005-C** | Request status transitions are performed inline in a view with no guard table. |

---

## 5. What requires a product decision

Fifty-plus open questions are recorded across the specs. These are the ones that block work:

| Ref | Decision needed | Blocks |
|---|---|---|
| SPEC-011 OQ-011-A/B | Who may review whom, and after which job states? | Fixing the review blocker |
| SPEC-009 OQ-009-B/C | Should a chat room close on job completion, and should a cancelling mechanic keep access? | Scoping the chat fix correctly |
| SPEC-001 OQ-001-C | May a user change role after signup? If so, does becoming a mechanic require verification? | Fixing role self-assignment |
| SPEC-007 OQ-007-A/B | What may a driver write on a job? Must completion be driver-confirmed? | Fixing driver job writes |
| SPEC-005 OQ-005-A + SPEC-007 OQ-007-E | What is the canonical state vocabulary? Are `en_route` / `in_progress` needed? Is `draft` real? | The whole transition table |
| SPEC-008 OQ-008-A/B/D | Who may see mechanic and driver locations, at what point, and at what precision? Is public supply visibility intentional? | All three location fixes |
| SPEC-006 OQ-006-C (ADR-005) | Pull-based discovery or push dispatch? | Notifications, Celery, matching |
| SPEC-010 OQ-010-A/B/C | What is the notification event catalogue, who receives each, and is push required? | The entire notification feature |
| SPEC-003 OQ-003-A | Is mechanic verification required before going live? | Trust model |
| SPEC-003 OQ-003-B (ADR-009) | Should offerings gate, rank, or do nothing? | Whether to commit the working-tree change |
| SPEC-006 OQ-006-A | Is the 30-minute request window a product rule or a performance guard? | Request expiry design |
| SPEC-001 OQ-001-A | Is phone-OTP sign-in supported, deprecated, or future? Code, README, and OpenAPI disagree. | Auth surface area |
| SPEC-001 OQ-001-B + SPEC-003 OQ-003-D (ADR-006) | Launch market and platform currency? `+233` vs `USD` default. | Pricing, payments |
| SPEC-012 OQ-012-A/D | Is Django admin the long-term ops surface? What must be audited? | Admin API, audit work |
| ADR-004 | Should a request ever have more than one job? | The acceptance-race fix |
| PRODUCT.md | Roadside assistance, general automotive marketplace, or both? | Lifecycle design |

---

## 6. Recommended next implementation slice

**Slice 1 — "Close the authorization holes" (recommended first, ~1 spec cycle).**

Rationale: these are the only findings that need **no product decision**, are individually small,
have a reference implementation already in the codebase, and are currently exploitable by any
authenticated user.

1. Scope `ChatRoomDetailView` and `ChatMessageCreateView` to participants, reusing the logic in
   `JobChatConsumer._get_room_for_user`. Foreign job id → `404`.
2. Make `role` read-only on `UserSerializer` (a one-line change pending OQ-001-C; read-only is
   the safe default and can be relaxed later).
3. Restrict `JobDetailView` writes to the assigned mechanic; make `status` and `notes`
   driver-read-only.
4. Narrow `preferred_vehicle` to the requesting driver's vehicles.
5. Handle `MechanicProfile.DoesNotExist` on the four unguarded call sites — return `409` with a
   "complete your mechanic profile" detail.
6. **Tests for each**, covering the authorization, not-found, and validation paths.

Update SPEC-001, 003, 004, 007, and 009 with verification evidence. No migration required; no
API contract broken for a well-behaved client.

**Slice 2 — "Make the job lifecycle safe."** Depends on OQ-005-A / OQ-007-E (state vocabulary)
and OQ-007-A. Introduce an explicit transition table, wrap acceptance in `transaction.atomic()`
with `select_for_update()`, add a constraint preventing a second non-cancelled job per request,
and return `409` for invalid transitions and lost races. Add the concurrency test
`CONVENTIONS.md` already asks for.

**Slice 3 — "Reviews and reputation."** Depends on OQ-011-A/B. Add eligibility checks, convert
the duplicate-review `IntegrityError` into a `409`, and implement rating aggregation on
`MechanicProfile` — which immediately makes the discovery payloads, the matching score, and the
model's default ordering meaningful for the first time.

**Slice 4 — "Notifications."** Depends on OQ-010-A/B/C and OQ-006-C. Largest product surface
still missing; also the point at which the unused Celery infrastructure starts earning its place
(and at which a Celery worker must be added to `render.yaml`).

**Deferred, but do not lose:** location privacy (needs OQ-008-A/B first, then likely touches
three endpoints at once); coordinate validation and input size limits; moving the issue-router
model off the local filesystem (ADR-010); mechanic verification.

---

## Files changed in this pass

Documentation only. No application code, migration, or dependency was touched.

- `specs/README.md` — status and provenance vocabulary, feature index
- `specs/001` … `specs/012` — all twelve rewritten from code evidence
- `docs/PRODUCT.md` — observed signals appended as open questions; baseline unchanged
- `docs/DOMAIN.md` — implemented entity map, state machines, and what the domain does not model
- `docs/ARCHITECTURE.md` — actual stack, layering, realtime, async, integrations, deployment
- `docs/API.md` — full endpoint inventory, conventions in force, contract quirks
- `docs/SECURITY.md` — baseline retained, with a standing assessment and 32 numbered findings
- `docs/CONVENTIONS.md` — conventions as practised, plus anti-patterns not to copy
- `docs/FEATURE-MATRIX.md` — backend column verified; other columns marked unverified
- `docs/DECISIONS.md` — ADR-003…ADR-010 recovered from code; open decisions indexed
- `docs/BOOTSTRAP-SYNC.md` — marked complete for this project
- `docs/SYNC-REPORT.md` — this report
