# SPEC-010 — Notifications

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

> **AMENDED by [SPEC-015](015-money-model.md) (ADR-022, 2026-08-18).** Five kinds added —
> `quote.submitted`, `quote.accepted`, `quote.declined`, `job.awaiting_confirmation` — and
> **`job.completed` changed recipient** from customer to provider, because completion is now the
> customer's own act.

## 1. Summary

Job and request lifecycle events produce `Notification` rows addressed to the counterparty, which
clients read via `GET /notifications/` and receive live over a per-user WebSocket group at
`ws/notifications/`.

**Product decision (2026-08-17):** in-app notifications only. No push (FCM/APNs), no email, no
SMS. Recorded as ADR-012 in `docs/DECISIONS.md`.

## 2. Problem

Before this slice nothing in the codebase created a notification, so neither party was ever told
anything: a customer did not learn that a provider had accepted, started, or completed, and both
sides had to poll (SPEC-006).

## 3. Actors

- Customer — notified of acceptance, start, completion, and provider cancellation.
- Service Provider — notified of customer cancellation and of reviews received. **Not**
  notified of nearby work (ADR-005).
- Administrator — read/write via Django admin.

## 4. Goals

- Inform a user of state changes they care about without polling.
- Keep an in-app history of those events.

## 5. Non-Goals

- Push (FCM/APNs), email, or SMS delivery — none of these exist for notifications. SMS exists
  only for auth OTP (SPEC-001).
- Notification preferences or quiet hours.
- Digesting or grouping.

## 6. Requirements

### REQ-1 — Persist a user-addressed notification
**ID:** DOM-010-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`Notification` stores a `kind`, `title`, `body`, JSON `payload`, and a `read_at` timestamp for a
given user. All rows are created through the single entry point
[apps/notifications/services.py](apps/notifications/services.py) `notify()`.

`kind` is now a `NotificationKind` `TextChoices` enum rather than free text, so it appears as a
typed enum in the OpenAPI document and clients can switch on it safely.

Evidence: [apps/notifications/models.py](apps/notifications/models.py), [apps/notifications/services.py](apps/notifications/services.py)

### REQ-2 — List my notifications
**ID:** API-010-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`GET /notifications/` returns the caller's notifications, newest first, paginated.

Evidence: [apps/notifications/views.py:10-17](apps/notifications/views.py#L10-L17)

### REQ-3 — Mark a notification read
**ID:** API-010-003 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`POST /notifications/{pk}/read/` stamps `read_at` and returns the number of rows updated.

Evidence: [apps/notifications/views.py:27-37](apps/notifications/views.py#L27-L37)

### REQ-4 — Ownership isolation
**ID:** SEC-010-004 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Both endpoints filter on `user=request.user`. Marking another user's notification read is a
no-op returning `{"updated": 0}` rather than an error — which also avoids disclosing existence.

Evidence: [apps/notifications/views.py:17](apps/notifications/views.py#L17), [apps/notifications/views.py:32-36](apps/notifications/views.py#L32-L36)

### REQ-5 — Event producers
**ID:** PROD-010-005 · **Priority:** Must · **Provenance:** PROPOSED (accepted 2026-08-17) · **Status:** IMPLEMENTED

A state change notifies the party who did **not** cause it. The actor is never notified of their
own action.

**Event catalogue** (`NotificationKind`), resolving OQ-010-A:

| `kind` | Trigger | Recipient | `payload` keys |
|---|---|---|---|
| `request.accepted` | provider accepts an open request | customer | `job_id`, `service_request_id` |
| `job.active` | provider starts the job | customer | `job_id`, `service_request_id` |
| `job.completed` | provider completes the job | customer | `job_id`, `service_request_id` |
| `job.cancelled` | either party cancels a job | the **other** party | `job_id`, `service_request_id` |
| `request.cancelled` | customer cancels a request with a live job | assigned provider | `service_request_id` |
| `review.received` | customer submits a review | reviewed provider | `job_id`, `review_id`, `rating` |

`payload` is the correlation contract: `Notification` has no foreign key to its subject, so these
keys are how a client navigates from a notification to the thing it is about.

**Not produced:** new-nearby-work for providers (discovery remains pull-based per ADR-005) and
per-chat-message notifications (chat has its own socket, and without push a row adds nothing).

Evidence: [apps/notifications/services.py](apps/notifications/services.py), called from [apps/jobs/services.py](apps/jobs/services.py) and [apps/reviews/signals.py](apps/reviews/signals.py)

### REQ-6 — Delivery transport
**ID:** PROD-010-006 · **Priority:** Must · **Provenance:** PROPOSED (accepted 2026-08-17) · **Status:** IMPLEMENTED

Two transports, both in-app:

1. **Pull** — `GET /notifications/`, with an `?unread=` filter and a dedicated unread-count
   endpoint for badging.
2. **Live** — `ws/notifications/?token=<jwt>` subscribes the connection to `user_{id}`, a group
   derived from the authenticated user and never from client input.

The broadcast is deferred to `transaction.on_commit`, so a client is never told about a state
change that then rolls back, and a channel-layer failure is caught and logged rather than
failing the domain operation that triggered it.

**Still NOT_IMPLEMENTED:** push (no device-token model), email, and SMS for notifications. SMS
exists only for auth OTP.

## 7. User Flow

1. A provider accepts a customer's request.
2. A `request.accepted` row is created for the customer and pushed to their `user_{id}` group.
3. A connected client renders it immediately; a returning client fetches
   `GET /notifications/?unread=true` or `GET /notifications/unread-count/`.
4. The client calls `POST /notifications/{id}/read/`, which returns the new unread count.

## 8. Business Rules

- Notifications are ordered `-created_at, -id`. The `id` tiebreaker matters: one transition can
  emit several notifications in the same instant, and an unstable sort duplicates or drops rows
  across paginated requests.
- `read_at` is null until marked; marking is idempotent (the filter requires `read_at__isnull=True`).
- All fields are read-only over the API — a notification cannot be created or edited by a client.
- Deleting a user cascades and removes their notifications.
- There is no "mark all read" and no delete. An unread **count** is available.

## 9. State Model

```text
unread (read_at = null) ──POST /{id}/read/──> read (read_at = timestamp)
```

One-way; there is no unread action.

## 10. API Contract

| Method | Path | Auth | Permission |
|---|---|---|---|
| GET | `/api/v1/notifications/` | JWT | `IsAuthenticated` |
| GET | `/api/v1/notifications/unread-count/` | JWT | `IsAuthenticated` |
| POST | `/api/v1/notifications/{pk}/read/` | JWT | `IsAuthenticated` |
| WS | `/ws/notifications/?token=<jwt>` | JWT (query param) | own group only |

`GET /notifications/` → `PageNumberPagination`, page size 20. Optional `?unread=true`.

```json
{ "id": "uuid", "kind": "request.accepted", "title": "A provider accepted your request",
  "body": "…", "payload": {"job_id": "uuid", "service_request_id": "uuid"},
  "read_at": null, "created_at": "…" }
```

`GET /notifications/unread-count/` → `{ "unread_count": 3 }`

`POST /notifications/{pk}/read/` — no body → `{ "updated": 1, "unread_count": 2 }`

WebSocket frame:

```json
{"kind": "notification", "data": { …the element shape above… }}
```

Errors: `401` unauthenticated. Notably **no `404`** — an unknown or foreign `pk` returns
`{"updated": 0}` with `200`, so notification existence is not disclosed.

## 11. Data Model

`notifications.Notification`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `user` | FK → `accounts.User` | CASCADE, `related_name="notifications"` |
| `kind` | char(64), indexed | `NotificationKind` choices; typed enum in the OpenAPI document |
| `title` | char(255), blank | |
| `body` | text, blank | |
| `payload` | JSON | default `{}`; no schema |
| `read_at` | datetime, null | |
| `created_at` | datetime | |

Index: `(user, -created_at)`. Ordering: `-created_at, -id`.
Migrations: `notifications/0001_initial`, `0002` (kind enum, body cap), `0003` (stable ordering).

**IMPLEMENTATION NOTE:** the model has no link to the subject of the notification — no generic
foreign key, no `job_id`/`request_id` column. Any correlation must live inside the unschema'd
`payload`, which nothing writes or reads.

## 12. Security

- **Authentication:** JWT.
- **Authorization:** self-scoped querysets on both endpoints.
- **Object-level access:** enforced by filtering; correct.
- **Sensitive data:** none currently, because no notification exists. Once producers are added,
  `title`/`body`/`payload` will carry job and location context and must not leak counterparty
  detail beyond what the recipient is entitled to see.
- **Abuse/rate limiting:** default `user` scope.
- **Auditability:** none.

### Observed security gaps

| ID | Finding | Severity |
|---|---|---|
| SECGAP-010-1 | `payload` is unschema'd JSON; once producers exist there is no guard against embedding data the recipient should not see | Low (today), Medium (once used) |
| SECGAP-010-2 | `Notification.__str__` renders `self.user.email`, which is `None` for phone-only accounts | Cosmetic |

## 13. Edge Cases

- Marking an already-read notification → `{"updated": 0}`, `200`.
- Marking another user's notification → `{"updated": 0}`, `200` — indistinguishable from the above.
- Malformed UUID in the path → `404` from the URL converter before the view runs.
- Empty list is the only observable state today.

## 14. Acceptance Criteria

- [x] A user can list their own notifications.
- [x] A user can mark their own notification read.
- [x] A user cannot read or mark another user's notification.
- [x] Notifications are not client-creatable.
- [x] Every job and request transition produces a notification for the counterparty.
- [x] A defined, typed event catalogue exists (`NotificationKind`).
- [x] Unread filter and unread count are available.
- [x] A live delivery transport exists (`ws/notifications/`).
- [x] The actor is never notified of their own action.
- [ ] Push delivery (FCM/APNs) — **NOT_IMPLEMENTED** by decision (ADR-012); revisit per OQ-010-C.
- [ ] Retention/pruning policy — **NOT_IMPLEMENTED** (OQ-010-F).

## 15. Tests

### Existing — `tests/test_notifications.py` (13 tests)
- **Production:** `notify()` creates an unread row; group name derives from the user; the
  declared catalogue is asserted exactly, so adding a kind without updating the spec fails.
- **Reading:** `401` unauthenticated; own rows only; `?unread=` filter; unread-count endpoint.
- **Marking read:** stamps `read_at` and returns the new count; second call returns `updated: 0`;
  another user's row is a no-op; unknown id is a no-op.
- **End to end:** accept → active → completed produces exactly the three expected kinds for the
  customer and nothing for the provider.

Additional coverage lives in `tests/test_job_lifecycle.py` (cancellation notifies the
counterparty), `tests/test_service_requests.py` (`request.cancelled`), and
`tests/test_reviews.py` (`review.received`).

### Existing — `tests/test_websockets.py` (4 notification tests)
- An authenticated user connects; anonymous is closed.
- A notification produced for the connected user is delivered over the socket with
  `read_at: null`.
- A notification produced for a **different** user is **not** delivered — the group name is
  derived from the authenticated user, never from client input.

These use `transaction=True`, so the `on_commit` broadcast actually fires (it does not under
pytest-django's default non-committing transaction).

### Still missing (gap)
- Nothing outstanding for this spec beyond push delivery, which is deferred by ADR-012.

## 16. Observability

- Logs: none.
- Metrics: none.
- Errors: shared DRF handler.
- Audit events: none.

## 17. Dependencies

- Would depend on SPEC-007 (job transitions) and SPEC-006 (new nearby work) as event sources.
- Celery and Channels are both already available and unused for this purpose.

## 18. Open Questions

- **OQ-010-A** — ~~What is the event catalogue?~~ **RESOLVED 2026-08-17** — see REQ-5.
- **OQ-010-B** — ~~Who is notified, and is the actor excluded?~~ **RESOLVED 2026-08-17:** the
  counterparty is notified; the actor never is.
- **OQ-010-C** — Is in-app sufficient, or is push required? **Deferred, not closed.** A roadside
  product where the customer is stranded and the provider is driving is a strong argument that push
  is not optional; ADR-012 accepts in-app for now because it needs no new infrastructure.
- **OQ-010-D** — ~~Synchronous or via Celery?~~ **RESOLVED 2026-08-17:** synchronous row creation
  inside the domain transaction, with the socket broadcast deferred to `on_commit`. Celery is not
  used, so no worker needs deploying for this feature.
- **OQ-010-E** — ~~Should `kind` be an enum?~~ **RESOLVED 2026-08-17:** yes, `NotificationKind`.
- **OQ-010-F** — What is the retention policy? Nothing prunes. Still open.
- **OQ-010-G** — Should a new chat message produce a notification? Currently no; it would only
  become useful alongside push.

## 19. Implementation Notes

- `NotificationMarkReadView` subclasses `GenericAPIView` and declares
  `serializer_class = NotificationSerializer`, but never instantiates it; the serializer is
  present only to satisfy schema generation. The response is a hand-built dict.
- The mark-read update uses a queryset `.update()`, so no model signal fires and `read_at` is set
  without loading the row — efficient, but also means any future post-save hook would be skipped.
- The absence of a subject reference on the model is the main obstacle to implementing REQ-5
  cleanly: a client receiving "your job was accepted" has no id to navigate to unless `payload`
  is used, and `payload` has no contract.
- `apps/notifications` has no `tests.py`, no `signals.py`, and no `tasks.py` — there is no
  scaffolding for producers at all.

## 20. Verification Evidence

- Files: [apps/notifications/services.py](apps/notifications/services.py), [apps/notifications/models.py](apps/notifications/models.py), [apps/notifications/consumers.py](apps/notifications/consumers.py), [apps/notifications/views.py](apps/notifications/views.py)
- Routes: [autrifix/api_urls.py](autrifix/api_urls.py), [apps/chat/routing.py](apps/chat/routing.py)
- Tests: `tests/test_notifications.py` — 13 tests, plus assertions in three other modules.
- Commands: `pytest -q` → 169 passed; `manage.py spectacular` → 0 errors, 0 warnings.
- Migrations: `notifications/0002` (kind enum, body cap), `notifications/0003` (stable ordering
  tiebreaker).
- Still dead: [apps/jobs/tasks.py](apps/jobs/tasks.py) `match_service_request_async` remains
  uncalled — notifications are produced synchronously, not via Celery (ADR-012).
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
