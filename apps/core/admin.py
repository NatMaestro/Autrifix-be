from django.contrib import admin

from apps.core.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only. An audit trail an operator can edit is not an audit trail."""

    list_display = ("created_at", "action", "actor_label", "target_type", "target_id")
    list_filter = ("action", "target_type", "created_at")
    search_fields = ("actor_label", "target_id", "action")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Retention pruning, if it is ever introduced, belongs in a management command
        # with its own audit entry — not in a click.
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]
