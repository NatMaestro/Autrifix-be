from django.contrib import admin, messages
from django.utils.html import format_html

from apps.core.exceptions import Conflict
from apps.providers import services as provider_services
from apps.providers.models import (
    Agency,
    AgencyMembership,
    ProviderProfile,
    ProviderServiceOffering,
    ProviderVerification,
)
from apps.providers.verification import VerificationStatus


@admin.register(ProviderProfile)
class ProviderProfileAdmin(admin.ModelAdmin):
    list_display = (
        "business_name",
        "user",
        "verification_level",
        "is_available",
        "rating_avg",
        "created_at",
    )
    list_filter = ("verification_level", "is_available")
    search_fields = ("business_name", "user__email", "user__phone")


@admin.register(ProviderServiceOffering)
class ProviderServiceOfferingAdmin(admin.ModelAdmin):
    list_display = ("provider", "category", "title", "hourly_rate", "is_active", "created_at")
    list_filter = ("is_active", "category")
    search_fields = ("mechanic__business_name", "title", "category__name")


@admin.register(ProviderVerification)
class ProviderVerificationAdmin(admin.ModelAdmin):
    """The review queue — SPEC-013 REQ-7.

    Decisions go through ``apps.providers.services.review_verification`` rather than being
    applied here, so the level change, the document purge, and the audit entry stay
    together no matter where a review is triggered from.
    """

    list_display = (
        "submitted_at",
        "provider",
        "status",
        "requested_level",
        "reviewed_at",
        "reviewed_by",
    )
    list_filter = ("status", "requested_level", "submitted_at")
    search_fields = ("mechanic__business_name", "provider__user__email", "provider__user__phone")
    date_hierarchy = "submitted_at"
    ordering = ("status", "submitted_at")
    readonly_fields = (
        "provider",
        "requested_level",
        "status",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
        "documents_preview",
    )
    fields = (
        "provider",
        "requested_level",
        "status",
        "documents_preview",
        "review_notes",
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
    )
    actions = ("approve_selected", "reject_selected")

    @admin.display(description="Submitted documents")
    def documents_preview(self, obj):
        """Inline previews so a decision can be made without leaving the page.

        Images exist only while the submission is pending — they are purged on decision
        (REQ-8), so a decided submission shows nothing here by design.
        """
        if obj is None or obj.pk is None:
            return "—"
        parts = []
        for field_name in ProviderVerification.DOCUMENT_FIELDS:
            file_field = getattr(obj, field_name)
            if file_field:
                parts.append(
                    format_html(
                        '<div style="display:inline-block;margin:0 12px 12px 0;text-align:center">'
                        '<div style="font-size:11px;color:#666">{}</div>'
                        '<a href="{}" target="_blank" rel="noopener">'
                        '<img src="{}" style="max-height:260px;border:1px solid #ddd"></a></div>',
                        field_name.replace("_", " "),
                        file_field.url,
                        file_field.url,
                    )
                )
        if not parts:
            return "Documents purged after review (SPEC-013 REQ-8)."
        return format_html("".join(parts))

    def has_add_permission(self, request):
        # Submissions come from the provider, never from an operator.
        return False

    def _review(self, request, queryset, *, approve: bool):
        verb = "Approved" if approve else "Rejected"
        done = skipped = 0
        for submission in queryset:
            try:
                provider_services.review_verification(
                    submission=submission,
                    approve=approve,
                    reviewer=request.user,
                    notes=submission.review_notes or "",
                )
                done += 1
            except Conflict:
                skipped += 1

        if done:
            self.message_user(request, f"{verb} {done} submission(s).", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} submission(s) that were already decided.",
                messages.WARNING,
            )

    @admin.action(description="Approve selected — grants the requested level")
    def approve_selected(self, request, queryset):
        self._review(request, queryset.filter(status=VerificationStatus.PENDING), approve=True)

    @admin.action(description="Reject selected — level unchanged")
    def reject_selected(self, request, queryset):
        self._review(request, queryset.filter(status=VerificationStatus.PENDING), approve=False)


class AgencyMembershipInline(admin.TabularInline):
    model = AgencyMembership
    extra = 0
    autocomplete_fields = ("provider",)


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    """Verifying an agency lifts every active member (SPEC-014 REQ-7), so treat this with
    the same care as an individual verification."""

    list_display = (
        "name",
        "provider_type",
        "verification_level",
        "registration_number",
        "created_at",
    )
    list_filter = ("provider_type", "verification_level")
    search_fields = ("name", "slug", "registration_number", "contact_email")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [AgencyMembershipInline]


@admin.register(AgencyMembership)
class AgencyMembershipAdmin(admin.ModelAdmin):
    list_display = ("provider", "agency", "role", "status", "joined_at")
    list_filter = ("status", "role")
    search_fields = ("agency__name", "provider__business_name")
