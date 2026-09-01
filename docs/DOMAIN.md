# Autrifix Backend Domain Model

**Last synchronized with code:** 2026-08-18.

This document records the **implemented** domain model. Implementation evidence is not
automatically product intent (`DECISIONS.md` ADR-002); divergences are flagged.

## Vocabulary

Settled by ADR-020 on 2026-08-18. The code and the documentation now agree, closing what the
first synchronization pass recorded as CONFLICT-002-A.

| Actor | Role value | Why not the obvious word |
|---|---|---|
| Customer | `customer` | `driver` read like a rideshare app — and once tow operators exist, *a tow operator is a driver*, so the word was ambiguous inside the code too |
| Service provider | `provider` | `mechanic` presumed a single trade; the platform also serves tow operators and agencies |
| Administrator | `admin` | — |

Trade lives on `ProviderProfile.provider_type` (`mechanic` / `tow` / `both`), not on the role.

**One deliberate inconsistency:** the Python packages are `apps/customers` and `apps/providers`,
but their Django **app labels** are still `drivers` and `mechanics`, so tables are `drivers_*` /
`mechanics_*` and string model references read `"drivers.CustomerProfile"`. Changing a label
orphans applied migration history. See ADR-020 and SPEC-014 OQ-014-G.

## Entity map

```text
accounts.User (UUID pk, role: customer|provider|admin)
  ├─1:1─ customers.CustomerProfile
  │        ├─1:N─ customers.Vehicle
  │        └─1:N─ jobs.ServiceRequest ──N:1── jobs.ServiceCategory (PROTECT)
  │                     │   └─N:1 (SET_NULL)─ customers.Vehicle  (preferred_vehicle)
  │                     └─1:N─ jobs.Job
  ├─1:1─ providers.ProviderProfile
  │        ├─1:N─ providers.ProviderServiceOffering ──N:1── jobs.ServiceCategory (PROTECT)
  │        ├─1:N─ providers.ProviderVerification
  │        ├─0:1─ providers.AgencyMembership ──N:1── providers.Agency
  │        └─1:N─ jobs.Job
  ├─1:N─ chat.ChatMessage          (as sender)
  ├─1:N─ reviews.Review            (as author)
  ├─1:N─ notifications.Notification
  └─0:N─ core.AuditEvent           (as actor — SET_NULL, see below)

jobs.Job
  ├─1:1─ chat.ChatRoom ──1:N── chat.ChatMessage
  ├─1:N─ jobs.Quote                (price proposals; at most one `pending`)
  ├─1:1─ payments.Payment          (STUB — no writer, no endpoint)
  └─1:N─ reviews.Review

accounts.PhoneOTP                  (standalone, keyed by phone string)
```

UUID primary keys throughout. Every foreign key is `CASCADE` except:

| Exception | Reason |
|---|---|
| `ServiceCategory` — `PROTECT` | Reference data in use must not vanish |
| `ServiceRequest.preferred_vehicle` — `SET_NULL` | History survives vehicle deletion |
| `AuditEvent.actor` — `SET_NULL` | **The only non-cascading FK by design.** A trail that disappears with the actor is worthless precisely when needed (ADR-016) |
| `ProviderVerification.reviewed_by` — `SET_NULL` | Decisions outlive the reviewer |

## Core entities

### User — `apps/accounts/models.py`

`AbstractUser` with `username` removed, `USERNAME_FIELD = "phone"`. Carries `role`, `phone`,
`email`, `avatar`, `is_email_verified`, `is_phone_verified`. A check constraint requires at least
one of phone or email.

Three sign-in paths: password, Google ID token, phone OTP. `role` is **read-only after signup**
(ADR-013). Specified in SPEC-001.

### CustomerProfile — `apps/customers/models.py`

`display_name` plus an optional home coordinate, created lazily on first touch of a customer
endpoint. The home coordinate is still written, read back, and **consumed by nothing**
(SPEC-002 OQ-002-A).

### ProviderProfile — `apps/providers/models.py`

`business_name`, `provider_type`, `bio`, a workshop coordinate, `service_radius_km`,
`is_available`, `verification_level`, and a `rating_avg` / `rating_count` pair.

- `rating_avg` / `rating_count` are **maintained** by `apps.reviews.services` on review save and
  delete (SPEC-011 REQ-5).
- `verification_level` is ordered `none → phone → documents → ghana_card` (SPEC-013).
- `service_radius_km` is stored but still never applied server-side (SPEC-006 OQ-006-D).

### ProviderServiceOffering — `apps/providers/models.py`

Declared coverage of a `ServiceCategory`, with optional title, description, `hourly_rate`, and
`per_km_rate`. Unique on `(provider, category, title)`.

Offerings do **not** gate which requests a provider sees (ADR-009) but do count toward profile
completeness for `phone`-level verification (SPEC-013 REQ-6).

### ProviderVerification — `apps/providers/models.py`

One review submission: `requested_level`, `status`, three document images, `reviewed_by`,
`review_notes`. **Images are purged on decision** (SPEC-013 REQ-8). At most one `pending`
submission per provider, by partial unique constraint.

### Agency / AgencyMembership — `apps/providers/models.py`

A business fielding several providers. The agency carries its own `verification_level`, which
**lifts** its active members' effective level but never lowers it (SPEC-014 REQ-7). One live
membership per provider, by partial unique constraint; removed memberships are kept as history.

**The individual provider remains the unit of work** — they hold the profile, accept the job, and
chat with the customer.

### Vehicle — `apps/customers/models.py`

Make and model are the only required fields, plus identification, service specs, notes, an
unschema'd `extra` bag, a photo, and `is_primary`. Plate and VIN are neither unique nor
validated. Only a derived `vehicle_summary` is ever shown to a provider.

### ServiceCategory — `apps/jobs/models.py`

Seeded by migration: `general-mechanic`, `battery-electrical`, `engine-overheat`, `tire-flat`,
`tow-recovery`, `brake-pads`. Carries `keywords`, `default_radius_km`, `priority`, and
`requires_destination` — the last marking a service that relocates the vehicle, which implies a
tow-capable provider (SPEC-014 REQ-4).

### ServiceRequest — `apps/jobs/models.py`

Customer, category, description, a required coordinate, optional **destination** coordinate,
status, and an optional `preferred_vehicle` (ownership-validated as of SPEC-004 CONFLICT-004-A).

### Job — `apps/jobs/models.py`

**`ServiceRequest` and `Job` are separate entities** (ADR-004). The request is the customer's ask;
the job is a provider's commitment to it.

`Job.service_request` is a plain `ForeignKey`, so a request may accumulate several jobs over time
— but a partial unique constraint (`unique_live_job_per_service_request`) allows only **one
non-cancelled** job at a time. That constraint is what makes concurrent acceptance safe.

The job also carries the money: `final_amount`, `currency`, and `work_finished_at`, written as
part of the finishing transition and never as a standalone edit (SPEC-015 REQ-7). The amount is
**recorded, never charged** — settlement is cash between the two parties (ADR-022).

### Quote — `apps/jobs/models.py`

A provider's price proposal for a job not yet done: `amount`, `currency`, `notes`, and a status of
`pending → accepted | declined | superseded`. At most one `pending` per job, by partial unique
constraint; submitting a revision supersedes the outstanding one.

Quoting is **optional**. A tow price is computable from per-km × distance and a jump start is a
known number; a repair's cost is not knowable until someone looks, and that is the case quoting
exists for (SPEC-015 REQ-5). Where an accepted quote exists, the gap to the recorded amount is
surfaced to the customer as `amount_variance` — disclosed, not enforced.

### ChatRoom / ChatMessage — `apps/chat/models.py`

One room per job, created at acceptance, addressed publicly by `job_id`. Messages carry a body
and/or an image; participant scoping lives in `apps/chat/selectors.py` and is shared by REST and
WebSocket.

### Notification — `apps/notifications/models.py`

User, typed `kind` (`NotificationKind`), title, body, `payload`, `read_at`. Produced by
`apps.notifications.services.notify` on every job and request transition, and on review receipt
(SPEC-010 REQ-5). `payload` carries the correlation ids, since the model has no FK to its subject.

### Review — `apps/reviews/models.py`

Job, author, 1–5 rating, comment. Unique on `(job, author)`. Written by the job's **customer**,
about a **completed** job only (ADR-011). The model does not record a subject; it is inferred as
the job's provider.

### AuditEvent — `apps/core/models.py`

Append-only record of `job.accepted`, `job.transitioned`, `request.cancelled`,
`auth.login_failed`, and the two verification actions. Carries `actor` (nullable),
`actor_label` (denormalised so the row outlives the account), target type/id, and metadata.
Reads are deliberately **not** audited (ADR-016).

### Payment — `apps/payments/models.py`

`amount_minor` (pesewas), `currency` (default `settings.PLATFORM_CURRENCY` = GHS), escrow status,
`rail`, `processor`, external intent id. No endpoint, no serializer consumer, no caller. **STUB**,
and explicitly not a committed product requirement (`PRODUCT.md`).

Its `USD` and `stripe` defaults were corrected in ADR-022 — not because anything reads them, but
because wrong scaffolding is what the first real integration would copy. `rail` defaults to
*undecided* rather than naming a processor nobody chose (SPEC-015 OQ-015-A).

## State machines

### Job — enforced

The transition table in `apps/jobs/services.py` (`JOB_TRANSITIONS`) is the definition. Anything
not in it returns `409`; re-sending the current status is an idempotent `200`.

```text
pending_accept ──> active ──> awaiting_confirmation ──> completed
      │              │           (provider finished,      (customer
      │              │            amount recorded)         confirmed)
      └──────────────┴──> cancelled
```

| From | To | Actor | Request becomes | Stamps |
|---|---|---|---|---|
| — (accept) | `pending_accept` | Provider | `matching` | — |
| `pending_accept` | `active` | Provider | `assigned` | `accepted_at` |
| `pending_accept` | `cancelled` | Provider (decline) | `open` | — |
| `pending_accept` | `cancelled` | Customer | `cancelled` | — |
| `active` | `awaiting_confirmation` | Provider | *unchanged* | `work_finished_at` |
| `awaiting_confirmation` | `completed` | **Customer** | `completed` | `completed_at` |
| `active` | `cancelled` | Provider (abandon) | `cancelled` | — |
| `active` | `cancelled` | Customer | `cancelled` | — |

Terminal states have no outgoing transitions.

**Completion is two-sided (ADR-022).** The provider records what is owed; only the customer can
close the job. `active → completed` no longer exists, and a customer's legal moves are now
cancellation *and* confirmation.

The `active → awaiting_confirmation` move requires `final_amount`; it is the only transition
marked `requires_amount`, and an amount sent with any other is a `409`. The request deliberately
stays `assigned` through `awaiting_confirmation` — so a separate guard refuses cancellation while
work is finished but unconfirmed (SPEC-015 REQ-8), which would otherwise be a way to walk away
from work already performed.

**A job the customer never confirms is auto-confirmed** after `JOB_AUTO_CONFIRM_AFTER`
(default 72h) by `manage.py sweep_stale_state`. Silence is recorded as silence: `auto_confirmed`
is set, the audit action is distinct, and the customer is told (SPEC-016 REQ-2).

### Quote

```text
pending ──> accepted | declined | superseded      (all terminal)
```

Only the assigned provider submits; only the customer answers. Declining is **not** a cancellation
— it invites a revision.

### ServiceRequest

Declared: `draft`, `open`, `matching`, `assigned`, `cancelled`, `completed`, `expired`.
**Reachable:** all but `draft` — every value above is written as a declared side effect of a job
transition, by `cancel_service_request`, or by the sweep.

`assigned` means a provider is actively working; `matching` means one has claimed but not yet
started. `draft` remains declared and unwritten (SPEC-005 OQ-005-A).

`expired` is written by `expire_stale_requests` when no provider claimed the request in time.
It is deliberately **not** `cancelled`: conflating them loses the difference between a customer
changing their mind and the platform finding nobody, which is the metric that says whether
supply is adequate (SPEC-016 REQ-3).

### ProviderProfile availability

```text
OFFLINE <──> ONLINE     (ONLINE requires both base coordinates)
```

Availability is independent of verification: an unverified provider may go online and browse, but
**cannot accept** (ADR-019).

### ProviderVerification

```text
pending ──> approved | rejected      (terminal; documents purged on decision)
```

### AgencyMembership

```text
invited ──> active ──> removed       (only `active` confers identity or inherited verification)
```

### Divergence from the original baseline lifecycle

The pre-SDD baseline proposed `DRAFT → SUBMITTED → MATCHING → ACCEPTED → EN_ROUTE → IN_PROGRESS →
COMPLETED`. The implementation shares `MATCHING`, `ASSIGNED` (≈ in progress) and `COMPLETED`.
There is still no submit step, and no distinction between "en route" and "working"
(SPEC-007 OQ-007-E).

## Geospatial behavior

- Plain `FloatField` latitude/longitude pairs. **No PostGIS, no GeoDjango, no spatial index** —
  a deliberate decision (ADR-003).
- WGS84 geodesic distance via `geopy`, computed in Python per candidate row after a naive
  bounding-box prefilter that does not handle the antimeridian.
- Coordinates are **range-validated** at model, serializer, query-parameter, and WebSocket layers
  from one source (`apps/core/validators.py`).
- Results are capped at 50 in both discovery directions; `/services/nearby/` reports `truncated`.
- **Precision is graded by trust.** A provider below `PROVIDER_EXACT_LOCATION_MIN_LEVEL` sees
  customer coordinates snapped to a ~1 km grid, with the published distance derived from the
  snapped point so the true one cannot be recovered by trilateration (SPEC-013 REQ-2).

Location drives discovery in both directions and the ranking within it. It does **not** drive
assignment; there is no dispatch (ADR-005).

## What the domain still does not model

- **Settlement.** Money is *recorded* — quoted, agreed, and confirmed — but never moved. Cash
  changes hands off-platform (ADR-022). No wallet, escrow, commission, or payout exists.
- **Derived pricing.** `hourly_rate` and `per_km_rate` are still read by nothing; a provider types
  a number (SPEC-015 OQ-015-F).
- **Disputes.** A customer who disagrees with an amount simply does not confirm (SPEC-015 OQ-015-E).
- **Dispatch.** Providers are never told work exists; discovery is pull-only.
- **Scheduling of the sweeps.** `manage.py sweep_stale_state` must be cron'd or the stuck
  states return; nothing in the app enforces that it runs (SPEC-016 §7).
- **Soft delete.** Every delete cascades destructively (SEC-GAP-19).
- **Equipment.** No flatbed/hook or tonnage modelling for towing (SPEC-014 OQ-014-C).
- **Trade-aware capacity.** Concurrent jobs are capped, but the cap is trade-blind — a tow
  operator queuing three pickups is normal, a mechanic on-site with three is not
  (SPEC-016 OQ-016-D).
- **Scheduling.** Every request is immediate; there is no booking concept.
- **Agency dispatch or payouts.** An agency is an identity and a verification scope, nothing
  more — deliberately (ADR-021). It now has an API (SPEC-017), but no work is ever routed to it.
- **Agency-initiated verification.** An agency's level can still only be set from the Django
  admin; `ProviderVerification` targets a person (SPEC-017 OQ-017-D).
