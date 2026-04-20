from rest_framework import serializers

from apps.reviews.models import Review


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ("id", "job", "author", "rating", "comment", "created_at")
        read_only_fields = ("id", "author", "created_at")
