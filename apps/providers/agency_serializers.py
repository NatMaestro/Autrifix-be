"""Agency serializers — SPEC-017.

Input and output are separate classes throughout. The reason is one field:
``verification_level`` is readable but must never be writable, and a single ``ModelSerializer``
with a growing ``read_only_fields`` tuple is one careless edit away from making the trust
ladder self-service (SPEC-014 REQ-7).
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.providers.agencies import AgencyRole, MembershipStatus
from apps.providers.models import Agency, AgencyMembership
from apps.providers.verification import ProviderType

#: Roles that can be handed out through the API. `owner` is reachable only by promoting an
#: existing member, never by invitation — an unaccepted owner is an agency with no live admin.
INVITABLE_ROLES = [
    (AgencyRole.MANAGER, AgencyRole.MANAGER.label),
    (AgencyRole.OPERATOR, AgencyRole.OPERATOR.label),
]


class AgencySerializer(serializers.ModelSerializer):
    """Read shape. Everything here is read-only by construction."""

    member_count = serializers.SerializerMethodField()
    my_role = serializers.SerializerMethodField()

    class Meta:
        model = Agency
        fields = (
            "id",
            "name",
            "slug",
            "provider_type",
            "verification_level",
            "contact_email",
            "contact_phone",
            "registration_number",
            "member_count",
            "my_role",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField())
    def get_member_count(self, agency: Agency) -> int:
        return agency.memberships.filter(status=MembershipStatus.ACTIVE).count()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_my_role(self, agency: Agency):
        """Saves the client a second call to work out which controls to render."""
        provider = self.context.get("provider")
        if provider is None:
            return None
        membership = agency.memberships.filter(
            provider=provider, status=MembershipStatus.ACTIVE
        ).first()
        return membership.role if membership else None


class AgencyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    provider_type = serializers.ChoiceField(
        choices=ProviderType.choices, default=ProviderType.MECHANIC
    )
    contact_email = serializers.EmailField(required=False, allow_blank=True, default="")
    contact_phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True, default=""
    )
    registration_number = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        default="",
        help_text="Registrar General's Department business registration, when available.",
    )


class AgencyUpdateSerializer(serializers.Serializer):
    """Same fields minus the slug, which is derived, and the verification level, which is
    granted by platform review rather than claimed."""

    name = serializers.CharField(max_length=200, required=False)
    provider_type = serializers.ChoiceField(choices=ProviderType.choices, required=False)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    registration_number = serializers.CharField(max_length=64, required=False, allow_blank=True)


class AgencyMembershipSerializer(serializers.ModelSerializer):
    agency_name = serializers.CharField(source="agency.name", read_only=True)
    provider_name = serializers.SerializerMethodField()

    class Meta:
        model = AgencyMembership
        fields = (
            "id",
            "agency",
            "agency_name",
            "provider",
            "provider_name",
            "role",
            "status",
            "invited_at",
            "joined_at",
            "removed_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_provider_name(self, membership: AgencyMembership) -> str:
        provider = membership.provider
        if provider.business_name:
            return provider.business_name
        user = getattr(provider, "user", None)
        full = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip()
        return full or "Provider"


class AgencyInviteSerializer(serializers.Serializer):
    phone = serializers.CharField(
        max_length=20,
        help_text="The phone number the provider signed up with. Local `0…` numbers are normalized.",
    )
    role = serializers.ChoiceField(choices=INVITABLE_ROLES, default=AgencyRole.OPERATOR)


class MembershipRespondSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class MembershipRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=AgencyRole.choices)
