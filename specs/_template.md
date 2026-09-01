# SPEC-XXX — <Feature Name>

**Status:** DRAFT  
**Owner:** Product / Engineering  
**Last Updated:** YYYY-MM-DD  
**Scope:** <backend | web | mobile | landing | cross-platform>

## 1. Summary

<One paragraph describing the feature and why it exists.>

## 2. Problem

<What user/business problem does this solve?>

## 3. Actors

- Customer
- Service Provider
- Administrator
- Other: <...>

Only include actors that actually participate in this feature.

## 4. Goals

- ...

## 5. Non-Goals

- ...

## 6. Requirements

### REQ-1
**ID:** PROD-XXX-001  
**Priority:** Must / Should / Could

<Precise requirement.>

### REQ-2
...

## 7. User Flow

1. ...
2. ...
3. ...

## 8. Business Rules

- ...

## 9. State Model

```text
STATE_A -> STATE_B -> STATE_C
```

Allowed transitions:

| From | Action | To | Actor | Conditions |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

## 10. API Contract

If applicable:

### Endpoint

`METHOD /path`

Authentication:
- Required / Not required

Permissions:
- ...

Request:
```json
{}
```

Response:
```json
{}
```

Errors:
- `400` ...
- `401` ...
- `403` ...
- `404` ...
- `409` ...

## 11. Data Model

Relevant entities:

- ...

Relationships:

- ...

## 12. Security

- Authentication:
- Authorization:
- Object-level access:
- Sensitive data:
- Abuse/rate limiting:
- Auditability:

## 13. Edge Cases

- ...
- ...
- ...

## 14. Acceptance Criteria

- [ ] ...
- [ ] ...
- [ ] ...

## 15. Tests

### Unit
- ...

### Integration
- ...

### E2E
- ...

## 16. Observability

- Logs:
- Metrics:
- Errors:
- Audit events:

## 17. Dependencies

- ...

## 18. Open Questions

- ...

## 19. Implementation Notes

Keep implementation-specific observations separate from product requirements.

## 20. Verification Evidence

- Tests:
- Commands:
- Relevant files:
- Review:
