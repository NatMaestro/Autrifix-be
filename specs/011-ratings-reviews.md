# SPEC-011 — Ratings & Reviews

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

A `Review` records a 1–5 rating and an optional comment about a completed job, written by that
job's customer, one per `(job, author)`. Creating or deleting a review recomputes the provider's
cached `rating_avg` / `rating_count`, which discovery, the presence broadcast, and the matching
score all read.

**Product decision (2026-08-17):** reviews are **one-directional** — the customer reviews the
provider — and only a `completed` job may be reviewed. Recorded as ADR-011 in
`docs/DECISIONS.md`.

## 2. Problem

Customers choosing between providers need a quality signal, and providers need a reputation that
rewards good work. Neither currently functions.

## 3. Actors

- Customer — intended author of a review about a completed job.
- Service Provider — intended subject; currently cannot see reviews at all.
- Administrator — read/write via Django admin.

## 4. Goals (intended)

- One review per job per author.
- A rating summary on the provider profile that discovery can rank by.

## 5. Non-Goals

- Provider-reviews-customer (rejected — see ADR-011).
- Review responses, disputes, or moderation.
- Free-text moderation or profanity filtering.

## 6. Requirements

### REQ-1 — Create a review
**ID:** PROD-011-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** CONFLICT

`POST /reviews/` creates a review with `job`, `rating` (1–5), and optional `comment`. `author` is
set from `request.user`.

**CONFLICT-011-B** — there is no check that the author participated in the job, that the job is
completed, or that the author is a customer. See §12.

Evidence: [apps/reviews/views.py:7-17](apps/reviews/views.py#L7-L17), [apps/reviews/serializers.py:6-11](apps/reviews/serializers.py#L6-L11)

### REQ-2 — List my reviews
**ID:** API-011-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

`GET /reviews/` returns reviews **authored by** the caller.

`PARTIAL` — this is the only read path. A provider calling it sees reviews they *wrote*, not
reviews *about them*. There is no endpoint anywhere that returns the reviews of a provider.

Evidence: [apps/reviews/views.py:11-14](apps/reviews/views.py#L11-L14)

### REQ-3 — One review per job per author
**ID:** DOM-011-003 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** PARTIAL

A `UniqueConstraint` on `(job, author)` prevents duplicates at the database level.

`PARTIAL` — the constraint is real, but a violation surfaces as an unhandled `IntegrityError`
→ `500`, not a `400`/`409`. DRF only auto-translates `unique_together`, not `Meta.constraints`,
into a validator.

Evidence: [apps/reviews/models.py:26-30](apps/reviews/models.py#L26-L30)

### REQ-4 — Rating bounds
**ID:** DOM-011-004 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

`rating` is a positive small integer validated to 1–5. The model validators are surfaced by
`ModelSerializer`, so out-of-range values return `400`.

Evidence: [apps/reviews/models.py:20-22](apps/reviews/models.py#L20-L22)

### REQ-5 — Aggregate into the provider's rating summary
**ID:** DOM-011-005 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** NOT_IMPLEMENTED

`ProviderProfile.rating_avg` and `rating_count` exist and are read in four places, but **no code
ever writes them**. Creating a review has no effect on any provider's rating.

See CONFLICT-011-A.

### REQ-6 — Reviews are visible where a customer chooses
**ID:** PROD-011-006 · **Priority:** Must · **Provenance:** PROPOSED · **Status:** NOT_IMPLEMENTED

Discovery payloads carry `rating_avg` / `rating_count`, so the intent is visible — but the values
are always `0` / `0` (REQ-5), and individual review text is not exposed anywhere.

## 7. User Flow (as built)

1. A job completes.
2. Nothing prompts anyone; no notification exists (SPEC-010).
3. If the client knows to, it posts a review.
4. The review is stored and never affects anything or is seen by anyone but its author.

## 8. Business Rules

- Reviews are ordered `-created_at`.
- `author` is read-only and server-assigned; authorship cannot be forged.
- `comment` may be blank and is unbounded.
- A review is tied to a **job**, not to a provider — so a provider's reputation is reachable only
  by traversing `Review → Job → ProviderProfile`. No index supports that traversal.
- Deleting a job cascades and destroys its reviews. Deleting a provider profile cascades to its
  jobs and therefore to every review about them.
- There is no time window: a review can be written at any point after the job row exists,
  including while it is still `pending_accept`.

## 9. State Model

None. A review is immutable in practice — the endpoint is `ListCreateAPIView`, so there is no
update or delete path over the API. Admin can edit or delete.

## 10. API Contract

| Method | Path | Auth | Permission |
|---|---|---|---|
| GET, POST | `/api/v1/reviews/` | JWT | `IsAuthenticated` |

Request:

```json
{ "job": "uuid", "rating": 5, "comment": "Fast and honest." }
```

Response `201`:

```json
{ "id": "uuid", "job": "uuid", "author": "user-uuid",
  "rating": 5, "comment": "Fast and honest.", "created_at": "…" }
```

Errors:
- `400` — `rating` outside 1–5; missing `job`; unknown `job` id
- `401` — unauthenticated
- `500` — duplicate `(job, author)` (REQ-3)

No `403` is ever returned; there is no authorization beyond authentication.
Pagination: `PageNumberPagination`, page size 20. Filtering: none.

## 11. Data Model

`reviews.Review`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `job` | FK → `jobs.Job` | CASCADE, `related_name="reviews"` |
| `author` | FK → `accounts.User` | CASCADE, `related_name="reviews_written"` |
| `rating` | positive small int | validators 1–5 |
| `comment` | text, blank | unbounded |
| `created_at` | datetime | |

Constraint: `UniqueConstraint(job, author)` named `unique_review_per_job_author`.
Migration: `reviews/0001_initial`.

**IMPLEMENTATION NOTE:** the model does not record *who is being reviewed*. It is inferred to be
the job's provider, but nothing in the schema says so — which is what makes CONFLICT-011-B
possible (a provider can review a job, and the subject would then be themselves).

## 12. Security

- **Authentication:** JWT.
- **Authorization:** none beyond authentication on the write path; self-scoped on the read path.
- **Object-level access:** **absent on create** (CONFLICT-011-B).
- **Sensitive data:** free-text comments about identifiable businesses, with no moderation.
- **Abuse/rate limiting:** default `user` scope. One review per job per author is the only cap;
  since job participation is unchecked, that cap is per-attacker, not per-customer.
- **Auditability:** none.

### CONFLICT-011-A — The rating summary was never computed
**Status:** RESOLVED (2026-08-17) · **Severity was:** High

`ProviderProfile.rating_avg` / `rating_count` are read by:

- [apps/providers/serializers.py:28-33](apps/providers/serializers.py#L28-L33) — the provider's own profile response
- [apps/providers/nearby_presence.py:40-41](apps/providers/nearby_presence.py#L40-L41) — every discovery payload and presence broadcast
- [apps/ai/matching.py:21](apps/ai/matching.py#L21) — 30% of the matching score
- [apps/providers/models.py:32](apps/providers/models.py#L32) — the model's default ordering

and written by **nothing**. Every provider showed `0.00 (0)` forever, the matching score's rating
term was a constant, and the default ordering `-rating_avg` was a silent no-op.

**Fix:** [apps/reviews/services.py](apps/reviews/services.py) `recalculate_provider_rating()`
aggregates `Avg("rating")` and `Count("id")` over `Review.objects.filter(job__mechanic_id=…)`
and writes both fields with a `queryset.update()` — chosen so the write does not re-fire the
`ProviderProfile` `post_save` presence broadcast on every review. It is wired to `post_save` and
`post_delete` on `Review` in [apps/reviews/signals.py](apps/reviews/signals.py), registered from
`ReviewsConfig.ready()`.

Recalculation runs **inline**, not on `transaction.on_commit`, so the cached summary rolls back
with the review if the surrounding transaction fails.

Migration `reviews/0003` backfills the summary for any reviews that predate this.

Verified by: `test_review_updates_provider_rating`, `test_rating_average_across_multiple_jobs`,
`test_deleting_a_review_recalculates`, `test_rating_appears_in_provider_profile_response`.

### CONFLICT-011-B — Anyone could review anything
**Status:** RESOLVED (2026-08-17) · **Severity was:** BLOCKER

`ReviewSerializer` was a bare `ModelSerializer` with `queryset=Job.objects.all()` and only
`IsAuthenticated` on the view, so any authenticated user could review any job in any state —
including a provider reviewing their own job.

**Fix:** `ReviewSerializer.validate_job()` requires that the author is the job's customer and that
the job is `completed`; both failures return the same message, so job existence is not
disclosed. `validate()` rejects a duplicate `(job, author)` with `409` before the database
constraint is reached.

Verified by: `test_unrelated_customer_cannot_review`, `test_provider_cannot_review_their_own_job`,
`test_incomplete_job_cannot_be_reviewed` (parametrized over three non-completed states),
`test_duplicate_review_is_409`, `test_author_cannot_be_forged`.

### Security gaps — current status

| ID | Finding | Severity | Status |
|---|---|---|---|
| SECGAP-011-1 | No participation, role, or job-status check on review creation | Blocker | **RESOLVED** |
| SECGAP-011-2 | Duplicate review returned `500` | Medium | **RESOLVED** — now `409` |
| SECGAP-011-3 | `comment` is unbounded and unmoderated | Low | **PARTIALLY RESOLVED** — capped at 2000 chars; moderation still OPEN (OQ-011-G) |
| SECGAP-011-4 | Reviews are destroyed when a provider profile is deleted | Medium | OPEN — needs a soft-delete or `PROTECT` decision (OQ-011-F) |

## 13. Edge Cases

- Reviewing the same job twice as the same author → `500` (should be `409`).
- Reviewing a job that does not exist → `400` from the related-field lookup.
- `rating: 0` or `rating: 6` → `400`. `rating: -1` → `400` (PositiveSmallIntegerField).
- Reviewing an `active` or `cancelled` job → currently accepted.
- A provider reviewing their own job → currently accepted.
- Job deleted after the review → review cascade-deleted.
- A provider with 50 five-star reviews still displays `0.00 (0)` everywhere (CONFLICT-011-A).

## 14. Acceptance Criteria

- [x] A review stores a 1–5 rating with an optional comment.
- [x] `author` cannot be forged.
- [x] Out-of-range ratings are rejected.
- [x] The database prevents duplicate `(job, author)`.
- [x] Only the job's customer may review it.
- [x] Only a **completed** job may be reviewed.
- [x] The direction is decided and enforced: customer → provider (ADR-011).
- [x] A duplicate review returns `409`, not `500`.
- [x] `rating_avg` / `rating_count` reflect real reviews, and update on delete.
- [x] A provider can see reviews about them (REQ-2).
- [x] The provider is notified when they receive a review.
- [ ] A customer can read a provider's reviews **before** choosing — **NOT_IMPLEMENTED** (REQ-6);
      the aggregate is visible in discovery, individual comments are not. Blocked on OQ-011-E.

## 15. Tests

### Existing — `tests/test_reviews.py` (19 tests)
- **Eligibility:** customer of a completed job succeeds; unrelated customer rejected; provider
  reviewing their own job rejected; each non-completed state rejected; duplicate `409`;
  anonymous `401`; rating bounds parametrized; `author` cannot be forged.
- **Aggregation:** single review sets the average; two jobs average correctly; deleting
  recalculates back to zero; the value surfaces on the provider profile response.
- **Listing:** customer sees reviews they wrote, provider sees reviews about them, unrelated user
  sees none.
- **Notification:** the provider receives a `review.received` notification carrying the rating.

## 16. Observability

- Logs: none.
- Metrics: none — no review volume, no rating distribution.
- Errors: duplicate creation is an unhandled `IntegrityError`, logged as an unexpected 500 by the
  shared handler.
- Audit events: none.

## 17. Dependencies

- SPEC-007 (jobs), SPEC-003 (the rating summary this should feed), SPEC-006 (discovery displays it).

## 18. Open Questions

- **OQ-011-A** — ~~One-directional or bidirectional?~~ **RESOLVED 2026-08-17:** one-directional,
  customer → provider (ADR-011). A bidirectional model would need a subject field on `Review` and a
  rating summary on `CustomerProfile`.
- **OQ-011-B** — ~~Must a job be `completed`?~~ **RESOLVED 2026-08-17:** yes. A job cancelled
  after the provider arrived is explicitly **not** reviewable; if that turns out to matter, it
  needs an "arrived" state first (SPEC-007 OQ-007-E).
- **OQ-011-C** — Is there a review window (e.g. 14 days after completion)?
- **OQ-011-D** — Should `rating_avg` be denormalised on `ProviderProfile` (fast reads, needs
  invalidation) or computed on demand? The field exists, implying denormalisation was intended.
- **OQ-011-E** — Should reviews be publicly readable per provider, and should comments be shown
  or only the aggregate?
- **OQ-011-F** — Should reviews survive provider-profile deletion (SECGAP-011-4)?
- **OQ-011-G** — Is moderation or dispute handling required before reviews are made public?

## 19. Implementation Notes

- `apps/reviews` is the smallest app in the codebase: a 33-line model, an 11-line serializer, and
  a 17-line view, with no signals, no tasks, and no permissions module. It reads as scaffolding
  that was never finished.
- Adding aggregation is a two-line change in principle (`post_save`/`post_delete` on `Review`
  recomputing `Avg("rating")` over `Review.objects.filter(job__provider=…)`), but it must be
  decided against OQ-011-A first — with no subject field, aggregating "reviews about a provider"
  means "reviews on jobs assigned to that provider", which would include a provider's review of
  their own job if CONFLICT-011-B is not fixed first.
- `Review.job` has no index beyond the FK, and the natural aggregation query filters on
  `job__provider`, a two-hop join.

## 20. Verification Evidence

- Files: [apps/reviews/serializers.py](apps/reviews/serializers.py), [apps/reviews/services.py](apps/reviews/services.py), [apps/reviews/signals.py](apps/reviews/signals.py), [apps/reviews/views.py](apps/reviews/views.py), [apps/reviews/apps.py](apps/reviews/apps.py)
- Tests: `tests/test_reviews.py` — 19 tests, all passing.
- Commands: `pytest -q` → 169 passed; `manage.py makemigrations --check --dry-run` → no changes.
- Migrations: `reviews/0002` (comment cap, `job` index), `reviews/0003` (rating backfill,
  reversible).
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
