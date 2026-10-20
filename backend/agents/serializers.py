from accounts.serializers import AccountRegisterSerializer, ProfileUpdateSerializer, UserSerializer
from rest_framework import serializers

from accounts.models import User
from ai.models import VideoProject
from brands.models import Brand, Campaign, JoinRequest, Product, Team, TeamInvitation
from commerce.models import (
    CommissionEntry,
    LedgerEntry,
    PayoutAccount,
    TrackingEvent,
    TrackingLink,
    WithdrawalRequest,
)

from .models import AgentProfile
from .query import (
    approved_videos,
    commission_payload,
    media_url,
    public_tracking_url,
)


class AgentProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = AgentProfile
        fields = ("id", "user", "bio", "status", "created_at", "updated_at")
        read_only_fields = ("id", "user", "status", "created_at", "updated_at")


class AgentRegisterSerializer(AccountRegisterSerializer):
    role = User.Role.AGENT

    def create(self, validated_data):
        user = super().create(validated_data)
        AgentProfile.objects.get_or_create(user=user)
        return user


class AgentMeUpdateSerializer(ProfileUpdateSerializer):
    bio = serializers.CharField(required=False, allow_blank=True)

    class Meta(ProfileUpdateSerializer.Meta):
        fields = ProfileUpdateSerializer.Meta.fields + ("bio",)

    def update(self, instance, validated_data):
        bio = validated_data.pop("bio", None)
        user = super().update(instance, validated_data)
        if bio is not None:
            profile, _ = AgentProfile.objects.get_or_create(user=user)
            profile.bio = bio
            profile.save(update_fields=["bio", "updated_at"])
        return user


class AgentImageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.CharField()


class AgentContentSerializer(serializers.ModelSerializer):
    preview_url = serializers.SerializerMethodField()
    export_url = serializers.SerializerMethodField()
    final_url = serializers.SerializerMethodField()

    class Meta:
        model = VideoProject
        fields = (
            "id",
            "status",
            "duration_seconds",
            "language",
            "preview_url",
            "final_url",
            "export_url",
            "updated_at",
        )
        read_only_fields = fields

    def get_preview_url(self, obj: VideoProject) -> str:
        return media_url(self.context.get("request"), obj.preview_video)

    def get_final_url(self, obj: VideoProject) -> str:
        return media_url(self.context.get("request"), obj.final_video)

    def get_export_url(self, obj: VideoProject) -> str:
        return media_url(self.context.get("request"), obj.export_file)


class AgentCampaignSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(read_only=True, allow_null=True)
    team_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = Campaign
        fields = ("id", "name", "status", "product_id", "team_id")
        read_only_fields = fields


class AgentBrandCardSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    product_count = serializers.IntegerField(read_only=True)
    team_count = serializers.IntegerField(read_only=True)
    membership_status = serializers.CharField(read_only=True, allow_blank=True)

    class Meta:
        model = Brand
        fields = (
            "id",
            "name",
            "description",
            "location",
            "website",
            "category",
            "category_name",
            "status",
            "product_count",
            "team_count",
            "membership_status",
        )
        read_only_fields = fields


class AgentTeamSerializer(serializers.ModelSerializer):
    brand_id = serializers.IntegerField(source="brand.id", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    membership_status = serializers.CharField(read_only=True, allow_blank=True)
    join_request_status = serializers.CharField(read_only=True, allow_blank=True)
    invitation_status = serializers.CharField(read_only=True, allow_blank=True)
    join_request_id = serializers.IntegerField(read_only=True, allow_null=True)
    invitation_id = serializers.IntegerField(read_only=True, allow_null=True)
    can_join = serializers.BooleanField(read_only=True)
    can_cancel_request = serializers.BooleanField(read_only=True)
    can_accept_invitation = serializers.BooleanField(read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    campaigns = AgentCampaignSerializer(many=True, read_only=True)

    class Meta:
        model = Team
        fields = (
            "id",
            "name",
            "description",
            "status",
            "brand_id",
            "brand_name",
            "membership_status",
            "join_request_status",
            "invitation_status",
            "join_request_id",
            "invitation_id",
            "can_join",
            "can_cancel_request",
            "can_accept_invitation",
            "member_count",
            "campaigns",
            "created_at",
        )
        read_only_fields = fields


class AgentProductCardSerializer(serializers.ModelSerializer):
    brand_id = serializers.IntegerField(source="brand.id", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    category_name = serializers.CharField(source="brand.category.name", read_only=True)
    images = serializers.SerializerMethodField()
    can_share = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "description",
            "price",
            "brand_id",
            "brand_name",
            "category_name",
            "images",
            "can_share",
            "created_at",
        )
        read_only_fields = fields

    def get_images(self, obj: Product):
        request = self.context.get("request")
        return [{"id": image.pk, "url": media_url(request, image.image)} for image in obj.images.all()]


class AgentProductDetailSerializer(AgentProductCardSerializer):
    demo_videos = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    commissions = serializers.SerializerMethodField()
    teams = serializers.SerializerMethodField()
    approved_claims = serializers.JSONField(read_only=True)
    offer = serializers.CharField(read_only=True)
    offer_expiry = serializers.DateField(read_only=True)
    product_url = serializers.CharField(read_only=True)
    materials = serializers.CharField(read_only=True)
    variants = serializers.JSONField(read_only=True)
    commission = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    commission_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta(AgentProductCardSerializer.Meta):
        fields = AgentProductCardSerializer.Meta.fields + (
            "demo_videos",
            "content",
            "commissions",
            "teams",
            "approved_claims",
            "offer",
            "offer_expiry",
            "product_url",
            "materials",
            "variants",
            "commission",
            "commission_amount",
        )

    def get_demo_videos(self, obj: Product):
        request = self.context.get("request")
        if not self.context.get("is_member"):
            return []
        return [
            {"id": video.pk, "url": media_url(request, video.video)}
            for video in obj.demo_videos.all()
        ]

    def get_content(self, obj: Product):
        if not self.context.get("is_member"):
            return []
        return AgentContentSerializer(
            approved_videos(obj),
            many=True,
            context=self.context,
        ).data

    def get_commissions(self, obj: Product):
        teams = self.context.get("member_teams") or []
        agent = self.context.get("agent")
        payloads = []
        for team in teams:
            payload = commission_payload(obj, agent, team)
            if payload:
                payloads.append(payload)
        return payloads

    def get_teams(self, obj: Product):
        teams = self.context.get("member_teams") or []
        return [{"id": team.pk, "name": team.name} for team in teams]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("is_member"):
            data["approved_claims"] = []
            data["offer"] = ""
            data["offer_expiry"] = None
            data["materials"] = ""
            data["variants"] = []
            data["commission"] = "0.00"
            data["commission_amount"] = "0.00"
            data["product_url"] = ""
        return data


class AgentJoinRequestSerializer(serializers.ModelSerializer):
    team_id = serializers.IntegerField(source="team.id", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    brand_id = serializers.IntegerField(source="team.brand.id", read_only=True)
    brand_name = serializers.CharField(source="team.brand.name", read_only=True)
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = JoinRequest
        fields = (
            "id",
            "team_id",
            "team_name",
            "brand_id",
            "brand_name",
            "status",
            "message",
            "can_cancel",
            "created_at",
            "responded_at",
        )
        read_only_fields = fields

    def get_can_cancel(self, obj: JoinRequest) -> bool:
        return obj.status == JoinRequest.Status.PENDING


class AgentInvitationSerializer(serializers.ModelSerializer):
    team_id = serializers.IntegerField(source="team.id", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    brand_id = serializers.IntegerField(source="team.brand.id", read_only=True)
    brand_name = serializers.CharField(source="team.brand.name", read_only=True)
    can_accept = serializers.SerializerMethodField()
    can_decline = serializers.SerializerMethodField()

    class Meta:
        model = TeamInvitation
        fields = (
            "id",
            "team_id",
            "team_name",
            "brand_id",
            "brand_name",
            "status",
            "created_at",
            "expires_at",
            "responded_at",
            "can_accept",
            "can_decline",
        )
        read_only_fields = fields

    def get_can_accept(self, obj: TeamInvitation) -> bool:
        return obj.status == TeamInvitation.Status.PENDING and not obj.is_expired()

    def get_can_decline(self, obj: TeamInvitation) -> bool:
        return obj.status == TeamInvitation.Status.PENDING and not obj.is_expired()


class TrackingLinkSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    product_id = serializers.IntegerField(source="product.id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    brand_id = serializers.IntegerField(source="brand.id", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    team_id = serializers.IntegerField(source="team.id", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    campaign_id = serializers.IntegerField(source="campaign.id", read_only=True, allow_null=True)
    campaign_name = serializers.SerializerMethodField()
    content_id = serializers.IntegerField(source="content.id", read_only=True, allow_null=True)
    clicks = serializers.IntegerField(read_only=True)
    opens = serializers.IntegerField(read_only=True)
    unique_opens = serializers.IntegerField(read_only=True)
    conversions = serializers.IntegerField(read_only=True)
    share_intents = serializers.IntegerField(read_only=True)
    share_confirmed = serializers.IntegerField(read_only=True)
    earnings_gross = serializers.SerializerMethodField()
    earnings_fee = serializers.SerializerMethodField()
    earnings_net = serializers.SerializerMethodField()
    commission = serializers.SerializerMethodField()

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
            "campaign_id",
            "campaign_name",
            "content_id",
            "clicks",
            "opens",
            "unique_opens",
            "conversions",
            "share_intents",
            "share_confirmed",
            "earnings_gross",
            "earnings_fee",
            "earnings_net",
            "commission",
            "created_at",
        )
        read_only_fields = fields

    def get_url(self, obj: TrackingLink) -> str:
        return public_tracking_url(obj.code)

    def get_campaign_name(self, obj: TrackingLink) -> str:
        return obj.campaign.name if obj.campaign_id else ""

    def _money(self, obj, attr: str) -> str:
        value = getattr(obj, attr, None)
        return str(value or "0.00")

    def get_earnings_gross(self, obj: TrackingLink) -> str:
        return self._money(obj, "earnings_gross")

    def get_earnings_fee(self, obj: TrackingLink) -> str:
        return self._money(obj, "earnings_fee")

    def get_earnings_net(self, obj: TrackingLink) -> str:
        return self._money(obj, "earnings_net")

    def get_commission(self, obj: TrackingLink):
        return commission_payload(obj.product, obj.agent, obj.team)


class TrackingLinkCreateSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    team = serializers.IntegerField()
    content = serializers.IntegerField(required=False, allow_null=True)
    campaign = serializers.IntegerField(required=False, allow_null=True)
    destination_url = serializers.CharField(required=False, allow_blank=True)


class TrackingEventSerializer(serializers.ModelSerializer):
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
        )
        read_only_fields = fields

    def get_label(self, obj: TrackingEvent) -> str:
        labels = {
            TrackingEvent.EventType.CREATED: "Link created",
            TrackingEvent.EventType.OPENED: "Open",
            TrackingEvent.EventType.CLICKED: "Open",
            TrackingEvent.EventType.SHARE_INTENT: "Share intent (copied in MISA)",
            TrackingEvent.EventType.SHARE_CONFIRMED: "Share confirmed (platform API)",
            TrackingEvent.EventType.CONVERSION: "Conversion",
            TrackingEvent.EventType.CONVERSION_REVERSED: "Conversion reversed",
        }
        return labels.get(obj.event_type, obj.event_type)


class CommissionTransactionSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    tracking_code = serializers.SerializerMethodField()

    class Meta:
        model = CommissionEntry
        fields = (
            "id",
            "status",
            "currency",
            "gross_amount",
            "platform_fee_percent",
            "platform_fee_amount",
            "agent_net_amount",
            "rate_type",
            "rate_value",
            "product_name",
            "brand_name",
            "team_name",
            "tracking_code",
            "created_at",
        )
        read_only_fields = fields

    def get_tracking_code(self, obj: CommissionEntry) -> str:
        return obj.tracking_link.code if obj.tracking_link_id else ""


class LedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = (
            "id",
            "entry_type",
            "bucket",
            "amount",
            "currency",
            "source_type",
            "source_id",
            "note",
            "metadata",
            "created_at",
        )
        read_only_fields = fields


class PayoutAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutAccount
        fields = ("id", "label", "destination_ref", "is_default", "created_at")
        read_only_fields = ("id", "created_at")

    def validate_label(self, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter a payout destination label.")
        return value

    def validate_destination_ref(self, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter a payout destination.")
        return value


class WithdrawalSerializer(serializers.ModelSerializer):
    payout_account_label = serializers.CharField(source="payout_account.label", read_only=True, default="")

    class Meta:
        model = WithdrawalRequest
        fields = (
            "id",
            "amount",
            "currency",
            "status",
            "destination_ref",
            "payout_account",
            "payout_account_label",
            "rejection_reason",
            "requested_at",
            "reviewed_at",
            "processed_at",
        )
        read_only_fields = fields


class WithdrawalCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    payout_account = serializers.IntegerField(required=False, allow_null=True)
