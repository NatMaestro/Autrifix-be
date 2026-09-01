import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.validators import latitude_validators, longitude_validators, validate_image_size
from apps.providers.agencies import AgencyRole, MembershipStatus
from apps.providers.verification import ProviderType, VerificationLevel, VerificationStatus


class ProviderProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_profile",
    )
    business_name = models.CharField(max_length=200)
    provider_type = models.CharField(
        max_length=20,
        choices=ProviderType.choices,
        default=ProviderType.MECHANIC,
        db_index=True,
        help_text="Trade this provider is in. Capability detail lives on service offerings.",
    )
    bio = models.TextField(max_length=2000, blank=True)
    base_latitude = models.FloatField(null=True, blank=True, validators=latitude_validators)
    base_longitude = models.FloatField(null=True, blank=True, validators=longitude_validators)
    service_radius_km = models.PositiveIntegerField(default=25)
    is_available = models.BooleanField(default=False, db_index=True)
    rating_avg = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
    )
    rating_count = models.PositiveIntegerField(default=0)
    verification_level = models.CharField(
        max_length=20,
        choices=VerificationLevel.choices,
        default=VerificationLevel.NONE,
        db_index=True,
        help_text="Controls how precisely this provider sees customer locations (SPEC-013).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-rating_avg", "-created_at"]
        indexes = [
            models.Index(fields=["is_available"]),
        ]

    def __str__(self):
        return self.business_name


class ProviderServiceOffering(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        ProviderProfile,
        on_delete=models.CASCADE,
        related_name="service_offerings",
    )
    category = models.ForeignKey(
        "jobs.ServiceCategory",
        on_delete=models.PROTECT,
        related_name="provider_offerings",
    )
    title = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Labour rate. Currency is undecided platform-wide — see ADR-006.",
    )
    per_km_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Towing rate per kilometre. Same currency caveat as hourly_rate.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("provider", "category", "title")
        indexes = [
            models.Index(fields=["provider", "is_active"]),
        ]

    def __str__(self):
        return self.title or self.category.name


class ProviderVerification(models.Model):
    """One verification submission, reviewed by a human — SPEC-013 REQ-7.

    Uploaded images are **purged when the submission is decided** (REQ-8). Manual review
    needs a human to see the document, so storage is unavoidable — but a permanent store of
    identity documents is a breach liability out of all proportion to its value.
    """

    DOCUMENT_FIELDS = ("id_document", "selfie", "workshop_photo")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        ProviderProfile,
        on_delete=models.CASCADE,
        related_name="verifications",
    )
    requested_level = models.CharField(
        max_length=20,
        choices=VerificationLevel.choices,
        default=VerificationLevel.DOCUMENTS,
    )
    status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True,
    )
    id_document = models.ImageField(
        upload_to="verification/", null=True, blank=True, validators=[validate_image_size]
    )
    selfie = models.ImageField(
        upload_to="verification/", null=True, blank=True, validators=[validate_image_size]
    )
    workshop_photo = models.ImageField(
        upload_to="verification/", null=True, blank=True, validators=[validate_image_size]
    )
    #: Reserved for the future Ghana Card tier. Deliberately unused — it costs nothing now
    #: and avoids a migration when Tier 3 arrives.
    ghana_card_number = models.CharField(max_length=32, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verifications_reviewed",
    )
    review_notes = models.TextField(max_length=2000, blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            # One open submission at a time; a provider cannot flood the review queue.
            models.UniqueConstraint(
                fields=["provider"],
                condition=models.Q(status=VerificationStatus.PENDING),
                name="unique_pending_verification_per_provider",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-submitted_at"]),
        ]

    def __str__(self):
        return f"Verification({self.provider_id}, {self.status})"

    def purge_documents(self) -> None:
        """Delete the stored images, keeping the decision record (REQ-8)."""
        for field_name in self.DOCUMENT_FIELDS:
            file_field = getattr(self, field_name)
            if file_field:
                file_field.delete(save=False)
                setattr(self, field_name, None)


class Agency(models.Model):
    """A business that fields several providers — SPEC-014 REQ-6.

    Verification lives here as well as on the individual: an agency verified once should not
    make each new operator re-submit documents, but the platform still needs to know a person
    is who they say they are. See ``effective_verification_level`` on ``ProviderProfile``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    provider_type = models.CharField(
        max_length=20,
        choices=ProviderType.choices,
        default=ProviderType.MECHANIC,
        db_index=True,
    )
    verification_level = models.CharField(
        max_length=20,
        choices=VerificationLevel.choices,
        default=VerificationLevel.NONE,
        db_index=True,
        help_text="Granted to the business; inherited by its active members.",
    )
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    #: Ghana's Registrar General's Department business registration, when supplied.
    registration_number = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "agencies"

    def __str__(self):
        return self.name


class AgencyMembership(models.Model):
    """One provider's place in one agency.

    A provider belongs to at most one agency at a time — enforced by a partial unique
    constraint on the non-removed rows, so leaving and rejoining keeps a history.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="memberships")
    provider = models.ForeignKey(
        "mechanics.ProviderProfile", on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(
        max_length=20, choices=AgencyRole.choices, default=AgencyRole.OPERATOR
    )
    status = models.CharField(
        max_length=20,
        choices=MembershipStatus.choices,
        default=MembershipStatus.INVITED,
        db_index=True,
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    joined_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-invited_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider"],
                condition=~models.Q(status=MembershipStatus.REMOVED),
                name="one_live_agency_membership_per_provider",
            ),
        ]
        indexes = [models.Index(fields=["agency", "status"])]

    def __str__(self):
        return f"{self.provider_id} @ {self.agency_id} ({self.status})"
