# Autrifix — Claude Code Project Instructions

## 1. Mission

Autrifix is an automotive/mechanical assistance platform. It is being developed as four related applications:

- `autrifix-be` — Django + Django REST Framework backend/API
- `autrifix-web` — Next.js web application
- `autrifix-mobile` — mobile application; implementation has not started yet
- `landing-page` — public marketing/landing website

Treat the specification repository in this project as the source of truth for intended behavior. Treat the existing codebase as the source of truth for what is actually implemented.

The two must not be confused.

## 2. Spec-Driven Development Rules

Before implementing a non-trivial feature:

1. Find the relevant specification under `specs/`.
2. Read the applicable product, domain, architecture, and API documentation.
3. Inspect the existing implementation before proposing changes.
4. Identify conflicts between the specification and the current code.
5. Update the specification when the intended behavior has changed.
6. Implement only the agreed behavior.
7. Add/update tests.
8. Run the relevant validation commands.
9. Review the diff for unintended changes.
10. Update implementation status/documentation.

Never silently invent product requirements.

If a requirement is unknown, mark it as `OPEN`, `TBD`, or `ASSUMPTION` and continue only when the uncertainty does not affect correctness.

## 3. Existing Code Is Evidence, Not Automatically the Spec

When documentation and code disagree:

- If the documented behavior is clearly intentional and current: align code to the spec.
- If the code represents a newer deliberate product decision: update the spec first, then implement/retain the code.
- If neither is clear: do not guess. Record the conflict in `docs/DECISIONS.md` or the relevant spec and ask for clarification when needed.

## 4. Scope Discipline

Do not:

- rewrite unrelated code;
- introduce a new framework without justification;
- change public APIs casually;
- change database models without checking downstream consumers;
- add dependencies merely for convenience;
- claim a feature is complete because a model/page/component exists;
- mark a specification complete without verification.

Prefer small, reviewable changes.

## 5. Specification Status

Use these statuses:

- `DRAFT` — proposed, incomplete, or not yet agreed
- `READY` — sufficiently precise to implement
- `IN_PROGRESS` — implementation underway
- `IMPLEMENTED` — implementation exists but verification may still be incomplete
- `VERIFIED` — implementation and tests/validation agree with the spec
- `DEPRECATED` — replaced by another specification

## 6. Requirement IDs

Requirements should use stable IDs:

- `PROD-*` — product requirements
- `DOM-*` — domain rules
- `API-*` — API behavior
- `WEB-*` — web behavior
- `MOB-*` — mobile behavior
- `LAND-*` — landing-page behavior
- `SEC-*` — security
- `NFR-*` — non-functional requirements

Do not renumber IDs merely because a document was reorganized.

## 7. Implementation Loop

Use this loop:

SPEC → PLAN → IMPLEMENT → TEST → REVIEW → UPDATE SPEC

A feature is not finished until the specification, implementation, and verification evidence are consistent.

## 8. Agent Review

For significant work, use a second review pass.

The implementation agent should not be the only judge of correctness.

The reviewer should inspect:

- requirement coverage;
- edge cases;
- security;
- authorization;
- API contract compatibility;
- data integrity;
- race/concurrency concerns;
- error handling;
- tests;
- regressions;
- documentation/spec accuracy.

The reviewer should report findings before code is considered complete.

## 9. Existing Project First

Before changing a project, inspect:

- package/dependency files;
- environment/configuration;
- source tree;
- routing;
- authentication;
- models/schema;
- API clients;
- existing tests;
- deployment configuration;
- database migrations;
- current documentation.

Do not assume the starter documentation is accurate. The initial SDD files in this repository are intentionally a baseline and should be enriched from the existing codebase.

## 10. Definition of Done

A feature is `VERIFIED` only when:

- the relevant spec is precise;
- acceptance criteria are satisfied;
- implementation is complete;
- automated tests exist where appropriate;
- relevant checks pass;
- authorization/security has been considered;
- API/client contracts are consistent;
- documentation is updated;
- a separate review has found no unresolved blocking issue.

## 11. When Asked to "Implement"

Do not immediately code a large feature.

First provide a concise implementation plan based on the relevant specification unless the task is clearly trivial.

Then implement the smallest coherent slice.

## 12. When Asked to "Update the Specs"

Inspect the codebase first.

Do not merely rewrite the starter markdown. Recover what is actually implemented, distinguish it from intended behavior, and update the documentation with evidence from the code.


## Backend-Specific Rules

Autrifix backend is Django + Django REST Framework.

Priorities:

1. Correct domain modeling.
2. Explicit authorization.
3. Stable API contracts.
4. Database integrity.
5. Testability.
6. Safe migrations.
7. Clear separation of business logic from transport concerns.

Before changing a model:

- inspect existing migrations;
- inspect serializers;
- inspect views/viewsets;
- inspect permissions;
- inspect consumers/tasks/signals if present;
- inspect frontend consumers;
- determine migration impact.

Do not expose fields merely because they exist on a model.

Prefer explicit serializers and permission checks.

For stateful workflows, define valid transitions rather than allowing arbitrary status updates.

When implementing an endpoint, update the corresponding API specification and test the success, validation, authorization, not-found, and conflict paths.
