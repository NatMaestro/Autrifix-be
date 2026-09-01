# Autrifix Product Context

## Product

Autrifix is an automotive/mechanical assistance platform connecting people who need vehicle assistance with service providers.

## Primary user types

### Customer

A person who owns or operates a vehicle and needs mechanical assistance, servicing, diagnosis, roadside assistance, or another automotive service.

### Service Provider

A person or business able to accept and perform automotive jobs.

### Administrator

A platform operator responsible for managing users, service providers, operational issues, and platform configuration.

## Core product concept

A customer can create a service request describing a vehicle problem or desired automotive service. The platform can facilitate discovery/matching, provider acceptance, job progress, communication, completion, and feedback.

## Product areas

- Identity and authentication
- Customer profiles
- Provider profiles
- Vehicles
- Service requests
- Matching / provider discovery
- Job lifecycle
- Location
- Communication
- Notifications
- Ratings/reviews
- Administration
- Future commercial/payment capabilities

## Important baseline constraint

This document is intentionally conservative. Features such as payments, subscriptions, insurance, towing partnerships, advanced dispatch algorithms, or other commercial integrations must not be treated as committed product requirements unless confirmed by an existing implementation or an explicit product decision.

## Current implementation truth

The existing codebase must be inspected before marking any feature as implemented.

---

## Signals observed in the backend (2026-08-17)

The following were recovered from the `autrifix-be` codebase during the initial
codebase-to-spec synchronization. **They are evidence, not product requirements**
(`DECISIONS.md` ADR-002). Each is listed with the question it raises rather than the conclusion
it might suggest.

Nothing in this section changes the baseline constraint above.

### Positioning

The backend's OpenAPI description and README describe the product as a **"roadside assistance
marketplace: customers, providers, real-time jobs"** — narrower than "automotive/mechanical
assistance platform" above. Several implementation details point the same way: a 30-minute
visibility window on the provider request feed, a `tow-recovery` service category, and a job
model with no scheduling.

> **OPEN QUESTION:** Is Autrifix a roadside-assistance product, a general automotive-service
> marketplace, or both? The two imply materially different lifecycles (immediate dispatch vs.
> booking).

### Launch market

Phone normalization maps local `0…` numbers to `+233` with an inline comment reading
"Accra / GH rollout default". The default SMS provider list includes Termii (a West African
provider). At the same time, `payments.Payment.currency` defaults to `USD` and
`ProviderServiceOffering.hourly_rate` carries no currency at all.

> **ANSWERED (ADR-022, 2026-08-18):** Ghana is the launch market and **GHS** is the platform
> currency, defined once at `settings.PLATFORM_CURRENCY`. The `USD` default on the payment stub
> was corrected. The payment *rail* remains open — Ghana is mobile-money-first, and that is a
> different integration from a card processor (SPEC-015 OQ-015-A).

### Matching

The platform performs **discovery**, not matching: providers browse nearby open requests and
claim one first-come-first-served. Nothing selects, offers, or ranks on behalf of a customer, and
nothing notifies anyone. A ranking helper and an unused background task exist, both suggesting
dispatch was once intended.

> **OPEN QUESTION:** Should the platform actively match, or remain a browse-and-claim
> marketplace? This is the single largest open product decision in the backend
> (`specs/006-matching-discovery.md` OQ-006-C).

### Trust and reputation

Reviews can be written, but no rating is ever aggregated and no provider reputation is visible.
There is no provider verification, approval, or licensing state anywhere in the system: a user
can self-assign the provider role and immediately accept work.

> **OPEN QUESTION:** What is the trust model for letting a stranger attend a customer's vehicle?

### Commercial capabilities

**Updated 2026-08-18 (ADR-022).** The platform now **records** money and does not **move** it: a
provider quotes, the customer accepts, the provider records the final amount, and the customer
confirms it. Settlement is cash, hand to hand, off-platform.

Payments proper remain **not** implemented. The `Payment` model and two escrow stubs still have no
endpoint, no serializer consumer, and no caller; their `USD` and `stripe` defaults were corrected
because wrong scaffolding is what a first integration copies.

> Whether Autrifix ever takes a cut — and whether by commission, subscription, or lead fee —
> remains **not a committed requirement**. It was deferred deliberately: the point of recording
> prices first is to have real data to design a revenue model against (SPEC-015 OQ-015-B).

### Capabilities that exist in code but are not in the product areas above

- **AI diagnostics** — an endpoint returning two hardcoded suggestions, described in code as a
  placeholder for "LLM + RAG in production".
- **AI issue routing** — a working rules-plus-naive-Bayes classifier that maps free text to a
  service category.

> **OPEN QUESTION:** Are AI-assisted diagnosis and routing product commitments, exploratory
> spikes, or scaffolding to remove?
