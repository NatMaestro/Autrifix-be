# Autrifix Backend Security Baseline

**Last synchronized with code:** 2026-08-18 (post-remediation).

The baseline rules below are unchanged — they remain the standard. Alongside each is a record of
where the implementation meets and fails them.

**Remediation status:** of the 35 findings now tracked, **26 are resolved**, 2 are partially
resolved, 1 is accepted by design for verified providers only, 4 are **deferred by decision**
(ADR-017), and the rest are open pending a product call or a design step.

Location harvesting is closed on both paths (ADR-018 coarsening + ADR-019 accept gate). The
highest-priority remaining item is no longer confidentiality but **availability** — see the
bottom of this document.

Almost every "RESOLVED" below is backed by a named test in `tests/`. The exceptions are the two
`SECRET_KEY` findings, which are configuration-boot behavior verified manually (see
`IMPLEMENTATION-LOG.md`), and SEC-GAP-14, which is resolved structurally rather than by a check.

---

## Identity

**Rules:** protect authentication endpoints; never store plaintext passwords; never commit
secrets; validate tokens using the established mechanism.

**Standing: mostly met.**

- Passwords use Django hashing with the default validator set plus a serializer `min_length=8`.
- OTP codes are stored as `SHA-256(SECRET_KEY:phone:code)` and consumed on use; re-issuing
  invalidates outstanding codes.
- Auth endpoints carry the `auth` throttle scope (30/min dev, 20/min prod) plus a per-phone
  hourly cap on OTP sends.
- JWT: 15-minute access tokens in production, rotating refresh tokens with
  blacklist-after-rotation.
- `.env` is git-ignored; `.env.example` and `.env.production.example` contain placeholders only.

Gaps:

| ID | Finding | Severity | Status |
|---|---|---|---|
| SEC-GAP-01 | No per-account brute-force lockout; throttling was IP/user-keyed only | Medium | **RESOLVED** — `LoginIdentifierRateThrottle` adds a second limit keyed by the targeted identifier (hashed), 10/min dev / 5/min prod, alongside the existing IP-keyed `auth` scope. `test_repeated_failed_logins_for_one_identifier_are_throttled`, `test_throttling_one_identifier_does_not_lock_out_another` |
| SEC-GAP-02 | `SECRET_KEY` fell back to a publicly known literal in base settings | Medium | **RESOLVED** — a default now exists only under `DEBUG`; a non-DEBUG boot without `SECRET_KEY` raises `ImproperlyConfigured` rather than starting with a known key |
| SEC-GAP-03 | `scripts/render-build.sh` exported a hardcoded build-time `SECRET_KEY` | Medium | **RESOLVED** — generates an ephemeral key per build; it is never persisted and never reaches the running service |
| SEC-GAP-04 | `/auth/logout/` has no throttle scope | Low | OPEN |
| SEC-GAP-05 | With `SMS_PROVIDER=console`, OTP codes are logged at WARNING | Low (dev) | OPEN — development-only by design |
| **SEC-GAP-33** | **Every failed login returned `500`, not `401`** — `IdentifierTokenObtainPairSerializer` referenced `jwt_api_settings.NO_ACTIVE_ACCOUNT_FOUND`, which does not exist in simplejwt 5.4.0, so wrong passwords and inactive accounts raised `AttributeError`. Found by the tests added during remediation, not by the code-reading pass. | High | **RESOLVED** — `test_login_with_wrong_password_is_401`, `test_login_for_inactive_user_is_401` |

---

## Authorization

**Rule:** every protected resource must answer — *is this authenticated actor allowed to perform
this action on this exact object?*

**Standing: was the weakest area of the backend; now the most thoroughly covered.**

Three patterns are in use — structural self-resolution, queryset scoping, and explicit
participant checks (see `API.md`). All authorization holes found in the synchronization pass are
now closed:

| ID | Finding | Severity | Status |
|---|---|---|---|
| SEC-GAP-06 | `GET /chat/jobs/{job_id}/` had no participant check | Blocker | **RESOLVED** — `apps/chat/selectors.py`; `test_unrelated_customer_cannot_read_room`, `test_unrelated_provider_cannot_read_room` |
| SEC-GAP-07 | `POST /chat/jobs/{job_id}/messages/` had no participant check | Blocker | **RESOLVED** — `test_unrelated_customer_cannot_post_message`, `test_unrelated_provider_cannot_post_message` |
| SEC-GAP-08 | `POST /reviews/` had no participation, role, or job-status check | Blocker | **RESOLVED** — `test_unrelated_customer_cannot_review`, `test_provider_cannot_review_their_own_job`, `test_incomplete_job_cannot_be_reviewed` |
| SEC-GAP-09 | `role` was client-writable at `/me/` | High | **RESOLVED** — read-only (ADR-013); `test_me_cannot_change_role` |
| SEC-GAP-10 | A customer could write job `status` and `notes` | High | **RESOLVED** — actor-aware transitions; `test_customer_cannot_complete_a_job`, `test_customer_cannot_edit_notes` |
| SEC-GAP-11 | Job status accepted any transition from any state | High | **RESOLVED** — `JOB_TRANSITIONS`; `test_skipping_active_is_409`, `test_completed_job_cannot_regress` |
| SEC-GAP-12 | `/ai/matching/preview/` accepted any `service_request_id` | Medium | **RESOLVED** — owner-or-staff scoped; `test_matching_preview_rejects_other_users_request` |
| SEC-GAP-13 | `preferred_vehicle` was not ownership-validated | Medium | **RESOLVED** — queryset narrowed; `test_another_customers_vehicle_is_rejected` |
| SEC-GAP-14 | A provider who cancelled retained chat access | High | **RESOLVED by design** — rooms are per-job; a re-accepted request gets a new job and a new room, so the declining provider keeps only their own dead conversation |

Non-participants receive `404`, never `403`, so resource existence is never confirmed.

---

## Customer data

**Rule:** protect personal information, phone/contact information, vehicle information, service
locations, private messages, and job history.

**Standing: partially met.**

Met: vehicle plates and VINs are never exposed to providers (only a derived
`"{year} {make} {model} · {color}"` summary); job and request querysets are participant-scoped.

Gaps:

| ID | Finding | Severity | Status |
|---|---|---|---|
| SEC-GAP-15 | `customer_name` fell back to the raw phone number, in the pre-acceptance feed | Medium | **RESOLVED** — falls back to `"Customer"`; `test_customer_name_does_not_leak_phone_number` |
| SEC-GAP-16 | Private messages readable by any authenticated user | Blocker | **RESOLVED** — see SEC-GAP-06 |
| SEC-GAP-17 | Django admin exposes full chat bodies and images, unaudited | High | OPEN — needs an operator-role decision (SPEC-012 OQ-012-C) |
| SEC-GAP-18 | Uploaded media has no access control — the URL is the only secret | Medium | OPEN |
| SEC-GAP-19 | Every FK is `CASCADE`; deleting a provider destroys job history and reviews about them | Medium | OPEN — needs a soft-delete decision (SPEC-011 OQ-011-F) |

---

## Location

**Rule:** precise service locations can be sensitive. Do not expose a user's location to
arbitrary users. Providers should receive only the location information necessary for a
legitimate job workflow.

**Standing: mostly met.** Two of the three violations are closed; the third is a product
decision. Recorded in `specs/008-location.md` CONFLICT-008-A.

| ID | Finding | Severity | Status |
|---|---|---|---|
| SEC-GAP-20 | `GET /services/nearby/` was `AllowAny`, enabling enumeration of every online provider | High | **RESOLVED** — authenticated (ADR-014); `test_services_nearby_requires_authentication` |
| SEC-GAP-21 | Presence events broadcast platform-wide with client-side filtering | High | **RESOLVED** — the consumer filters by the subscriber's own radius before sending |
| SEC-GAP-22 | A browsing provider sees the customer's exact coordinate and description pre-acceptance | High | **ACCEPTED BY DESIGN for verified providers** (ADR-015); **CLOSED for unverified ones**: coordinates are grid-snapped with the distance derived from the snapped point (ADR-018), and acceptance — the other route to an exact location — is gated on verification (ADR-019). Identity no longer leaks (SEC-GAP-15). |
| SEC-GAP-23 | Coordinates are never coarsened | Medium | **CLOSED for the browse path** (ADR-015): coarsening degrades the accept/decline signal. Reopen for any new disclosure surface. |

---

## API abuse

**Rule:** consider throttling, brute-force protection, request validation, file upload
restrictions, input size limits, and enumeration risks.

**Standing: partial.**

Met: DRF throttling is configured globally with anon/user/auth/ai scopes and tightened in
production; UUID primary keys everywhere make id enumeration impractical; not-found and
not-owned both return `404`, so ownership is not disclosed.

Gaps:

| ID | Finding | Severity | Status |
|---|---|---|---|
| SEC-GAP-24 | No coordinate validation anywhere; out-of-range latitude reached `geopy` (a 500 vector) | Medium | **RESOLVED** — `apps/core/validators.py` applied at model, serializer, query-parameter, and WebSocket layers |
| SEC-GAP-25 | No input size limits on `description`, `comment`, `bio`, message `body` | Medium | **RESOLVED** — 2000 chars (4000 for chat body), plus caps on `issue_text` and `symptoms` |
| SEC-GAP-26 | No file upload size restrictions | Medium | **PARTIALLY RESOLVED** — 5 MB cap on avatars, vehicle photos, and chat images. No dimension cap or type allowlist beyond Pillow. |
| SEC-GAP-27 | `ai` throttle scope applied only to `/ai/diagnostics/` | Low | **RESOLVED** — all three AI endpoints |
| SEC-GAP-28 | No cap on open requests per customer, no duplicate detection, no concurrent-job cap | Medium | **RESOLVED** (SPEC-016 REQ-4/5) for the two caps; duplicate detection remains open |
| SEC-GAP-36 | Agency invitation by phone reveals whether a number belongs to a provider account | Low | OPEN — throttled at `20/hour`; attacker needs a provider account and an agency (SPEC-017 OQ-017-A) |
| SEC-GAP-29 | Django admin has no login rate limit and no IP restriction | Medium | OPEN |
| SEC-GAP-30 | Request creation drives synchronous local-disk writes via ML training | Low | OPEN — see `DECISIONS.md` ADR-010, recommended for reversal |

---

## Transport & platform

**Standing: good.** Production settings enforce `SECRET_KEY` length and non-empty
`ALLOWED_HOSTS`, and enable `SECURE_SSL_REDIRECT`, HSTS (1 year, includeSubDomains),
secure session and CSRF cookies, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS = DENY`, and
`SECURE_REFERRER_POLICY = same-origin`, with `SECURE_PROXY_SSL_HEADER` configurable.

CORS is allowlisted from `CORS_ALLOWED_ORIGINS` (empty by default) with credentials enabled;
`CSRF_TRUSTED_ORIGINS` is likewise environment-driven.

| ID | Finding | Severity |
|---|---|---|
| SEC-GAP-31 | JWTs travel in the WebSocket **query string**, which proxies, load balancers, and access logs routinely record. | Medium |
| SEC-GAP-32 | `JwtQueryAuthMiddleware` catches every exception and degrades to `AnonymousUser`, so token validation failures are invisible in logs. | Low |

---

## Auditability

**Rule:** for sensitive operational actions, determine whether an audit trail is required.

**Standing: determined and implemented for domain actions (ADR-016); deferred for
administrative actions (ADR-017).**

`core.AuditEvent` records `job.accepted`, `job.transitioned`, `request.cancelled`, and
`auth.login_failed`, with actor, target, and metadata. Design points that make it worth having:

- **The row outlives its actor** — `SET_NULL` plus a denormalised `actor_label`. The only
  non-cascading foreign key in the codebase, because a trail that vanishes with the provider who
  deleted their profile is worthless exactly when it matters.
- **Failed logins record `reason` and `account_exists`,** so the trail distinguishes "no such
  account" from "wrong password" even though the API response is deliberately identical.
- **Read-only in admin** — no add, change, or delete.
- **Auditing cannot break the audited action** — a write failure logs and returns. Revisit if
  auditing becomes a compliance rather than operational requirement.

Deliberately **not** audited: reads (high volume, low value — request logs cover them) and
successful logins.

| ID | Finding | Severity | Status |
|---|---|---|---|
| SEC-GAP-34 | Administrative actions, including an operator reading a private conversation, are unaudited | High | **DEFERRED** (ADR-017) — the one read worth auditing |
| SEC-GAP-35 | No audit retention policy; nothing prunes | Low | OPEN (SPEC-012 OQ-012-H) |

---

## Secrets

**Standing: met.** All credentials are environment-driven: `SECRET_KEY`, database URL, Redis
URLs, Twilio, Termii, Google client id, and Cloudinary. No real secret appears in the repository;
`.env` is git-ignored, and `render.yaml` marks sensitive values `sync: false` or
`generateValue: true`.

---

## Remaining work, in priority order

**1. Decide the launch value of `PROVIDER_MIN_ACCEPT_LEVEL` (SPEC-013 OQ-013-G).**

This is now an *availability* risk rather than a confidentiality one, but it is the most
consequential open item. ADR-019 gates accepting on verification, so at `documents` — the default
— **no provider can work until manually reviewed.** On day one that means no accepted jobs at
all, and review turnaround becomes the critical path for the whole marketplace, dependent on one
person.

Running at `phone` during launch avoids the cold start at the cost of early providers being only
phone-verified (which in Ghana still carries indirect Ghana Card linkage via SIM registration).
Either choice is defensible; making it by accident is not.

**Location harvesting is now closed on both paths:** coarsened browsing (ADR-018) stops bulk
scraping, and the accept gate (ADR-019) stops accept-then-cancel. Nobody unverified attends a
customer.

**Deferred by decision (ADR-017) — admin side**

2. SEC-GAP-17 / 29 / 34 — admin can read any private conversation unaudited; no admin login
   throttling; no IP restriction; administrative actions unaudited. Note the API login is now
   protected per-identifier, so **admin is the remaining unprotected door.**

**Blocked on a product decision**

3. ~~**SEC-GAP-28** — volume caps~~ **DONE** (SPEC-016). Originally described as: volume caps (open requests per customer, concurrent jobs per provider). These
   are business rules, not abuse controls (SPEC-003 OQ-003-C).
4. **SEC-GAP-19** — soft delete, so a provider cannot erase their own negative history
   (SPEC-011 OQ-011-F).
5. **SEC-GAP-35** — audit retention policy (SPEC-012 OQ-012-H).

**Needs a design step, not a decision**

6. **SEC-GAP-18** — media access control (signed URLs or a proxying view).
7. **SEC-GAP-30** — move the ML routing model off the local filesystem (ADR-010). The path is now
   configurable, which is a mitigation, not a fix.
