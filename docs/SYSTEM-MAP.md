# Autrifix System Map

Autrifix consists of four sibling projects:

```text
autrifix-be/
  Django + Django REST Framework
  Backend/API

autrifix-web/
  Next.js
  Web client

autrifix-mobile/
  Mobile client
  Not started

landing-page/
  Public marketing website
```

## Dependency direction

```text
                 ┌──────────────────┐
                 │   Autrifix BE    │
                 │ Django / DRF API  │
                 └───────┬──────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
       ┌──────▼──────┐      ┌──────▼──────┐
       │ Autrifix Web│      │Autrifix Mobile│
       └─────────────┘      └───────────────┘

       ┌──────────────────────┐
       │    Landing Page      │
       │ Public marketing site│
       └──────────────────────┘
```

The backend owns authoritative domain state and API contracts.

Web and mobile are clients.

The landing page communicates the product publicly and should not invent product capabilities.

## Cross-project changes

When a feature spans projects:

1. define product behavior;
2. update backend contract/spec;
3. update web/mobile client specs;
4. implement backend;
5. implement clients;
6. test integration;
7. review cross-project consistency.
