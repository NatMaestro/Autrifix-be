"""Agency HTTP surface — SPEC-017.

Two resource families, split by whose thing they are:

- ``/providers/agencies/...`` — the business, seen from inside it. Membership is what makes
  it visible at all; administration is what makes it writable.
- ``/providers/memberships/...`` — the individual's own place in an agency, including
  invitations they have not accepted. An invitee is not yet a member, so their invitation
  cannot live behind an agency-scoped lookup.

Authorization lives in ``agency_services``, not here. These views resolve the actors and
hand off.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsProvider
from apps.providers import agency_services
from apps.providers.agencies import MembershipStatus
from apps.providers.agency_serializers import (
    AgencyCreateSerializer,
    AgencyInviteSerializer,
    AgencyMembershipSerializer,
    AgencySerializer,
    AgencyUpdateSerializer,
    MembershipRespondSerializer,
    MembershipRoleSerializer,
)
from apps.providers.models import AgencyMembership
from apps.providers.selectors import ensure_provider_profile


class ProviderScopedMixin:
    permission_classes = (permissions.IsAuthenticated, IsProvider)

    def provider(self):
        return ensure_provider_profile(self.request.user)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False):
            ctx["provider"] = self.provider()
        return ctx


@extend_schema(
    tags=["agencies"],
    summary="Create an agency",
    request=AgencyCreateSerializer,
    responses={201: AgencySerializer},
)
class AgencyCreateView(ProviderScopedMixin, generics.CreateAPIView):
    """The creator becomes the agency's first active owner.

    A provider holds at most one live membership, so creating while already in an agency is
    a `409` rather than a silent second membership.
    """

    serializer_class = AgencyCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = AgencyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        agency = agency_services.create_agency(
            provider=self.provider(), **serializer.validated_data
        )
        return Response(
            AgencySerializer(agency, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["agencies"], summary="Read or edit an agency")
class AgencyDetailView(ProviderScopedMixin, APIView):
    """Visible only to its own members; `404` otherwise, so ids stay unconfirmable.

    `verification_level` is absent from the writable fields on purpose — an agency that
    could set its own level would lift every member's effective level with it.
    """

    serializer_class = AgencySerializer

    def get(self, request, id):
        provider = self.provider()
        agency = agency_services.visible_agency_or_404(provider, id)
        return Response(AgencySerializer(agency, context={"provider": provider}).data)

    @extend_schema(request=AgencyUpdateSerializer, responses={200: AgencySerializer})
    def patch(self, request, id):
        provider = self.provider()
        agency = agency_services.visible_agency_or_404(provider, id)

        serializer = AgencyUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        agency = agency_services.update_agency(
            agency=agency, provider=provider, **serializer.validated_data
        )
        return Response(AgencySerializer(agency, context={"provider": provider}).data)


@extend_schema(tags=["agencies"], summary="List members or invite one")
class AgencyMemberListCreateView(ProviderScopedMixin, generics.ListCreateAPIView):
    """Any member reads the roster; only an owner or manager adds to it.

    Invitations are addressed by the phone number the provider signed up with — the only
    identifier an agency admin plausibly knows for their own staff.
    """

    throttle_scope = "agency_invite"

    def get_throttles(self):
        # Scoped only on the write path: listing the roster is not the abusable direction.
        if self.request.method == "POST":
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_serializer_class(self):
        return (
            AgencyInviteSerializer
            if self.request.method == "POST"
            else AgencyMembershipSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AgencyMembership.objects.none()
        agency = agency_services.visible_agency_or_404(self.provider(), self.kwargs["id"])
        return (
            agency.memberships.exclude(status=MembershipStatus.REMOVED)
            .select_related("provider__user", "agency")
            .order_by("role", "invited_at")
        )

    @extend_schema(request=AgencyInviteSerializer, responses={201: AgencyMembershipSerializer})
    def create(self, request, *args, **kwargs):
        provider = self.provider()
        agency = agency_services.visible_agency_or_404(provider, self.kwargs["id"])

        serializer = AgencyInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership = agency_services.invite_provider(
            agency=agency,
            actor_provider=provider,
            phone=serializer.validated_data["phone"],
            role=serializer.validated_data["role"],
        )
        return Response(
            AgencyMembershipSerializer(membership).data, status=status.HTTP_201_CREATED
        )


@extend_schema(tags=["agencies"], summary="Change a member's role, or remove them")
class AgencyMemberDetailView(ProviderScopedMixin, APIView):
    """`DELETE` is both "remove this person" and "leave this agency".

    Removal is a status change rather than a delete: an agency that could erase who worked
    for it would erase the attribution the audit trail depends on.
    """

    serializer_class = AgencyMembershipSerializer

    def _membership(self, agency, membership_id) -> AgencyMembership:
        from rest_framework.generics import get_object_or_404

        return get_object_or_404(
            AgencyMembership.objects.select_related("provider__user", "agency"),
            id=membership_id,
            agency=agency,
        )

    @extend_schema(request=MembershipRoleSerializer, responses={200: AgencyMembershipSerializer})
    def patch(self, request, id, membership_id):
        provider = self.provider()
        agency = agency_services.visible_agency_or_404(provider, id)
        membership = self._membership(agency, membership_id)

        serializer = MembershipRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership = agency_services.change_member_role(
            agency=agency,
            actor_provider=provider,
            membership=membership,
            role=serializer.validated_data["role"],
        )
        return Response(AgencyMembershipSerializer(membership).data)

    @extend_schema(responses={200: AgencyMembershipSerializer})
    def delete(self, request, id, membership_id):
        provider = self.provider()
        agency = agency_services.visible_agency_or_404(provider, id)
        membership = self._membership(agency, membership_id)

        membership = agency_services.remove_member(
            agency=agency, actor_provider=provider, membership=membership
        )
        return Response(AgencyMembershipSerializer(membership).data)


@extend_schema(
    tags=["agencies"],
    summary="My agency memberships and invitations",
    responses={200: AgencyMembershipSerializer(many=True)},
)
class MyMembershipListView(ProviderScopedMixin, generics.ListAPIView):
    """Includes invitations not yet answered — which is the point of the endpoint."""

    serializer_class = AgencyMembershipSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AgencyMembership.objects.none()
        return (
            AgencyMembership.objects.filter(
                provider=self.provider(),
                status__in=agency_services.LIVE_MEMBERSHIP_STATUSES,
            )
            .select_related("agency", "provider__user")
            .order_by("-invited_at")
        )


@extend_schema(
    tags=["agencies"],
    summary="Accept or decline an agency invitation",
    request=MembershipRespondSerializer,
    responses={200: AgencyMembershipSerializer},
)
class MembershipRespondView(ProviderScopedMixin, APIView):
    serializer_class = MembershipRespondSerializer

    def post(self, request, id):
        from rest_framework.generics import get_object_or_404

        provider = self.provider()
        membership = get_object_or_404(
            AgencyMembership.objects.select_related("agency", "provider__user"),
            id=id,
            provider=provider,
        )

        serializer = MembershipRespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership = agency_services.respond_to_invitation(
            membership=membership,
            provider=provider,
            accept=serializer.validated_data["accept"],
        )
        return Response(AgencyMembershipSerializer(membership).data)
