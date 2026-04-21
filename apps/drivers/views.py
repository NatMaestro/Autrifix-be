from rest_framework import generics, permissions

from apps.accounts.models import UserRole
from apps.accounts.permissions import IsDriver
from apps.drivers.models import DriverProfile, Vehicle
from apps.drivers.serializers import DriverProfileSerializer, VehicleSerializer


class DriverProfileDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = DriverProfileSerializer
    permission_classes = (permissions.IsAuthenticated, IsDriver)
    queryset = DriverProfile.objects.all()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DriverProfile.objects.none()
        return DriverProfile.objects.filter(user=self.request.user)

    def get_object(self):
        if getattr(self, "swagger_fake_view", False):
            return DriverProfile()
        profile, _ = DriverProfile.objects.get_or_create(user=self.request.user)
        return profile


class VehicleListCreateView(generics.ListCreateAPIView):
    serializer_class = VehicleSerializer
    permission_classes = (permissions.IsAuthenticated, IsDriver)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Vehicle.objects.none()
        profile = ensure_driver_profile(self.request.user)
        return Vehicle.objects.filter(driver=profile)

    def perform_create(self, serializer):
        profile = ensure_driver_profile(self.request.user)
        serializer.save(driver=profile)


class VehicleDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = VehicleSerializer
    permission_classes = (permissions.IsAuthenticated, IsDriver)
    lookup_field = "id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Vehicle.objects.none()
        profile = ensure_driver_profile(self.request.user)
        return Vehicle.objects.filter(driver=profile)


def ensure_driver_profile(user):
    if user.role != UserRole.DRIVER:
        return None
    profile, _ = DriverProfile.objects.get_or_create(user=user)
    return profile
