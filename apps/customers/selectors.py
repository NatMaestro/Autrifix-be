"""Single source of truth for resolving a customer's profile.

Previously two different ``ensure_customer_profile`` helpers existed (in ``apps.customers``
and ``apps.jobs``) with different behavior for non-customers.
"""

from __future__ import annotations

from apps.accounts.models import UserRole
from apps.core.exceptions import Conflict
from apps.customers.models import CustomerProfile


def ensure_customer_profile(user) -> CustomerProfile:
    """Return the user's customer profile, creating it on first use.

    Raises ``Conflict`` (409) rather than silently creating a customer profile for a
    user who is not a customer.
    """
    if getattr(user, "role", None) != UserRole.CUSTOMER:
        raise Conflict("This account is not a customer account.")
    profile, _created = CustomerProfile.objects.get_or_create(user=user)
    return profile
