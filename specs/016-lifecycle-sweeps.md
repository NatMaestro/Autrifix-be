# SPEC-016 — Lifecycle Sweeps and Volume Limits

**Status:** READY
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

Two lifecycle states could be entered and then never left by any user action, and nothing
limited how much work either party could pile up. This closes both.

A periodic sweep auto-confirms jobs the customer never answered and expires requests no
provider ever claimed. Two volume ceilings cap open requests per customer and concurrent
jobs per provider.

## 2. Problem

**Nobody owns stuck state.** A job in `awaiting_confirmation` waits on a customer who has no
incentive to return — the work is done and the amount is already known to them. A request
sitting `open` waits on a provider who may never appear. Neither state has a party motivated
to resolve it, so neither resolves.

The costs compound quietly. A provider with an unconfirmed job cannot be reviewed, cannot
close it out, and sees it occupy their list indefinitely. A customer's request list fills
with work that will never happen, and the platform's own metrics count requests as live that
died hours ago.

**Nothing capped volume.** A retry loop could open a hundred requests. A provider could claim
every request in a city — not necessarily maliciously, just over-eagerly — and deny them to
anyone else, since claiming is first-come-first-served and nothing charged for it
(SEC-GAP-28).

## 3. Requirements

### REQ-1 — Sweeps run from cron, not Celery

`python manage.py sweep_stale_state`, idempotent, safe alongside live traffic, with
`--dry-run` and `--only {jobs,requests}`.

**Rationale.** Celery is configured with exactly one task that is never called, and ADR-012
deliberately keeps it out of the request path. Deploying a worker and a broker to run two
queries an hour is more infrastructure than the problem justifies, and more that can break
silently. A cron'd management command has no daemon to die.

Each row is re-read under `select_for_update` before being changed, so a sweep racing a real
confirmation or acceptance loses gracefully rather than double-writing.

### REQ-2 — A job the customer never confirms is auto-confirmed

After `JOB_AUTO_CONFIRM_AFTER` (default 72 hours from `work_finished_at`), the job moves to
`completed` and the request to `completed`.

**Silence is recorded as silence, not as agreement.** `Job.auto_confirmed` is set, the audit
action is `job.auto_confirmed` (distinct from `job.transitioned`, actor `None`), and the
customer is notified that it happened.

**Rationale.** This is a real transfer of risk onto the customer, so the system should never
be able to present it as something it wasn't. A review or dispute has to be able to
distinguish "the customer agreed to GHS 250" from "the customer stopped replying" — and once
those two are the same database row, the difference is gone for good.

The customer is told *because* they did not act. An amount that became binding by timeout
should not be discovered later.

**Closes SPEC-015 OQ-015-D.**

### REQ-3 — An unclaimed request expires

After `REQUEST_EXPIRES_AFTER` (default 6 hours from `updated_at`), an `open` request moves to
a new terminal state, `expired`, and the customer is notified.

Only `open` requests expire. A `matching` request has a provider actively deciding on it, and
pulling it out from under them mid-decision is worse than leaving it.

**`expired` is a new status, not a reuse of `cancelled`.** Conflating them loses the
difference between "the customer changed their mind" and "the platform found nobody" — which
is precisely the metric that tells you whether supply is adequate.

`updated_at` rather than `created_at`, so a request returned to the pool by a declining
provider gets a fresh clock.

**Closes SPEC-005 OQ-005-C.**

### REQ-4 — A customer's open requests are capped

`MAX_OPEN_REQUESTS_PER_CUSTOMER` (default 3) counts requests in `open` or `matching`. Over
the cap, creation returns `409`. Setting it to `0` disables the limit.

**`assigned` is excluded.** Once a provider is committed the request is no longer competing
for anyone's attention, and counting it would stop a customer whose car is being fixed from
reporting a second, unrelated breakdown.

### REQ-5 — A provider's concurrent jobs are capped

`MAX_CONCURRENT_JOBS_PER_PROVIDER` (default 3) counts jobs in `pending_accept` or `active`.
Over the cap, acceptance returns `409`. Enforced in `accept_service_request`, so it holds for
every caller.

**`awaiting_confirmation` is excluded, and this is the subtle one.** The provider has
finished; they are waiting on somebody else. If finished-but-unconfirmed work occupied a
slot, a single unresponsive customer could idle a provider for the entire confirmation
window — punishing the wrong party for someone else's silence, and turning REQ-2's timeout
into a denial-of-service on the provider's livelihood.

**Closes SEC-GAP-28.**

### REQ-6 — Limits are settings, not constants

All four are environment-tunable. They are abuse ceilings rather than product rules, and the
right values are not knowable before there is traffic.

## 4. Out of scope

- Per-provider or per-agency overrides on the caps.
- A reminder before auto-confirmation (see OQ-016-C).
- Reviving an expired request. The customer creates a new one.
- Pruning old audit rows — still SPEC-012 OQ-012-H.

## 5. Data model

```text
jobs.Job
  + auto_confirmed  bool, default False

jobs.ServiceRequestStatus
  + expired                          (terminal; distinct from `cancelled`)

core.AuditAction
  + job.auto_confirmed               (actor NULL — the platform, not a person)
  + request.expired

notifications.NotificationKind
  + job.auto_confirmed               -> customer
  + request.expired                  -> customer
```

Settings: `JOB_AUTO_CONFIRM_AFTER`, `REQUEST_EXPIRES_AFTER`,
`MAX_OPEN_REQUESTS_PER_CUSTOMER`, `MAX_CONCURRENT_JOBS_PER_PROVIDER`.

## 6. Acceptance criteria

- [x] A stale `awaiting_confirmation` job is confirmed; a fresh one is not
- [x] Auto-confirmation sets `auto_confirmed`, writes an actor-less audit row, and notifies
      both parties; a customer's own confirmation does neither
- [x] Sweeping twice writes one audit row, not two
- [x] `active` and terminal jobs are never swept
- [x] A stale `open` request expires; `matching` and fresh ones do not
- [x] An expired request can be neither accepted (`409`) nor cancelled (`409`)
- [x] `--dry-run` writes nothing; `--only` scopes the sweep
- [x] Both caps return `409` at the limit and `0` disables them
- [x] `assigned` requests and `awaiting_confirmation` jobs do not count against their caps
- [x] Cancelling frees a request slot

Covered by `tests/test_lifecycle_sweeps.py` (23).

## 7. Deployment

The sweep must be scheduled or none of REQ-2/REQ-3 happens. Hourly is ample:

```cron
0 * * * * cd /app && python manage.py sweep_stale_state
```

**This is the one part of the slice that can be silently forgotten.** Everything else fails
loudly; an unscheduled sweep just means the stuck states come back.

## 8. Open questions

**OQ-016-A — Are 72 hours and 6 hours the right windows?**
Both are guesses. 72 hours is generous enough that a distracted customer is not surprised and
short enough that a provider is not held indefinitely. 6 hours assumes roadside urgency — a
booking product would want far longer. Revisit with real timing data.

**OQ-016-B — The expiry window and the feed window disagree.**
A request is *discoverable* for 30 minutes (SPEC-006 REQ-3) but stays `open` for 6 hours. For
5½ of those hours a customer is waiting on a request no provider can still see. Either the
feed window should extend or expiry should shorten; the current pair is not a designed
answer. Tied to SPEC-006 OQ-006-A and to the dispatch decision (OQ-006-C) — if providers were
notified rather than browsing, the feed window would stop mattering.

**OQ-016-C — Should the customer get a reminder before auto-confirmation?**
A single "confirm within 24 hours" nudge would make the timeout considerably fairer, and is
cheap now the sweep exists. Not built because it needs a second timestamp to avoid nagging on
every run.

**OQ-016-D — Is a concurrent-job cap of 3 right for every trade?**
Probably not. A tow operator queuing three pickups is normal; a mechanic on-site with three
open jobs is not doing any of them. The cap is currently trade-blind. It may belong on
`ProviderType`, or on the provider's own profile once there is evidence.

## 9. Related

- SPEC-015 (money model — OQ-015-D is what REQ-2 answers), SPEC-005 (request lifecycle),
  SPEC-007 (job lifecycle), SPEC-006 (the feed window OQ-016-B collides with)
- ADR-012 (Celery stays out of the request path), ADR-016 (audit trail)
- `docs/SECURITY.md` SEC-GAP-28
