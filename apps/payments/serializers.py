from rest_framework import serializers

from apps.payments.models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = (
            "id",
            "job",
            "amount_cents",
            "currency",
            "escrow_status",
            "provider",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
