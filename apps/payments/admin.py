from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "amount_cents", "currency", "escrow_status", "created_at")
    list_filter = ("escrow_status", "currency")
