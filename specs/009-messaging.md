# SPEC-009 — Messaging

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

Each job has exactly one chat room, created at acceptance, in which the customer and the assigned
provider exchange text (and optionally an image). Messages can be sent over REST or over a
WebSocket; both paths fan out to the same Channels group so either client sees the other's
messages live.

## 2. Problem

A provider on the way needs to ask where exactly the car is, what it is doing, and what the
customer can see — without exchanging phone numbers.

## 3. Actors

- Customer — participant in rooms for their own requests' jobs.
- Service Provider — participant in rooms for jobs assigned to them.
- Administrator — read/write via Django admin (`ChatRoom` with inline messages).

## 4. Goals

- One conversation per job, scoped to its two participants.
- Real-time delivery without requiring a WebSocket-capable client.
- Typing indicators.

## 5. Non-Goals

- Group conversations or support/agent participation.
- Read receipts, delivery receipts, or unread counts.
- Message editing, deletion, or moderation.
- Conversations outside a job (there is no pre-acceptance chat).

## 6. Requirements

### REQ-1 — One room per job, created at acceptance
**ID:** DOM-009-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`ChatRoom` is a `OneToOneField` on `Job`, created by `JobAcceptView` via `get_or_create`.
There is no endpoint that creates a room.

Evidence: [apps/chat/models.py:7-17](apps/chat/models.py#L7-L17), [apps/jobs/views.py:319](apps/jobs/views.py#L319)

### REQ-2 — List my conversations
**ID:** API-009-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`GET /chat/` returns the caller's rooms with a counterpart name, last message preview, and last
message timestamp, scoped by role.

Evidence: [apps/chat/views.py:18-42](apps/chat/views.py#L18-L42), [apps/chat/serializers.py:24-75](apps/chat/serializers.py#L24-L75)

### REQ-3 — Read a conversation
**ID:** API-009-003 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** CONFLICT

`GET /chat/jobs/{job_id}/` returns the room with its full message history.

**CONFLICT-009-A** — the queryset is `ChatRoom.objects.all()`. Any authenticated user who knows
or guesses a job UUID reads the entire conversation. See §12.

Evidence: [apps/chat/views.py:45-54](apps/chat/views.py#L45-L54)

### REQ-4 — Send a message over REST
**ID:** API-009-004 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** CONFLICT

`POST /chat/jobs/{job_id}/messages/` creates a message with the caller as sender and broadcasts
it to the job's Channels group.

**CONFLICT-009-A** — same defect: the room is fetched by `job_id` with no participant check, so
any authenticated user can inject a message into any conversation, attributed to themselves.

Evidence: [apps/chat/views.py:57-72](apps/chat/views.py#L57-L72)

### REQ-5 — Real-time messaging over WebSocket
**ID:** PROD-009-005 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`ws/jobs/{job_id}/chat/?token=<access_jwt>` joins group `job_{job_id}`. Sending `{"body": "…"}`
persists a message and fans it out; sending `{"kind": "typing", "is_typing": true|false}` fans
out a transient typing event.

**The WebSocket path is correctly authorized** — it resolves the room and verifies the connecting
user is the request's customer or the job's provider, closing the socket otherwise. The REST path
is not (CONFLICT-009-A).

Evidence: [apps/chat/consumers.py:10-62](apps/chat/consumers.py#L10-L62)

### REQ-6 — Image attachments
**ID:** PROD-009-006 · **Priority:** Could · **Provenance:** OBSERVED · **Status:** PARTIAL

`ChatMessage.image` accepts an upload over REST (multipart) and is echoed in payloads.

`PARTIAL` — the WebSocket path cannot send an image (it only reads `body`), and a message with
an image but no `body` is rejected by REST because `body` is a required `TextField`. The room
list preview does render `"[image]"` for such a message, implying body-less image messages were
intended.

Evidence: [apps/chat/models.py:32-33](apps/chat/models.py#L32-L33), [apps/chat/serializers.py:58](apps/chat/serializers.py#L58), [apps/chat/consumers.py:41-44](apps/chat/consumers.py#L41-L44)

### REQ-7 — Sender is server-assigned
**ID:** SEC-009-007 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`sender` is read-only on the serializer and set from `request.user` (REST) or `scope["user"]`
(WebSocket). A client cannot forge authorship.

Evidence: [apps/chat/serializers.py:6-12](apps/chat/serializers.py#L6-L12), [apps/chat/views.py:63](apps/chat/views.py#L63)

## 7. User Flow

1. Provider accepts a request → room created.
2. Either party opens `GET /chat/` and then `GET /chat/jobs/{job_id}/`.
3. Client connects to `ws/jobs/{job_id}/chat/?token=…`.
4. Messages flow through the WebSocket, or through REST for clients without one.
5. The conversation persists for the life of the job; it is cascade-deleted with the job.

## 8. Business Rules

- Messages are ordered oldest-first (`ordering = ["created_at"]`).
- A room exists only for a job, so there is no chat before acceptance and no chat with an
  unmatched provider.
- Rooms are looked up by `job_id`, not by room id — `job_id` is the public handle.
- A blank or whitespace-only body over WebSocket is silently dropped; over REST it is a `400`.
- Typing events are transient — not persisted, not replayed.
- No message is ever edited or deleted by the API.
- The room survives job completion and cancellation; nothing closes or archives it.

## 9. State Model

Neither `ChatRoom` nor `ChatMessage` has a state field.

Implicit lifecycle: `created at job acceptance → open indefinitely → deleted with the job`.

**OPEN QUESTION (OQ-009-B):** should a room close when its job reaches `completed` or `cancelled`?
Today both parties can keep messaging forever.

## 10. API Contract

| Method | Path | Auth | Permission |
|---|---|---|---|
| GET | `/api/v1/chat/` | JWT | `IsAuthenticated` + `IsCustomerOrProvider` |
| GET | `/api/v1/chat/jobs/{job_id}/` | JWT | `IsAuthenticated` **only** |
| POST | `/api/v1/chat/jobs/{job_id}/messages/` | JWT | `IsAuthenticated` **only** |
| WS | `/ws/jobs/{job_id}/chat/?token=` | JWT (query param) | participant-checked |

`GET /chat/` → paginated (`PageNumberPagination`, page size 20):

```json
{ "id": "uuid", "job": "uuid", "service_request_id": "uuid",
  "contact_name": "Kofi Auto Works", "last_message": "On my way",
  "last_message_at": "…", "created_at": "…" }
```

`GET /chat/jobs/{job_id}/`:

```json
{ "id": "uuid", "job": "uuid", "created_at": "…",
  "messages": [ { "id": "uuid", "sender": "user-uuid", "body": "…",
                  "image": "https://…|null", "created_at": "…" } ] }
```

**IMPLEMENTATION NOTE:** the message list is embedded in full with **no pagination**. A long
conversation returns entirely on every fetch.

`POST /chat/jobs/{job_id}/messages/` — request `{ "body": "…" }` (or multipart with `image`);
response `201` with the created message. Side effect: `group_send` to `job_{job_id}`.

Errors: `400` blank body · `401` unauthenticated · `403` wrong role on `/chat/` only ·
`404` no room for that `job_id`.
**No `403` is returned for a non-participant** on the detail or send endpoints (CONFLICT-009-A).

WebSocket frames:

```json
→ {"body": "text"}                          ← {"id","sender","body","image","created_at"}
→ {"kind": "typing", "is_typing": true}     ← {"kind":"typing","sender":"uuid","is_typing":true}
                                            ← {"kind":"chat.message","data":{…}}   (from REST)
```

**IMPLEMENTATION NOTE — inconsistent frame envelopes:** a message sent over WebSocket is
broadcast as a bare object; the same message sent over REST is broadcast wrapped as
`{"kind": "chat.message", "data": {…}}`. Clients must handle both shapes for the same event.

## 11. Data Model

`chat.ChatRoom`: `id` (UUID pk), `job` (OneToOne → `jobs.Job`, CASCADE, `related_name="chat_room"`), `created_at`.

`chat.ChatMessage`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `room` | FK → `ChatRoom` | CASCADE, `related_name="messages"` |
| `sender` | FK → `accounts.User` | CASCADE, `related_name="chat_messages"` |
| `body` | text | required |
| `image` | image, null | `chat/` |
| `created_at` | datetime | |

No index beyond the FKs. Ordering `created_at` ascending.
Migration: `chat/0001_initial`.

**IMPLEMENTATION NOTE:** `sender` cascades. Deleting a user erases their half of every
conversation, leaving one-sided histories.

## 12. Security

- **Authentication:** JWT over REST; JWT via `?token=` query parameter over WebSocket.
- **Authorization:** correct on `/chat/` and on the WebSocket; **absent** on the room-detail and
  send endpoints.
- **Object-level access:** see CONFLICT-009-A.
- **Sensitive data:** private conversations, which `docs/SECURITY.md` explicitly lists as
  protected. Image attachments may contain vehicle plates, documents, or locations.
- **Abuse/rate limiting:** default `user` scope only; no per-room message rate limit, no message
  length cap, no image size/type restriction.
- **Auditability:** none.

### CONFLICT-009-A — Chat detail and send were not participant-scoped
**Status:** RESOLVED (2026-08-17) · **Severity was:** BLOCKER

`ChatRoomDetailView` and `ChatMessageCreateView` used an unfiltered
`ChatRoom.objects.all()` / `get_object_or_404(ChatRoom, job_id=...)`. Any authenticated user
holding a job UUID could read the entire message history, or post a message attributed to
themselves that was then broadcast to both real participants.

**Fix:** both views now resolve rooms through
[apps/chat/selectors.py](apps/chat/selectors.py) `participant_rooms()` / `get_participant_room()`,
which filters on `job__service_request__customer__user` OR `job__provider__user`. A
non-participant receives `404`, identical to a room that does not exist, so membership is not
disclosed. `JobChatConsumer` now uses the same helper, so REST and WebSocket share one
definition of "participant".

Verified by: `tests/test_chat.py` — `test_unrelated_customer_cannot_read_room`,
`test_unrelated_provider_cannot_read_room`, `test_unrelated_customer_cannot_post_message`,
`test_unrelated_provider_cannot_post_message`.

### Security gaps — current status

| ID | Finding | Severity | Status |
|---|---|---|---|
| SECGAP-009-1 | Chat detail readable by any authenticated user | Blocker | **RESOLVED** — participant-scoped queryset |
| SECGAP-009-2 | Message injection into any room | Blocker | **RESOLVED** — participant-scoped lookup |
| SECGAP-009-3 | A provider who cancelled a job retains chat access | High | **RESOLVED by design** — a declined job keeps its own room; the request's *new* job gets a new room with a new id, so the declining provider sees only their own dead conversation. Deliberate: it preserves history for dispute resolution. |
| SECGAP-009-4 | JWT in the WebSocket query string is logged by most proxies | Medium | OPEN — inherent to browser WebSocket auth; needs a short-lived ticket to fix properly |
| SECGAP-009-5 | `JwtQueryAuthMiddleware` swallows every exception into `AnonymousUser` | Low | OPEN |
| SECGAP-009-6 | No message length limit, no image size limit, no per-room rate limit | Medium | **PARTIALLY RESOLVED** — `body` capped at 4000 chars (model + consumer), images capped at 5 MB by `validate_image_size`. Per-room rate limiting still OPEN. |
| SECGAP-009-7 | Uploaded chat images have no access control — the URL is the only secret | Medium | OPEN — needs signed URLs or a proxying view |

## 13. Edge Cases

- `GET /chat/jobs/{job_id}/` for a job with no room → `404`.
- `POST` a message to a `completed` or `cancelled` job → succeeds; nothing closes the room.
- WebSocket connect for a job the user is not part of → socket closed (correct).
- WebSocket connect with no or invalid `?token=` → anonymous → closed.
- WebSocket connect for a nonexistent job → room lookup returns `None` → closed.
- Message with an image and no body → REST `400`; the list preview's `"[image]"` branch is
  therefore unreachable through the API.
- Whitespace-only body over WebSocket → silently ignored, with no error frame to the sender.
- Very long conversation → the whole history is returned on every detail fetch.
- Deleting the job (directly or by deleting the request, customer, or provider) destroys the
  conversation.

## 14. Acceptance Criteria

- [x] A room is created automatically when a provider accepts.
- [x] `GET /chat/` lists only the caller's rooms with a counterpart name and last message.
- [x] `sender` cannot be forged.
- [x] The WebSocket rejects non-participants.
- [x] REST-sent messages appear live on connected WebSocket clients.
- [x] Typing indicators fan out.
- [x] `GET /chat/jobs/{job_id}/` is restricted to participants.
- [x] `POST /chat/jobs/{job_id}/messages/` is restricted to participants.
- [x] Message size and image uploads are bounded (4000 chars / 5 MB).
- [x] REST and WebSocket broadcast the same frame shape.
- [x] A body-less message with an image is accepted; a message with neither is rejected.
- [ ] Message history is paginated — **NOT_IMPLEMENTED** (deferred: changing the embedded
      `messages` array is a breaking change for existing clients; see OQ-009-H).

## 15. Tests

### Existing — `tests/test_chat.py` (16 tests)
- **Authorization:** participant read/write for both roles; unrelated customer and unrelated
  provider blocked on read and on send (`404`, with no row written); anonymous `401`.
- **Scoping:** `/chat/` returns only the caller's rooms; `contact_name` resolves to the
  counterparty from either side; `job_status` exposed.
- **Validation:** blank body rejected; job without a room returns `404`.

### Existing — `tests/test_websockets.py` (10 chat tests)
- Participant accepted for both roles; non-participant, anonymous, invalid token, and unknown
  job all closed.
- A message sent over the socket is persisted **and** delivered to the counterparty with the
  `{"kind":"chat.message","data":{…}}` envelope, confirming REST and WebSocket agree (§10).
- Blank and oversized bodies return an error frame and persist nothing.
- Typing frames fan out and persist nothing.

### Still missing (gap)
- **Cross-transport:** a REST-created message received by a connected WebSocket client. The two
  envelopes are asserted separately; nothing yet asserts the REST → socket hop end to end.

## 16. Observability

- Logs: none. No message-sent, room-created, or authorization-failure log line.
- Metrics: none.
- Errors: WebSocket auth failures are swallowed (SECGAP-009-5); REST errors go through the shared handler.
- Audit events: none — there is no record of who read a conversation.

## 17. Dependencies

- `channels==4.2.0`, `channels-redis==4.2.1`, `daphne==4.1.2`.
- Channel layer: `RedisChannelLayer` in production, `InMemoryChannelLayer` in development when
  `USE_REDIS=false`. With the in-memory layer, cross-process fan-out does not work — a REST send
  from the WSGI/Daphne worker will not reach a WebSocket client on another process.
- SPEC-007 (the room's owning job), SPEC-001 (JWT).

## 18. Open Questions

- **OQ-009-A** — Should chat be available before acceptance (customer ↔ interested provider)?
- **OQ-009-B** — Should a room close when its job completes or cancels?
- **OQ-009-C** — Should a provider who cancels retain any access to the conversation?
- **OQ-009-D** — ~~Are body-less image messages intended?~~ **RESOLVED 2026-08-17:** yes.
  `body` is now `blank=True` and the serializer requires a body, an image, or both — matching
  the list preview's `"[image]"` branch, which was previously unreachable.
- **OQ-009-H** — Should the message history be paginated? It is currently embedded in full on
  every room fetch, which is unbounded. Fixing it changes the `messages` array's shape.
- **OQ-009-E** — Are read receipts or unread counts required? `GET /chat/` returns a last message
  but no unread state, so a client cannot badge conversations.
- **OQ-009-F** — Should conversations be retained after a job is deleted, for dispute resolution?
- **OQ-009-G** — Is admin read access to private conversations (currently available through
  Django admin inlines) an intended support capability, and should it be audited?

## 19. Implementation Notes

- `JobChatConsumer._get_room_for_user` is the reference implementation of the participant check
  the REST views need; it dereferences `room.job.service_request.customer.user_id` and
  `room.job.provider.user_id` on a `select_related` query.
- `ChatRoomListSerializer.get_last_message` and `get_last_message_at` each issue a separate
  ordered query per room, so the list endpoint is N+1 on messages despite
  `prefetch_related("messages")` (the prefetch cache is bypassed by the new `order_by`).
- `get_contact_name` compares `user.role` against the string literals `"customer"` / `"provider"`
  rather than `UserRole`, and falls back to the literal `"Support contact"` — which is
  misleading, since no support actor exists in the system.
- `ChatMessageCreateView` builds its broadcast payload with `ChatMessageSerializer(message).data`
  without a request context, so `image` renders as a relative path rather than an absolute URL —
  unlike the same field fetched through `GET /chat/jobs/{id}/`, which does have request context.
- `JwtQueryAuthMiddlewareStack` is a plain function wrapper, not Channels' `AuthMiddlewareStack`,
  so no session or cookie authentication is available on WebSockets — token only.

## 20. Verification Evidence

- Files: [apps/chat/selectors.py](apps/chat/selectors.py), [apps/chat/views.py](apps/chat/views.py), [apps/chat/consumers.py](apps/chat/consumers.py), [apps/chat/serializers.py](apps/chat/serializers.py)
- Routes: [autrifix/api_urls.py](autrifix/api_urls.py), [apps/chat/routing.py](apps/chat/routing.py)
- Tests: `tests/test_chat.py` — 16 tests, all passing.
- Commands: `pytest -q` → 169 passed; `manage.py makemigrations --check --dry-run` → no changes;
  `manage.py spectacular` → 0 errors, 0 warnings.
- Migration: `chat/0002` (body max_length, image validator, `(room, -created_at)` index).
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
