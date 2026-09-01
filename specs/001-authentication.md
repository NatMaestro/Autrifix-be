# SPEC-001 — Authentication & Identity

**Status:** VERIFIED
**Owner:** Product / Engineering
**Last Updated:** 2026-08-18
**Scope:** backend

## 1. Summary

Autrifix issues JWT credentials to three kinds of identity: customer, provider, and admin.
A single `User` model carries the role; there is no separate identity provider. Three sign-in
paths exist in code: email/phone + password, Google ID token, and SMS one-time code.

## 2. Problem

Customers and providers need an account before they can post or accept work, on both web and
(future) mobile clients, in a market where email is not universal.

## 3. Actors

- Customer
- Service Provider
- Administrator (Django admin / superuser only)

## 4. Goals

- Single identity per person, usable from any client.
- Role attached to identity at signup.
- Stateless API auth suitable for web and mobile.

## 5. Non-Goals

- Email verification flows (removed from the schema — see §19).
- Social providers other than Google.
- Multi-tenant / organization accounts.

## 6. Requirements

### REQ-1 — Password registration
**ID:** PROD-001-001 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A visitor may create an account with `email`, `phone`, `password`, `password_confirm`, and an
optional `role` of `customer` or `provider`. Both email and phone are required. The response
returns the user profile plus a JWT access/refresh pair.

Evidence: [apps/accounts/serializers.py:64-112](apps/accounts/serializers.py#L64-L112), [apps/accounts/views.py:320-334](apps/accounts/views.py#L320-L334)

### REQ-2 — Password login by either identifier
**ID:** PROD-001-002 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A user may authenticate with a single `identifier` field containing either an email address or
an E.164 phone number, plus `password`. Legacy `email` / `phone` keys are accepted as aliases;
the first non-empty value wins.

Evidence: [apps/accounts/serializers.py:26-61](apps/accounts/serializers.py#L26-L61), [apps/accounts/auth_utils.py:9-20](apps/accounts/auth_utils.py#L9-L20)

### REQ-3 — Google sign-in
**ID:** PROD-001-003 · **Priority:** Should · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

A visitor may exchange a Google Identity Services `id_token` for a JWT pair. On first sign-in
the account is created from the Google email with an optional `role`, and the matching customer
or provider profile is created eagerly. Returns `503` when `GOOGLE_OAUTH_CLIENT_ID` is unset or
the `google-auth` package is missing.

Evidence: [apps/accounts/views.py:231-295](apps/accounts/views.py#L231-L295)

### REQ-4 — Phone OTP sign-in
**ID:** PROD-001-004 · **Priority:** Could · **Provenance:** OBSERVED · **Status:** PARTIAL

`POST /auth/send-otp/` issues a 6-digit code by SMS; `POST /auth/verify-otp/` consumes it and
returns a JWT pair, creating a passwordless account on first success.

`PARTIAL` because: OTP accounts are created with no customer/provider profile, and the OpenAPI
description labels these endpoints "legacy … for future use" while the code path is live.

Evidence: [apps/accounts/views.py:110-205](apps/accounts/views.py#L110-L205), [apps/accounts/otp_service.py](apps/accounts/otp_service.py), [autrifix/settings/base.py:206-212](autrifix/settings/base.py#L206-L212)

**OPEN QUESTION (OQ-001-A):** Is phone-OTP sign-in a supported MVP path, a deprecated path, or
a future path? Code, README, and OpenAPI description disagree.

### REQ-5 — Token lifecycle
**ID:** API-001-005 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Access tokens are short-lived and refresh tokens rotate; the previous refresh token is
blacklisted after rotation. Logout blacklists the presented refresh token.

| Setting | development | production |
|---|---|---|
| `ACCESS_TOKEN_LIFETIME` | 60 min | 15 min (`JWT_ACCESS_MINUTES`) |
| `REFRESH_TOKEN_LIFETIME` | 14 days | 7 days (`JWT_REFRESH_DAYS`) |
| `ROTATE_REFRESH_TOKENS` | true | true |
| `BLACKLIST_AFTER_ROTATION` | true | true |

Evidence: [autrifix/settings/base.py:196-204](autrifix/settings/base.py#L196-L204), [autrifix/settings/production.py:52-54](autrifix/settings/production.py#L52-L54)

### REQ-6 — Self-service profile read/update
**ID:** API-001-006 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

An authenticated user may read and update their own account at `/me/`. Writable: `email`,
`first_name`, `last_name`, `avatar`. Read-only: `id`, `phone`, `role`, `is_email_verified`,
`date_joined`.

`email` updates are checked case-insensitively against other accounts, matching the
case-insensitive lookup login uses.

Evidence: [apps/accounts/views.py](apps/accounts/views.py), [apps/accounts/serializers.py](apps/accounts/serializers.py)

### REQ-10 — Brute-force protection is per targeted account
**ID:** SEC-001-010 · **Priority:** Must · **Provenance:** PRODUCT (`docs/SECURITY.md`) · **Status:** IMPLEMENTED

Login attempts are limited **twice over**: by the IP-keyed `auth` scope, and independently by
the identifier being targeted.

| Scope | Keyed on | development | production |
|---|---|---|---|
| `auth` | IP (or user) | 30/min | 20/min |
| `login_identifier` | the submitted identifier, SHA-256 hashed | 10/min | 5/min |

Without the second limit, an attacker spreading attempts across addresses could grind one
account, and one NAT'd office could exhaust the shared budget for everyone behind it. The
identifier is hashed so cache keys never contain an email address or phone number.

**IMPLEMENTATION NOTE:** the limit counts *attempts*, not failures, which is DRF's standard
behavior. At 5–10/min a legitimate user retyping a password is unaffected.

Evidence: [apps/accounts/throttling.py](apps/accounts/throttling.py), applied via `LOGIN_THROTTLES` in [apps/accounts/views.py](apps/accounts/views.py)

### REQ-9 — Role is not self-service
**ID:** SEC-001-009 · **Priority:** Must · **Provenance:** PRODUCT (decided 2026-08-17) · **Status:** IMPLEMENTED

A user's `role` is fixed at signup and cannot be changed by the account holder. Changing it
requires an administrator.

Rationale: `role` decides which endpoints an account may reach, including accepting jobs and
publishing a workshop location. With no provider-verification gate in place (SPEC-003 REQ-6),
self-assignment would let any customer become a live service provider instantly.

Recorded as ADR-013 in `docs/DECISIONS.md`.

**Because the choice is permanent, it must never be made by default (ADR-023, 2026-09-01).**
`/auth/google/` and `/auth/verify-otp/` create an account on first use, and both used to fall
back to `customer` when the client sent no role — silently and irreversibly assigning a
provider to the customer side of the product, closing the provider funnel for those two paths
without any error.

Creating an account now requires an explicit role. Where one would be needed and none was
given, both endpoints return `400` with:

```json
{"code": "signup_role_required", "choices": ["customer", "provider"]}
```

Signing in to an *existing* account is unaffected, and a supplied role still applies only at
creation — it is not a route around this requirement.

Two implementation constraints this imposes, both load-bearing:

- The OTP code is validated **before** any account lookup, so the endpoint cannot be used to
  discover which phone numbers are registered.
- Validation is separated from consumption (`PhoneOTP.is_code_valid`). Refusing after
  consuming would burn the caller's only code and make the retry-with-a-role fail as
  "invalid or expired" — turning a recoverable prompt into a dead end.

Evidence: `read_only_fields` on [apps/accounts/serializers.py](apps/accounts/serializers.py)
`UserSerializer`; [apps/accounts/views.py](apps/accounts/views.py) `signup_role_required_response`;
verified by `test_me_cannot_change_role` and `tests/test_signup_role.py` (8).

### REQ-7 — Role assignment is not self-elevating to admin
**ID:** SEC-001-007 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Neither registration nor profile update may set `role = admin`.

Evidence: [apps/accounts/serializers.py:95-96](apps/accounts/serializers.py#L95-L96), [apps/accounts/serializers.py:142-145](apps/accounts/serializers.py#L142-L145)

### REQ-8 — Ghana-first phone normalization
**ID:** DOM-001-008 · **Priority:** Must · **Provenance:** OBSERVED · **Status:** IMPLEMENTED

Phone input is normalized to E.164. Local numbers beginning `0` are mapped to `+233` (Ghana).

Evidence: [apps/accounts/phone.py:8-29](apps/accounts/phone.py#L8-L29)

**OPEN QUESTION (OQ-001-B):** Is Ghana the committed launch market, or is `+233` a development
default? A non-Ghanaian local number silently becomes a Ghanaian one.

## 7. User Flow

**Password:** register (email + phone + password) → receive tokens → call `/me/` → client routes
by `role`.
**Google:** client obtains `id_token` → `POST /auth/google/` → receive tokens.
**OTP:** `POST /auth/send-otp/` → receive SMS → `POST /auth/verify-otp/` → receive tokens.

## 8. Business Rules

- Email uniqueness is enforced case-insensitively at the serializer; the DB constraint is
  case-sensitive `unique`. IMPLEMENTATION NOTE: Google sign-in also matches `email__iexact`.
- A `User` row must have at least a phone or an email (`CheckConstraint accounts_user_phone_or_email`).
- Registration requires **both**; only Google and OTP produce single-identifier accounts.
- Password strength uses Django's default validator set (min length, common-password, numeric,
  attribute-similarity) plus a serializer `min_length=8`.
- OTP codes are stored as `SHA-256(SECRET_KEY:phone:code)`, never in plaintext, TTL 300s default,
  and issuing a new code consumes all outstanding codes for that phone.

## 9. State Model

Identity has no explicit state machine. Relevant flags:

| Field | Meaning | Written by |
|---|---|---|
| `is_active` | Django default; blocks login when false | Admin only |
| `is_email_verified` | Set true only by Google when Google reports `email_verified` | `GoogleAuthView` |
| `role` | customer / provider / admin | Signup, `/me/` (see CONFLICT-001-A) |

**IMPLEMENTATION NOTE:** `is_email_verified` is never set by the password-registration path, so
password accounts remain unverified forever and nothing consumes the flag.

## 10. API Contract

Base path: `/api/v1/`. Scheme: `Authorization: Bearer <access>`.

| Method | Path | Auth | Permission | Throttle |
|---|---|---|---|---|
| POST | `/auth/register/` | none | AllowAny | `auth` |
| POST | `/auth/login/` | none | (default) | `auth` |
| POST | `/auth/google/` | none | AllowAny | `auth` |
| POST | `/auth/send-otp/` | none | AllowAny | `auth` + per-phone cap |
| POST | `/auth/verify-otp/` | none | AllowAny | `auth` |
| POST | `/auth/logout/` | none (refresh token in body) | — | none |
| POST | `/auth/token/` | none | (default) | `auth` |
| POST | `/auth/token/refresh/` | none | (default) | `auth` |
| POST | `/auth/refresh-token/` | none | (default) | `auth` |
| GET/PUT/PATCH | `/me/` | JWT | IsAuthenticated | `user` |
| GET | `/health/` | none | AllowAny | `anon` |

`POST /auth/register/` request:

```json
{ "email": "a@b.com", "phone": "+233540000001", "password": "…", "password_confirm": "…", "role": "customer" }
```

Response `201`:

```json
{ "id": "uuid", "phone": "+233…", "email": "a@b.com", "role": "customer",
  "first_name": "", "last_name": "", "avatar": null, "is_email_verified": false,
  "date_joined": "…", "access": "…", "refresh": "…" }
```

`POST /auth/login/` request: `{ "identifier": "a@b.com | +233…", "password": "…" }`
Response `200`: `{ "access": "…", "refresh": "…" }`

Errors:
- `400` — validation (mismatched passwords, duplicate email/phone, unparseable phone, invalid Google token, wrong/expired OTP)
- `401` — `no_active_account` for bad credentials or inactive user
- `429` — throttle scope `auth`, or >`OTP_SEND_MAX_PER_HOUR` OTPs for one phone
- `503` — Google not configured / `google-auth` missing / SMS provider failure

`/me/` read-only fields: `id`, `phone`, `is_email_verified`, `date_joined`.

## 11. Data Model

`accounts.User` (`AUTH_USER_MODEL`, `USERNAME_FIELD = "phone"`, `REQUIRED_FIELDS = []`):

| Field | Type | Notes |
|---|---|---|
| `id` | UUID pk | non-sequential, safe to expose |
| `phone` | char(20) unique, null | E.164 |
| `email` | email unique, null | |
| `avatar` | image | `avatars/` |
| `role` | char(20) indexed | `customer` (default) / `provider` / `admin` |
| `is_email_verified` | bool | |
| + `AbstractUser` fields | | `username` removed |

`accounts.PhoneOTP`: `id`, `phone` (indexed), `code_hash`, `expires_at`, `consumed_at`, `created_at`.

Relationships: `User 1—0..1 CustomerProfile`, `User 1—0..1 ProviderProfile`.

Migrations: `0001_initial` → `0002_phone_otp_auth` → `0003_user_avatar` →
`0004_user_phone_optional` (adds the phone-or-email check constraint) → `0005_email_otp` →
`0006_delete_emailotp`.

## 12. Security

- **Authentication:** `rest_framework_simplejwt.JWTAuthentication` is the only DRF authentication class; it is the project-wide default.
- **Authorization:** DRF default permission is `IsAuthenticated`; auth endpoints opt out with `AllowAny`.
- **Object-level access:** `/me/` resolves the object from `request.user`, so cross-user access is structurally impossible.
- **Sensitive data:** passwords hashed by Django; OTP codes hashed with the secret key; no plaintext credential is persisted or logged.
- **Abuse/rate limiting:** scope `auth` = 30/min (dev) / 20/min (prod); plus a cache counter capping OTP sends per phone per hour.
- **Auditability:** none. No authentication audit log exists.

### CONFLICT-001-A — `role` was client-writable at `/me/`
**Status:** RESOLVED (2026-08-17) · **Severity was:** High

`UserSerializer` exposed `role` as writable and only blocked `admin`, so any authenticated user
could `PATCH /me/ {"role": "provider"}` and immediately gain provider-only endpoints.

**Fix:** `role` added to `read_only_fields` (REQ-9). The now-redundant `validate_role` guard was
removed — a read-only field cannot be set at all, which is a stronger guarantee than validating
its value.

Verified by: `test_me_cannot_change_role`.

### CONFLICT-001-B — Failed login returned 500 instead of 401
**Status:** RESOLVED (2026-08-17) · **Severity was:** High · **Found by:** the tests added in this slice

`IdentifierTokenObtainPairSerializer` raised
`AuthenticationFailed(jwt_api_settings.NO_ACTIVE_ACCOUNT_FOUND)`, but that attribute does not
exist on SimpleJWT 5.4.0's settings object. Every wrong password and every inactive-account login
therefore raised `AttributeError` inside the serializer and returned **`500`**, not `401` — and
logged an exception on each one.

This was not caught by the synchronization pass: the line looks correct and there was no test
exercising a failed login.

**Fix:** replaced with a literal class constant, `NO_ACTIVE_ACCOUNT`, used identically for "no
such user", "wrong password", and "inactive account" so the endpoint cannot be used to enumerate
accounts.

Verified by: `test_login_with_wrong_password_is_401`, `test_login_for_inactive_user_is_401`.

### Security gaps — current status

| ID | Finding | Severity | Status |
|---|---|---|---|
| SECGAP-001-1 | `role` self-assignment via `/me/` | High | **RESOLVED** |
| SECGAP-001-2 | `SECRET_KEY` defaulted to a publicly known literal | Medium | **RESOLVED** — default exists only under `DEBUG`; a non-DEBUG boot without it raises `ImproperlyConfigured` |
| SECGAP-001-3 | `scripts/render-build.sh` exported a hardcoded build-time `SECRET_KEY` | Medium | **RESOLVED** — generates an ephemeral per-build key |
| SECGAP-001-4 | No per-identifier brute-force lockout | Medium | **RESOLVED** — REQ-10 |
| SECGAP-001-5 | `/auth/logout/` has no throttle scope | Low | OPEN |
| SECGAP-001-6 | OTP rate limit is per-process under LocMem in development | Low | OPEN — correct under Redis |
| SECGAP-001-7 | Avatar uploads had no size limit | Low | **RESOLVED** — 5 MB cap via `validate_image_size` |
| SECGAP-001-8 | `/me/` allowed taking an email differing only by case from another account | Low | **RESOLVED** — case-insensitive uniqueness check |

## 13. Edge Cases

- Registering with an email that differs only by case → rejected (`email__iexact`).
- Registering with an email that already exists on a Google-created account → rejected; there is no account-linking flow. **OPEN QUESTION (OQ-001-D):** should a Google user be able to add a password, or a password user sign in with Google?
- `verify-otp` for a phone that already belongs to a password account → logs that user in without a password. **ASSUMPTION:** intentional passwordless fallback; unverified.
- Phone shorter than 9 digits → `400 Invalid phone number format.`
- Google account with no email → `400`.
- Google `email_verified=false` → account still created, `is_email_verified` stays false.
- OTP replay → second use fails, because `verify_and_consume` stamps `consumed_at`.
- Superuser creation requires a phone (`create_superuser` raises otherwise).

## 14. Acceptance Criteria

- [x] Registration returns `201` with profile + tokens.
- [x] Login succeeds with email or E.164 phone.
- [x] Duplicate email or phone returns `400`.
- [x] Bad credentials return `401`, not `400`.
- [x] Refresh rotates and blacklists the old token.
- [x] `role: "admin"` is rejected at registration.
- [x] `role` cannot be changed by the account holder after signup (REQ-9).
- [x] A failed login returns `401`, not `500` (CONFLICT-001-B).
- [x] Bad credentials, unknown account, and inactive account are indistinguishable.
- [x] Per-identifier brute-force protection exists (REQ-10).
- [x] A non-DEBUG boot without `SECRET_KEY` refuses to start.
- [ ] Every sign-in path creates the role-matching profile — **PARTIAL**; profiles are created
      lazily on first use by every customer and provider endpoint, so this is no longer a
      functional gap, only an eager-vs-lazy difference.

## 15. Tests

### Existing — `tests/test_auth.py` (19 tests)
- **Registration:** happy path with tokens; `admin` role rejected; password mismatch; duplicate
  email rejected case-insensitively.
- **Login:** parametrized over `identifier` / `email` / `phone`; wrong password `401`; inactive
  user `401`; missing identifier `400`.
- **Tokens:** refresh rotates and returns a new refresh token; logout blacklists it and a reuse
  attempt returns `401`.
- **`/me/`:** `401` anonymous; returns own profile; updates name; **cannot** change role; cannot
  take another account's email.

- **Throttling:** repeated failed logins for one identifier reach `429`; throttling that
  identifier does **not** lock out a different account.

### Still missing (gap)
- OTP: issue, verify, expiry, replay, per-phone cap.
- Google: missing config → 503; invalid token → 400; existing-email match.

## 16. Observability

- Logs: SMS failures (`logger.exception`), diagnostics requests, unhandled exceptions via `apps.core.exceptions.custom_exception_handler`. In `console` SMS mode the OTP body — including the code — is logged at WARNING.
- Metrics: none.
- Audit events: none.

## 17. Dependencies

`djangorestframework-simplejwt` (+ `token_blacklist`), `google-auth`, optional `twilio`,
Termii over plain HTTP, Django cache (OTP rate limit).

## 18. Open Questions

- **OQ-001-A** — Is phone-OTP sign-in supported, deprecated, or future?
- **OQ-001-B** — Is Ghana (`+233`) the committed default market?
- **OQ-001-C** — ~~May a user change their own role after signup?~~ **RESOLVED 2026-08-17:** no
  (REQ-9, ADR-013). Revisit if provider verification is built (SPEC-003 OQ-003-A).
- **OQ-001-D** — Should Google and password identities for the same email be linked?
- **OQ-001-E** — Is email verification a requirement? The `EmailOTP` model was added in
  `0005_email_otp` and deleted in `0006_delete_emailotp` ("deferred to a later release"), yet
  `User.is_email_verified` remains and nothing consumes it.

## 19. Implementation Notes

- `USERNAME_FIELD` is `phone`, so SimpleJWT's default obtain serializer would demand `phone` +
  `password`. The project overrides `TOKEN_OBTAIN_SERIALIZER` globally to the identifier-based
  serializer to avoid that.
- `IdentifierTokenObtainPairSerializer` is a plain `Serializer`, not SimpleJWT's
  `TokenObtainPairSerializer`; it mints the token pair itself inside `validate()`.
- Four routes reach token issue/refresh (`/auth/login/`, `/auth/token/`, `/auth/refresh-token/`,
  `/auth/token/refresh/`). The alias views are `@extend_schema(exclude=True)`, so the published
  OpenAPI document shows fewer routes than the URLconf serves.
- SMS providers: `console` (logs), `twilio` (SDK), `termii` (raw HTTP, 15s timeout, no retry).
  In `DEBUG`, a Termii failure silently falls back to console delivery.
- `LogoutView` subclasses SimpleJWT's `TokenBlacklistView`, which sets `permission_classes = ()`;
  logout therefore needs no access token, only a valid refresh token.

## 20. Verification Evidence

- Files: [apps/accounts/](apps/accounts/), [autrifix/api_urls.py](autrifix/api_urls.py), [autrifix/settings/base.py](autrifix/settings/base.py)
- Tests: `tests/test_auth.py` — 17 tests, all passing.
- Commands: `pytest -q` → 169 passed; `manage.py makemigrations --check --dry-run` → no changes;
  `manage.py check --deploy` with production settings → 2 advisory warnings only.
- Migration: `accounts/0007` (avatar size validator).
- Review: implemented and self-reviewed 2026-08-17. Not independently reviewed.
