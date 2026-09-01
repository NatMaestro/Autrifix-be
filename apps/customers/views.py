from rest_framework import generics, permissions

from apps.accounts.permissions import IsCustomer
from apps.customers.models import Vehicle
from apps.customers.selectors import ensure_customer_profile
from apps.customers.serializers import CustomerProfileSerializer, VehicleSerializer


class CustomerProfileDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = CustomerProfileSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomer)

    def get_object(self):
        return ensure_customer_profile(self.request.user)


class CustomerVehicleQuerysetMixin:
    """Vehicles are always scoped to the calling customer's own garage."""

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Vehicle.objects.none()
        return Vehicle.objects.filter(customer=ensure_customer_profile(self.request.user))


class VehicleListCreateView(CustomerVehicleQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = VehicleSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomer)

    def perform_create(self, serializer):
        serializer.save(customer=ensure_customer_profile(self.request.user))


class VehicleDetailView(CustomerVehicleQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = VehicleSerializer
    permission_classes = (permissions.IsAuthenticated, IsCustomer)
    lookup_field = "id"
