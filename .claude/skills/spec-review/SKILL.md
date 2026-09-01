---
name: spec-review
description: Review an Autrifix implementation against its specification.
---

# Specification Review

Check:

- every acceptance criterion;
- API contract;
- authorization;
- state transitions;
- validation;
- edge cases;
- security;
- concurrency/race conditions;
- data integrity;
- tests;
- regressions;
- observability;
- documentation.

Classify findings:

- BLOCKER
- HIGH
- MEDIUM
- LOW
- NOTE

Do not approve work with unresolved BLOCKER/HIGH findings.
