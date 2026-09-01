# Autrifix Backend Documentation

This directory documents the Django/DRF backend.

**Last synchronized with code:** 2026-08-17 — see [`SYNC-REPORT.md`](SYNC-REPORT.md).

## Core documents

| Document | Contents |
|---|---|
| [`PRODUCT.md`](PRODUCT.md) | Product context and baseline constraints, plus signals observed in the backend |
| [`DOMAIN.md`](DOMAIN.md) | Implemented entity map, relationships, and state machines |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Stack, layering, realtime, async work, integrations, deployment |
| [`API.md`](API.md) | Full endpoint inventory and contract conventions |
| [`SECURITY.md`](SECURITY.md) | Security baseline plus a standing assessment and numbered findings |
| [`CONVENTIONS.md`](CONVENTIONS.md) | Conventions as practised in this codebase |
| [`DECISIONS.md`](DECISIONS.md) | ADRs, including decisions recovered from the code |
| [`FEATURE-MATRIX.md`](FEATURE-MATRIX.md) | Per-capability implementation status |
| [`SYSTEM-MAP.md`](SYSTEM-MAP.md) | How the four Autrifix projects relate |
| [`AGENT-WORKFLOW.md`](AGENT-WORKFLOW.md) | The workflow to follow for feature work |
| [`SYNC-REPORT.md`](SYNC-REPORT.md) | Result of the initial codebase-to-spec synchronization |
| [`IMPLEMENTATION-LOG.md`](IMPLEMENTATION-LOG.md) | What has shipped since, with evidence and client-visible changes |
| [`REVIEW-GUIDE.md`](REVIEW-GUIDE.md) | Where to focus a review, ordered by consequence-if-wrong |
| [`BOOTSTRAP-SYNC.md`](BOOTSTRAP-SYNC.md) | The one-off adoption task — **already complete for this project** |

## Specs

Feature specifications live under [`../specs/`](../specs/). Start at
[`specs/README.md`](../specs/README.md) for the feature index, the implementation-status
vocabulary, and the requirement-provenance convention.

## Reading order

- **New to the backend:** `ARCHITECTURE.md` → `DOMAIN.md` → `API.md`.
- **Picking up work:** `IMPLEMENTATION-LOG.md` for current state, then `SECURITY.md`
  "Remaining work" and `DECISIONS.md` "Open decisions".
- **Reviewing the work so far:** start at `REVIEW-GUIDE.md`.
- **Reviewing a change:** `SECURITY.md` and `CONVENTIONS.md`, then the spec's §12–§15.
- **Integrating a client:** `API.md`, plus the client-visible changes table in
  `IMPLEMENTATION-LOG.md`.

## Standing caveat

Specifications state intended behavior; the codebase is evidence of actual behavior. Where the
two disagree the disagreement is recorded as a `CONFLICT` in the relevant spec rather than
silently resolved. Requirements marked `OBSERVED` were reconstructed from code and still need
product confirmation before being treated as committed (`DECISIONS.md` ADR-002).
