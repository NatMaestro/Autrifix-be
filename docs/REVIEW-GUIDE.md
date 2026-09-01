# Review Guide

`CLAUDE.md` §8 asks for a second reviewer before work is considered complete. Everything to date
has been self-reviewed only; **you are the reviewer**. This guide points you at the parts where a
mistake would matter most, so you are not reading 3,000 lines of diff uniformly.

Ordered by consequence-if-wrong, not by size.

---

## 1. The job state machine — `apps/jobs/services.py`

**Why it matters most:** it is the commercial record. A wrong transition or a lost race means a
customer and a provider disagree about what happened, and there is money behind that later.

Read `JOB_TRANSITIONS` first — it is a plain tuple of six rows and it *is* the specification. Ask:

- Are these the six moves you want, and are the actor columns right? In particular: **a customer may
  only ever cancel.** Everything else is provider-only.
- `pending_accept → cancelled` by a **provider** returns the request to `open` (a decline);
  by a **customer** it cancels the request (they changed their mind). Two different outcomes from
  the same target status — is that the behavior you want?
- `active → cancelled` by a customer is allowed with no penalty, even though the provider may
  already be on site. Deliberate, and flagged as OQ-007-G.
- Re-sending the current status is a `200` no-op, not a `409`. Idempotent by choice.

Then check `accept_service_request`: lock → status check → create → chat room → status write, all
inside `@transaction.atomic`. The `IntegrityError` catch is the second line of defence behind
`unique_live_job_per_service_request`.

**Cross-check with:** `tests/test_job_lifecycle.py` — especially
`test_transition_table_has_no_moves_out_of_terminal_states` and `test_allowed_targets_reports_role_specific_moves`,
which assert the table's shape rather than individual endpoints.

## 2. Authorization scoping — `apps/chat/selectors.py`, and every `get_queryset`

**Why it matters:** three of the five original blocking defects were missing object scoping.

`participant_rooms()` is now the single definition of "who is in this conversation", shared by
REST and WebSocket. Verify the `Q(...) | Q(...)` covers exactly the customer of the request and the
assigned provider, and nobody else.

Then skim every `get_queryset` in `apps/*/views.py` and confirm each filters by the caller.
The convention: **a non-owned object returns `404`, never `403`**, so existence is not disclosed.

**Cross-check with:** `tests/test_chat.py` (the four non-participant tests) and
`tests/test_reviews.py` (eligibility).

## 3. Review eligibility — `apps/reviews/serializers.py`

Short file, high blast radius: it decides who can affect a provider's public reputation. Confirm
`validate_job` requires *both* that the author is the job's customer *and* that the job is
`completed`, and that both failures return the same message.

Then `apps/reviews/services.py`: the aggregate is over `Review.objects.filter(job__mechanic_id=…)`.
If ADR-011 ever changes to bidirectional reviews, **this query silently becomes wrong** — it
would start counting a provider's reviews *of customers* toward the provider's own rating.

## 4. The product decisions — `docs/DECISIONS.md` ADR-011 … ADR-018

These encode your answers. If any is not what you meant, the code follows from it:

| ADR | Decision | Undo cost if wrong |
|---|---|---|
| ADR-011 | Reviews: customer → provider, completed only | Medium — needs a subject field on `Review` |
| ADR-012 | In-app notifications only | Low — additive to add push later |
| ADR-013 | `role` fixed at signup | Low — one `read_only_fields` entry |
| ADR-014 | Discovery requires auth | Low, but **breaks any anonymous client** |
| ADR-015 | Provider sees exact customer location before accepting | Low to reverse; **but read the residual-risk note** |
| ADR-016 | Audit state changes, not reads | Low — hooks are one call each |
| ADR-017 | Admin deferred | None |
| ADR-018 | Graded verification; gate precision | Medium — the level is a setting away from stricter or looser |
| ADR-019 | Unverified providers browse but cannot accept | Low to reverse; **but read the cold-start note** |

**ADR-019 is the one to sanity-check operationally.** Gating acceptance on your manual review
makes you the critical path for the whole marketplace: at the default `documents` threshold, no
provider can earn until you approve them. Decide `PROVIDER_MIN_ACCEPT_LEVEL` for launch
deliberately (OQ-013-G) — `phone` avoids a cold start, `documents` is the stricter steady state.

**ADR-015 + ADR-018 are best read together.** ADR-015 accepts a risk (a browsing provider sees
customer locations); ADR-018 bounds it (an *unverified* one sees a ~1 km grid). The question worth
asking is whether the threshold is in the right place: `PROVIDER_EXACT_LOCATION_MIN_LEVEL`
defaults to `documents`, so a provider must pass **your** manual review before seeing exact pins.
If review turnaround is slow, that is friction on the supply side — dropping it to `phone` is a
one-line settings change (SPEC-013 OQ-013-B).

Also worth deciding: **what "good enough" looks like when you review a submission.** You are the
only reviewer, so your bar *is* the policy. It is not written down anywhere yet.

## 4b. Location coarsening — `apps/core/geo.py` + `NearbyOpenRequestsView`

The newest and subtlest logic. `coarsen_coordinate` snaps to a ~1 km grid; the view then derives
**distance from the snapped point** for unverified providers.

That last part is the whole design. If distance were computed from the true point, three queries
from different vantages would recover the true location and the coarsening would be decorative.
`test_trilateration_cannot_recover_the_true_coordinate` is the test to read.

Worth sanity-checking: radius filtering still uses the *true* distance, so an unverified provider
sees the correct set of jobs — only their precision differs. Confirm that is what you want.

## 5. Client-breaking changes — `docs/IMPLEMENTATION-LOG.md`

Three changes break existing clients on purpose:

- `GET /services/nearby/` now requires authentication.
- Illegal job transitions return `409` where they used to return `200`.
- A request being worked on reports `assigned`, not `matching`.

Worth confirming against `autrifix-web` before deploying, since that project was not inspected.

## 6. Migrations — the two that touch data

Seven of nine migrations are field metadata. Two do real work:

- `jobs/0006` cancels pre-existing duplicate live jobs before adding
  `unique_live_job_per_service_request`. **Check the "keep the earliest" rule matches how you'd
  resolve a genuine double-acceptance in production data.**
- `reviews/0003` backfills rating summaries from existing reviews. Reversible.

## 7. What is deliberately *not* done

So you can confirm each was a decision, not a miss:

- Administration — deferred (ADR-017); admin remains the unprotected door.
- A **written standard for approving a verification submission** — the bar is currently whatever
  you decide in the moment (SPEC-013 OQ-013-I).
- Reviewer scaling — designed but not built (SPEC-013 §18b).
- Automated document checks and Ghana Card / NIA verification — Tiers 2–3, modelled but not built.
- Push notifications, dispatch to providers, request expiry, soft delete, media access control.
- Audit retention — nothing prunes.
- The ML routing model still writes to local disk on every request creation (ADR-010, still
  recommended for reversal).

---

## Running it yourself

```bash
pytest -q                                    # 243 passed, 1 skipped (SQLite)
pytest --cov=apps --cov-report=term-missing
python manage.py makemigrations --check --dry-run
python manage.py spectacular --fail-on-warn --file /dev/null
```

To run the concurrency test, which SQLite cannot exercise:

```bash
docker run -d --name pg -e POSTGRES_USER=autrifix -e POSTGRES_PASSWORD=autrifix \
  -e POSTGRES_DB=autrifix -p 55432:5432 postgres:16-alpine
USE_POSTGRES_TESTS=1 DATABASE_URL=postgresql://autrifix:autrifix@127.0.0.1:55432/autrifix pytest -q
```

CI runs both legs automatically.

## If you find something

Record it where it belongs rather than only fixing it: a spec's §12 for an authorization issue,
`DECISIONS.md` for a decision you want changed, `SECURITY.md` for a new finding. The specs are
meant to stay true — that is the whole point of the exercise.
