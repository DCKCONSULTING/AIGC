from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from commerce.models import (
    AuditLog,
    CommissionEntry,
    CommissionRule,
    Conversion,
    LedgerEntry,
    PayoutAccount,
    PlatformSettings,
    TrackingEvent,
    TrackingLink,
    Wallet,
    WithdrawalRequest,
)
from commerce.services.ledger import (
    approve_withdrawal,
    mark_withdrawal_paid,
    reject_withdrawal,
    reverse_commission,
    start_withdrawal_processing,
)


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    list_display = ("platform_fee_percent", "default_currency", "commission_hold_days", "updated_at")

    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CommissionRule)
class CommissionRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "scope", "rate_type", "rate_value", "is_active", "updated_at")
    list_filter = ("scope", "rate_type", "is_active")
    search_fields = ("name",)


@admin.register(TrackingLink)
class TrackingLinkAdmin(admin.ModelAdmin):
    list_display = ("code", "agent", "product", "team", "campaign", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("code", "agent__username", "product__name")
    readonly_fields = ("code", "created_at", "updated_at")


@admin.register(TrackingEvent)
class TrackingEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "link_code", "created_at")
    list_filter = ("event_type",)
    search_fields = ("link_code",)
    readonly_fields = (
        "tracking_link",
        "link_code",
        "event_type",
        "session_key",
        "referrer",
        "user_agent",
        "ip_hash",
        "visitor_key",
        "flagged",
        "metadata",
        "created_at",
    )

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Conversion)
class ConversionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "source",
        "external_id",
        "gross_value",
        "currency",
        "agent",
        "product",
        "created_at",
    )
    list_filter = ("status", "source", "currency")
    search_fields = ("external_id", "idempotency_key", "agent__username")
    readonly_fields = (
        "tracking_link",
        "agent",
        "brand",
        "product",
        "team",
        "campaign",
        "content",
        "tracking_event",
        "commission_entry",
        "source",
        "source_name",
        "external_id",
        "idempotency_key",
        "gross_value",
        "currency",
        "status",
        "rejection_reason",
        "processed_at",
        "metadata",
        "created_at",
    )

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CommissionEntry)
class CommissionEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agent",
        "product",
        "gross_amount",
        "platform_fee_percent",
        "agent_net_amount",
        "status",
        "created_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("agent__username", "product__name")
    readonly_fields = (
        "agent",
        "brand",
        "product",
        "team",
        "tracking_link",
        "tracking_event",
        "campaign",
        "rule",
        "currency",
        "gross_amount",
        "platform_fee_percent",
        "platform_fee_amount",
        "agent_net_amount",
        "rate_type",
        "rate_value",
        "product_price_snapshot",
        "sale_amount",
        "available_at",
        "status",
        "created_at",
    )

    actions = ("reverse_selected",)

    @admin.action(description="Reverse selected commissions (ledger)")
    def reverse_selected(self, request, queryset):
        reversed_count = 0
        for entry in queryset:
            try:
                reverse_commission(entry, actor=request.user, reason="Reversed from Django admin.")
                reversed_count += 1
            except ValidationError as exc:
                self.message_user(request, f"Commission {entry.pk}: {exc}", level=messages.ERROR)
        if reversed_count:
            self.message_user(request, f"Reversed {reversed_count} commission(s).")


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("agent", "pending_balance", "available_balance", "withdrawn_balance", "currency")
    search_fields = ("agent__username", "agent__email")
    readonly_fields = (
        "pending_balance",
        "available_balance",
        "withdrawn_balance",
        "paid_balance",
        "updated_at",
    )


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "wallet", "agent", "entry_type", "bucket", "amount", "currency", "created_at")
    list_filter = ("entry_type", "bucket", "currency")
    readonly_fields = (
        "wallet",
        "agent",
        "currency",
        "entry_type",
        "bucket",
        "amount",
        "commission",
        "withdrawal",
        "source_type",
        "source_id",
        "idempotency_key",
        "metadata",
        "note",
        "created_at",
    )

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PayoutAccount)
class PayoutAccountAdmin(admin.ModelAdmin):
    list_display = ("label", "agent", "destination_ref", "is_default")
    search_fields = ("agent__username", "destination_ref")


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "agent", "amount", "currency", "status", "requested_at")
    list_filter = ("status", "currency")
    search_fields = ("agent__username", "destination_ref")
    readonly_fields = (
        "agent",
        "wallet",
        "payout_account",
        "amount",
        "currency",
        "status",
        "destination_ref",
        "rejection_reason",
        "requested_at",
        "reviewed_at",
        "processed_at",
        "reviewer",
    )
    actions = (
        "approve_selected",
        "start_processing_selected",
        "mark_paid_selected",
        "reject_selected",
    )

    def has_add_permission(self, request):
        return False

    @admin.action(description="Approve selected (ledger, no payout)")
    def approve_selected(self, request, queryset):
        self._run(request, queryset, lambda row: approve_withdrawal(row, reviewer=request.user), "approved")

    @admin.action(description="Mark processing (internal accounting)")
    def start_processing_selected(self, request, queryset):
        self._run(
            request,
            queryset,
            lambda row: start_withdrawal_processing(row, reviewer=request.user),
            "marked processing",
        )

    @admin.action(description="Mark paid in ledger (not a payment-provider confirmation)")
    def mark_paid_selected(self, request, queryset):
        self._run(
            request,
            queryset,
            lambda row: mark_withdrawal_paid(row, reviewer=request.user),
            "marked paid in ledger",
        )

    @admin.action(description="Reject and return funds to available")
    def reject_selected(self, request, queryset):
        self._run(
            request,
            queryset,
            lambda row: reject_withdrawal(row, reviewer=request.user, reason="Rejected from Django admin."),
            "rejected",
        )

    def _run(self, request, queryset, fn, verb: str):
        done = 0
        for row in queryset:
            try:
                fn(row)
                done += 1
            except ValidationError as exc:
                self.message_user(request, f"Withdrawal {row.pk}: {exc}", level=messages.ERROR)
        if done:
            self.message_user(request, f"{done} withdrawal(s) {verb}.")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "object_type", "object_id", "created_at")
    list_filter = ("action",)
    search_fields = ("action", "object_id", "actor__username")
    readonly_fields = ("actor", "impersonator", "action", "object_type", "object_id", "payload", "created_at")

    def has_change_permission(self, request, obj=None):
        return False
