"""Agency membership vocabulary — SPEC-014 REQ-6.

An agency is a business that fields several providers: a garage chain, or a towing company
with a fleet. The individual provider stays the unit of work — they hold the profile, accept
the job, and chat with the customer — while the agency is who the business *is*.

Keeping the job attached to the individual rather than the agency is deliberate: a customer
needs to know which person is coming, and the audit trail needs a person to attribute
actions to.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class AgencyRole(models.TextChoices):
    """What a member may do inside their agency."""

    OWNER = "owner", _("Owner")
    MANAGER = "manager", _("Manager")
    OPERATOR = "operator", _("Operator")


#: Roles that may administer the agency itself — invite, remove, edit the business.
AGENCY_ADMIN_ROLES = frozenset({AgencyRole.OWNER, AgencyRole.MANAGER})


class MembershipStatus(models.TextChoices):
    INVITED = "invited", _("Invited")
    ACTIVE = "active", _("Active")
    REMOVED = "removed", _("Removed")
