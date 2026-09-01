# SPEC-013 — Provider Verification

**Status:** READY
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

A graded verification level on `ProviderProfile` that controls **how precisely a provider sees
customer locations** and **whether they may accept work**, and gives customers a trust signal.

An unverified provider can sign up, go online, and browse — at coarsened precision — but cannot
accept a job. Seeing the work they are missing is the intended nudge toward completing
verification, and it means nobody unverified ever attends a customer.

This spec exists because of ADR-015. That decision accepted that a browsing provider sees
customers' exact locations, on the assumption that an online provider is a plausible service
provider — an assumption nothing enforced. This is the enforcement.

## 2. Problem

Anyone can register with `role=provider`, go online, and read every open request within their
radius: exact coordinate, problem description, vehicle, and customer display name. There is no
check that they are a real provider, a real person, or acting in good faith.

Three distinct threats, which need different controls:

| Threat | Control |
|---|---|
| **Harvesting** — scraping customer locations and demand patterns | Coarsened location for untrusted accounts + signup friction + behavioural detection |
| **Targeting** — locating a specific person | The same, plus identity accountability at higher levels |
| **Harm at the job** | Identity accountability, traceability, and a badge the customer can act on |

**IMPLEMENTATION NOTE:** identity verification buys *accountability and deterrence*, not safety.
Knowing a provider's Ghana Card number does not make them safe; it makes them traceable. The
levels below should be read as deterrence tiers, not as screening.

## 3. Actors

- Service Provider — browses immediately, submits a verification request, sees their
  own status and what it unlocks.
- Administrator — reviews submissions and grants or refuses a level. **The project owner is the
  reviewer** (decision, 2026-08-17).
- Customer — sees a provider's verification level as a badge, and may cancel freely.

## 4. Goals

- Remove the standing ability of any new account to harvest exact customer locations.
- Keep supply-side *onboarding* fast — signing up, going online, and browsing need no review —
  while making verification a precondition for earning.
- Make the value of verification visible: a provider should be able to see the work they are
  missing.
- Give customers a signal they can act on.
- Leave a clean upgrade path to automated document checks and Ghana Card verification without a
  schema change.

## 5. Non-Goals

- Vetting competence, qualifications, or workmanship.
- Insurance, bonding, or background checks (a possible Tier 4, out of scope).
- Verifying customers.
- Automated document/liveness checks or NIA integration in this slice — the model accommodates
  them; the integrations are future work.

## 6. Requirements

### REQ-1 — Verification is a level, not a flag
**ID:** DOM-013-001 · **Priority:** Must · **Provenance:** PRODUCT (decision 2026-08-17) · **Status:** IMPLEMENTED

`ProviderProfile.verification_level` is an ordered value:

| Level | Meaning | How it is reached |
|---|---|---|
| `none` | Nothing verified | Default on profile creation |
| `phone` | Phone number verified by OTP **and** profile complete | Self-service, automatic |
| `documents` | ID and selfie reviewed and approved by a human | Manual review |
| `ghana_card` | Identity confirmed against the national register | Future — reserved |

Ordering is defined once in `apps.providers.verification.VERIFICATION_LEVEL_ORDER`; comparisons
go through `level_at_least()`. A level is never inferred from a boolean.

### REQ-2 — Untrusted providers see coarsened customer locations
**ID:** SEC-013-002 · **Priority:** Must · **Provenance:** PRODUCT · **Status:** IMPLEMENTED

In `GET /jobs/requests/nearby/`, a provider below `PROVIDER_EXACT_LOCATION_MIN_LEVEL`
(default `documents`) receives each request's coordinate **snapped to a ~1 km grid**.

**The distance is computed from the snapped coordinate, not the true one.** This matters: a
provider controls the `lat`/`lng` they search from, so an exact distance returned alongside a
coarsened point would allow the true point to be recovered by trilateration from three queries.
Coarsening once and deriving everything from the coarsened value closes that.

A provider at or above the threshold sees exact coordinates.

Everyone sees the exact coordinate **after accepting** — navigation needs it, and acceptance
creates an audited `Job` row tied to their identity.

Evidence: [apps/core/geo.py](apps/core/geo.py) `coarsen_coordinate`, [apps/jobs/views.py](apps/jobs/views.py) `NearbyOpenRequestsView`

### REQ-3 — Browse freely; accept only when verified
**ID:** PROD-013-003 · **Priority:** Must · **Provenance:** PRODUCT (decision 2026-08-18, revising 2026-08-17) · **Status:** IMPLEMENTED

An unverified provider may go online and **browse** nearby requests, at coarsened precision
(REQ-2). They may **not accept** one until they reach `PROVIDER_MIN_ACCEPT_LEVEL`
(default `documents`).

Attempting to accept returns `403` with a payload naming the current level, the required level,
and where to go next — so the client can render an upsell rather than a dead end.

**Rationale (product):** letting a provider see the work they cannot yet take is the conversion
lever. An empty, gated app gives them nothing to want; a visible queue of nearby jobs gives them
a reason to finish verification.

**Security consequence:** this closes the accept-then-cancel harvesting path that REQ-2 alone
left open, and guarantees that **nobody unverified ever attends a customer.** Together, REQ-2
(coarsened browsing) and REQ-3 (gated accepting) cover both halves of the exposure ADR-015
accepted.

**Enforced in the service layer** (`accept_service_request`), not the view, so the gate holds for
every caller — admin actions and any future background dispatch included.

An existing job is unaffected by later demotion: the gate gates *new* accepts, not work in hand.

Evidence: [apps/jobs/services.py](apps/jobs/services.py), [apps/providers/verification.py](apps/providers/verification.py) `can_accept_jobs`

**RISK — cold start.** At launch nobody is verified, so nobody can accept, so customers get no
service. Review turnaround becomes the critical path for the entire marketplace, and with a
single reviewer that is a hard dependency on one person's availability. `PROVIDER_MIN_ACCEPT_LEVEL`
is a setting precisely so it can be run at `phone` (self-service, instant) during launch and
raised to `documents` once a provider base exists. See OQ-013-G.

### REQ-4 — Customers see the badge
**ID:** PROD-013-004 · **Priority:** Must · **Provenance:** PRODUCT (decision 2026-08-17) · **Status:** IMPLEMENTED

`verification_level` is exposed on the provider in job payloads and in nearby-provider discovery,
so a customer can see who they are dealing with. Combined with the existing customer cancellation
(SPEC-007 REQ-7), a customer who is not comfortable can cancel at no cost.

### REQ-5 — Self-service phone verification
**ID:** PROD-013-005 · **Priority:** Must · **Provenance:** OBSERVED + PROPOSED · **Status:** IMPLEMENTED

Registration collects a phone number but never verifies it. An authenticated user may now verify
theirs: request a code with the existing `POST /auth/send-otp/`, then confirm with
`POST /me/verify-phone/`. Success sets `User.is_phone_verified`.

Reaching `phone` level additionally requires a complete profile (REQ-6). The check runs on
demand, so a provider reaches `phone` as soon as both conditions hold.

**Ghana-specific note:** SIM registration in Ghana is linked to the Ghana Card, so a verified
phone number carries more identity weight here than it would elsewhere. It is an *indirect*
link, not proof, and the current enforcement regime should be confirmed rather than assumed.

### REQ-6 — Profile completeness gate
**ID:** DOM-013-006 · **Priority:** Must · **Provenance:** PROPOSED · **Status:** IMPLEMENTED

A profile is complete when it has a `business_name`, both base coordinates, and at least one
active service offering. Incomplete profiles cannot reach `phone` level.

This also finally gives `ProviderServiceOffering` a purpose: ADR-009 removed its influence over
discovery, leaving it inert.

### REQ-7 — Manual document review
**ID:** PROD-013-007 · **Priority:** Must · **Provenance:** PRODUCT (decision 2026-08-17) · **Status:** IMPLEMENTED

A provider submits an ID document, a selfie, and a workshop photo. The reviewer approves or
rejects in Django admin. Approval raises the level to `documents`; rejection records a reason and
leaves the level unchanged.

At most one `pending` submission per provider, enforced by a partial unique constraint.

### REQ-8 — Submitted documents are not retained
**ID:** SEC-013-008 · **Priority:** Must · **Provenance:** PROPOSED · **Status:** IMPLEMENTED

Uploaded images are deleted when the submission is decided, whether approved or rejected. Only
the outcome, the reviewer, the timestamp, and the notes persist.

Manual review requires a human to *see* the document, so storage is unavoidable — but it is
transient by design. A permanent store of Ghana Card images is a breach liability out of all
proportion to its value.

**Ghana's Data Protection Act, 2012 (Act 843)** imposes obligations on data controllers, and
handling national ID data raises the stakes. Confirm the current registration requirements with
the Data Protection Commission before enabling any higher tier.

### REQ-9 — Verification events are audited
**ID:** SEC-013-009 · **Priority:** Must · **Provenance:** PRODUCT (ADR-016) · **Status:** IMPLEMENTED

Submission and review decisions write `AuditEvent` rows: who submitted, who decided, what the
outcome was, and which level was granted.

## 7. User Flow

**Provider:** sign up → complete profile → go online → **browse nearby requests at coarsened
precision, but every accept returns 403 with what is needed** → verify phone → submit documents →
wait → approved → exact locations unlock, accepting unlocks, badge shows on jobs.

**Reviewer:** open Django admin → `Provider verifications` filtered to `pending` → inspect the
three images → approve or reject with a note → images are purged, level applied, event audited.

**Customer:** sees the provider's badge on the job; may cancel if not comfortable.

## 8. Business Rules

- Levels only move up through review; a rejection never lowers an existing level.
- `phone` is granted automatically and re-evaluated on demand — losing completeness (e.g.
  deactivating the last offering) can drop a provider back to `none`.
- `documents` and above are granted only by a reviewer and are not re-evaluated automatically.
- Two independent thresholds, both settings: `PROVIDER_EXACT_LOCATION_MIN_LEVEL` (see exact
  coordinates) and `PROVIDER_MIN_ACCEPT_LEVEL` (accept work). Both default to `documents`.
- Browsing is never gated by verification level, only coarsened.
- The accept gate applies at the moment of acceptance. Demotion afterwards does not disturb an
  existing job.
- A provider always sees the exact coordinate for a job they have accepted.

## 9. State Model

```text
                    submit
none ──(phone verified + profile complete)──> phone ──────────> pending review
                                                                  │
                                              approved ───────────┼──> documents
                                              rejected  ──────────┘   (level unchanged)
```

Submission states: `pending → approved | rejected`. Terminal on decision; a provider may submit
again after a rejection.

## 10. API Contract

| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/v1/me/verify-phone/` | Any authenticated | `{"code": "123456"}` — code from `POST /auth/send-otp/` |
| GET | `/api/v1/providers/verification/` | Provider | current level, entitlements, completeness, latest submission |
| POST | `/api/v1/providers/verification/` | Provider | multipart: `id_document`, `selfie`, `workshop_photo` |
| POST | `/api/v1/jobs/requests/{id}/accept/` | Provider | `403 verification_required` below the accept threshold |

`403` from acceptance:

```json
{
  "detail": "Your account must be verified to accept jobs.",
  "code": "verification_required",
  "current_level": "phone",
  "required_level": "documents",
  "verification_url": "/api/v1/providers/verification/"
}
```

`GET /providers/verification/`:

```json
{
  "verification_level": "phone",
  "exact_location_unlocked": false,
  "can_accept_jobs": false,
  "accept_requires_level": "documents",
  "profile_complete": true,
  "phone_verified": true,
  "missing_requirements": [],
  "submission": {
    "id": "uuid", "status": "pending", "requested_level": "documents",
    "submitted_at": "…", "reviewed_at": null, "review_notes": ""
  }
}
```

Errors: `400` validation (missing images, oversized upload) · `401` · `403` non-provider ·
`409` a submission is already pending, or the phone code is wrong/expired.

## 11. Data Model

`providers.ProviderProfile.verification_level` — char(20), indexed, default `none`.

`providers.ProviderVerification`

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | |
| `provider` | FK → `ProviderProfile` | CASCADE, `related_name="verifications"` |
| `requested_level` | char(20) | `documents` for now |
| `status` | char(20), indexed | `pending` / `approved` / `rejected` |
| `id_document`, `selfie`, `workshop_photo` | image, null | **purged on decision** (REQ-8) |
| `ghana_card_number` | char(32), blank | reserved for the future tier; unused |
| `submitted_at` | datetime | |
| `reviewed_at` | datetime, null | |
| `reviewed_by` | FK → User, SET_NULL | survives reviewer deletion |
| `review_notes` | text, blank | |

Constraint: `unique_pending_verification_per_provider` — partial unique on `provider` where
`status = pending`.

`accounts.User.is_phone_verified` — bool, default false.

## 12. Security

- **Authentication:** JWT throughout.
- **Authorization:** `IsProvider` plus self-scoping; a provider sees only their own submissions.
  Review is staff-only, via Django admin.
- **Object-level access:** submissions are resolved from `request.user`, never by id.
- **Sensitive data:** identity documents. Transient by design (REQ-8), and never exposed over the
  API — the serializer returns status only, never image URLs.
- **Abuse:** one pending submission at a time; uploads capped at 5 MB by the shared validator.
- **Auditability:** REQ-9.

### Residual risks — accepted, and worth restating

| Risk | Mitigation | Status |
|---|---|---|
| An unverified provider accepts a job purely to reveal the exact location, then cancels | Unverified providers cannot accept at all (REQ-3) | **CLOSED** — this was OQ-013-A, resolved by the 2026-08-18 decision |
| A *verified* provider does the same | Audited (ADR-016); accept-to-completion ratio makes it visible; identity is known and reviewed | Accepted — the point of verification is that this is attributable |
| Cold start: no verified providers means no accepted jobs | `PROVIDER_MIN_ACCEPT_LEVEL` can run at `phone` during launch | **Open operational risk** (OQ-013-G) |
| Approved provider later acts badly | Level can be revoked in admin | Accepted |
| Coarsening reduces the usefulness of the feed for genuine new providers | Distance stays accurate to the grid; the threshold is configurable | Accepted |
| Document review is only as good as the reviewer | Single named reviewer, audited decisions | Accepted |

## 13. Edge Cases

- Provider verifies phone but has no offerings → stays `none`; `missing_requirements` says why.
- Provider reaches `phone`, then deactivates their last offering → drops to `none` on next
  evaluation. Deliberate: the gate reflects current state.
- Second submission while one is pending → `409`.
- Rejected provider resubmits → allowed; a new row, previous images already purged.
- Approved provider's images are already gone if a dispute arises later → only notes remain.
  Deliberate (REQ-8).
- A provider at `documents` who is demoted in admin immediately loses exact locations.
- A job already accepted keeps its exact location regardless of level.

## 14. Acceptance Criteria

- [x] Verification is an ordered level, compared through one helper.
- [x] An unverified provider sees grid-snapped coordinates in the feed.
- [x] The returned distance is derived from the snapped coordinate, so trilateration cannot
      recover the true point.
- [x] A verified provider sees exact coordinates.
- [x] Any provider sees the exact coordinate for a job they have accepted.
- [x] Verification does not prevent going online or browsing.
- [x] An unverified provider cannot accept, and the `403` names the level required.
- [x] A refused acceptance creates no job and leaves the request `open`.
- [x] The accept threshold is configurable, and `phone` alone does not unlock it by default.
- [x] Demotion does not disturb a job already in hand.
- [x] Customers see the provider's level on jobs and in discovery.
- [x] Phone verification is self-service and sets `is_phone_verified`.
- [x] `phone` level requires phone verification **and** a complete profile.
- [x] One pending submission per provider, enforced in the database.
- [x] Images are purged on decision.
- [x] Submission and review are audited.
- [ ] Automated document/liveness checks — **NOT_IMPLEMENTED** (future Tier 2).
- [ ] Ghana Card verification against NIA — **NOT_IMPLEMENTED** (future Tier 3).
- [ ] `PROVIDER_MIN_ACCEPT_LEVEL` chosen deliberately for launch — **blocked on OQ-013-G**.

## 15. Tests

`tests/test_verification.py`:

- **Levels:** ordering helper; default `none`; `phone` granted only with both phone verification
  and completeness; loss of completeness demotes.
- **Disclosure:** unverified provider receives snapped coordinates and a distance consistent with
  them; **trilateration test** — three queries from different points must not recover the true
  coordinate; verified provider receives exact coordinates; the accepted job exposes the exact
  coordinate regardless of level.
- **Participation:** an unverified provider can go online and browse, but acceptance returns
  `403` with the required level; a refused accept creates no job and leaves the request `open`;
  the threshold is configurable; approval unlocks acceptance end to end.
- **Badge:** level appears in job payloads and nearby-provider discovery.
- **Submission:** happy path; duplicate pending → `409`; non-provider → `403`; images not exposed
  over the API.
- **Review:** approval raises the level and purges images; rejection leaves the level and purges
  images; both are audited.
- **Phone:** correct code verifies; wrong/expired code → `409`.

## 16. Observability

- Logs: verification submitted, approved, rejected.
- Audit: `provider.verification_submitted`, `provider.verification_reviewed` (REQ-9).
- Metrics: none yet. Worth adding: submissions pending, median time-to-decision, approval rate —
  a queue nobody watches is a queue that stalls.

## 17. Dependencies

- SPEC-003 (provider profiles), SPEC-006/008 (the feed and disclosure), SPEC-012 REQ-7 (audit).
- Existing `PhoneOTP` infrastructure (SPEC-001 REQ-4) — reused rather than rebuilt.
- Future: a KYC provider for Tier 2/3. Candidates to evaluate for Ghana include Smile ID
  (which acquired the Ghana-focused Appruve), Dojah, Prembly, Youverify, and VerifyMe. **Pricing,
  coverage, and NIA accreditation status are unverified here and must be confirmed directly.**

## 18. Open Questions

- **OQ-013-A** — ~~Should unverified providers have a daily accept cap?~~ **RESOLVED 2026-08-18:**
  moot — they cannot accept at all (REQ-3).
- **OQ-013-G** — What is `PROVIDER_MIN_ACCEPT_LEVEL` set to *at launch*? `documents` is the
  intended steady state, but it makes review turnaround the critical path for the whole
  marketplace on day one. Running at `phone` initially and raising it once a provider base exists
  avoids a cold start; the trade is that early providers are only phone-verified.
- **OQ-013-H** — How does review scale beyond one reviewer? Needs: multiple reviewer accounts,
  queue assignment or claiming to avoid double review, per-reviewer audit attribution (already
  captured via `reviewed_by`), turnaround measurement, and an escalation path for disputed
  rejections. Deferred with the admin surface (ADR-017), but the data model already supports
  attributing decisions to distinct reviewers.
- **OQ-013-B** — Should the exact-location threshold sit at `documents` (current default) or
  `phone`? Lower it if supply growth suffers.
- **OQ-013-C** — Should a customer be able to *filter* discovery to verified providers only?
- **OQ-013-D** — What is the turnaround-time commitment for review, and what happens if it is
  missed? Since ADR-019 this is the marketplace's critical path, not just a courtesy.
- **OQ-013-I** — What is the written standard for approving a submission? With a single reviewer
  the bar is whatever they decide that day; it is not recorded anywhere, which makes it
  impossible to hand over or to defend a rejection.
- **OQ-013-E** — Should reaching `documents` require business registration (RGD) for shops, as
  distinct from individuals?
- **OQ-013-F** — Is a police clearance certificate wanted for a future "insured" tier?

## 18b. Scaling review beyond one reviewer

You are the only reviewer today, and ADR-019 has made that role load-bearing: an unreviewed
provider cannot earn, so a stalled queue stalls the marketplace. Recording what a scaled version
needs, so the current design does not quietly foreclose it.

**Already in place, by luck or design:**

- `reviewed_by` is a real FK with `SET_NULL`, so decisions are attributable per reviewer and
  survive a reviewer leaving.
- Every decision writes an `AuditEvent` naming the actor (ADR-016).
- Review goes through `review_verification()`, not the admin, so any future queue UI, API, or
  bulk tool inherits the level change, the document purge, and the audit entry for free.

**What a scaled version would need to add:**

| Need | Why | Rough shape |
|---|---|---|
| Reviewer role | `is_staff` is all-or-nothing today; a reviewer should not get the whole database | A Django group with model-level permissions, or the operator roles deferred in ADR-017 |
| Claiming | Two reviewers should not open the same submission | `claimed_by` + `claimed_at`, released on a timeout |
| Turnaround measurement | A queue nobody measures is a queue that stalls | `submitted_at → reviewed_at` percentiles; oldest-pending-age alarm |
| Escalation | A rejected provider has no recourse today | An appeal state, or a second-reviewer requirement for rejections |
| Consistency | Two reviewers will disagree about a blurry ID | A written standard — the missing piece even with **one** reviewer (OQ-013-I) |
| Partial automation | Volume will outgrow humans before it outgrows the model | Tier 2 provider does document/liveness; a human reviews only exceptions |

**The natural sequence** is not "hire reviewers" but **automate the common case first**: a Tier 2
provider clears clean submissions instantly and routes only the ambiguous ones to a person. That
keeps the human in the loop where judgement actually helps, and removes the cold-start pressure
that ADR-019 creates.

None of this is built. It is recorded so the eventual design starts from the constraints rather
than rediscovering them.

## 19. Implementation Notes

- The grid snap is deliberately crude: `round(coordinate / grid_degrees) * grid_degrees`, with the
  longitude step scaled by `cos(latitude)` so the cell stays roughly square. At Ghana's latitude
  the difference is small; the helper is written to be correct anyway.
- `PROVIDER_EXACT_LOCATION_MIN_LEVEL` is a setting, not a constant, precisely so the
  supply-versus-privacy trade can be retuned without a deploy of new code.
- `evaluate_automatic_level()` is called on profile read and on phone verification rather than
  driven by signals. Signals on `ProviderProfile` already trigger presence broadcasts; adding
  level evaluation there would fire a broadcast on every offering change.
- The reserved `ghana_card_number` field is deliberately unused. It costs nothing now and avoids
  a migration when Tier 3 arrives.

## 20. Verification Evidence

- Files: [apps/providers/verification.py](apps/providers/verification.py), [apps/providers/models.py](apps/providers/models.py), [apps/providers/views.py](apps/providers/views.py), [apps/providers/admin.py](apps/providers/admin.py), [apps/core/geo.py](apps/core/geo.py)
- Tests: `tests/test_verification.py`
- Review: to be reviewed by the project owner (`docs/REVIEW-GUIDE.md`).
