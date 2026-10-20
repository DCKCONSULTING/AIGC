from django.conf import settings
from rest_framework import serializers

from commerce.models import Conversion, TrackingEvent, TrackingLink
from commerce.services.commissions import money


class TrackingLinkStatsSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    product_id = serializers.IntegerField(source="product.id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    brand_id = serializers.IntegerField(source="brand.id", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    team_id = serializers.IntegerField(source="team.id", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    agent_id = serializers.IntegerField(source="agent.id", read_only=True)
    agent_name = serializers.SerializerMethodField()
    campaign_id = serializers.IntegerField(source="campaign.id", read_only=True, allow_null=True)
    campaign_name = serializers.SerializerMethodField()
    content_id = serializers.IntegerField(source="content.id", read_only=True, allow_null=True)
    opens = serializers.IntegerField(read_only=True)
    unique_opens = serializers.IntegerField(read_only=True)
    clicks = serializers.IntegerField(read_only=True)
    conversions = serializers.IntegerField(read_only=True)
    share_intents = serializers.IntegerField(read_only=True)
    share_confirmed = serializers.IntegerField(read_only=True)

    class Meta:
        model = TrackingLink
        fields = (
            "id",
            "code",
            "url",
            "status",
            "product_id",
            "product_name",
            "brand_id",
            "brand_name",
            "team_id",
            "team_name",
            "agent_id",
            "agent_name",
            "campaign_id",
            "campaign_name",
            "content_id",
            "opens",
            "unique_opens",
            "clicks",
            "conversions",
            "share_intents",
            "share_confirmed",
            "created_at",
        )
        read_only_fields = fields

    def get_url(self, obj: TrackingLink) -> str:
        return f"{settings.SITE_URL.rstrip('/')}/s/{obj.code}"

    def get_campaign_name(self, obj: TrackingLink) -> str:
        return obj.campaign.name if obj.campaign_id else ""

    def get_agent_name(self, obj: TrackingLink) -> str:
        return obj.agent.name or obj.agent.username


class TrackingEventPublicSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = TrackingEvent
        fields = (
            "id",
            "event_type",
            "label",
            "link_code",
            "created_at",
            "metadata",
            "flagged",
        )
        read_only_fields = fields

    def get_label(self, obj: TrackingEvent) -> str:
        labels = {
            TrackingEvent.EventType.CREATED: "Link created",
            TrackingEvent.EventType.OPENED: "Open",
            TrackingEvent.EventType.CLICKED: "Open",
            TrackingEvent.EventType.SHARE_INTENT: "Share intent (copied in MISA)",
            TrackingEvent.EventType.SHARE_CONFIRMED: "Share confirmed (manual record)",
            TrackingEvent.EventType.CONVERSION: "Conversion",
            TrackingEvent.EventType.CONVERSION_REVERSED: "Conversion reversed",
        }
        return labels.get(obj.event_type, obj.event_type)


class ConversionIngestSerializer(serializers.Serializer):
    tracking_code = serializers.CharField(required=False, allow_blank=True)
    tracking_link = serializers.IntegerField(required=False)
    source = serializers.ChoiceField(choices=Conversion.Source.choices, default=Conversion.Source.BRAND)
    source_name = serializers.CharField(required=False, allow_blank=True, max_length=80)
    external_id = serializers.CharField(required=False, allow_blank=True, max_length=120)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=64)
    gross_value = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    currency = serializers.CharField(required=False, allow_blank=True, max_length=3)
    settle = serializers.BooleanField(required=False, allow_null=True, default=None)

    def validate_currency(self, value: str) -> str:
        return (value or "").strip().upper()

    def validate_gross_value(self, value):
        if value is None:
            return value
        return money(value)

    def validate(self, attrs):
        if not (attrs.get("external_id") or "").strip() and not (attrs.get("idempotency_key") or "").strip():
            raise serializers.ValidationError(
                {
                    "external_id": "Provide an external_id or idempotency_key so this conversion cannot be paid twice."
                }
            )
        return attrs


class ConversionSerializer(serializers.ModelSerializer):
    tracking_code = serializers.SerializerMethodField()
    commission_id = serializers.IntegerField(source="commission_entry_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    agent_name = serializers.SerializerMethodField()

    class Meta:
        model = Conversion
        fields = (
            "id",
            "status",
            "source",
            "source_name",
            "external_id",
            "idempotency_key",
            "tracking_code",
            "agent",
            "agent_name",
            "brand",
            "brand_name",
            "product",
            "product_name",
            "team",
            "campaign",
            "gross_value",
            "currency",
            "commission_id",
            "rejection_reason",
            "processed_at",
            "created_at",
        )
        read_only_fields = fields

    def get_tracking_code(self, obj: Conversion) -> str:
        return obj.tracking_link.code if obj.tracking_link_id else ""

    def get_agent_name(self, obj: Conversion) -> str:
        return obj.agent.name or obj.agent.username
