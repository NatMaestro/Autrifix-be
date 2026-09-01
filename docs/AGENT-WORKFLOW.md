# Autrifix Agent Workflow

## Standard workflow

### 1. Explore

Read:

- `CLAUDE.md`
- relevant `docs/*`
- relevant `specs/*`
- current implementation

### 2. Specify

Before significant implementation, make the intended behavior precise.

If the spec is incomplete, update it first.

### 3. Plan

Create a short implementation plan:

- files/modules affected;
- data/API changes;
- UI changes;
- tests;
- migration/deployment concerns.

### 4. Implement

Implement only the approved scope.

### 5. Verify

Run relevant:

- unit tests;
- integration tests;
- type checks;
- lint;
- build;
- migrations/checks.

Use the project's actual commands; do not invent commands.

### 6. Review

Have a second agent/reviewer inspect the change.

### 7. Synchronize

Update:

- specification status;
- acceptance criteria;
- implementation notes;
- verification evidence;
- decision records if a significant decision occurred.

## Reviewer prompt

> Review this implementation against the relevant Autrifix specification. Do not rewrite the feature. Identify requirement gaps, incorrect assumptions, security/authorization issues, state-transition bugs, API incompatibilities, missing edge cases, test gaps, regressions, and documentation/spec mismatches. Classify findings as BLOCKER, HIGH, MEDIUM, LOW, or NOTE. Only mark the work ready when there are no unresolved BLOCKER/HIGH findings.

## Important

The reviewer is not allowed to approve a feature solely because tests pass. Tests can encode the wrong behavior.

The specification and product intent remain the reference for correctness.
