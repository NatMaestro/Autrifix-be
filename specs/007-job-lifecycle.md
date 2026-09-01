# SPEC-007 — Job Lifecycle

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

> **AMENDED by [SPEC-015](015-money-model.md) (ADR-022, 2026-08-18).** The job state machine
> gained `awaiting_confirmation`, and `active → completed` was **removed**. A provider records the
> amount owed and finishes; **only the customer can close the job.** Where this document says a
> provider completes a job, read SPEC-015 §4 instead.

## 1. Summary

A `Job` is created when a provider accepts a service request. It is the operational record that
links a request to a provider, owns the chat room, and carries the timestamps for acceptance and
completion. The provider drives its state; the customer can read it — and, today, also write it
(CONFLICT-007-C).

## 2. Problem

Once a provider has claimed a request, both parties need a shared object that says who is
working on what, what stage it is at, and when it finished.

## 3. Actors

- Service Provider — accepts, starts, completes, or cancels the job.
- Customer — reads the job; has no defined write action (see CONFLICT-007-C).
- Administrator — read/write via Django admin.

## 4. Goals

- Represent an accepted request as a single, auditable work item.
- Record acceptance and completion times.
- Cascade the request's status from the job's outcome.

## 5. Non-Goals

- Rescheduling or reassignment to a different provider.
- Work items, parts, or line-item billing.
- Arrival tracking / ETA.

## 6. Requirements

### REQ-1 — Job entity distinct from the request
**ID:** DOM-007-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`ServiceRequest` and `Job` are separate entities. The request is the customer's ask; the job is the
provider's commitment. `docs/DOMAIN.md` left this open ("Whether `ServiceRequest` and `Job` are
separate entities or one lifecycle entity must follow the existing implementation"); the code
answers: separate.

Evidence: [apps/jobs/models.py:44-113](apps/jobs/models.py#L44-L113)

### REQ-2 — Acceptance creates the job
**ID:** PROD-007-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

`POST /jobs/requests/{request_id}/accept/` by a provider:

1. loads the request with `status=open` (else `404`);
2. creates a `Job` with `status=pending_accept`;
3. creates the `ChatRoom` for that job;
4. sets the request to `matching`;
5. returns `201` with the job.

`PARTIAL` — not atomic and not race-safe. See CONFLICT-007-A.

Evidence: [apps/jobs/views.py:305-322](apps/jobs/views.py#L305-L322)

### REQ-3 — Provider advances the job
**ID:** PROD-007-003 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

A provider may `PATCH /jobs/{id}/` with a new `status`. Three transitions have side effects:

| `status` sent | Side effect |
|---|---|
| `active` | stamps `accepted_at` (only if not already set) |
| `completed` | stamps `completed_at` and sets the request to `completed` |
| `cancelled` | sets the request to `open` if the job was `pending_accept`, else `cancelled` |

`PARTIAL` — there is no transition table; any status may be sent from any state.
See CONFLICT-007-B.

Evidence: [apps/jobs/views.py:170-195](apps/jobs/views.py#L170-L195)

### REQ-4 — Participants see only their own jobs
**ID:** SEC-007-004 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`GET /jobs/` and `GET /jobs/{id}/` filter by role: a customer sees jobs whose request belongs to
them; a provider sees jobs assigned to them. Any other role gets an empty queryset, and a
non-participant id returns `404`.

Evidence: [apps/jobs/views.py:126-168](apps/jobs/views.py#L126-L168)

### REQ-5 — Chat room lifecycle is tied to the job
**ID:** DOM-007-005 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A `ChatRoom` is created at acceptance, one per job, and cascades on job deletion.

Evidence: [apps/jobs/views.py:319](apps/jobs/views.py#L319), [apps/chat/models.py:7-17](apps/chat/models.py#L7-L17)

### REQ-6 — Timestamps are server-controlled
**ID:** SEC-007-006 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`accepted_at` and `completed_at` are read-only on the serializer and stamped server-side.

Evidence: [apps/jobs/serializers.py:158-166](apps/jobs/serializers.py#L158-L166)

### REQ-7 — Customer-initiated cancellation
**ID:** PROD-007-007 · **Priority:** Must · **Provenance:** PROPOSED (accepted 2026-08-17) · **Status:** IMPLEMENTED

A customer may cancel their own job, before or after the provider has started. The job moves to
`cancelled`, the service request moves to `cancelled` (it is not returned to the pool — the
customer no longer wants the work), and the provider is notified.

A customer may also cancel the underlying request directly via
`POST /jobs/requests/{id}/cancel/`, which cancels any live job as a side effect (SPEC-005 REQ-7).

Evidence: [apps/jobs/services.py](apps/jobs/services.py) `JOB_TRANSITIONS` customer rows, `cancel_service_request()`

**ASSUMPTION:** a customer cancelling an `active` job — where the provider may already be on site
— is permitted with no penalty or fee. There is no cancellation-policy concept in the system.
See OQ-007-G.

## 7. User Flow

1. Provider accepts an open request → job `pending_accept`, request `matching`, chat room created.
2. Provider `PATCH {"status": "active"}` → `accepted_at` stamped; request stays `matching`.
3. Both parties chat (SPEC-009).
4. Provider `PATCH {"status": "completed"}` → `completed_at` stamped, request `completed`.
5. Customer may leave a review (SPEC-011).

Alternate: provider `PATCH {"status": "cancelled"}` from `pending_accept` → request returns to
`open`; from `active` → request `cancelled`.

## 8. Business Rules

- A job always has exactly one provider and one service request.
- `accepted_at` is stamped only on the **first** move to `active`; a second one leaves it.
- Completion of the job is what completes the request; there is no separate customer confirmation.
- A cancelled `pending_accept` job is treated as a **decline** and returns the work to the pool;
  a cancelled `active` job is treated as an abandonment and kills the request.
- The cancelled job row itself is retained in both cases, so a request returned to the pool keeps
  a `cancelled` job attached to it.
- Jobs are ordered `-created_at`. There is no index on `Job.provider` or on
  `service_request__customer` beyond the FK indexes.
- Deleting a job cascades to its chat room, messages, reviews, and payment.

## 9. State Model

```text
                 accept
   (request open) ────> pending_accept ──active──> active ──completed──> completed
                              │                       │
                              │ cancelled             │ cancelled
                              ▼                       ▼
                        cancelled                 cancelled
                    (request → open)          (request → cancelled)
```

Intended transitions:

| From | Action | To | Actor | Conditions | Side effects |
|---|---|---|---|---|---|
| — | accept request | `pending_accept` | Provider | request is `open` | job + chat room created; request → `matching` |
| `pending_accept` | start | `active` | Assigned provider | — | `accepted_at = now` |
| `active` | complete | `completed` | Assigned provider | — | `completed_at = now`; request → `completed` |
| `pending_accept` | decline | `cancelled` | Assigned provider | — | request → `open` |
| `active` | abandon | `cancelled` | Assigned provider | — | request → `cancelled` |

**Enforcement:** the table above is now the implementation. It lives as
`JOB_TRANSITIONS` in [apps/jobs/services.py](apps/jobs/services.py); anything not listed returns
`409` with the permitted targets in the detail message. Re-sending the job's current status is an
idempotent no-op (`200`), not a conflict.

### CONFLICT-007-A — Acceptance was neither atomic nor race-safe
**Status:** RESOLVED (2026-08-17) · **Severity was:** High

`JobAcceptView.post` read the request, created the job, then updated the request status — with no
transaction, no locking, and no constraint. Two providers posting concurrently could both create
a job.

**Fix, in three layers:**

1. `accept_service_request()` is wrapped in `@transaction.atomic` and takes
   `SELECT … FOR UPDATE` on the service request before checking its status.
2. A partial unique constraint, `unique_live_job_per_service_request`
   (`UniqueConstraint(fields=["service_request"], condition=~Q(status="cancelled"))`), makes a
   second live job impossible at the database level even if the lock is bypassed.
3. The resulting `IntegrityError` is translated to `409`, so the losing provider gets a
   meaningful response rather than a 500.

Job, chat room, and request-status update now commit or roll back together.

Migration `jobs/0006` cancels pre-existing duplicate live jobs (keeping the earliest) before
applying the constraint, so the migration cannot fail on existing data.

Verified by: `test_second_provider_accepting_gets_409`,
`test_only_one_live_job_per_request_at_database_level`,
`test_declined_request_can_be_accepted_by_another_provider`.

### CONFLICT-007-B — No transition validation
**Status:** RESOLVED (2026-08-17) · **Severity was:** High

Any status was previously accepted from any state, in either direction.

**Fix:** `transition_job()` looks the requested move up in `JOB_TRANSITIONS` keyed by
`(source, target, actor_role)`. A move that is not in the table raises `Conflict` (409). Terminal
states have no outgoing transitions, so a completed or cancelled job cannot regress. Timestamps
are stamped by the transition definition, not by ad-hoc `if` branches.

Verified by: `test_skipping_active_is_409`, `test_completed_job_cannot_regress`,
`test_resending_current_status_is_an_idempotent_noop`,
`test_transition_table_has_no_moves_out_of_terminal_states`.

### CONFLICT-007-C — A customer could write job status and notes
**Status:** RESOLVED (2026-08-17) · **Severity was:** High

**Fix:** the transition table is actor-aware. A customer's only legal move is to `cancelled`
(REQ-7); `active` and `completed` are provider-only and return `409` for a customer. `notes` is
made read-only for customers in `JobSerializer.__init__` based on the request user's role, so a
customer can read the provider's working record but not overwrite it.

Verified by: `test_customer_cannot_complete_a_job`, `test_customer_cannot_start_a_job`,
`test_customer_cannot_edit_notes`, `test_provider_can_edit_notes`.

**OQ-007-A resolved (2026-08-17):** a customer may write **only** a cancellation. Everything else on
the job belongs to the provider.

## 10. API Contract

| Method | Path | Auth | Permission |
|---|---|---|---|
| POST | `/api/v1/jobs/requests/{request_id}/accept/` | JWT | `IsAuthenticated` + `IsProvider` |
| GET | `/api/v1/jobs/` | JWT | `IsAuthenticated` + `IsCustomerOrProvider` |
| GET, PUT, PATCH | `/api/v1/jobs/{id}/` | JWT | `IsAuthenticated` + `IsCustomerOrProvider` |

`POST …/accept/` — no request body. Response `201`:

```json
{ "id": "uuid", "service_request": "uuid", "provider": "uuid",
  "provider_name": "Kofi Auto Works", "customer_name": "Ama K.",
  "service_category_name": "Auto Electrical (Battery / Starter)",
  "status": "pending_accept", "accepted_at": null, "completed_at": null,
  "notes": "", "created_at": "…", "updated_at": "…" }
```

Errors:
- `401` unauthenticated · `403` not a provider
- `404` — request not found **or not open** (the two are indistinguishable to the caller)
- `500` — provider has no profile (SPEC-003 CONFLICT-003-A)
- No `409` is ever returned, including for concurrent acceptance (CONFLICT-007-A)

`PATCH /jobs/{id}/` — writable fields: `status`, `notes`. Read-only: `id`, `service_request`,
`provider`, `accepted_at`, `completed_at`, `created_at`, `updated_at`.

Pagination: `GET /jobs/` uses `PageNumberPagination`, page size 20.
Filtering: none — a customer cannot filter to active jobs; the client filters client-side.

## 11. Data Model

`jobs.Job`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `service_request` | FK → `jobs.ServiceRequest` | CASCADE, `related_name="jobs"` — **not** OneToOne |
| `provider` | FK → `mechanics.ProviderProfile` | CASCADE, `related_name="jobs"` |
| `status` | char(20), indexed | `pending_accept` (default) / `active` / `completed` / `cancelled` |
| `accepted_at` | datetime, null | stamped on first `active` |
| `completed_at` | datetime, null | stamped on first `completed` |
| `notes` | text, blank | writable by both participants |
| `created_at` / `updated_at` | datetime | |

Downstream one-to-ones and reverse FKs: `chat.ChatRoom` (OneToOne, CASCADE),
`payments.Payment` (OneToOne, CASCADE), `reviews.Review` (FK, CASCADE).

Migration: `jobs/0001_initial`.

## 12. Security

- **Authentication:** JWT on every job endpoint.
- **Authorization:** role gate plus participant-scoped querysets. Acceptance is provider-only.
- **Object-level access:** enforced through `get_queryset` on both list and detail — a
  non-participant receives `404`, not `403`, so job existence is not confirmed. This is correct.
- **Sensitive data:** the job payload carries the customer's name-or-phone and the provider's
  business name; both parties are already matched, so disclosure is appropriate here.
- **Abuse/rate limiting:** default `user` scope. Nothing limits how many requests a provider can
  accept or how fast.
- **Auditability:** none. Who changed a job's status, and when, is not recorded; only the two
  stamped timestamps survive, and a customer-written status change leaves no trace at all.

### Observed security gaps

| ID | Finding | Severity |
|---|---|---|
| SECGAP-007-1 | Customer can write job `status` and `notes` (CONFLICT-007-C) | High |
| SECGAP-007-2 | Arbitrary status transitions in both directions (CONFLICT-007-B) | High |
| SECGAP-007-3 | Concurrent acceptance produces duplicate jobs (CONFLICT-007-A) | High |
| SECGAP-007-4 | No audit trail for state changes on a commercial work record | Medium |
| SECGAP-007-5 | A provider can accept unlimited concurrent jobs (SPEC-003 OQ-003-C) | Low |

## 13. Edge Cases

- Accepting an already-accepted request → `404` (it is no longer `open`) — correct behavior,
  but only wins the race by timing, not by locking.
- Accepting a `cancelled` or `completed` request → `404`.
- Provider declines a `pending_accept` job → request returns to `open` with a stale `created_at`,
  so it may already be outside the 30-minute discovery window (SPEC-006 REQ-3) and be
  effectively invisible.
- Repeated `PATCH {"status": "completed"}` → `completed_at` is preserved; the request is
  re-completed on the first call only.
- `PATCH {"status": "active"}` on a `completed` job → allowed; `accepted_at` is already set so it
  is left alone, and the job silently regresses.
- Job whose request was deleted → cascade-deleted along with its chat and reviews.
- Provider deletes their profile / user → all their jobs are cascade-deleted, including
  completed history and the customer's reviews of them. **OPEN QUESTION (OQ-007-D).**
- A customer's job list includes jobs from **all** their requests, including cancelled ones; there
  is no filter.

## 14. Acceptance Criteria

- [x] Accepting an open request creates a job in `pending_accept` and a chat room.
- [x] Accepting a non-open request returns `404`.
- [x] `accepted_at` / `completed_at` are stamped server-side and are read-only.
- [x] Completing a job completes its service request.
- [x] Declining a `pending_accept` job returns the request to `open`.
- [x] Participants see only their own jobs; non-participants get `404`.
- [x] Only the assigned provider may start or complete a job.
- [x] Only valid transitions are accepted; invalid ones return `409`.
- [x] Concurrent acceptance yields exactly one job.
- [x] Acceptance is transactional.
- [x] A customer can cancel (REQ-7).
- [x] A missing provider profile yields `409`, not `500`.
- [x] Both parties are notified of transitions they did not perform.
- [ ] State changes are audited — **NOT_IMPLEMENTED** (blocked on SPEC-012 OQ-012-D).

## 15. Tests

### Existing — `tests/test_job_lifecycle.py` (26 tests)
- **Acceptance:** happy path (job + chat room + request → `matching`); customer `403`; missing
  provider profile `409`; unknown request `404`; non-open request `409`; second provider `409`;
  database-level constraint asserted directly with `pytest.raises(IntegrityError)`.
- **Transitions:** every legal move and its side effect on the request; `pending_accept →
  completed` rejected; completed job cannot regress; same-status PATCH is an idempotent no-op;
  a declined request can be re-accepted by a different provider.
- **Actor gating:** customer cannot start or complete; customer may cancel; customer cannot edit
  `notes`; provider can.
- **Visibility:** non-participant `404`; job list participant-scoped.
- **Table invariants:** no transitions out of terminal states; `allowed_targets` is role-specific.
- **Notifications:** counterparty notified, actor not.

- **True concurrency:** `test_concurrent_acceptance_yields_exactly_one_job` runs two real threads
  through `accept_service_request` against a shared barrier and asserts exactly one `accepted`
  and one `conflict`, one `Job` row, and the request left in `matching`.

  **It skips on SQLite.** `connection.features.has_select_for_update` is `False` there, so Django
  silently drops `SELECT … FOR UPDATE` and the test would exercise only the database constraint.
  CI runs a `[sqlite, postgres]` matrix so the PostgreSQL leg executes it; verified locally
  against PostgreSQL 16 (191 passed, nothing skipped).

  **IMPLEMENTATION NOTE:** this means the default local test run never exercises the locking
  layer — the constraint is what protects the invariant there. That is why
  `test_only_one_live_job_per_service_request` asserts the constraint directly rather than
  relying on the race test.

### Still missing (gap)
- Nothing outstanding for this spec beyond the independent review noted in §20.

## 16. Observability

- Logs: none. No job created / accepted / completed / cancelled log line exists.
- Metrics: none — no acceptance rate, time-to-accept, or completion rate.
- Errors: shared DRF handler.
- Audit events: none.

## 17. Dependencies

- SPEC-005 (requests), SPEC-006 (acceptance entry point), SPEC-009 (chat room created here),
  SPEC-011 (reviews reference the job), payments (`Payment` is a OneToOne on `Job`, unused).

## 18. Open Questions

- **OQ-007-A** — ~~What may a customer write on a job?~~ **RESOLVED 2026-08-17:** cancellation only.
- **OQ-007-G** — Should a customer cancelling an `active` job (provider already on site) incur a
  fee or penalty? Currently free and unlimited; there is no cancellation-policy concept.
- **OQ-007-B** — Should completion require customer confirmation, or is the provider's word final?
- **OQ-007-C** — Should a declined request re-enter the pool with a refreshed `created_at` so it stays discoverable?
- **OQ-007-D** — Should completed jobs survive the deletion of a provider profile? Today CASCADE destroys the history and the customer's reviews.
- **OQ-007-E** — Are the four job states sufficient? `docs/DOMAIN.md` proposes `EN_ROUTE` and `IN_PROGRESS` as distinct stages; `active` currently means both.
- **OQ-007-F** — Should a job be reassignable to another provider instead of cancelled?

## 19. Implementation Notes

- `perform_update` calls `self.get_object()` a second time to read the previous status, after
  DRF has already fetched and bound the instance. It re-queries and re-runs permission checks.
- Each branch of `perform_update` returns early after `serializer.save()`, so the fall-through
  `serializer.save()` at the end is what handles customers, admins, and every non-special status.
- The request-status writes use `save(update_fields=["status", "updated_at"])`, which does update
  `updated_at` explicitly because `auto_now` fields are only refreshed when included in
  `update_fields`.
- `JobSerializer` exposes `service_request` and `provider` as bare UUIDs plus three derived
  display names, so a client needs a second call to get request details (coordinates,
  description, category) for a job.
- `Job.service_request` being a plural FK is the structural enabler of CONFLICT-007-A; making it
  a `OneToOneField` (or adding a partial unique constraint on non-cancelled jobs) would close
  the race at the database level.

## 20. Verification Evidence

- Files: [apps/jobs/services.py](apps/jobs/services.py) (state machine), [apps/jobs/models.py](apps/jobs/models.py) (constraint), [apps/jobs/views.py](apps/jobs/views.py), [apps/jobs/serializers.py](apps/jobs/serializers.py)
- Routes: [autrifix/api_urls.py](autrifix/api_urls.py)
- Tests: `tests/test_job_lifecycle.py` — 26 tests, all passing.
- Commands: `pytest -q` → 169 passed; `manage.py makemigrations --check --dry-run` → no changes;
  `manage.py check` → no issues.
- Migration: `jobs/0006` — adds `unique_live_job_per_service_request`, preceded by a
  `RunPython` that cancels pre-existing duplicate live jobs so the constraint can be applied
  safely.
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
