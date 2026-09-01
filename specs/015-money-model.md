# SPEC-015 — Money Model

**Status:** READY
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

Autrifix **records** money; it does not **move** money.

A provider proposes a price (a *quote*), the customer accepts or declines it, and when the work
is finished the provider records the amount owed. The job does not close until the **customer
confirms** that amount. Settlement is cash, hand to hand, off-platform.

That is the whole of it. There is no wallet, no escrow, no commission, no payout. What this spec
buys is a **priced, two-sided, disputable record of every job** — which is both the honest
description of what happens on the ground today, and the dataset any future revenue model has to
be designed from.

## 2. Problem

Two problems, and they are not the same size.

**The small one:** the platform has no idea what anything costs. `hourly_rate` and `per_km_rate`
sit on `ProviderServiceOffering` and are never read. No job carries a price. A marketplace that
cannot answer "what does a jump start cost in Accra?" cannot price its own take rate, cannot
detect gouging, and cannot show a customer what to expect.

**The large one:** completion is one-sided. A provider PATCHes `status: completed` and the job is
closed, the request is closed, and the customer can be asked to pay whatever is said out loud.
The customer's only recorded act in the entire lifecycle is cancellation. Once money is attached
to a job, one-sided completion stops being an asymmetry and becomes a liability: the platform
would be publishing an amount that only one party ever agreed to.

**This is why the two-sided change is worth doing now and not later.** It is the expensive one —
it changes the job state machine, the notification catalogue, the request lifecycle, and every
client that closes a job. Doing it before the web app exists costs a migration. Doing it after
costs a migration *and* a client rewrite *and* a period where live jobs are mid-flight across two
contracts.

## 3. Actors

| Actor | Can |
|---|---|
| Provider | Submit and revise quotes; record the final amount when finishing |
| Customer | Accept or decline a quote; confirm the final amount |
| Administrator | Read everything (SPEC-012, deferred) |

Nobody can do the other's half. That is the point.

## 4. Requirements

### REQ-1 — Money is recorded, never processed

`Job.final_amount` (`Decimal`, 2dp) and `Job.currency` record what the customer owes. No code
path debits, credits, holds, or transfers. `apps/payments/` remains scaffolding with no caller.

**Rationale.** Taking money means choosing a rail, registering as a merchant, handling refunds and
chargebacks, and holding other people's funds. None of that is knowable before there is volume,
and all of it is reversible-in-principle but expensive-in-practice to get wrong.

### REQ-2 — The platform currency is GHS

`settings.PLATFORM_CURRENCY`, defaulting to `GHS`, is the single definition. Clients do not supply
a currency; one supplied is ignored.

**Rationale.** Ghana is the launch market — phone normalization already defaults to `+233` and the
SMS provider list is West African. The `USD` default on the payment stub was scaffolding that
nobody had revisited, and it is corrected in this slice rather than left to be copied. This closes
half of the PRODUCT.md "launch market" open question.

### REQ-3 — Amounts are bounded and validated in the service layer

Non-negative, at most `MAX_AMOUNT` (1,000,000.00), quantized to 2dp. Enforced in
`apps.jobs.services`, not only in a serializer.

**Rationale.** The ceiling is a typo guard, not a business rule: a slipped decimal point must not
become a bill. Enforcing in the service means the invariant holds for the admin and for any future
non-HTTP caller, which is the same reason the verification gate lives there.

### REQ-4 — A job gains an `awaiting_confirmation` state

```text
pending_accept ──> active ──> awaiting_confirmation ──> completed
```

- `active → awaiting_confirmation` is the **provider's**; it requires `final_amount`.
- `awaiting_confirmation → completed` is the **customer's**, and only theirs.

The `active → completed` transition is **removed**. A provider can no longer close a job.

**API-015-A:** `PATCH /api/jobs/{id}/` with `{"status": "awaiting_confirmation", "final_amount":
"250.00"}`. Missing amount → `400`. Illegal move → `409`.

### REQ-5 — Quoting exists and is optional

`Quote` is a first-class row: `job`, `amount`, `currency`, `notes`, `status`, `created_at`,
`responded_at`. States: `pending → accepted | declined | superseded`.

- Only the **assigned provider** may submit. Only the **customer** may respond.
- Submitting a new quote **supersedes** the outstanding one.
- At most one `pending` quote per job, by partial unique constraint.
- Quotes are legal only while the job is `pending_accept` or `active`.

**API-015-B:** `GET|POST /api/jobs/{job_id}/quotes/`
**API-015-C:** `POST /api/jobs/{job_id}/quotes/{quote_id}/respond/` with `{"accept": bool}`

**Rationale for optional.** A tow price is computable up front from per-km × distance; a jump start
is a known number; a repair's cost is genuinely unknowable until someone looks. Forcing a quote on
the first two adds a round trip that buys nothing, and would push providers to quote a placeholder
— which is worse than no quote, because it looks like agreement.

**Rationale for supersede-not-error.** A provider who opens the bonnet and finds more wrong needs
to revise. Requiring an explicit withdraw-then-resubmit leaves the customer looking at a price
nobody intends to honour for as long as the dance takes.

**Rationale for declining ≠ cancelling.** A declined quote invites a revised one. Wiring decline to
job cancellation would make price negotiation a one-shot game and cost both parties the job over
what may be a GHS 20 gap.

### REQ-6 — The gap between agreed and charged is surfaced, not enforced

`JobSerializer.amount_variance` = `final_amount − accepted_quote.amount`, or `null` when there is
no accepted quote or the work is unfinished. Positive means the customer is being asked for more
than they agreed to.

The final amount is **not** clamped to the quote.

**Rationale.** Clamping sounds protective and is not: a repair that turns out to need a part the
provider could not have foreseen would either have to be finished at a loss or abandoned. What the
customer actually needs is not a cap but *disclosure* — the number in front of them, next to what
they agreed to, before they press confirm. Enforcement without a dispute mechanism would also give
the platform an obligation it has no process to discharge.

**OPEN QUESTION (OQ-015-C):** should a variance above some threshold require a fresh quote rather
than a confirmation? Deferred until there is evidence of how often, and how far, amounts drift.

### REQ-7 — Recording an amount is part of finishing, never a standalone edit

`final_amount` is rejected on a `PATCH` that carries no status transition (`409`), and on any
transition not marked `requires_amount`.

**Rationale.** Otherwise a provider could revise the bill after the customer had already seen it,
and the confirmation would be attached to a number that had since changed.

### REQ-8 — Finished work cannot be cancelled

While any job on a request is `awaiting_confirmation`, `POST /api/jobs/requests/{id}/cancel/`
returns `409`, and the customer's `awaiting_confirmation → cancelled` transition does not exist.

**Rationale.** The request stays `assigned` through `awaiting_confirmation`, which without this
guard would leave cancellation open as a way to walk away from work already performed.

### REQ-9 — Notifications follow the acting party

| Kind | Recipient | When |
|---|---|---|
| `quote.submitted` | Customer | Provider proposes a price |
| `quote.accepted` | Provider | Customer agrees |
| `quote.declined` | Provider | Customer declines |
| `job.awaiting_confirmation` | Customer | Provider finished; carries `final_amount` and `currency` |
| `job.completed` | **Provider** | Customer confirmed |

`job.completed` changes recipient in this slice. It previously went to the customer on the
provider's action; completion is now the customer's own act, so they learn the outcome from the
HTTP response and the provider is the one who needs telling.

### REQ-10 — Quote actions are audited

`quote.submitted` and `quote.responded` join the `AuditAction` catalogue, with actor, amount, and
response in metadata.

**Rationale.** A price dispute is exactly the scenario ADR-016 built the trail for.

## 5. Out of scope

- Any movement of funds; escrow; wallets; payouts.
- Commission, subscription, or lead fees — see OQ-015-B.
- Formal dispute resolution. A customer who disagrees with an amount today does not confirm, and
  the job sits. See OQ-015-D, which is a real operational gap and is called one.
- Automatic pricing from `hourly_rate` / `per_km_rate`. The fields stay unread; a provider types
  a number. Deriving a suggested price is a later slice with better data behind it.

## 6. Data model

```text
jobs.Job
  + work_finished_at   datetime, null
  + final_amount       decimal(10,2), null
  + currency           char(3), blank
  + status gains `awaiting_confirmation`

jobs.Quote  (new)
    job          FK -> Job (CASCADE), related_name="quotes"
    amount       decimal(10,2)
    currency     char(3)
    notes        text, blank
    status       pending | accepted | declined | superseded
    created_at, responded_at
    UniqueConstraint(job) WHERE status = 'pending'

payments.Payment  (stub, corrected — still no writer)
    amount_cents -> amount_minor      (pesewas are not cents)
    provider     -> processor         (`provider` collided with service provider)
    currency default USD -> settings.PLATFORM_CURRENCY
    + rail       unset | mobile_money | card | bank_transfer | cash
```

## 7. Acceptance criteria

- [x] Provider finishing a job records an amount and does **not** close it
- [x] Customer confirmation closes both job and request
- [x] Provider cannot confirm their own work (`409`)
- [x] Finishing without an amount is `400`; negative and absurd amounts are `400`
- [x] `final_amount` cannot be edited outside the finishing transition (`409`)
- [x] Finished work cannot be cancelled by either party (`409`)
- [x] Provider submits, revises (superseding), customer accepts or declines
- [x] Customer cannot quote; provider cannot respond; outsiders get `404`
- [x] A superseded or already-answered quote cannot be answered (`409`)
- [x] Currency is the platform's regardless of input
- [x] `amount_variance` reports the gap, and is `null` when there is nothing to compare
- [x] A job can be finished and confirmed with no quote at all
- [x] Both parties read the price thread; outsiders get `404`
- [x] Quote actions appear in the audit trail
- [x] Notifications land on the counterparty, never the actor

Covered by `tests/test_quotes.py` (30), plus the money and confirmation cases in
`tests/test_job_lifecycle.py`, `tests/test_audit.py`, and `tests/test_notifications.py`.

## 8. Open questions

**OQ-015-A — What payment rail, if the platform ever takes one?**
Undecided, and deliberately so. Ghana is mobile-money-first: MTN MoMo dominant, Telecel and
AirtelTigo behind it, with aggregators (Hubtel, Paystack, Flutterwave, expressPay) fronting them.
Card penetration is low enough that a card-only rail would exclude most of the market. The stub now
defaults to `rail=""` rather than claiming a processor nobody chose.

**OQ-015-B — What is the revenue model?**
Deferred by explicit product decision: collect price data first. The candidates are commission per
job, a provider subscription, and a lead fee — and they differ mainly in how badly they behave when
settlement is in cash. **Commission on cash is the trap:** the platform would be invoicing
providers for money it never held and cannot see, which converts every collection failure into a
support case and gives both parties a reason to settle off-platform. A subscription or lead fee has
no such coupling. Revisit when there is a distribution of `final_amount` to look at.

**OQ-015-D — What happens to a job the customer never confirms?**
Today: nothing. It sits in `awaiting_confirmation` indefinitely, the request stays `assigned`, and
the provider cannot be reviewed or move on. This is a **known operational gap**, not an oversight.
The plausible answers — auto-confirm after N days, provider-initiated escalation, admin resolution
— all need either a scheduler (no Celery worker is deployed; ADR-010) or the admin surface
(SPEC-012, deferred). Flagged rather than half-built.

**OQ-015-E — Should a customer be able to dispute rather than only confirm?**
Not in this slice, by product decision. A `disputed` state is cheap to add and expensive to
operate: it needs someone to adjudicate. Revisit if unconfirmed jobs turn out to be disputes rather
than inattention.

**OQ-015-F — Should the platform suggest a price?**
`hourly_rate` and `per_km_rate` exist and are still unread. Once there is a corpus of
`final_amount` by category and distance, a suggested range is both possible and more useful than
the declared rates. Not now.

## 9. Related

- ADR-022 (this decision), ADR-006 (currency, previously unanswered), ADR-016 (audit trail)
- SPEC-005 (service requests — cancellation guard), SPEC-007 (job lifecycle — the state machine)
- SPEC-010 (notifications — five new kinds), SPEC-011 (reviews — still gated on `completed`,
  which now means *customer-confirmed*, a strictly stronger precondition)
