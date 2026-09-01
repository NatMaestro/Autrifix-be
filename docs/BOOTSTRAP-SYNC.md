# Autrifix SDD Bootstrap Task

> **Completed for `autrifix-be` on 2026-08-17.**
>
> Every spec under `specs/` and every document under `docs/` was rewritten from code evidence in
> that pass. No application code, migration, or dependency was changed. The resulting report is
> recorded in [`SYNC-REPORT.md`](SYNC-REPORT.md).
>
> Re-run this task only when adopting SDD in another project (`autrifix-web`,
> `autrifix-mobile`, `landing-page`). For ongoing work on this backend, follow
> [`AGENT-WORKFLOW.md`](AGENT-WORKFLOW.md) instead.

Run this task once after copying these SDD files into an existing repository.

## Objective

Replace the initial baseline documentation with evidence from the current codebase.

## Instructions

1. Read `CLAUDE.md`.
2. Read `docs/SYSTEM-MAP.md`.
3. Read `docs/AGENT-WORKFLOW.md`.
4. Inspect the entire source tree.
5. Inspect dependency manifests.
6. Inspect configuration/environment references without exposing secrets.
7. Inspect tests.
8. Inspect routes/pages/endpoints.
9. Inspect models/schema/migrations where applicable.
10. Inspect authentication/authorization.
11. Inspect integrations.
12. Inspect deployment configuration.
13. Compare findings against `specs/`.
14. Update the relevant specs.
15. Mark implementation status accurately.
16. Add implementation notes where behavior is observed but product intent is uncertain.
17. Add open questions for decisions that cannot be inferred safely.
18. Do not change application code during this synchronization pass.
19. Produce a final "Spec Synchronization Report".

## Synchronization Report

Include:

### Implemented
- ...

### Partial
- ...

### Missing
- ...

### Conflicts
- ...

### Unknown / Needs Product Decision
- ...

### Recommended Next Slice
- ...
