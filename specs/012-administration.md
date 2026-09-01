# SPEC-012 — Administration

**Status:** IMPLEMENTED — the operator API was built on 2026-09-01 (ADR-024)
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

> **No longer deferred.** ADR-017 parked this spec; ADR-024 unparked the part that had become
> load-bearing. An operator API now exists under `/api/v1/admin/`, gated on `IsAdmin`.
>
> **Scope is narrow on purpose.** It covers verification review, user search, job history, and
> operational counts. It does **not** cover reading private conversations (which would widen
> SEC-GAP-17/34), serving the verification documents (SEC-GAP-18, now OQ-012-I), editing
> accounts, or scoped operator roles (OQ-012-B). Django admin remains the surface for
> general-purpose editing, and SEC-GAP-29 (no admin login rate limit) is still open.
>
> The **audit trail** (REQ-7, ADR-016) was implemented ahead of the rest, because the job
> lifecycle depends on it rather than administration.

## 1. Summary

Administration is **entirely Django admin**. Every domain model is registered and editable at
`/admin/`. There is no administrative REST API, no admin-facing endpoint of any kind, and the
two admin-oriented DRF permission classes that exist (`IsAdmin`, `ReadOnlyUnlessAdmin`) are
never applied to a view.

Overall classification: **PARTIAL** — operable for an engineer, absent as a product surface.

## 2. Problem

Someone has to onboard and correct providers, resolve disputes, unstick jobs, manage the service
catalogue, and answer support questions. Today that requires Django admin access, which is a
staff-level credential over the whole database.

## 3. Actors

- Administrator — a `User` with `is_staff` (and effectively `is_superuser`).
- Support operator — **does not exist** as a distinct role.

## 4. Goals (as built)

- Give an operator a way to inspect and correct any record.
- Manage the service category catalogue.

## 5. Non-Goals (as built)

- Any administrative capability exposed to a web or mobile client.
- Role-scoped operator permissions.
- Moderation queues, dispute workflows, or refunds.

## 6. Requirements

### REQ-1 — Admin role exists on the identity model
**ID:** DOM-012-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

`UserRole.ADMIN` exists and `create_superuser` sets it. Self-registration as admin is blocked
(SPEC-001 REQ-7).

`PARTIAL` — the role grants nothing on its own. Every API surface gates on `IsCustomer`,
`IsProvider`, or `IsCustomerOrProvider`, so a user whose role is `admin` but who lacks `is_staff`
can reach **no** domain endpoint: `/jobs/`, `/chat/`, `/customers/…`, `/providers/…` all return
`403`. The admin role is API-inert.

Evidence: [apps/accounts/models.py:11-14](apps/accounts/models.py#L11-L14), [apps/accounts/models.py:41-49](apps/accounts/models.py#L41-L49); role gates in [apps/accounts/permissions.py](apps/accounts/permissions.py)

### REQ-2 — Django admin covers every domain model
**ID:** PROD-012-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

All eleven models are registered:

| App | Models registered | Notes |
|---|---|---|
| accounts | `User` (custom `UserAdmin`), `PhoneOTP` | OTP hash/timestamps read-only |
| customers | `CustomerProfile` (+ `Vehicle` inline), `Vehicle` | |
| providers | `ProviderProfile`, `ProviderServiceOffering` | |
| jobs | `ServiceCategory` (slug prepopulated), `ServiceRequest`, `Job` | |
| chat | `ChatRoom` (+ `ChatMessage` inline) | full message bodies and images visible |
| notifications | `Notification` | |
| reviews | `Review` | |
| payments | `Payment` | |

Evidence: `apps/*/admin.py`

### REQ-3 — Service catalogue management
**ID:** PROD-012-003 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

`ServiceCategory` is fully editable in admin, including `keywords`, `priority`,
`default_radius_km`, and `is_active`.

`PARTIAL` — the categories that matter are **seeded by migration** (`jobs/0002`, `jobs/0004`),
and the issue router's rule table (`RULES` in `apps/ai/issue_router.py`) is a Python constant an
operator cannot touch. Renaming or deactivating a seeded category silently degrades routing,
because `_rule_pick` matches intent tokens against category names, slugs, descriptions, and
keywords.

Evidence: [apps/jobs/admin.py:6-12](apps/jobs/admin.py#L6-L12), [apps/ai/issue_router.py:23-74](apps/ai/issue_router.py#L23-L74)

### REQ-4 — Administrative REST API
**Status:** IMPLEMENTED (2026-09-01, ADR-024)

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/stats/` | Operational counts, including the auto-confirmation count |
| GET | `/admin/users/` | Search by name, email, or phone; filter by role |
| GET | `/admin/jobs/` | Job history, filterable by status |
| GET | `/admin/verifications/` | Review queue, **oldest first**, filterable by status |
| POST | `/admin/verifications/{id}/review/` | Approve or decline; a decline requires a reason |

All five gate on `IsAdmin`, which existed from the beginning and had been applied to nothing.
Review goes through `provider_services.review_verification`, so approval never downgrades an
existing level and documents are purged either way — the operator API cannot reach a state the
domain forbids.

Covered by `tests/test_administration.py` (27), where the authorization cases carry most of
the weight: an operator endpoint that leaked to a customer or provider would expose every
user's contact details and every job on the platform.

#### Original note (superseded)
**ID:** PROD-012-004 · **Priority:** Must · **Provenance:** PROPOSED · **Status:** NOT_IMPLEMENTED

No admin endpoint exists. `IsAdmin` and `ReadOnlyUnlessAdmin` are defined and never imported by
any view — confirmed by grep. The `autrifix-web` project cannot build an admin console against
this backend today.

Evidence: [apps/accounts/permissions.py:6-9](apps/accounts/permissions.py#L6-L9), [apps/accounts/permissions.py:32-40](apps/accounts/permissions.py#L32-L40); no importer.

### REQ-5 — Operational intervention
**ID:** PROD-012-005 · **Priority:** Should · **Provenance:** PROPOSED · **Status:** PARTIAL

An operator can unstick a job or request by editing `status` directly in admin.

`PARTIAL` and unsafe — admin edits bypass every side effect in `JobDetailView.perform_update`.
Setting a job to `completed` in admin does not stamp `completed_at` and does not complete the
request. Nothing validates transitions there either. This is a real operational hazard given that
CONFLICT-007-B already leaves transitions unguarded at the API.

### REQ-6 — Provider verification / approval
**ID:** PROD-012-006 · **Priority:** Must · **Provenance:** PROPOSED · **Status:** NOT_IMPLEMENTED

There is no verification state on `ProviderProfile` and no approval step. A self-registered user
who sets `role = provider` at signup is immediately a live service provider.

**Escalated by ADR-015:** because a provider now sees customers' exact locations before accepting,
verification is the compensating control for customer location privacy, not merely a quality bar.
It is the highest-priority open product question (SPEC-003 OQ-003-A).

### REQ-7 — Audit trail
**ID:** SEC-012-007 · **Priority:** Must · **Provenance:** PRODUCT (ADR-016) · **Status:** IMPLEMENTED

The platform records an append-only `core.AuditEvent` for state changes and failed logins.

| `action` | Recorded when | Metadata |
|---|---|---|
| `job.accepted` | a provider claims a request | `service_request_id`, `provider_id` |
| `job.transitioned` | any job state change | `from`, `to`, `actor_role`, `service_request_id`, `service_request_status` |
| `request.cancelled` | a customer cancels | `from`, `cancelled_job_ids` |
| `auth.login_failed` | wrong credentials or inactive account | `identifier`, `reason`, `account_exists`, `ip` |

Fields: `action`, `actor` (nullable), `actor_label`, `target_type`, `target_id`, `metadata`,
`created_at`.

Three design points, each deliberate:

1. **The row outlives its actor.** `actor` is `SET_NULL` and `actor_label` denormalises who it
   was. This is the only foreign key in the codebase that does not cascade — a trail that
   disappears when a provider deletes their profile is worthless precisely when it is needed.
2. **Auditing never breaks the audited action.** A write failure is logged and swallowed.
   Losing one row beats failing a transition a customer and provider are waiting on. Revisit if
   auditing becomes a compliance rather than operational requirement.
3. **Reads are not audited** (ADR-016). Failed logins record enough to distinguish
   "no such account" from "wrong password" even though the API response is deliberately
   identical for both.

Exposed read-only in Django admin: no add, no change, no delete, all fields read-only.

Evidence: [apps/core/models.py](apps/core/models.py), [apps/core/audit.py](apps/core/audit.py), [apps/core/admin.py](apps/core/admin.py); hooks in [apps/jobs/services.py](apps/jobs/services.py) and [apps/accounts/serializers.py](apps/accounts/serializers.py)

**Not yet audited, and deferred with the rest of administration:** administrative actions,
including an operator reading a private conversation (SEC-GAP-17).

## 7. User Flow (as built)

1. An engineer creates a superuser with `python manage.py createsuperuser` (phone required).
2. They log in at `/admin/` with a session cookie.
3. They edit records directly.

There is no operator onboarding flow, no scoped access, and no in-product admin experience.

## 8. Business Rules

- Django admin uses **session** authentication, not JWT — a separate credential path from the API,
  with CSRF protection and `SessionMiddleware` enabled.
- `is_staff` gates admin access; `role == admin` does not.
- Superuser creation requires a phone number (`UserManager.create_superuser` raises otherwise).
- `PhoneOTPAdmin` marks `code_hash`, `expires_at`, `consumed_at`, and `created_at` read-only, so
  an operator cannot forge or extend an OTP through admin. Good.
- No admin action is logged beyond Django's built-in `LogEntry` (which covers admin edits only,
  and is not surfaced anywhere).

## 9. State Model

None. Administration has no workflow.

## 10. API Contract

**None.** The only administrative surface is `/admin/` (HTML, session-authenticated), plus the
OpenAPI documentation surfaces:

| Path | Purpose | Auth |
|---|---|---|
| `/admin/` | Django admin | session, `is_staff` |
| `/api/schema/` | OpenAPI 3 document | as configured by DRF defaults |
| `/api/docs/` | Swagger UI | — |
| `/api/redoc/` | ReDoc | — |
| `/swagger/` | redirect to Swagger UI | — |
| `/` | redirect to `/api/docs/` | — |

**IMPLEMENTATION NOTE:** the schema preprocessing hook restricts the published document to
`/api/v1/…` paths, so `/admin/` is excluded from the OpenAPI output.

## 11. Data Model

Administration owns no models. It operates over every other app's models.

There is **no audit model** anywhere in the codebase: no `AuditLog`, no `created_by`/`updated_by`
columns, no change history on any domain model. `docs/SECURITY.md` asks that this be determined
for sensitive operational actions; the determination has not been made.

## 12. Security

- **Authentication:** Django session for `/admin/`; separate from the JWT API.
- **Authorization:** `is_staff` for admin access. Django groups and per-model permissions are
  available (`filter_horizontal` on groups/user_permissions in `UserAdmin`) but no groups are
  defined by the project.
- **Object-level access:** none — admin is all-or-nothing per model.
- **Sensitive data:** admin exposes everything: private chat message bodies and images
  (`ChatMessageInline`), customer and provider coordinates, phone numbers, vehicle plates and VINs,
  and payment records.
- **Abuse/rate limiting:** DRF throttles do **not** apply to `/admin/`; there is no admin login
  rate limit or lockout.
- **Auditability:** Django's `LogEntry` records admin model changes but is not exposed, monitored,
  or retained deliberately. API-side changes are not audited at all.

### Observed security gaps

| ID | Finding | Severity |
|---|---|---|
| ID | Finding | Severity | Status |
|---|---|---|---|
| SECGAP-012-1 | No admin API and no scoped operator role — any operational task requires full-database staff access | High | **DEFERRED** (ADR-017) |
| SECGAP-012-2 | Admin can read every private conversation via `ChatMessageInline`, unaudited | High | **DEFERRED** (ADR-017); the one read worth auditing, explicitly excluded from ADR-016 scope |
| SECGAP-012-3 | Admin status edits bypass all workflow side effects (REQ-5) | Medium | **DEFERRED** — and now more visible, since API transitions are validated while admin edits are not |
| SECGAP-012-4 | No brute-force protection or lockout on the admin login form | Medium | **DEFERRED** (ADR-017). Note the API login *is* now protected per-identifier (SPEC-001 REQ-10) — admin is the remaining unprotected door |
| SECGAP-012-5 | No audit log for any sensitive operational action | Medium | **RESOLVED for domain actions** (REQ-7); administrative actions remain deferred |
| SECGAP-012-6 | `/admin/` shares an origin with the API and is not IP-restricted | Medium | **DEFERRED** (ADR-017) |
| SECGAP-012-7 | `UserAdmin` allows changing `role`, `is_staff`, `is_superuser` with no separation of duties | Low | **DEFERRED** — and load-bearing now: since ADR-013 made `role` read-only over the API, admin is the *only* way to correct a role |

## 13. Edge Cases

- A user with `role = admin` but `is_staff = False` → locked out of both admin and every API
  endpoint (REQ-1).
- Deactivating a `ServiceCategory` that has offerings or requests → the category cannot be
  *deleted* (`PROTECT`), but deactivating it removes it from creation choices while existing
  requests keep referencing it.
- Deleting a `ProviderProfile` in admin → cascades to their jobs, chat rooms, messages, reviews,
  and payments. There is no soft delete anywhere in the codebase.
- Editing `Job.status` in admin → no timestamps, no request cascade (REQ-5).
- `CustomerProfileAdmin.search_fields` searches `user__email`, which is null for phone-only
  accounts, so those customers are unfindable by search.

## 14. Acceptance Criteria

- [x] Every domain model is inspectable and editable by an operator.
- [x] Service categories are manageable.
- [x] OTP hashes cannot be edited through admin.
- [x] Self-registration as admin is blocked.
- [x] Domain state changes and failed logins are audited, durably (REQ-7).
- [x] The audit trail is visible but not editable by operators.
- [ ] An administrative API exists — **DEFERRED** (REQ-4, ADR-017).
- [ ] `role = admin` grants meaningful API access — **DEFERRED** (REQ-1).
- [ ] Operator actions on jobs run through the same transition rules as the API — **DEFERRED** (REQ-5).
- [ ] Provider verification exists — **NOT_IMPLEMENTED** (REQ-6). *Not deferred: escalated by ADR-015.*
- [ ] Administrative actions are audited — **DEFERRED** (ADR-017).
- [ ] Admin access is scoped so support staff cannot read all private messages — **DEFERRED**.
- [ ] An audit retention policy exists — **NOT_IMPLEMENTED** (OQ-012-H).

## 15. Tests

### Existing — `tests/test_audit.py` (11 tests), covering REQ-7 only
- **What is audited:** acceptance; every transition with `from`/`to`; the acting role;
  request cancellation including the jobs it killed; failed logins for an existing account, an
  unknown account, and an inactive account — the last two distinguishable *only* in the audit
  trail, since the API response is deliberately identical.
- **What is not:** successful logins; reads (a discovery sweep produces zero rows).
- **Durability:** an audit row survives `actor.delete()`, keeping `actor_label` and metadata —
  the property that makes the trail worth having.
- **Resilience:** with `AuditEvent.objects.create` patched to raise, job acceptance still
  returns `201`.

### Missing (gap) — deferred with ADR-017
- **Integration:** `/admin/` requires `is_staff`; a `role = admin` non-staff user is rejected.
- **Integration (once REQ-4 exists):** `IsAdmin` and `ReadOnlyUnlessAdmin` per role.
- **Smoke:** every registered `ModelAdmin` loads its changelist without error.

## 16. Observability

- Logs: Django request logs at INFO; `apps` loggers at DEBUG in development, INFO in production
  when `LOG_JSON=true`. No admin-specific logging.
- Metrics: none.
- Errors: Django's own admin error handling; DRF's handler does not apply.
- Audit events: `django.contrib.admin.models.LogEntry` only, unexposed.

## 17. Dependencies

- `django.contrib.admin`, `sessions`, `messages`, `auth` — all installed.
- Whitenoise serves admin static files in production;
  `CompressedManifestStaticFilesStorage` is configured, and `scripts/render-build.sh` runs
  `collectstatic` at build time.

## 18. Open Questions

- **OQ-012-A** — ~~Is Django admin the long-term operations surface?~~ **RESOLVED 2026-08-17:**
  the admin side is deferred as its own piece of work (ADR-017). Django admin remains the
  interim surface.
- **OQ-012-B** — What operator roles exist (support, ops, finance) and what may each see? Today
  there is exactly one tier with full access. *Deferred with ADR-017.*
- **OQ-012-C** — Should support be able to read private conversations, and must that be audited?
  *Deferred with ADR-017; explicitly out of ADR-016's audit scope.*
- **OQ-012-D** — ~~What must be audited?~~ **RESOLVED 2026-08-17:** state changes and failed
  logins; not reads (ADR-016, REQ-7).
- **OQ-012-H** — What is the audit retention policy? Nothing prunes today. Needs deciding before
  the table grows; pruning should itself be an audited management command, not an admin click.
- **OQ-012-E** — Should providers require approval before going live (REQ-6)?
- **OQ-012-F** — Should operators be able to cancel or reassign a job, and should that follow the
  same transition rules as the API?
- **OQ-012-G** — Should service categories be operator-managed at runtime, or remain
  migration-seeded so that routing rules and catalogue stay in step (REQ-3)?

## 19. Implementation Notes

- `IsAdmin` accepts either `is_superuser` **or** `role == admin`, while Django admin accepts only
  `is_staff`. Three different notions of "admin" coexist: `is_staff`, `is_superuser`, and
  `role == admin`. Nothing keeps them consistent — `create_superuser` sets all three, but an
  operator promoting a user in admin can set any subset.
- `ReadOnlyUnlessAdmin` is a ready-made pattern for a future read-mostly admin API; it allows any
  authenticated user to read and restricts writes to admins.
- `ServiceCategoryAdmin` uses `prepopulated_fields = {"slug": ("name",)}`. Since the issue router
  keys its trained ML model by **slug**, editing a category name in admin can change the slug and
  orphan every trained class in `var/issue_router_model.json` (SPEC-006 §19).
- There are no custom management commands beyond Django's built-ins, and no data-repair or
  backfill scripts.

## 20. Verification Evidence

- Files: `apps/*/admin.py` (9 files incl. `apps/core/admin.py`), [apps/core/models.py](apps/core/models.py), [apps/core/audit.py](apps/core/audit.py), [apps/accounts/permissions.py](apps/accounts/permissions.py), [autrifix/urls.py](autrifix/urls.py)
- Tests: `tests/test_audit.py` — 11 tests covering REQ-7. The rest of this spec has none.
- Commands: `pytest -q` → 206 passed; `manage.py makemigrations --check --dry-run` → no changes.
- Migration: `core/0001_initial` (`AuditEvent`) — the first migration in `apps.core`.
- Confirmed by grep: `IsAdmin` and `ReadOnlyUnlessAdmin` still have no importers.
- Confirmed by inspection: no path under `/api/v1/` is admin-gated.
- Review: REQ-7 implemented and self-reviewed 2026-08-17. The remainder of this spec is
  deferred and unimplemented (ADR-017).
