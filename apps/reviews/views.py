from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions

from apps.reviews.models import Review
from apps.reviews.serializers import ReviewSerializer


@extend_schema(tags=["reviews"])
class ReviewListCreateView(generics.ListCreateAPIView):
    """Reviews the caller wrote, plus reviews written about them as a provider."""

    serializer_class = ReviewSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        user = self.request.user
        return (
            Review.objects.filter(Q(author=user) | Q(job__provider__user=user))
            .select_related("job", "job__provider", "author")
            .distinct()
        )

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
