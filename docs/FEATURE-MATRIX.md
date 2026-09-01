# Autrifix Feature Matrix

**Last synchronized with code:** 2026-08-18 (backend only).

The **Backend** column now reflects verified code inspection. Web, Mobile, and Landing were not
inspected in this pass and remain unverified baseline entries.

Status vocabulary is defined in [`specs/README.md`](../specs/README.md):
`IMPLEMENTED` · `PARTIAL` · `STUB` · `NOT_IMPLEMENTED` · `UNKNOWN` · `CONFLICT`.

| Capability | Backend | Web | Mobile | Landing | Spec |
|---|---|---|---|---|---|
| Authentication | **IMPLEMENTED** — password, Google, phone OTP; JWT with rotation; role fixed at signup | Unverified | Not started | N/A | [001](../specs/001-authentication.md) |
| Customer profile | **IMPLEMENTED** — lazy creation; coordinate pairing enforced. Home location still has no consumer (OQ-002-A) | Unverified | Not started | N/A | [002](../specs/002-customer-profiles.md) |
| Provider profile | **IMPLEMENTED** — availability, offerings, live rating summary | Unverified | Not started | Marketing | [003](../specs/003-provider-profiles.md) |
| Provider verification | **IMPLEMENTED** to Tier 1 — graded level gating location precision **and job acceptance**; manual document review. Automated/Ghana Card tiers future | Unverified | Not started | N/A | [013](../specs/013-provider-verification.md) |
| Vehicle management | **IMPLEMENTED** — full CRUD with service specs, ownership-scoped | Unverified | Not started | N/A | [004](../specs/004-vehicles.md) |
| Service requests | **IMPLEMENTED** — create/list/read/cancel; validated coordinates | Unverified | Not started | Marketing | [005](../specs/005-service-requests.md) |
| Matching / discovery | **IMPLEMENTED** as discovery — authenticated, validated, radius-filtered. No dispatch, by decision (ADR-005) | Unverified | Not started | Marketing | [006](../specs/006-matching-discovery.md) |
| Job lifecycle | **IMPLEMENTED** — explicit transition table, atomic acceptance, DB-enforced single live job | Unverified | Not started | Marketing | [007](../specs/007-job-lifecycle.md) |
| Location | **IMPLEMENTED** — geodesic distance, validated bounds, `distance_km` both directions. Pre-acceptance disclosure accepted by design (ADR-015) | Unverified | Not started | N/A | [008](../specs/008-location.md) |
| Messaging | **IMPLEMENTED** — REST + WebSocket, participant-scoped on both | Unverified | Not started | N/A | [009](../specs/009-messaging.md) |
| Notifications | **IMPLEMENTED** — 6-event catalogue, rows + per-user WebSocket. No push (ADR-012) | Unverified | Not started | N/A | [010](../specs/010-notifications.md) |
| Ratings / reviews | **IMPLEMENTED** — customer→provider on completed jobs; live aggregation | Unverified | Not started | Marketing | [011](../specs/011-ratings-reviews.md) |
| Administration | **DEFERRED** (ADR-017) — Django admin only; no admin API | Unverified | Future | N/A | [012](../specs/012-administration.md) |
| Provider types (provider / tow / both) | **IMPLEMENTED** — trade discriminator, trade-aware discovery, capability-filtered feed | Unverified | Not started | Marketing | [014](../specs/014-provider-types-and-agencies.md) |
| Towing specifics | **PARTIAL** — destination coordinates and per-km rate captured; price is typed by the provider, not derived (SPEC-015 OQ-015-F) | Unverified | Not started | Marketing | [014](../specs/014-provider-types-and-agencies.md) |
| Agencies | **IMPLEMENTED** — model, membership, inherited verification, and a full API: create, invite, respond, roles, leave/remove | Unverified | Not started | N/A | [014](../specs/014-provider-types-and-agencies.md), [017](../specs/017-agency-api.md) |
| Lifecycle sweeps & volume limits | **IMPLEMENTED** — auto-confirmation, request expiry, per-customer and per-provider caps. **Requires a cron entry to have any effect** | N/A | N/A | N/A | [016](../specs/016-lifecycle-sweeps.md) |
| Money model (quotes + two-sided completion) | **IMPLEMENTED** — quotes, recorded amounts, customer confirmation, variance disclosure | Unverified | Not started | N/A | [015](../specs/015-money-model.md) |
| Payments / settlement | **STUB** — money is recorded, never moved; settlement is cash off-platform. `Payment` model + escrow stubs have no endpoint and no caller | Not started | Not started | TBD | [015](../specs/015-money-model.md) — rail and revenue model deliberately open |
| AI diagnostics | **STUB** — returns two hardcoded suggestions | Unverified | Not started | N/A | see [006](../specs/006-matching-discovery.md) §19 |
| Issue routing (AI) | **PARTIAL** — rules + naive Bayes; model persistence still not deployment-safe (ADR-010) | Unverified | Not started | N/A | [006](../specs/006-matching-discovery.md) |
| Background jobs | **STUB** — Celery configured; one task, never called (ADR-012 keeps it that way) | N/A | N/A | N/A | see [ARCHITECTURE.md](ARCHITECTURE.md) |
| Audit trail | **IMPLEMENTED** for domain actions — `core.AuditEvent`; admin actions deferred (ADR-017) | N/A | N/A | N/A | [012](../specs/012-administration.md) REQ-7 |

## Backend infrastructure

| Capability | Status | Notes |
|---|---|---|
| PostgreSQL (Neon or local) | IMPLEMENTED | `DATABASE_URL` or `POSTGRES_*`; auto `sslmode` for Neon hosts |
| Redis (cache, Celery, Channels) | IMPLEMENTED | key-prefixed; LocMem/in-memory fallback in development |
| WebSockets (Daphne + Channels) | IMPLEMENTED | chat and provider presence |
| OpenAPI documentation | IMPLEMENTED | Swagger UI, ReDoc, `/api/schema/` |
| Throttling | IMPLEMENTED | `ai` scope now on all three AI endpoints |
| Pagination | PARTIAL | the two discovery endpoints stay capped at 50; `/services/nearby/` now returns a `truncated` flag |
| Filtering / search | PARTIAL | still no `FilterSet`; `?unread=` on notifications is the only filter |
| Transactions | IMPLEMENTED | `@transaction.atomic` on acceptance, transitions, cancellation, and vehicle primary-flag writes |
| Input validation | IMPLEMENTED | coordinate bounds, size caps, and upload limits centralised in `apps/core/validators.py` |
| CI | IMPLEMENTED | GitHub Actions: Postgres + Redis, migrate, pytest |
| Automated tests | **284 tests** | incl. 21 WebSocket, 11 audit, 37 verification, 40 provider-types/tow/agencies |
| Deployment (Render) | IMPLEMENTED | web service only — no Celery worker, which ADR-012 makes acceptable |
| Deployment (Docker) | IMPLEMENTED | web + Celery worker + Postgres + Redis |
| Migration hygiene | IMPLEMENTED | `makemigrations --check` clean; 9 migrations added 2026-08-17, one self-repairing |
| OpenAPI hygiene | IMPLEMENTED | `manage.py spectacular` → 0 errors, 0 warnings |

## Blocking defects

**All five blocking defects recorded on 2026-08-17 were fixed the same day**, each with tests.
See [SECURITY.md](SECURITY.md) for the full status table.

| Area | Defect | Status |
|---|---|---|
| Messaging | Chat detail and message-send not participant-scoped | **FIXED** |
| Reviews | Review creation had no participation, role, or job-status check | **FIXED** |
| Identity | `role` client-writable at `PATCH /me/` | **FIXED** |
| Identity | Failed login returned `500` instead of `401` (found during remediation) | **FIXED** |
| Job lifecycle | Customer-writable status; unvalidated transitions; non-atomic acceptance | **FIXED** |
| Location | Provider coordinates public and broadcast platform-wide | **FIXED** |

Provider verification — previously the top open item — is now specified and implemented to
Tier 1 ([SPEC-013](../specs/013-provider-verification.md)). An unverified provider sees only
coarsened customer locations, so ADR-015's residual exposure is closed by degree rather than left
to trust.

Location harvesting is closed on both paths (ADR-018 coarsening, ADR-019 accept gate). The
highest-priority remaining item is now **operational, not security**: choosing
`PROVIDER_MIN_ACCEPT_LEVEL` for launch (SPEC-013 OQ-013-G), since at the default `documents` no
provider can work until manually reviewed.

## Cross-project note

Web, mobile, and landing statuses in this matrix are inherited from the baseline and were **not**
verified. They should be marked `UNKNOWN` rather than trusted until each project has had its own
synchronization pass.
