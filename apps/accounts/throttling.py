"""Login throttling keyed by the account being targeted.

The project-wide ``auth`` scope is keyed by IP (or user), so an attacker spreading attempts
across addresses could grind a single account, and a single NAT'd office could exhaust the
budget for everyone behind it. This adds a second, independent limit keyed by the
*identifier being attempted* (``docs/SECURITY.md`` SEC-GAP-01).

Both limits apply; whichever is reached first returns ``429``.
"""

from __future__ import annotations

import hashlib

from rest_framework.throttling import SimpleRateThrottle


class LoginIdentifierRateThrottle(SimpleRateThrottle):
    """Rate-limit login attempts per targeted account identifier."""

    scope = "login_identifier"

    def get_cache_key(self, request, view):
        data = request.data if isinstance(getattr(request, "data", None), dict) else {}
        identifier = (
            (data.get("identifier") or "")
            or (data.get("email") or "")
            or (data.get("phone") or "")
        )
        identifier = str(identifier).strip().lower()
        if not identifier:
            # Nothing to key on; the IP-based scopes still apply.
            return None
        # Hashed so cache keys never contain an email address or phone number.
        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}
