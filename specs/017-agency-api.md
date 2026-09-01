# SPEC-017 — Agency API

**Status:** READY
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

The HTTP surface for the agency model SPEC-014 built: register a business, invite providers
into it, accept or decline, manage roles, and leave or remove.

SPEC-014 delivered the schema, the memberships, and the verification inheritance that makes
agencies worth having — and no endpoints. This makes it usable.

## 2. Problem

An agency could only be created from the Django admin. That is the worst state to leave a
feature in: the schema is paid for, the migrations are applied, `effective_verification_level`
already consults it on every job acceptance, and no provider can reach any of it.

The feature's whole point — onboarding an operator into an already-verified agency without a
second document review — was unreachable by the people it was built for.

## 3. Actors

| Actor | Can |
|---|---|
| Provider (no agency) | Create an agency; accept or decline an invitation |
| Operator | Read the agency and its roster; leave |
| Manager | The above, plus invite, remove, and change roles |
| Owner | The above; at least one must always exist |
| Customer | Nothing. Agencies are not customer-facing (OQ-017-C) |

## 4. Requirements

### REQ-1 — Two resource families, split by ownership

```text
/providers/agencies/...      the business, seen from inside it
/providers/memberships/...   the individual's own place in one
```

**Rationale.** An invitee is not yet a member, so their invitation cannot live behind an
agency-scoped lookup without a hole in that lookup. Splitting on *whose thing it is* keeps
the agency endpoints uniformly member-only.

| Method | Path | Who |
|---|---|---|
| POST | `/providers/agencies/` | any provider without a live membership |
| GET PATCH | `/providers/agencies/{id}/` | member reads; admin writes |
| GET POST | `/providers/agencies/{id}/members/` | member reads; admin invites |
| PATCH DELETE | `/providers/agencies/{id}/members/{membership_id}/` | admin; `DELETE` is also self-leave |
| GET | `/providers/memberships/` | own memberships, invitations included |
| POST | `/providers/memberships/{id}/respond/` | the invitee |

### REQ-2 — The creator becomes the first owner

Creation makes an `active` `owner` membership in the same transaction. A provider already
holding a live membership gets `409`.

**Rationale.** An agency with no members is unreachable — nothing could make it visible, and
nobody could invite anyone into it.

### REQ-3 — `verification_level` is never writable through the API

Absent from both write serializers. Granted by platform review only.

**This is the load-bearing rule of the whole spec.** An agency's level *lifts every active
member's effective level* (SPEC-014 REQ-7), which in turn governs exact-location visibility
and job acceptance (SPEC-013). An agency that could set its own level would let one signup
mint verified providers at will — turning the entire trust ladder into a self-service form.

Input and output use separate serializer classes for this reason: a single `ModelSerializer`
with a growing `read_only_fields` tuple is one careless edit away from that outcome.

### REQ-4 — Membership is visibility

Every agency endpoint resolves through the caller's own live membership. Outsiders get `404`,
never `403` — the same reasoning applied to job ids: an agency id should not be confirmable
from outside it.

### REQ-5 — Invitations are addressed by phone

`POST .../members/` with `{"phone": "...", "role": "manager|operator"}`. The number is
normalized (local `0…` → `+233`). Unknown number, or a number belonging to a customer:
`404`. Provider already in an agency or already invited: `409`.

`owner` cannot be invited (`400`) — ownership is transferred by promoting an existing member.
An unaccepted owner is an agency with no live administrator.

**Rationale.** A phone number is the only identifier an agency admin plausibly knows for
their own staff. The alternatives are worse: browsing providers to find an id is a broader
discovery leak, and invite codes are more machinery for the same result.

### REQ-6 — Declining ends the membership row

A declined invitation moves to `removed`, not to a fourth state.

**Rationale.** The one-live-membership constraint counts `invited` and `active`. A declined
invitation left in any other state would trap the provider — unable to join anywhere,
including the agency they just turned down.

### REQ-7 — An agency always keeps at least one owner

Demoting or removing the last active owner is `409`.

**Rationale.** Without it an agency can be left with no one able to administer it,
recoverable only from the Django admin — which is exactly the escape hatch this spec exists
to remove.

### REQ-8 — Removal is history, not deletion

`status = removed` plus `removed_at`. The row survives.

**Rationale.** An agency that could erase who worked for it would erase the attribution the
audit trail depends on — and the incentive to do so is strongest precisely when the record
matters.

A removed provider is notified, because removal can *lower* their effective verification
level and with it their ability to accept work.

### REQ-9 — Agency actions are audited

`agency.created`, `agency.member_invited`, `agency.membership_changed` (joined, declined,
left, removed, role changed).

**Rationale.** Membership changes a provider's effective verification level, so every one is
a trust-relevant event.

### REQ-10 — Invitations are throttled

`agency_invite` scope, 20/hour. See OQ-017-A.

## 5. Out of scope

- Dispatching work to an agency for it to assign — explicitly rejected in ADR-021. The
  individual provider remains the unit of work.
- Agency-level payouts, billing, or revenue splits. Nothing pays anyone (ADR-022).
- Agency-level ratings — still SPEC-014 OQ-014-D.
- Customer-facing agency profiles (OQ-017-C).
- Transferring an agency to a provider outside it.

## 6. Acceptance criteria

- [x] A provider creates an agency and becomes its active owner; a customer cannot (`403`)
- [x] A second agency while already in one is `409`; slug collisions resolve
- [x] A new agency starts at `verification_level = none`, and the API cannot change that
- [x] Members read; outsiders get `404`; operators cannot edit or invite (`403`)
- [x] Invite by phone works; unknown numbers and customers are `404`; `owner` is `400`
- [x] Inviting someone with a live membership is `409`
- [x] Invitee accepts or declines; declining frees their slot; nobody else can answer
- [x] An invitation cannot be answered twice (`409`)
- [x] `/memberships/` lists pending invitations
- [x] The last owner can neither be demoted nor leave (`409`)
- [x] Removal preserves the row, notifies the provider, and is audited
- [x] A member can leave on their own; an operator cannot remove anyone else (`403`)
- [x] **Joining a verified agency lifts the member's effective level; removal drops it again**

Covered by `tests/test_agency_api.py` (39).

## 7. Open questions

**OQ-017-A — Invitation by phone is an enumeration oracle.**
An authenticated agency admin can learn whether any given number belongs to a provider
account, by the difference between `404` and `201`. Throttled at 20/hour rather than
redesigned: the alternatives (invite codes, or provider-initiated join requests) are more
machinery, and the attacker must already hold a provider account and an agency. Recorded as
**SEC-GAP-36**. Revisit if agency signup ever becomes frictionless.

**OQ-017-B — What happens to live jobs when a member is removed?**
Today: nothing. If the provider's ability to accept work came from the agency's inherited
level, removal drops it — but jobs already accepted continue. That is probably right (the
customer is expecting *that* person), but it is currently an accident rather than a decision.

**OQ-017-C — Should customers see agencies at all?**
"Kaneshie Towing" is a stronger trust signal to a stranded customer than an individual's
name. Nothing exposes it. Bundle with the agency-ratings question (SPEC-014 OQ-014-D), since
both turn on whether reputation attaches to the person or the business.

**OQ-017-D — How does an agency get verified?**
`ProviderVerification` targets a provider, not an agency. Today an agency's level can only be
set from the Django admin — which makes REQ-3 safe but leaves the intended flow unbuilt.
Needs either an agency-scoped verification submission or a deliberate "admin-only, by
arrangement" decision.

## 8. Related

- SPEC-014 (the model, and REQ-7 inheritance this exposes), ADR-021 (agency shape)
- SPEC-013 (verification levels — what REQ-3 protects)
- `docs/SECURITY.md` SEC-GAP-36
