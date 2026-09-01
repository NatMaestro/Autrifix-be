"""Read shapes for the operator surface — SPEC-012 REQ-4.

Every serializer here is **read-only except where an action needs input**. Administration is
inspection and a small number of deliberate interventions; a general-purpose editable API over
every model is what Django admin already is, and duplicating it in DRF would double the
surface without adding a control.
"""

from rest_framework import serializers

from apps.accounts.models import User
from apps.jobs.models import Job
from apps.providers.models import ProviderVerification


class AdminUserSerializer(serializers.ModelSerializer):
    """A user as an operator needs to see them, and no more.

    Deliberately omits `password`, tokens, and anything an operator has no business reading.
    """

    provider_verification_level = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "role",
            "is_active",
            "is_phone_verified",
            "is_email_verified",
            "provider_verification_level",
            "date_joined",
        )
        read_only_fields = fields

    @staticmethod
    def get_provider_verification_level(user) -> str | None:
        provider = getattr(user, "provider_profile", None)
        return provider.verification_level if provider else None


class AdminVerificationSerializer(serializers.ModelSerializer):
    """A submission awaiting review.

    **The document images are not exposed.** They are purged on decision (SPEC-013 REQ-8), and
    serving them through a JSON API would put identity documents behind nothing but a URL
    (SEC-GAP-18). A reviewer opens them in Django admin, where access is at least
    staff-gated — recorded as OQ-012-I rather than quietly solved the easy way.
    """

    provider_id = serializers.UUIDField(source="provider.id", read_only=True)
    provider_name = serializers.CharField(source="provider.business_name", read_only=True)
    provider_type = serializers.CharField(source="provider.provider_type", read_only=True)
    current_level = serializers.CharField(source="provider.verification_level", read_only=True)
    reviewed_by_label = serializers.SerializerMethodField()

    class Meta:
        model = ProviderVerification
        fields = (
            "id",
            "provider_id",
            "provider_name",
            "provider_type",
            "current_level",
            "requested_level",
            "status",
            "submitted_at",
            "reviewed_at",
            "reviewed_by_label",
            "review_notes",
        )
        read_only_fields = fields

    @staticmethod
    def get_reviewed_by_label(submission) -> str | None:
        reviewer = submission.reviewed_by
        if reviewer is None:
            return None
        name = f"{reviewer.first_name or ''} {reviewer.last_name or ''}".strip()
        return name or reviewer.email or reviewer.phone or str(reviewer.pk)


class AdminVerificationReviewSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    notes = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
        default="",
        help_text="Shown to the provider when a submission is declined.",
    )

    def validate(self, attrs):
        # A rejection with no reason leaves the provider unable to fix anything, which turns
        # a review queue into a dead end for them.
        if not attrs.get("approve") and not (attrs.get("notes") or "").strip():
            raise serializers.ValidationError(
                {"notes": "Give a reason when declining — the provider is shown this."}
            )
        return attrs


class AdminJobSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    provider_name = serializers.CharField(source="provider.business_name", read_only=True)
    service_category_name = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = (
            "id",
            "service_request",
            "customer_name",
            "provider_name",
            "service_category_name",
            "status",
            "final_amount",
            "currency",
            "auto_confirmed",
            "accepted_at",
            "work_finished_at",
            "completed_at",
            "created_at",
        )
        read_only_fields = fields

    @staticmethod
    def get_customer_name(job) -> str:
        customer = getattr(job.service_request, "customer", None)
        user = getattr(customer, "user", None)
        if user is None:
            return "Customer"
        full = f"{user.first_name or ''} {user.last_name or ''}".strip()
        return full or getattr(customer, "display_name", "") or "Customer"

    @staticmethod
    def get_service_category_name(job) -> str | None:
        category = getattr(job.service_request, "category", None)
        return category.name if category else None
