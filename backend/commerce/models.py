"""
MISA commerce domain.

Existing models mapped here (not duplicated):
- Brand, Product, Team, Campaign → brands
- Agent → accounts.User (role=agent) + agents.AgentProfile
- Content/video → ai.VideoProject
- Brand-level share codes → brands.ProductShareLink (unchanged OneToOne)

New here: TrackingLink (per-agent), events, commission rules/entries,
wallets, ledger, withdrawals, platform fee, audit log, conversions.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ImmutableMixin:
    immutable_fields: tuple[str, ...] = ()

    def save(self, *args, **kwargs):
        if self.pk and self.immutable_fields:
            previous = self.__class__.objects.filter(pk=self.pk).values(*self.immutable_fields).first()
            if previous:
                for field in self.immutable_fields:
                    if previous[field] != getattr(self, field):
                        raise ValidationError("This record is immutable.")
        super().save(*args, **kwargs)


class PlatformSettings(models.Model):
    platform_fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("3.00"),
        help_text="Platform fee as a percent of gross agent commission. Not hard-coded in calculation.",
    )
    default_currency = models.CharField(
        max_length=3,
        default="USD",
        help_text="MISA currently supports a single wallet currency. Mixing currencies is rejected.",
    )
    commission_hold_days = models.PositiveIntegerField(
        default=0,
        help_text="Days a commission stays pending before it becomes withdrawable. 0 means the pending→available transition is explicit and immediate.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform settings"
        verbose_name_plural = "Platform settings"

    def __str__(self) -> str:
        return f"Platform fee {self.platform_fee_percent}%"

    def clean(self):
        if self.platform_fee_percent < 0 or self.platform_fee_percent > 100:
            raise ValidationError("Platform fee must be between 0 and 100.")

    @classmethod
    def load(cls) -> "PlatformSettings":
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "platform_fee_percent": Decimal("3.00"),
                "default_currency": "USD",
                "commission_hold_days": 0,
            },
        )
        return obj


class CommissionRule(models.Model):
    class Scope(models.TextChoices):
        PLATFORM = "platform", "Platform default"
        BRAND = "brand", "Brand"
        PRODUCT = "product", "Product"
        TEAM = "team", "Team"
        AGENT = "agent", "Agent override"

    class RateType(models.TextChoices):
        FIXED = "fixed", "Fixed amount"
        PERCENT = "percent", "Percent of product price"

    name = models.CharField(max_length=120, blank=True)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    brand = models.ForeignKey(
        "brands.Brand",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="commission_rules",
    )
    product = models.ForeignKey(
        "brands.Product",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="commission_rules",
    )
    team = models.ForeignKey(
        "brands.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="commission_rules",
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="commission_rules",
    )
    rate_type = models.CharField(max_length=16, choices=RateType.choices)
    rate_value = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or f"{self.scope} {self.rate_type} {self.rate_value}"


class TrackingLink(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        REVOKED = "revoked", "Revoked"

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tracking_links",
    )
    brand = models.ForeignKey(
        "brands.Brand",
        on_delete=models.CASCADE,
        related_name="tracking_links",
    )
    product = models.ForeignKey(
        "brands.Product",
        on_delete=models.CASCADE,
        related_name="tracking_links",
    )
    team = models.ForeignKey(
        "brands.Team",
        on_delete=models.CASCADE,
        related_name="tracking_links",
    )
    campaign = models.ForeignKey(
        "brands.Campaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracking_links",
    )
    content = models.ForeignKey(
        "ai.VideoProject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracking_links",
    )
    code = models.CharField(max_length=16, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    destination_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.code

    def save(self, *args, **kwargs):
        if self.product_id and not self.brand_id:
            self.brand_id = self.product.brand_id
        if not self.code:
            from brands.codes import allocate_public_code

            self.code = allocate_public_code()
        super().save(*args, **kwargs)

    def destination(self) -> str:
        return (self.destination_url or self.product.product_url or "").strip()


class TrackingEvent(ImmutableMixin, models.Model):
    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        OPENED = "opened", "Opened"
        CLICKED = "clicked", "Clicked (legacy alias of opened)"
        SHARE_INTENT = "share_intent", "Share intent (in-app copy)"
        SHARE_CONFIRMED = "share_confirmed", "Share confirmed (platform API)"
        CONVERSION = "conversion", "Conversion"
        CONVERSION_REVERSED = "conversion_reversed", "Conversion reversed"

    tracking_link = models.ForeignKey(
        TrackingLink,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    link_code = models.CharField(max_length=16)
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    session_key = models.CharField(max_length=64, blank=True)
    visitor_key = models.CharField(max_length=64, blank=True, db_index=True)
    referrer = models.CharField(max_length=500, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    flagged = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_fields = (
        "tracking_link_id",
        "link_code",
        "event_type",
        "session_key",
        "visitor_key",
        "referrer",
        "user_agent",
        "ip_hash",
        "flagged",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tracking_link", "event_type", "visitor_key"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} {self.link_code}"


class CommissionEntry(ImmutableMixin, models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SETTLED = "settled", "Settled"
        REVERSED = "reversed", "Reversed"

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="commission_entries",
    )
    brand = models.ForeignKey(
        "brands.Brand",
        on_delete=models.PROTECT,
        related_name="commission_entries",
    )
    product = models.ForeignKey(
        "brands.Product",
        on_delete=models.PROTECT,
        related_name="commission_entries",
    )
    team = models.ForeignKey(
        "brands.Team",
        on_delete=models.PROTECT,
        related_name="commission_entries",
    )
    tracking_link = models.ForeignKey(
        TrackingLink,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commission_entries",
    )
    campaign = models.ForeignKey(
        "brands.Campaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commission_entries",
    )
    tracking_event = models.ForeignKey(
        TrackingEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commission_entries",
    )
    rule = models.ForeignKey(
        CommissionRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commission_entries",
    )
    currency = models.CharField(max_length=3, default="USD")
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    platform_fee_percent = models.DecimalField(max_digits=5, decimal_places=2)
    platform_fee_amount = models.DecimalField(max_digits=12, decimal_places=2)
    agent_net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    rate_type = models.CharField(max_length=16)
    rate_value = models.DecimalField(max_digits=12, decimal_places=2)
    product_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    available_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this commission may move from pending to available. Set from platform hold policy at conversion time.",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_fields = (
        "agent_id",
        "brand_id",
        "product_id",
        "team_id",
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
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Commission entries"

    def __str__(self) -> str:
        return f"Commission {self.agent_net_amount} {self.currency}"


class Conversion(ImmutableMixin, models.Model):
    """Payment-system-agnostic conversion ingest.

    Commission is calculated from the resolved rule, not from a specific PSP.
    Duplicate external conversions are rejected by idempotency_key / source+external_id.
    """

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSED = "processed", "Processed"
        REJECTED = "rejected", "Rejected"
        DUPLICATE = "duplicate", "Duplicate"

    class Source(models.TextChoices):
        BRAND = "brand", "Brand reported"
        WEBHOOK = "webhook", "External webhook"
        MANUAL = "manual", "Manual"
        TEST = "test", "Test"

    tracking_link = models.ForeignKey(
        TrackingLink,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sale_conversions",
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="conversions",
    )
    brand = models.ForeignKey(
        "brands.Brand",
        on_delete=models.PROTECT,
        related_name="conversions",
    )
    product = models.ForeignKey(
        "brands.Product",
        on_delete=models.PROTECT,
        related_name="conversions",
    )
    team = models.ForeignKey(
        "brands.Team",
        on_delete=models.PROTECT,
        related_name="conversions",
    )
    campaign = models.ForeignKey(
        "brands.Campaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversions",
    )
    content = models.ForeignKey(
        "ai.VideoProject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversions",
    )
    tracking_event = models.ForeignKey(
        TrackingEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversions",
    )
    commission_entry = models.OneToOneField(
        CommissionEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversion",
    )
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.BRAND)
    source_name = models.CharField(max_length=80, blank=True)
    external_id = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=64, unique=True)
    gross_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    rejection_reason = models.CharField(max_length=255, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_fields = (
        "agent_id",
        "brand_id",
        "product_id",
        "team_id",
        "source",
        "source_name",
        "external_id",
        "idempotency_key",
        "gross_value",
        "currency",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                condition=~Q(external_id=""),
                name="uniq_conversion_source_external_id",
            )
        ]

    def __str__(self) -> str:
        return f"Conversion {self.external_id or self.idempotency_key} ({self.status})"


class Wallet(models.Model):
    agent = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
    )
    currency = models.CharField(max_length=3, default="USD")
    pending_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Earned commissions still inside the holding period. Not withdrawable.",
    )
    available_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Withdrawable funds. Open withdrawal requests debit this immediately.",
    )
    withdrawn_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Funds marked paid in the ledger. Not a payment-provider confirmation.",
    )
    paid_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Alias of withdrawn_balance for existing APIs.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Wallet {self.agent}"


class LedgerEntry(ImmutableMixin, models.Model):
    class EntryType(models.TextChoices):
        COMMISSION_EARNED = "commission_earned", "Commission earned"
        PLATFORM_FEE = "platform_fee", "Platform fee"
        COMMISSION_PENDING = "commission_pending", "Commission pending (legacy)"
        COMMISSION_AVAILABLE = "commission_available", "Commission available"
        COMMISSION_REVERSED = "commission_reversed", "Commission reversed"
        WITHDRAWAL_REQUESTED = "withdrawal_requested", "Withdrawal requested"
        WITHDRAWAL_HOLD = "withdrawal_hold", "Withdrawal hold (legacy)"
        WITHDRAWAL_PAID = "withdrawal_paid", "Withdrawal paid"
        WITHDRAWAL_REVERSED = "withdrawal_reversed", "Withdrawal reversed"
        WITHDRAWAL_RELEASE = "withdrawal_release", "Withdrawal release (legacy)"
        ADJUSTMENT = "adjustment", "Adjustment"

    class Bucket(models.TextChoices):
        PENDING = "pending", "Pending"
        AVAILABLE = "available", "Available"
        WITHDRAWN = "withdrawn", "Withdrawn"
        PAID = "paid", "Paid (legacy withdrawn)"

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="entries")
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )
    currency = models.CharField(max_length=3, default="USD")
    entry_type = models.CharField(max_length=32, choices=EntryType.choices)
    bucket = models.CharField(max_length=16, choices=Bucket.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission = models.ForeignKey(
        CommissionEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    withdrawal = models.ForeignKey(
        "WithdrawalRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    source_type = models.CharField(max_length=80, blank=True)
    source_id = models.CharField(max_length=64, blank=True)
    idempotency_key = models.CharField(max_length=80, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    immutable_fields = (
        "wallet_id",
        "agent_id",
        "currency",
        "entry_type",
        "bucket",
        "amount",
        "commission_id",
        "withdrawal_id",
        "source_type",
        "source_id",
        "idempotency_key",
        "metadata",
        "note",
    )

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "Ledger entries"
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="uniq_ledger_idempotency_key",
            )
        ]

    def __str__(self) -> str:
        return f"{self.entry_type} {self.amount} {self.currency}"

    def delete(self, *args, **kwargs):
        raise ValidationError("Ledger entries cannot be deleted.")


class PayoutAccount(models.Model):
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payout_accounts",
    )
    label = models.CharField(max_length=120)
    destination_ref = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]

    def __str__(self) -> str:
        return self.label


class WithdrawalRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Pending"
        APPROVED = "approved", "Approved"
        PROCESSING = "processing", "Processing"
        PAID = "paid", "Paid"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="withdrawal_requests",
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="withdrawals")
    payout_account = models.ForeignKey(
        PayoutAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawals",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    destination_ref = models.CharField(max_length=255, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_withdrawals",
    )

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self) -> str:
        return f"Withdrawal {self.amount} {self.currency} ({self.status})"


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    impersonator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="impersonated_audit_logs",
    )
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} {self.object_type}"
