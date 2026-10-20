from rest_framework import serializers

from accounts.models import User
from ai.models import VideoProject
from brands.models import Campaign, JoinRequest, Product, Team, TeamInvitation, TeamMembership
from brands.query import APPROVED_CONTENT_STATUSES, owned_brand_ids
from commerce.models import CommissionRule


class BrandTeamSerializer(serializers.ModelSerializer):
    brand_id = serializers.IntegerField(source="brand.id", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    pending_requests = serializers.IntegerField(read_only=True)
    pending_invites = serializers.IntegerField(read_only=True)

    class Meta:
        model = Team
        fields = (
            "id",
            "name",
            "description",
            "status",
            "brand_id",
            "brand_name",
            "member_count",
            "pending_requests",
            "pending_invites",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "brand_id",
            "brand_name",
            "member_count",
            "pending_requests",
            "pending_invites",
            "created_at",
            "updated_at",
        )

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter a team name.")
        return value

    def validate_status(self, value: str) -> str:
        if value and value not in Team.Status.values:
            raise serializers.ValidationError("Invalid team status.")
        return value


class BrandMemberSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    agent_id = serializers.IntegerField()
    agent_name = serializers.CharField()
    agent_username = serializers.CharField()
    agent_email = serializers.CharField()
    status = serializers.CharField()
    joined_at = serializers.DateTimeField()
    links = serializers.IntegerField()
    opens = serializers.IntegerField()
    unique_opens = serializers.IntegerField(required=False)
    clicks = serializers.IntegerField()
    conversions = serializers.IntegerField()
    gross_commission = serializers.CharField()
    misa_fee = serializers.CharField()
    agent_net_earnings = serializers.CharField()
    commission_override_type = serializers.CharField(allow_blank=True)
    commission_override_value = serializers.CharField(allow_null=True)
    effective_commission = serializers.DictField(required=False)
    commission_layers = serializers.DictField(required=False)
    team_id = serializers.IntegerField(required=False)
    team_name = serializers.CharField(required=False)
    brand_id = serializers.IntegerField(required=False)
    brand_name = serializers.CharField(required=False)


class MembershipUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TeamMembership.Status.choices, required=False)
    commission_override_type = serializers.ChoiceField(
        choices=TeamMembership.OverrideType.choices,
        required=False,
        allow_blank=True,
    )
    commission_override_value = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
    )


class BrandInvitationSerializer(serializers.ModelSerializer):
    team_id = serializers.IntegerField(source="team.id", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    brand_id = serializers.IntegerField(source="team.brand.id", read_only=True)
    brand_name = serializers.CharField(source="team.brand.name", read_only=True)
    agent_id = serializers.IntegerField(source="agent.id", read_only=True)
    agent_name = serializers.CharField(source="agent.name", read_only=True)
    agent_username = serializers.CharField(source="agent.username", read_only=True)
    agent_email = serializers.EmailField(source="agent.email", read_only=True)
    invited_by_name = serializers.CharField(source="invited_by.name", read_only=True)
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = TeamInvitation
        fields = (
            "id",
            "team_id",
            "team_name",
            "brand_id",
            "brand_name",
            "agent_id",
            "agent_name",
            "agent_username",
            "agent_email",
            "status",
            "invited_by_name",
            "created_at",
            "expires_at",
            "responded_at",
            "can_cancel",
        )
        read_only_fields = fields

    def get_can_cancel(self, obj: TeamInvitation) -> bool:
        return obj.status == TeamInvitation.Status.PENDING and not obj.is_expired()


class InviteAgentSerializer(serializers.Serializer):
    agent = serializers.IntegerField()
    expires_in_days = serializers.IntegerField(required=False, min_value=1, max_value=90)


class BrandJoinRequestSerializer(serializers.ModelSerializer):
    team_id = serializers.IntegerField(source="team.id", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    brand_id = serializers.IntegerField(source="team.brand.id", read_only=True)
    brand_name = serializers.CharField(source="team.brand.name", read_only=True)
    agent_id = serializers.IntegerField(source="agent.id", read_only=True)
    agent_name = serializers.CharField(source="agent.name", read_only=True)
    agent_username = serializers.CharField(source="agent.username", read_only=True)
    agent_email = serializers.EmailField(source="agent.email", read_only=True)
    can_review = serializers.SerializerMethodField()

    class Meta:
        model = JoinRequest
        fields = (
            "id",
            "team_id",
            "team_name",
            "brand_id",
            "brand_name",
            "agent_id",
            "agent_name",
            "agent_username",
            "agent_email",
            "status",
            "message",
            "created_at",
            "responded_at",
            "can_review",
        )
        read_only_fields = fields

    def get_can_review(self, obj: JoinRequest) -> bool:
        return obj.status == JoinRequest.Status.PENDING


class AgentSearchSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "name", "email", "location", "status")
        read_only_fields = fields

    def get_status(self, obj: User) -> str:
        profile = getattr(obj, "agent_profile", None)
        return profile.status if profile else "active"


class BrandContentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    duration_seconds = serializers.IntegerField()
    language = serializers.CharField()
    preview_url = serializers.CharField(allow_blank=True)
    final_url = serializers.CharField(allow_blank=True)
    export_url = serializers.CharField(allow_blank=True)
    updated_at = serializers.DateTimeField()
    available = serializers.BooleanField()


class BrandCampaignSerializer(serializers.ModelSerializer):
    brand_id = serializers.IntegerField(source="brand.id", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    product_id = serializers.IntegerField(source="product.id", read_only=True, allow_null=True)
    product_name = serializers.CharField(source="product.name", read_only=True, allow_null=True)
    team_id = serializers.IntegerField(source="team.id", read_only=True, allow_null=True)
    team_name = serializers.CharField(source="team.name", read_only=True, allow_null=True)
    content_id = serializers.IntegerField(source="content.id", read_only=True, allow_null=True)
    content_status = serializers.SerializerMethodField()
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), required=False, allow_null=True
    )
    team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), required=False, allow_null=True)
    content = serializers.PrimaryKeyRelatedField(
        queryset=VideoProject.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Campaign
        fields = (
            "id",
            "name",
            "description",
            "status",
            "brand",
            "brand_id",
            "brand_name",
            "product",
            "product_id",
            "product_name",
            "team",
            "team_id",
            "team_name",
            "content",
            "content_id",
            "content_status",
            "start_at",
            "end_at",
            "commission_type",
            "commission_value",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "brand_id",
            "brand_name",
            "product_id",
            "product_name",
            "team_id",
            "team_name",
            "content_id",
            "content_status",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {"brand": {"required": False}}

    def get_content_status(self, obj: Campaign) -> str:
        return obj.content.status if obj.content_id else ""

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter a campaign name.")
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        brand = attrs.get("brand") or getattr(self.instance, "brand", None)
        product = attrs.get("product", getattr(self.instance, "product", None))
        team = attrs.get("team", getattr(self.instance, "team", None))
        content = attrs.get("content", getattr(self.instance, "content", None))
        owned = set(owned_brand_ids(request)) if request else set()
        if brand and owned and brand.pk not in owned:
            raise serializers.ValidationError({"brand": "Choose one of your brands."})
        if product and brand and product.brand_id != brand.pk:
            raise serializers.ValidationError({"product": "Product must belong to this brand."})
        if team and brand and team.brand_id != brand.pk:
            raise serializers.ValidationError({"team": "Team must belong to this brand."})
        if content:
            if content.product.brand_id != (brand.pk if brand else content.product.brand_id):
                raise serializers.ValidationError({"content": "Content must belong to this brand."})
            if product and content.product_id != product.pk:
                raise serializers.ValidationError({"content": "Content must belong to the assigned product."})
            if content.status not in APPROVED_CONTENT_STATUSES:
                raise serializers.ValidationError(
                    {"content": "Only approved or exported Studio videos can be assigned."}
                )
        commission_type = attrs.get("commission_type", getattr(self.instance, "commission_type", ""))
        commission_value = attrs.get("commission_value", getattr(self.instance, "commission_value", None))
        if commission_type and commission_value is None:
            raise serializers.ValidationError({"commission_value": "Enter a commission value."})
        if commission_value is not None and commission_value < 0:
            raise serializers.ValidationError({"commission_value": "Commission must be zero or greater."})
        return attrs


class CommissionRuleSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True, default="")
    team_name = serializers.CharField(source="team.name", read_only=True, default="")
    agent_name = serializers.CharField(source="agent.name", read_only=True, default="")
    brand_name = serializers.CharField(source="brand.name", read_only=True, default="")

    class Meta:
        model = CommissionRule
        fields = (
            "id",
            "name",
            "scope",
            "brand",
            "brand_name",
            "product",
            "product_name",
            "team",
            "team_name",
            "agent",
            "agent_name",
            "rate_type",
            "rate_value",
            "currency",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "brand_name",
            "product_name",
            "team_name",
            "agent_name",
            "created_at",
            "updated_at",
        )


class CommissionRuleWriteSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=[
            CommissionRule.Scope.BRAND,
            CommissionRule.Scope.PRODUCT,
            CommissionRule.Scope.TEAM,
            CommissionRule.Scope.AGENT,
        ]
    )
    rate_type = serializers.ChoiceField(choices=CommissionRule.RateType.choices)
    rate_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    product = serializers.IntegerField(required=False, allow_null=True)
    team = serializers.IntegerField(required=False, allow_null=True)
    agent = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_blank=True)
    brand = serializers.IntegerField(required=False, allow_null=True)
