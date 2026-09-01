# Autrifix Backend Decisions

Use this document for Architecture Decision Records (ADRs) and important product/technical decisions.

ADR-003 onward were **recovered from the codebase** during the 2026-08-17 synchronization pass.
They record decisions that are evidently in force in the implementation but were never written
down. They are marked `Accepted (recovered)` where the code and its own comments make the intent
unambiguous, and `Proposed (observed)` where the code shows a decision was taken but the
rationale — and therefore whether it should stand — is not recoverable.

> **Vocabulary note.** Entries dated before 2026-08-18 use the original `driver` /
> `mechanic` vocabulary. They are historical records and are deliberately **not**
> rewritten — see ADR-020 for the rename.

---

## ADR-001 — Adopt Specification-Driven Development

**Status:** Accepted

Autrifix will use specifications as an explicit source of intended behavior, while existing code remains evidence of actual implementation.

### Consequences

- feature work starts from a spec;
- implementation changes require spec synchronization;
- agents must distinguish intended behavior from observed behavior;
- significant decisions are recorded rather than rediscovered.

## ADR-002 — Separate Product Intent From Implementation Evidence

**Status:** Accepted

The codebase may contain historical or accidental behavior. Reverse-engineering the code does not automatically make every observed behavior a product requirement.

---

## ADR-003 — No PostGIS: lat/lng floats with geopy distance

**Status:** Accepted (recovered)

**Context:** The product is location-centric, which normally suggests GeoDjango/PostGIS. That
brings a GDAL/OSGeo4W toolchain dependency onto every developer machine and CI runner, and ties
the deployment to a PostGIS-capable database.

**Decision:** Store coordinates as plain `FloatField` pairs. Compute WGS84 geodesic distance in
Python with `geopy`, after narrowing candidates with a bounding-box query. Render maps on the
client.

**Evidence:** [`apps/core/geo.py`](../apps/core/geo.py) module docstring ("no GDAL/PostGIS
required; maps stay on the client"); [`README.md`](../README.md) ("No GDAL/OSGeo4W");
`geopy==2.4.1` as the only geo dependency.

**Consequences:**
- Trivial local setup and portability to any PostgreSQL host, including Neon.
- No spatial index: distance is O(candidates) in Python per query. Adequate at MVP volume;
  it becomes the dominant cost of `/services/nearby/` as the mechanic pool grows.
- The bounding-box arithmetic is duplicated in two modules and does not handle the antimeridian.
- Revisiting this later means a migration to `PointField` plus a PostGIS-capable database.

## ADR-004 — Separate `ServiceRequest` and `Job` entities

**Status:** Accepted (recovered)

**Context:** `DOMAIN.md` explicitly left open whether the request and the job are one lifecycle
entity or two.

**Decision:** Two entities. `ServiceRequest` is the driver's ask; `Job` is a mechanic's
commitment to it. The job's outcome cascades onto the request's status.

**Evidence:** [`apps/jobs/models.py`](../apps/jobs/models.py); `JobAcceptView` creates a `Job`
and moves the request to `matching`.

**Consequences:**
- Clean separation of "what the customer wants" from "who is doing it".
- `Job.service_request` is a `ForeignKey`, not `OneToOneField`, so a request can accumulate
  several jobs — the structural cause of the concurrent-acceptance defect (SPEC-007
  CONFLICT-007-A). Whether multiple jobs per request is intended, or an oversight, is
  **unresolved**; see OQ below.
- The two status vocabularies must be kept coherent by hand; nothing enforces it.

## ADR-005 — Pull-based discovery, not dispatch

**Status:** Proposed (observed)

**Context:** A marketplace can push work to a chosen provider, or let providers browse and claim.

**Decision (as implemented):** Providers browse. A mechanic polls nearby open requests and
claims one first-come-first-served. The platform never selects, offers, or notifies.

**Evidence:** [`apps/jobs/views.py`](../apps/jobs/views.py) `NearbyOpenRequestsView` +
`JobAcceptView`; no notification producer exists; `match_service_request_async` is defined and
never called.

**Consequences:**
- Simple and predictable; no dispatch fairness or timeout logic needed.
- A stranded driver has no feedback loop and no guarantee anyone will look.
- The unused Celery task and the "Integrate: push notification, WebSocket broadcast" comment
  suggest push dispatch was intended and abandoned. **This decision needs confirming or
  reversing** (SPEC-006 OQ-006-C).

## ADR-006 — Ghana-first phone normalization

**Status:** Proposed (observed)

**Context:** Users enter phone numbers in local format.

**Decision (as implemented):** Normalize to E.164; map a leading `0` to `+233`.

**Evidence:** [`apps/accounts/phone.py`](../apps/accounts/phone.py) — "Ghana local numbers
starting with 0 are mapped to +233 (Accra / GH rollout default)".

**Consequences:**
- Correct for the apparent launch market.
- A non-Ghanaian local number is silently rewritten as Ghanaian, with no error.
- Correct for the launch market, which **ADR-022 confirmed as Ghana**. The conflicting `USD`
  default on `payments.Payment` is corrected in that slice; the platform currency is now GHS via
  `settings.PLATFORM_CURRENCY`.
- The payment *rail* remains open (SPEC-015 OQ-015-A). `ProviderServiceOffering.hourly_rate` and
  `per_km_rate` still carry no currency, but are also still unread by any code path.

## ADR-007 — Identifier-based login over SimpleJWT's default

**Status:** Accepted (recovered)

**Context:** `User.USERNAME_FIELD` is `phone`, so SimpleJWT's default obtain serializer would
require a `phone` + `password` body. Users may have registered with either email or phone.

**Decision:** Override `SIMPLE_JWT["TOKEN_OBTAIN_SERIALIZER"]` globally with
`IdentifierTokenObtainPairSerializer`, which resolves a single `identifier` field to a user by
email or normalized phone, and accepts legacy `email` / `phone` keys as aliases.

**Evidence:** [`autrifix/settings/base.py`](../autrifix/settings/base.py) with an inline comment;
[`apps/accounts/serializers.py`](../apps/accounts/serializers.py); [`apps/accounts/auth_utils.py`](../apps/accounts/auth_utils.py).

**Consequences:**
- One login endpoint for both identifier types.
- The serializer is a plain `Serializer` that mints tokens itself rather than extending
  SimpleJWT's, so SimpleJWT's own hooks (`get_token`, custom claims) do not apply.
- Four routes now reach token issue/refresh; two are hidden from the OpenAPI schema.

## ADR-008 — Defer email verification

**Status:** Accepted (recovered)

**Context:** An `EmailOTP` model was added and then removed.

**Decision:** Email verification is deferred to a later release. Registration requires both email
and phone, and neither is verified at signup.

**Evidence:** migration `accounts/0005_email_otp` creates `EmailOTP`; `accounts/0006_delete_emailotp`
removes it with the comment "email verification deferred to a later release".

**Consequences:**
- `User.is_email_verified` survives but is set only by Google sign-in and read by nothing.
- Password accounts remain permanently unverified.
- The phone OTP endpoints remain live while the OpenAPI description calls them "legacy … for
  future use" — an unresolved contradiction (SPEC-001 OQ-001-A).

## ADR-009 — Drop hard category filtering from the mechanic request feed

**Status:** Proposed (observed) · **uncommitted working-tree change**

**Context:** `NearbyOpenRequestsView` previously restricted open requests to the categories a
mechanic had declared as active offerings.

**Decision (as implemented):** Remove the filter. Show all nearby open requests regardless of the
mechanic's declared offerings.

**Evidence:** [`apps/jobs/views.py`](../apps/jobs/views.py) — "Strict category matching can hide
valid nearby requests from online mechanics when profile setup is incomplete or category naming
drifts." Confirmed as an uncommitted modification via `git diff` on 2026-08-17.

**Consequences:**
- Mechanics with incomplete profiles still see work — the stated goal.
- `MechanicServiceOffering` now influences nothing at all; it is captured, editable, and inert.
- The alternative — using offerings as a **ranking** signal rather than a hard filter — was not
  attempted. **Needs a decision** (SPEC-003 OQ-003-B).
- This change is not yet committed, so it may or may not represent settled intent.

## ADR-010 — Filesystem-persisted incremental ML routing model

**Status:** Proposed (observed) · **recommended for reversal**

**Context:** Free-text problem descriptions need routing to a service category.

**Decision (as implemented):** A hybrid router — keyword rules first, then an incremental naive
Bayes classifier — with the model persisted as JSON at `var/issue_router_model.json` and trained
**synchronously inside `ServiceRequestSerializer.create()`** on every request.

**Evidence:** [`apps/ai/issue_router.py`](../apps/ai/issue_router.py), [`apps/jobs/serializers.py`](../apps/jobs/serializers.py).

**Consequences:**
- No external ML dependency; the router works out of the box from seeded keywords.
- **Not deployment-safe.** The file lives on local disk under `BASE_DIR`; the Render and Docker
  targets both have ephemeral filesystems, the web and Celery containers do not share a volume,
  and the guarding `threading.Lock` is per-process. The model effectively resets on every deploy
  and diverges per replica.
- Request creation performs blocking disk I/O on the hot path.
- The model is keyed by category **slug**, and `ServiceCategoryAdmin` prepopulates slug from
  name — renaming a category in admin can orphan every trained class.

**Partial mitigation (2026-08-17):** the path is now configurable via
`ISSUE_ROUTER_MODEL_PATH` (settings + env), so it can be pointed at a mounted volume in
production and is redirected to a temp file under test settings — previously every test run
dirtied the tracked `var/issue_router_model.json`. The underlying decision still stands as
**recommended for reversal**: the durability, cross-process, and hot-path-I/O problems are
inherent to filesystem persistence, not to the path.

---

## ADR-011 — Reviews are one-directional, on completed jobs only

**Status:** Accepted (2026-08-17)

**Context:** `Review` had no notion of who was being reviewed, and no eligibility checks at all —
any authenticated user could review any job in any state, including a mechanic reviewing their
own job (SPEC-011 CONFLICT-011-B). Fixing it required deciding the direction first.

**Decision:** A review is written **by the driver of a job, about the mechanic who did it**, and
only once the job is `completed`. One review per `(job, author)`. A job cancelled after the
mechanic arrived is explicitly not reviewable.

**Alternatives:** Bidirectional (mechanic also rates the driver) — rejected for now; it needs a
subject field on `Review` and a second rating summary on `DriverProfile`, roughly doubling the
surface for no MVP benefit.

**Consequences:**
- `MechanicProfile.rating_avg` / `rating_count` can be computed unambiguously as an aggregate
  over `Review.objects.filter(job__mechanic=…)`, which is what
  `apps.reviews.services.recalculate_mechanic_rating` does.
- Drivers accumulate no reputation. If driver ratings are ever wanted, `Review` needs a subject
  column and this ADR is superseded.
- "Reviewable" is now coupled to job completion, so a dispute about an abandoned job has no
  review outlet. See SPEC-011 OQ-011-B.

## ADR-012 — In-app notifications only; synchronous production, deferred delivery

**Status:** Accepted (2026-08-17)

**Context:** The `Notification` model and read API existed but nothing ever created a row
(SPEC-010). Both push and Celery-based dispatch were plausible.

**Decision:** Produce notification rows **synchronously**, inside the same transaction as the
domain change that caused them, through the single entry point
`apps.notifications.services.notify`. Push the payload to a per-user Channels group
(`user_{id}`) via `transaction.on_commit`. No FCM/APNs, no email, no SMS.

**Alternatives:** Celery dispatch — rejected because no worker is deployed on Render and the
existing `match_service_request_async` task has never been called; adding a delivery hop would
mean deploying and monitoring a worker for a feature that fits in the request path.

**Consequences:**
- A client is never told about a state change that then rolls back.
- A channel-layer failure is caught and logged; it cannot fail the domain operation.
- Notification production adds one INSERT to each transition — acceptable.
- **A stranded driver with the app closed is still not reached.** This is the main known
  limitation and the strongest argument for revisiting push (SPEC-010 OQ-010-C).
- Under `USE_REDIS=false` the in-memory channel layer does not cross processes, so live delivery
  is development-only unless Redis is configured.

## ADR-013 — `role` is fixed at signup

**Status:** Accepted (2026-08-17)

**Context:** `UserSerializer` exposed `role` as writable and blocked only `admin`, so any driver
could `PATCH /me/ {"role": "mechanic"}` and immediately accept jobs (SPEC-001 CONFLICT-001-A).

**Decision:** `role` is read-only on `/me/`. Changing it requires an administrator.

**Alternatives:** Free switching — rejected while no mechanic-verification gate exists;
self-assignment would let anyone become a live service provider instantly. Switching with
approval — deferred; it is really SPEC-003 REQ-6 (verification) wearing a different hat.

**Consequences:**
- Closes the escalation path with a one-line change and no migration.
- A user who genuinely picked the wrong role at signup now needs support intervention. There is
  no admin API, so that means Django admin (SPEC-012 REQ-4).
- Revisit if and when mechanic verification is built.

## ADR-014 — Mechanic discovery requires authentication

**Status:** Accepted (2026-08-17)

**Context:** `GET /services/nearby/` was `AllowAny` and returned every available mechanic's exact
workshop coordinates and business name. Sweeping `lat`/`lng` enumerated the entire supply side
within the anonymous throttle budget (SPEC-008 SECGAP-008-1).

**Decision:** The endpoint requires authentication.

**Alternatives:** Keep it public with coarsened coordinates or a count only — a reasonable
middle ground, rejected for now because no client is known to depend on anonymous access and the
simpler change closes the hole outright.

**Consequences:**
- Any pre-signup "mechanics near you" feature on the landing page or web app stops working and
  would need the coarsened variant instead.
- Enumeration now costs an account, and is attributable.
- Does **not** address the converse disclosure: a browsing mechanic still sees drivers' exact
  request coordinates before accepting (SPEC-008 OQ-008-B, still open).

## ADR-015 — A mechanic sees the driver's exact location before accepting

**Status:** Accepted (2026-08-17)

**Context:** `GET /jobs/requests/nearby/` discloses the driver's exact coordinate, problem
description, and vehicle summary to any online mechanic within radius, before any relationship
exists. The synchronization pass flagged this against `SECURITY.md` ("mechanics should receive
only the location information necessary for a legitimate job workflow") and left it open as
OQ-008-B.

**Decision:** This is intended behavior. A mechanic needs to see where the job is in order to
decide whether to accept it; withholding the location until after acceptance would mean
accepting blind. Accordingly the feed now also returns `distance_km` per request, which is the
form of the information a mechanic actually reasons about.

**Alternatives considered:** coarsening the coordinate (~1 km grid) while browsing and revealing
the exact point on acceptance. Rejected: distance-to-job is the primary accept/decline input, and
a coarsened point degrades exactly the signal the decision depends on.

**Consequences:**
- SEC-GAP-22 and SPEC-008 SECGAP-008-2 are closed as **accepted by design**, not fixed.
- The residual exposure is real and now concentrated in one place: **any account that can become
  an online mechanic can harvest driver locations and problem descriptions across its radius.**
  There is currently no verification gate on becoming a mechanic — a user simply registers with
  `role=mechanic`.
- **The compensating control is therefore mechanic verification (SPEC-003 REQ-6 / OQ-003-A), which
  this decision promotes from "nice to have" to the primary safeguard for driver location
  privacy.** It should be treated as such when it is scoped.
- Partial mitigations already in place: discovery requires authentication (ADR-014), the feed is
  limited to `open` requests within a 30-minute window and a bounded radius, and `driver_name`
  no longer discloses a phone number.

## ADR-016 — Audit state changes and failed logins; do not audit reads

**Status:** Accepted (2026-08-17)

**Context:** Nothing in the system was audited (SPEC-012 OQ-012-D). `SECURITY.md` asks that the
need be *determined* for sensitive operational actions; the determination had never been made.

**Decision:** Record an append-only `core.AuditEvent` for:

| Audited | Why |
|---|---|
| `job.accepted` | Start of the commercial relationship |
| `job.transitioned` | The commercial record — what a payment or service dispute turns on |
| `request.cancelled` | Who cancelled, from what state, and which jobs it killed |
| `auth.login_failed` | The security record; the only signal that an account is under attack |

**Do not audit reads.** Location lookups, feed browsing, and profile reads are orders of
magnitude more voluminous and rarely answer a question that request logs cannot. The one read
worth auditing is an administrator opening a private conversation — deferred with the rest of
administration (ADR-017).

Successful logins are also not audited: high volume, and the JWT already carries the session.

**Consequences:**
- Volume is bounded by job throughput plus throttled login failures — a few rows per job.
- `AuditEvent.actor` is `SET_NULL` with a denormalised `actor_label`. **This is the one place in
  the codebase that deliberately does not cascade:** a trail that vanishes when a mechanic
  deletes their profile is worthless precisely when it is needed.
- Audit writes are wrapped so a failure logs and returns `None` rather than breaking the audited
  action. Losing one row is preferable to failing a transition two people are waiting on. If
  auditing ever becomes a compliance requirement rather than an operational one, this trade-off
  must be revisited.
- Exposed read-only in Django admin — no add, change, or delete, and every field read-only.
- **No retention policy exists.** Nothing prunes. This needs deciding before the table grows
  (SPEC-012 OQ-012-H).

## ADR-017 — Administration is deferred

**Status:** Accepted (2026-08-17)

**Context:** SPEC-012 is the only spec still at `DRAFT`. Administration is Django-admin-only:
no admin API, no operator roles, no admin-action auditing, and `role = admin` grants nothing at
the API layer.

**Decision:** Defer. The admin side will be built later as its own piece of work.

**Consequences:**
- SEC-GAP-17 (admin can read any private conversation, unaudited) and SEC-GAP-29 (no admin login
  throttling, no IP restriction) remain **open and accepted for now**.
- Operational intervention still means full-database staff access via Django admin, and admin
  edits still bypass the transition table (SPEC-012 REQ-5) — an operator can put a job into a
  state the API would reject.
- `AuditEvent` is registered in admin, so at least the trail is visible to operators today.
- SPEC-012 stays `DRAFT` deliberately; it is not an oversight.

## ADR-018 — Graded mechanic verification; gate precision, not participation

**Status:** Accepted (2026-08-17) · **Partially superseded by ADR-019** — the participation clause was reversed on 2026-08-18 · **Specified in:** [SPEC-013](../specs/013-provider-verification.md)

**Context:** ADR-015 accepted that a browsing mechanic sees drivers' exact locations, on the
assumption that an online mechanic is a plausible service provider. Nothing enforced that
assumption: anyone could register with `role=mechanic`, go online, and read every open request
in their radius. ADR-015 explicitly promoted verification to the compensating control.

**Decision:** Verification is an **ordered level** (`none → phone → documents → ghana_card`) that
gates **how precisely** a mechanic sees driver locations, not whether they may participate.

- Below `documents` (configurable): coordinates snapped to a ~1 km grid, with the published
  distance derived from the snapped point.
- At or above: exact coordinates.
- Everyone, after accepting: exact coordinates.

Tier 1 (manual document review by the project owner, in Django admin) is implemented. Automated
document/liveness checks and Ghana Card verification against NIA are future tiers the model
accommodates without a schema change.

**Alternatives considered:**

- *Gate going online entirely.* Rejected — supply-side friction kills marketplaces early, and no
  supply means no product.
- *Coarsen for everyone.* Rejected — contradicts ADR-015; distance-to-job is the primary
  accept/decline input.
- *A single `is_verified` boolean.* Rejected — a level costs nothing now and avoids a migration
  plus an audit of scattered `==` checks when a tier is added.

**Consequences:**

- The **trilateration hazard** had to be designed around: a mechanic chooses the point they
  search from, so publishing an exact distance beside a coarsened coordinate would let the true
  point be recovered from three queries. Everything shown to an untrusted caller is therefore
  derived from the coarsened point. This is the subtlest part of the design and has a dedicated
  test.
- `MechanicServiceOffering` finally does something again: it is part of the completeness gate.
  ADR-009 had left it inert.
- Documents are **purged on decision** — manual review needs a human to see them, but a permanent
  store of identity documents is a breach liability out of proportion to its value. A dispute
  after the fact has only the reviewer's notes.
- Review is a **manual queue with a single reviewer**, which is a bottleneck by construction.
  Turnaround is a product commitment nobody has made yet (SPEC-013 OQ-013-D).
- **Not closed:** an unverified mechanic can still accept a job to reveal an exact location and
  then cancel. Every accept and cancel is audited and the single-live-job constraint limits
  throughput, so it is detectable — but it is not prevented (SPEC-013 OQ-013-A).
  **Superseded 2026-08-18:** ADR-019 gates acceptance on verification, closing this path
  outright. OQ-013-A is moot.
- Ghana's Data Protection Act (Act 843) obligations should be confirmed before enabling any tier
  that handles Ghana Card data.

## ADR-019 — Unverified mechanics may browse but not accept

**Status:** Accepted (2026-08-18) · **Supersedes the participation clause of ADR-018**

**Context:** ADR-018 gated *precision* only: an unverified mechanic saw coarsened locations but
could still accept work. That left two things open — the accept-then-cancel path to exact
locations (OQ-013-A), and the fact that an entirely unvetted account could be dispatched to a
customer's roadside.

**Decision:** An unverified mechanic may sign up, go online, and **browse** nearby requests
(coarsened, per ADR-018). They may **not accept** one until they reach
`MECHANIC_MIN_ACCEPT_LEVEL`, default `documents`. Acceptance returns `403` with the current
level, the required level, and the verification URL.

**Rationale:** primarily a product one — a mechanic who can see the work they are missing has a
concrete reason to finish verification, where a gated empty app gives them nothing to want. The
security benefit follows for free.

**Alternatives considered:**

- *Gate browsing too.* Rejected — it removes the conversion lever entirely and gives a new
  mechanic no reason to stay.
- *Keep accepts open and add a daily cap for unverified mechanics* (the OQ-013-A proposal).
  Rejected — more machinery, weaker guarantee, and it still lets an unvetted person attend a
  customer.

**Consequences:**

- **Both halves of ADR-015's exposure are now covered.** Coarsening stops browse-harvesting;
  the accept gate stops accept-harvesting. OQ-013-A is closed as moot.
- **Nobody unverified ever attends a customer** — a materially stronger safety property than
  ADR-018 alone.
- **Cold start is now a real operational risk.** At launch nobody is verified, so nobody can
  accept, so drivers get no service. Review turnaround becomes the critical path for the whole
  marketplace, dependent on one person. `MECHANIC_MIN_ACCEPT_LEVEL` is a setting so it can run at
  `phone` during launch and be raised later — that choice is OQ-013-G and should be made
  deliberately before go-live, not discovered.
- Enforced in `accept_service_request`, so admin actions and any future dispatch are covered too.
- Demotion does not disturb a job already in hand; the gate applies at acceptance.
- Review-queue metrics move from "nice to have" to operationally necessary: a stalled queue now
  stalls revenue.

## ADR-020 — Customer / provider vocabulary, and one provider role with a trade

**Status:** Accepted (2026-08-18) · **Specified in:** [SPEC-014](../specs/014-provider-types-and-agencies.md)

**Context:** The platform is not only for mechanics. Tow operators and agencies are in scope,
and the signup copy "sign up as driver" read like a rideshare app in a market where Uber, Bolt
and Yango all operate.

There was a second, sharper problem inside the codebase: **a tow operator is a driver.** Once
towing is in scope, `driver` meaning "the customer" sits next to providers who literally drive
for a living — `job.service_request.driver.user` becomes actively misleading.

**Decision:**

1. `driver` → **`customer`**. This also settles CONFLICT-002-A, where `PRODUCT.md` said
   "Customer" and the code said `driver`.
2. `mechanic` → **`provider`**, one role covering every trade.
3. Trade lives on **`ProviderProfile.provider_type`** (`mechanic` / `tow` / `both`), not on the
   role.
4. Clean break: `/drivers/*` → `/customers/*`, `/mechanics/*` → `/providers/*`, no aliases.

**Alternatives considered:**

- *`motorist` or `road_user`.* `motorist` reads best in English but skews toward cars, and
  Ghana's vehicle mix includes many okada and pragya riders. `road_user` is broader but
  bureaucratic. `customer` is vehicle-agnostic and pairs naturally with `provider`.
- *Separate `mechanic` and `tow` roles.* Rejected — verification, discovery, jobs, chat,
  reviews and ratings are identical for both, so it would duplicate every path, and a garage
  that also runs a tow truck could not be represented at all.
- *No type field; capability via service offerings only.* Rejected — `tow-recovery` already
  existed as a category, but a customer could not then filter discovery by trade, and a towing
  business would have no identity in the system.

**Consequences:**

- ~518 identifier occurrences across 48 files, 7 routes, and the role values are stored strings
  — so a data migration, and a **comprehensive break of the `autrifix-web` contract**.
- **Package directories renamed** (`apps/drivers` → `apps/customers`, `apps/mechanics` →
  `apps/providers`) but **app labels deliberately preserved** as `drivers` / `mechanics`.
  Changing a label orphans every applied row in `django_migrations` and needs manual SQL on
  each deployment — real risk for the least valuable half of the rename. Tables therefore stay
  `drivers_*` / `mechanics_*`, and string model references keep the old label prefix. This is
  the one place where the code reads inconsistently, and it is a deliberate trade.
- Renames are hand-written `RenameModel` / `RenameField` operations, so data is preserved
  rather than dropped and recreated.
- Ordering constraints had to be pinned: historical data migrations resolve models by their
  **old** names, so `mechanics/0006` depends on `reviews/0003`; and `RenameField` does not
  rewrite `Meta.indexes` or `Meta.constraints`, which on SQLite breaks the table rebuild — so
  dependent indexes and constraints are dropped before the rename and recreated after.

## ADR-021 — Agencies: the business is verified, the person does the work

**Status:** Accepted (2026-08-18) · **Specified in:** [SPEC-014](../specs/014-provider-types-and-agencies.md)

**Context:** Tow companies and garage chains field several operators. Modelling them as
individual providers only would mean every operator submits the same business documents, and
the business itself has no identity.

**Decision:** `Agency` with `AgencyMembership`. The **individual provider remains the unit of
work** — they hold the profile, accept the job, and chat with the customer. The agency carries
the business identity and its own verification level, which **lifts** its active members'
effective level but never lowers it.

**Alternatives considered:** dispatching jobs to the agency, which then assigns an operator.
Rejected for now — it needs an assignment queue and leaves the customer not knowing who is
coming until later.

**Consequences:**

- Onboarding an operator into a verified agency needs no second document review — the point of
  the feature.
- A customer always knows which person is coming, and the audit trail has an individual to
  attribute actions to.
- **Verifying an agency is a higher-stakes action than verifying one person**: it lifts everyone
  in it, including operators added later. The admin surface says so.
- One live membership per provider, enforced by a partial unique constraint; removed
  memberships are retained as history.
- Not built: invitation flow over the API, agency-level ratings, payouts, or assignment. Admin
  only for now.

---

## Open decisions

Decisions the synchronization pass could not make. Each is recorded as an `OPEN QUESTION` in the
relevant spec; the highest-impact ones are listed here.

Resolved on 2026-08-17: OQ-001-C (ADR-013), OQ-011-A/B (ADR-011), OQ-010-A/B/D/E (ADR-012),
OQ-008-A (ADR-014), OQ-008-B (ADR-015), OQ-012-D (ADR-016), OQ-012-A (ADR-017),
OQ-003-A (ADR-018), OQ-007-A,
OQ-008-B and OQ-013-* (ADR-019), the provider-type and agency questions (ADR-020, ADR-021), and
on 2026-08-18 the currency half of ADR-006 (ADR-022 — GHS).
OQ-009-D, and the multiple-jobs-per-request question raised under ADR-004 (answer: at most one
*live* job, enforced by constraint).

Still open, highest-impact first:

| Ref | Question | Blocks |
|---|---|---|
| **SPEC-013 OQ-013-G** | **What is `MECHANIC_MIN_ACCEPT_LEVEL` at launch — `phone` or `documents`?** | **Cold start: at `documents`, no mechanic can work until reviewed.** Decide before go-live. |
| SPEC-013 OQ-013-D | What is the review turnaround commitment, and what happens if it is missed? | Now the marketplace's critical path (ADR-019) |
| SPEC-013 OQ-013-H | How does review scale past one reviewer? | Operational capacity |
| SPEC-013 OQ-013-B | Should the exact-location threshold sit at `documents` or `phone`? | Supply growth versus privacy |
| SPEC-006 OQ-006-C | Pull-based discovery or push dispatch? (ADR-005) | Whether mechanics get notified of new work |
| SPEC-010 OQ-010-C | Is in-app enough, or is push required? (ADR-012) | Reaching a stranded driver with the app closed |
| SPEC-005 OQ-005-A / SPEC-007 OQ-007-E | Is `draft` real? Are `en_route` and `in_progress` needed as distinct states? | Further state-machine work |
| SPEC-006 OQ-006-A | Is the 30-minute feed window a product rule? | Request expiry design |
| SPEC-005 OQ-005-B | May a driver edit a request after acceptance? | Request edit rules |
| SPEC-003 OQ-003-B | Should offerings gate, rank, or do nothing? (ADR-009) | Whether to keep the uncommitted feed change |
| SPEC-012 OQ-012-H | What is the audit retention policy? (ADR-016) | Table growth; nothing prunes |
| SPEC-012 OQ-012-B | What operator roles exist, and what may each see? | `admin` is all-or-nothing (ADR-024) |
| SPEC-012 OQ-012-I | How does a reviewer see the submitted documents outside Django admin? | Verification review workflow |
| SPEC-001 OQ-001-A | Is phone-OTP sign-in supported, deprecated, or future? | Auth surface area |
| SPEC-015 OQ-015-D | **What happens to a job the customer never confirms?** | Jobs strand in `awaiting_confirmation`; needs a scheduler or admin |
| SPEC-015 OQ-015-B | What is the revenue model — commission, subscription, or lead fee? | Deferred pending price data (ADR-022) |
| SPEC-015 OQ-015-A | Which payment rail, if the platform ever takes one? | Any future money movement |
| SPEC-011 OQ-011-F | Should reviews survive mechanic-profile deletion? | Reputation integrity |

## ADR-022 — Money is recorded, not moved; completion is two-sided

**Status:** Accepted (2026-08-18) · **Specified in:** [SPEC-015](../specs/015-money-model.md)

**Context:** No job carried a price. `hourly_rate` and `per_km_rate` were written and never read,
so the platform could not answer what anything costs — which is the input every possible revenue
model needs. Separately, completion was one-sided: a provider PATCHed `status: completed` and the
job closed. The customer's only recorded act in the whole lifecycle was cancellation.

The two are the same problem once money is attached. An amount that only the provider ever agreed
to is not a record; it is an assertion the platform is publishing on their behalf.

**Decision:** The provider records `final_amount` when finishing, which moves the job to
`awaiting_confirmation` rather than closing it. **Only the customer can move it to `completed`.**
A `Quote` model lets the provider propose a price beforehand and the customer accept or decline
it; quoting is optional, and the gap between an accepted quote and the recorded amount is
surfaced rather than enforced.

The platform moves no money. Settlement is cash between the two parties. `apps/payments/` stays a
stub — with its `USD` and `stripe` defaults corrected, because wrong scaffolding gets copied.

**Alternatives considered:**

- *Keep one-sided completion and just add an amount.* Cheapest, and the one that ages worst: it is
  the expensive half to change later, because it breaks the job state machine and every client
  that closes a job. Doing it before the web app exists costs a migration; doing it after costs a
  migration plus a client rewrite plus live jobs stranded across two contracts.
- *Mandatory quotes.* Rejected: a tow price is per-km × distance and a jump start is a known
  number. Forcing a quote there buys nothing and pushes providers to enter placeholders, which
  look like agreement and are not.
- *Clamp the final amount to the accepted quote.* Sounds protective, is not — a repair needing an
  unforeseeable part would have to be finished at a loss or abandoned. Disclosure of the variance
  is the honest control, and it is what a customer can actually act on.
- *Take a commission now.* Rejected, and specifically the commission-on-cash variant: the platform
  would invoice providers for money it never held and cannot verify, turning every collection
  failure into a support case and giving both sides a reason to settle off-platform.

**Consequences:**

- Every completed job now carries a price both parties agreed to — the dataset a revenue model can
  be designed from, which is why the model itself is deferred (OQ-015-B).
- Reviews are unaffected in code but strengthened in meaning: they were already gated on
  `completed`, which now means *customer-confirmed*.
- `job.completed` changes recipient, from customer to provider. A contract change, taken now
  precisely because there is no client to break.
- **A customer who never confirms strands the job.** `awaiting_confirmation` has no timeout, and
  the request stays `assigned`. Every fix needs either a scheduler (none deployed — ADR-010) or
  the admin surface (SPEC-012, deferred). Recorded as OQ-015-D rather than half-built.
- Disputes have no formal path. A customer who disagrees simply does not confirm (OQ-015-E).

**Partially settles ADR-006.** The currency question is answered — GHS, from
`settings.PLATFORM_CURRENCY`. The payment *rail* is explicitly left open (OQ-015-A): Ghana is
mobile-money-first, and a card-only integration would exclude most of the market.


## ADR-023 — Passwordless signup must not invent a role

**Status:** Accepted (2026-09-01) · **Specified in:** [SPEC-001](../specs/001-authentication.md) REQ-9

**Context:** `/auth/google/` and `/auth/verify-otp/` both create an account on first use, and
both defaulted `role` to `customer` when the client sent none. Because `role` is read-only
afterwards (ADR-013), that default was **permanent**. A provider who signed in with Google
became a customer, with no error, no indication anything had gone wrong, and no route out —
the web app then showed them a role picker that the API silently ignored.

This closed the provider funnel for two of the three sign-in paths, and it did so invisibly.

**Decision:** Creating an account requires an explicit role. Both endpoints return
`400` with `{"code": "signup_role_required", "choices": [...]}` when they would otherwise
create an account with a guessed role. **Signing in to an existing account is unaffected**,
and a supplied role still applies only at creation — it is not a back door around ADR-013.

**Alternatives considered:** allowing one role change while the account has no history. It
rescues people already mis-assigned but leaves the silent default — the actual cause — in
place, and needs a definition of "untouched" spanning jobs, requests, verification, and
agency membership. Rejected in favour of preventing the mis-assignment.

**Consequences:**

- Clients must handle `signup_role_required` on both endpoints. The web login page now asks
  and retries; the register page already passed a role and is unchanged.
- The OTP path required splitting verification from consumption. Refusing *after*
  `verify_and_consume` burned the caller's only code, so the retry failed as "invalid or
  expired" — a dead end. `PhoneOTP.is_code_valid` checks without consuming, and the code is
  consumed only on a path that succeeds. **The check still runs before any account lookup**,
  so the endpoint does not become a phone-number enumeration oracle.
- Naming note: that helper cannot be called `check` — it shadows Django's `Model.check()`
  and breaks the system-check framework. pytest does not run system checks, so the suite
  passed while `manage.py` was broken; `spectacular` caught it.

**Resolves** web CONFLICT-W001-A: the profile page's role picker is removed and replaced
with a read-only display.


## ADR-024 — An operator API, narrow on purpose

**Status:** Accepted (2026-09-01) · **Supersedes the deferral in** ADR-017 · **Specified in:**
[SPEC-012](../specs/012-administration.md)

**Context:** ADR-017 deferred administration: Django admin was the operations surface, and
building a second one before the product had shape would have been premature. That reasoning
has expired. Verification review is now on the critical path for provider supply — a provider
who cannot be reviewed cannot accept work at all — and it required a staff credential over the
entire database to perform.

The web app also carried five convincing admin pages backed by hardcoded arrays, where an
operator could believe they had approved a verification.

**Decision:** A REST operator API under `/api/v1/admin/`, gated on `IsAdmin` — a permission
class that had existed since the beginning and was applied to nothing. Five endpoints:
verification queue and review, user search, job history, and operational counts.

**Deliberately excluded, and why each:**

- **Private conversations.** SEC-GAP-17/34 records that administrative reads of chat are
  unaudited. Not exposing them means this slice does not widen that gap; solving it properly
  needs the audited-read design that gap describes.
- **The verification documents themselves.** They are purged on decision (SPEC-013 REQ-8), and
  serving identity documents through a JSON API would protect them with nothing but a URL
  (SEC-GAP-18). A reviewer opens them in Django admin, which is at least staff-gated. Recorded
  as OQ-012-I rather than solved the convenient way.
- **Editing users and jobs.** Every intervention goes through the same service layer the
  product uses, so an operator cannot reach a state the domain forbids. General-purpose
  editing remains Django admin's job.
- **Scoped operator roles.** `admin` stays all-or-nothing. Support, ops, and finance plausibly
  want different visibility, but that is a product question (OQ-012-B) and guessing at it
  would bake in a permission model nobody has chosen.

**Consequences:**

- Verification review no longer requires a database-wide staff credential — the main thing
  this was for.
- The queue is served **oldest-first**. Newest-first starves whoever has waited longest, which
  is exactly the complaint verification delays generate (SPEC-013 OQ-013-D).
- A decline **requires a reason**, enforced server-side. A refusal with no reason leaves the
  provider unable to fix anything, turning a review queue into a dead end for them.
- Operational counts surface `jobs_auto_confirmed` prominently. Each one is a customer charged
  because they did not answer rather than because they agreed, so a rising number is a signal
  the confirmation window is wrong — the risk SPEC-016 REQ-2 knowingly accepted.
- `role=admin` is no longer API-inert. It grants exactly these five endpoints and nothing else.


## Adding a decision

```text
### ADR-XXX — <Title>

**Status:** Proposed / Accepted / Superseded

**Context:** ...

**Decision:** ...

**Alternatives:** ...

**Consequences:** ...
```
