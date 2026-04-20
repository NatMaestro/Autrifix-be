from rest_framework import generics, permissions

from apps.accounts.permissions import IsMechanic
from apps.mechanics.models import MechanicProfile, MechanicServiceOffering
from apps.mechanics.serializers import MechanicProfileSerializer, MechanicServiceOfferingSerializer


class MechanicProfileDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = MechanicProfileSerializer
    permission_classes = (permissions.IsAuthenticated, IsMechanic)

    def get_object(self):
        user = self.request.user
        default_name = (
            user.email.split("@")[0]
            if user.email
            else (user.phone or "Workshop")
        )
        profile, _ = MechanicProfile.objects.get_or_create(
            user=user,
            defaults={"business_name": default_name},
        )
        return profile


class MechanicServiceOfferingListCreateView(generics.ListCreateAPIView):
    serializer_class = MechanicServiceOfferingSerializer
    permission_classes = (permissions.IsAuthenticated, IsMechanic)

    def get_queryset(self):
        mechanic = MechanicProfile.objects.get(user=self.request.user)
        return (
            MechanicServiceOffering.objects.filter(mechanic=mechanic)
            .select_related("category")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        mechanic = MechanicProfile.objects.get(user=self.request.user)
        serializer.save(mechanic=mechanic)


class MechanicServiceOfferingDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MechanicServiceOfferingSerializer
    permission_classes = (permissions.IsAuthenticated, IsMechanic)
    lookup_field = "id"

    def get_queryset(self):
        mechanic = MechanicProfile.objects.get(user=self.request.user)
        return MechanicServiceOffering.objects.filter(mechanic=mechanic).select_related("category")
