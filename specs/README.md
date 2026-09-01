# Backend Specifications

Specifications define intended backend behavior.

**Last synchronized with code:** 2026-08-17, after the first remediation slice
(see `docs/IMPLEMENTATION-LOG.md`).

## Feature map

| Spec | Feature | Spec status | Tests |
|---|---|---|---|
| [001](001-authentication.md) | Authentication & identity | VERIFIED | 19 |
| [002](002-customer-profiles.md) | Customer profiles | VERIFIED | 5 |
| [003](003-provider-profiles.md) | Provider profiles | VERIFIED | 11 |
| [004](004-vehicles.md) | Vehicles | VERIFIED | 11 |
| [005](005-service-requests.md) | Service requests | VERIFIED | 24 |
| [006](006-matching-discovery.md) | Matching / discovery | VERIFIED | 27 + 7 ws |
| [007](007-job-lifecycle.md) | Job lifecycle | VERIFIED | 28 |
| [008](008-location.md) | Location | VERIFIED | shared |
| [009](009-messaging.md) | Messaging | VERIFIED | 16 + 10 ws |
| [010](010-notifications.md) | Notifications | VERIFIED | 13 + 4 ws |
| [011](011-ratings-reviews.md) | Ratings/reviews | VERIFIED | 19 |
| [012](012-administration.md) | Administration | DRAFT (deferred, ADR-017) | 11 (audit only) |
| [013](013-provider-verification.md) | Provider verification | READY | 37 |
| [014](014-provider-types-and-agencies.md) | Provider types & agencies | READY | 40 |
| [015](015-money-model.md) | Money model — quotes & two-sided completion | READY | 40 |
| [016](016-lifecycle-sweeps.md) | Lifecycle sweeps & volume limits | READY | 23 |
| [017](017-agency-api.md) | Agency API | READY | 39 |
| — | Commercial/payment capabilities | Not specified | STUB — not a committed requirement |

Total: **284 tests** (283 + 1 that runs only on PostgreSQL).

`VERIFIED` here means implementation, tests, and spec agree, and a self-review found no
unresolved blocking issue.

Per `CLAUDE.md` §8, independent review is the last Definition-of-Done item: the project owner is
reviewing. See [`docs/REVIEW-GUIDE.md`](../docs/REVIEW-GUIDE.md), which orders the work by
consequence-if-wrong rather than by size.

SPEC-012 is `DRAFT` **by decision** (ADR-017), not by neglect — the admin side is deferred. Its
one implemented part is the audit trail (REQ-7), which the job lifecycle depends on.

## Implementation status vocabulary

Every requirement in these specs carries an implementation classification:

| Status | Meaning |
|---|---|
| `IMPLEMENTED` | Behavior exists in code and matches the requirement as written. |
| `PARTIAL` | Behavior exists but is incomplete, unenforced, or covers only some actors/paths. |
| `STUB` | A model, task, module, or endpoint exists but performs no real work / is never invoked. |
| `NOT_IMPLEMENTED` | No code implements this. |
| `UNKNOWN` | Cannot be determined from the code without a product decision. |
| `CONFLICT` | Implementation contradicts the baseline documentation or another spec. |

## Requirement provenance

Because these specs were reconstructed from an existing codebase, every requirement also
records where it came from. Observed code is **evidence**, not automatically approved product
intent (`docs/DECISIONS.md` ADR-002).

| Provenance | Meaning |
|---|---|
| `PRODUCT` | Stated in `docs/PRODUCT.md` or an accepted decision record. |
| `OBSERVED` | Derived from the current implementation. **Needs product confirmation** before being treated as committed. |
| `PROPOSED` | Written during synchronization to close an obvious gap. Not yet agreed. |

Markers used inline:

- `IMPLEMENTATION NOTE` — observed behavior worth recording, no product claim attached.
- `ASSUMPTION` — a reading of intent that is probably right but unverified.
- `OPEN QUESTION` — product intent cannot be safely inferred; needs a human decision.

## Rule

A spec is not considered complete merely because an endpoint or model exists.

Every feature should describe:

- actors;
- requirements;
- business rules;
- state transitions;
- API contract;
- authorization;
- edge cases;
- acceptance criteria;
- tests;
- verification evidence.
