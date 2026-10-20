from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsBrandOwner
from ai.models import VideoProject
from brands.models import (
    Brand,
    Campaign,
    JoinRequest,
    Product,
    Team,
    TeamInvitation,
    TeamMembership,
)
from brands.query import (
    content_ref,
    django_error_response,
    event_counts,
    get_owned_campaign,
    get_owned_product,
    get_owned_team,
    member_performance_rows,
    money_totals,
    owned_brand_ids,
    owned_brands,
    owned_campaigns,
    owned_products,
    owned_teams,
    performance_payload,
    scoped_links,
    sort_member_rows,
)
from brands.serializers import primary_brand_for
from brands.services.membership import (
    accept_join_request,
    cancel_invitation,
    invite_agent,
    reject_join_request,
    set_membership_status,
    set_team_status,
)
from commerce.models import CommissionEntry, CommissionRule, TrackingEvent, TrackingLink
from commerce.services.audit import record_audit
from commerce.services.commissions import preview_commission, upsert_commission_rule

from .management_serializers import (
    AgentSearchSerializer,
    BrandCampaignSerializer,
    BrandInvitationSerializer,
    BrandJoinRequestSerializer,
    BrandMemberSerializer,
    BrandTeamSerializer,
    CommissionRuleSerializer,
    CommissionRuleWriteSerializer,
    InviteAgentSerializer,
    MembershipUpdateSerializer,
)


def _audit(request, action, obj, payload=None):
    record_audit(
        action=action,
        actor=request.user,
        impersonator=getattr(request, "impersonator", None),
        object_type=obj.__class__.__name__,
        object_id=str(getattr(obj, "pk", "")),
        payload=payload or {},
    )


def _default_brand(request, brand_id=None) -> Brand:
    brands = owned_brands(request)
    if brand_id:
        return get_object_or_404(brands, pk=brand_id)
    brand = primary_brand_for(request.user, request)
    if brand is None or brand.pk not in set(owned_brand_ids(request)):
        raise DjangoValidationError("Create a brand before managing teams.")
    return brand


def _annotate_teams(queryset):
    return queryset.annotate(
        member_count=Count(
            "memberships",
            filter=Q(memberships__status=TeamMembership.Status.ACTIVE),
            distinct=True,
        ),
        pending_requests=Count(
            "join_requests",
            filter=Q(join_requests__status=JoinRequest.Status.PENDING),
            distinct=True,
        ),
        pending_invites=Count(
            "invitations",
            filter=Q(invitations__status=TeamInvitation.Status.PENDING),
            distinct=True,
        ),
    )


class BrandTeamListCreateView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        teams = _annotate_teams(owned_teams(request))
        status_filter = request.query_params.get("status")
        if status_filter:
            teams = teams.filter(status=status_filter)
        return Response(BrandTeamSerializer(teams, many=True).data)

    def post(self, request):
        serializer = BrandTeamSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        brand_id = request.data.get("brand") or request.data.get("brand_id")
        try:
            if not brand_id and owned_brands(request).count() > 1:
                raise DjangoValidationError("Choose a brand for this team.")
            brand = _default_brand(request, brand_id)
        except DjangoValidationError as exc:
            return django_error_response(exc)
        if Team.objects.filter(brand=brand, name=serializer.validated_data["name"]).exists():
            return Response(
                {"name": "A team with this name already exists for this brand."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        team = serializer.save(brand=brand)
        _audit(request, "team.created", team, {"name": team.name})
        team = _annotate_teams(owned_teams(request).filter(pk=team.pk)).first()
        return Response(BrandTeamSerializer(team).data, status=status.HTTP_201_CREATED)


class BrandTeamDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        team = get_owned_team(request, pk)
        team = _annotate_teams(owned_teams(request).filter(pk=team.pk)).first()
        members = member_performance_rows(team, request)
        status_filter = request.query_params.get("status")
        query = (request.query_params.get("q") or "").strip().lower()
        if status_filter:
            members = [row for row in members if row["status"] == status_filter]
        if query:
            members = [
                row
                for row in members
                if query in row["agent_name"].lower()
                or query in row["agent_username"].lower()
                or query in row["agent_email"].lower()
            ]
        members = sort_member_rows(members, request.query_params.get("sort"))
        product_id = request.query_params.get("product")
        product = None
        if product_id:
            product = get_owned_product(request, product_id)
            for row in members:
                preview = preview_commission(product=product, agent=row["agent_id"] and User.objects.filter(pk=row["agent_id"]).first(), team=team)
                row["effective_commission"] = preview.get("effective")
                row["commission_layers"] = preview.get("layers")
        invitations = TeamInvitation.objects.filter(team=team).select_related(
            "agent", "team", "team__brand", "invited_by"
        )
        requests = JoinRequest.objects.filter(team=team).select_related(
            "agent", "team", "team__brand"
        )
        return Response(
            {
                "team": BrandTeamSerializer(team).data,
                "members": BrandMemberSerializer(members, many=True).data,
                "invitations": BrandInvitationSerializer(invitations, many=True).data,
                "join_requests": BrandJoinRequestSerializer(requests, many=True).data,
            }
        )

    def patch(self, request, pk):
        team = get_owned_team(request, pk)
        serializer = BrandTeamSerializer(
            team, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if name and Team.objects.filter(brand=team.brand, name=name).exclude(pk=team.pk).exists():
            return Response(
                {"name": "A team with this name already exists for this brand."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        status_value = serializer.validated_data.get("status")
        if status_value:
            try:
                set_team_status(team, status_value)
            except DjangoValidationError as exc:
                return django_error_response(exc)
        serializer.save()
        team.refresh_from_db()
        _audit(request, "team.updated", team, {"name": team.name, "status": team.status})
        team = _annotate_teams(owned_teams(request).filter(pk=team.pk)).first()
        return Response(BrandTeamSerializer(team).data)


class BrandTeamInviteView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        team = get_owned_team(request, pk)
        serializer = InviteAgentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        agent = User.objects.filter(
            pk=serializer.validated_data["agent"],
            role=User.Role.AGENT,
            is_active=True,
        ).first()
        if agent is None:
            return Response({"agent": "Select an eligible agent."}, status=status.HTTP_400_BAD_REQUEST)
        profile = getattr(agent, "agent_profile", None)
        if profile and profile.status == "suspended":
            return Response({"agent": "This agent is suspended."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            invite = invite_agent(
                team=team,
                agent=agent,
                invited_by=request.user,
                expires_in_days=serializer.validated_data.get("expires_in_days", 14),
            )
        except DjangoValidationError as exc:
            return django_error_response(exc)
        _audit(request, "team.invited", invite, {"agent": agent.pk, "team": team.pk})
        return Response(BrandInvitationSerializer(invite).data, status=status.HTTP_201_CREATED)


class BrandInvitationListView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        invites = TeamInvitation.objects.filter(
            team__brand_id__in=owned_brand_ids(request)
        ).select_related("agent", "team", "team__brand", "invited_by")
        team = request.query_params.get("team")
        status_filter = request.query_params.get("status")
        if team:
            invites = invites.filter(team_id=team)
        if status_filter:
            invites = invites.filter(status=status_filter)
        return Response(BrandInvitationSerializer(invites, many=True).data)


class BrandInvitationCancelView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        invite = get_object_or_404(
            TeamInvitation.objects.filter(team__brand_id__in=owned_brand_ids(request)),
            pk=pk,
        )
        try:
            invite = cancel_invitation(invite)
        except DjangoValidationError as exc:
            return django_error_response(exc)
        _audit(request, "invitation.cancelled", invite)
        return Response(BrandInvitationSerializer(invite).data)


class BrandJoinRequestListView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        rows = JoinRequest.objects.filter(
            team__brand_id__in=owned_brand_ids(request)
        ).select_related("agent", "team", "team__brand")
        team = request.query_params.get("team")
        status_filter = request.query_params.get("status", JoinRequest.Status.PENDING)
        if team:
            rows = rows.filter(team_id=team)
        if status_filter and status_filter != "all":
            rows = rows.filter(status=status_filter)
        return Response(BrandJoinRequestSerializer(rows, many=True).data)


class BrandJoinRequestApproveView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        join_request = get_object_or_404(
            JoinRequest.objects.filter(team__brand_id__in=owned_brand_ids(request)),
            pk=pk,
        )
        try:
            accept_join_request(join_request, reviewed_by=request.user)
        except DjangoValidationError as exc:
            return django_error_response(exc)
        join_request.refresh_from_db()
        _audit(request, "join_request.approved", join_request)
        return Response(BrandJoinRequestSerializer(join_request).data)


class BrandJoinRequestRejectView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        join_request = get_object_or_404(
            JoinRequest.objects.filter(team__brand_id__in=owned_brand_ids(request)),
            pk=pk,
        )
        try:
            reject_join_request(join_request, reviewed_by=request.user)
        except DjangoValidationError as exc:
            return django_error_response(exc)
        _audit(request, "join_request.rejected", join_request)
        return Response(BrandJoinRequestSerializer(join_request).data)


class BrandMembershipDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def patch(self, request, pk):
        membership = get_object_or_404(
            TeamMembership.objects.filter(team__brand_id__in=owned_brand_ids(request)).select_related(
                "team", "agent"
            ),
            pk=pk,
        )
        serializer = MembershipUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "status" in data:
            try:
                set_membership_status(membership, data["status"])
            except DjangoValidationError as exc:
                return django_error_response(exc)
        if "commission_override_type" in data or "commission_override_value" in data:
            override_type = data.get("commission_override_type", membership.commission_override_type)
            override_value = data.get("commission_override_value", membership.commission_override_value)
            if override_type == "":
                membership.commission_override_type = ""
                membership.commission_override_value = None
            else:
                membership.commission_override_type = override_type
                membership.commission_override_value = override_value
            membership.save(
                update_fields=["commission_override_type", "commission_override_value", "updated_at"]
            )
        membership.refresh_from_db()
        _audit(request, "membership.updated", membership, {"status": membership.status})
        rows = member_performance_rows(membership.team, request, [membership])
        return Response(BrandMemberSerializer(rows[0]).data)


class BrandAgentSearchView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        team_id = request.query_params.get("team")
        agents = User.objects.filter(role=User.Role.AGENT, is_active=True).select_related("agent_profile")
        agents = agents.exclude(agent_profile__status="suspended")
        if query:
            agents = agents.filter(
                Q(username__icontains=query)
                | Q(name__icontains=query)
                | Q(email__icontains=query)
            )
        if team_id:
            team = get_owned_team(request, team_id)
            agents = agents.exclude(
                team_memberships__team=team,
                team_memberships__status=TeamMembership.Status.ACTIVE,
            )
        agents = agents.order_by("name", "username")[:25]
        return Response(AgentSearchSerializer(agents, many=True).data)


class BrandAgentListView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        memberships = TeamMembership.objects.filter(
            team__brand_id__in=owned_brand_ids(request)
        ).select_related("agent", "team", "team__brand")
        team = request.query_params.get("team")
        status_filter = request.query_params.get("status")
        query = (request.query_params.get("q") or "").strip().lower()
        if team:
            memberships = memberships.filter(team_id=team)
        if status_filter:
            memberships = memberships.filter(status=status_filter)
        else:
            memberships = memberships.exclude(status=TeamMembership.Status.REMOVED)
        rows = []
        for membership in memberships:
            agent = membership.agent
            if query and query not in " ".join(
                [agent.name, agent.username, agent.email]
            ).lower():
                continue
            rows.append(
                {
                    "id": membership.pk,
                    "agent_id": agent.pk,
                    "agent_name": agent.name or agent.username,
                    "agent_username": agent.username,
                    "agent_email": agent.email,
                    "status": membership.status,
                    "team_id": membership.team_id,
                    "team_name": membership.team.name,
                    "brand_id": membership.team.brand_id,
                    "brand_name": membership.team.brand.name,
                    "joined_at": membership.joined_at,
                }
            )
        return Response(rows)


class BrandCampaignListCreateView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        campaigns = owned_campaigns(request)
        status_filter = request.query_params.get("status")
        team = request.query_params.get("team")
        product = request.query_params.get("product")
        if status_filter:
            campaigns = campaigns.filter(status=status_filter)
        if team:
            campaigns = campaigns.filter(team_id=team)
        if product:
            campaigns = campaigns.filter(product_id=product)
        return Response(BrandCampaignSerializer(campaigns, many=True, context={"request": request}).data)

    def post(self, request):
        data = request.data.copy()
        try:
            brand = _default_brand(request, data.get("brand"))
        except DjangoValidationError as exc:
            return django_error_response(exc)
        data["brand"] = brand.pk
        serializer = BrandCampaignSerializer(data=data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        campaign = serializer.save(brand=brand)
        _audit(request, "campaign.created", campaign, {"name": campaign.name})
        return Response(
            BrandCampaignSerializer(campaign, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class BrandCampaignDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        campaign = get_owned_campaign(request, pk)
        links = scoped_links(request).filter(campaign=campaign)
        payload = BrandCampaignSerializer(campaign, context={"request": request}).data
        payload["performance"] = performance_payload(request, links)
        if campaign.content_id:
            payload["content_ref"] = content_ref(campaign.content, request)
        return Response(payload)

    def patch(self, request, pk):
        campaign = get_owned_campaign(request, pk)
        serializer = BrandCampaignSerializer(
            campaign,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        campaign.refresh_from_db()
        _audit(request, "campaign.updated", campaign, {"status": campaign.status})
        return Response(BrandCampaignSerializer(campaign, context={"request": request}).data)


class BrandCampaignPerformanceView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        campaign = get_owned_campaign(request, pk)
        links = scoped_links(request).filter(campaign=campaign)
        return Response(performance_payload(request, links))


class BrandPerformanceView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        data = performance_payload(request)
        links = scoped_links(request)
        by_product = []
        for row in (
            links.values("product_id", "product__name")
            .annotate(
                opens=Count("events", filter=Q(events__event_type=TrackingEvent.EventType.OPENED)),
                unique_opens=Count(
                    "events__visitor_key",
                    filter=Q(events__event_type=TrackingEvent.EventType.OPENED)
                    & ~Q(events__visitor_key=""),
                    distinct=True,
                ),
                conversions=Count(
                    "events", filter=Q(events__event_type=TrackingEvent.EventType.CONVERSION)
                ),
            )
            .order_by("-conversions", "-opens")[:10]
        ):
            if row["opens"] or row["conversions"]:
                by_product.append(
                    {
                        "id": row["product_id"],
                        "name": row["product__name"],
                        "opens": row["opens"],
                        "unique_opens": row["unique_opens"],
                        "clicks": row["opens"],
                        "conversions": row["conversions"],
                    }
                )
        data["by_product"] = by_product
        return Response(data)


class BrandDistributionView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        products = owned_products(request)
        product_id = request.query_params.get("product")
        if product_id:
            products = products.filter(pk=product_id)
        brand_ids = set(owned_brand_ids(request))
        projects = VideoProject.objects.filter(product__brand_id__in=brand_ids).select_related("product")
        links = TrackingLink.objects.filter(brand_id__in=brand_ids)
        events = TrackingEvent.objects.filter(tracking_link__brand_id__in=brand_ids)
        commissions = CommissionEntry.objects.filter(brand_id__in=brand_ids).exclude(
            status=CommissionEntry.Status.REVERSED
        )
        payload = []
        for product in products:
            product_projects = [item for item in projects if item.product_id == product.pk]
            available = [item for item in product_projects if item.status in ("approved", "exported")]
            product_links = links.filter(product=product)
            product_events = events.filter(tracking_link__product=product)
            counts = event_counts(product_events)
            money = money_totals(commissions.filter(product=product))
            active_agents = (
                TeamMembership.objects.filter(
                    team__brand=product.brand,
                    status=TeamMembership.Status.ACTIVE,
                )
                .values("agent_id")
                .distinct()
                .count()
            )
            payload.append(
                {
                    "product_id": product.pk,
                    "product_name": product.name,
                    "brand_id": product.brand_id,
                    "brand_name": product.brand.name,
                    "generated_content": len(product_projects),
                    "available_videos": len(available),
                    "content": [content_ref(item, request) for item in product_projects],
                    "available_content": [content_ref(item, request) for item in available],
                    "active_agents": active_agents,
                    "tracking_links": product_links.count(),
                    "opens": counts["opens"],
                    "unique_opens": counts["unique_opens"],
                    "clicks": counts["clicks"],
                    "conversions": counts["conversions"],
                    "commission_generated": money["gross_commission"],
                }
            )
        return Response(payload)


class BrandCommissionRuleListCreateView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        rules = CommissionRule.objects.filter(
            Q(brand_id__in=owned_brand_ids(request))
            | Q(product__brand_id__in=owned_brand_ids(request))
            | Q(team__brand_id__in=owned_brand_ids(request))
        ).exclude(scope=CommissionRule.Scope.PLATFORM)
        scope = request.query_params.get("scope")
        if scope:
            rules = rules.filter(scope=scope)
        return Response(CommissionRuleSerializer(rules, many=True).data)

    def post(self, request):
        serializer = CommissionRuleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            brand, product, team, agent = _resolve_rule_targets(request, data)
            rule = upsert_commission_rule(
                scope=data["scope"],
                rate_type=data["rate_type"],
                rate_value=data["rate_value"],
                brand=brand,
                product=product,
                team=team,
                agent=agent,
                name=data.get("name") or "",
            )
        except DjangoValidationError as exc:
            return django_error_response(exc)
        except Http404:
            raise
        _audit(request, "commission_rule.upserted", rule, {"scope": rule.scope})
        return Response(CommissionRuleSerializer(rule).data, status=status.HTTP_201_CREATED)


class BrandCommissionRuleDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def _get(self, request, pk) -> CommissionRule:
        return get_object_or_404(
            CommissionRule.objects.filter(
                Q(brand_id__in=owned_brand_ids(request))
                | Q(product__brand_id__in=owned_brand_ids(request))
                | Q(team__brand_id__in=owned_brand_ids(request))
            ).exclude(scope=CommissionRule.Scope.PLATFORM),
            pk=pk,
        )

    def patch(self, request, pk):
        rule = self._get(request, pk)
        serializer = CommissionRuleWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            if "rate_type" in data or "rate_value" in data:
                rule = upsert_commission_rule(
                    scope=data.get("scope", rule.scope),
                    rate_type=data.get("rate_type", rule.rate_type),
                    rate_value=data.get("rate_value", rule.rate_value),
                    brand=rule.brand,
                    product=rule.product,
                    team=rule.team,
                    agent=rule.agent,
                    name=data.get("name", rule.name),
                )
            elif "name" in data:
                rule.name = data["name"]
                rule.save(update_fields=["name", "updated_at"])
        except DjangoValidationError as exc:
            return django_error_response(exc)
        if "is_active" in request.data:
            rule.is_active = bool(request.data.get("is_active"))
            rule.save(update_fields=["is_active", "updated_at"])
        _audit(request, "commission_rule.updated", rule)
        return Response(CommissionRuleSerializer(rule).data)

    def delete(self, request, pk):
        rule = self._get(request, pk)
        rule.is_active = False
        rule.save(update_fields=["is_active", "updated_at"])
        _audit(request, "commission_rule.deactivated", rule)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BrandCommissionPreviewView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        product_id = request.query_params.get("product")
        if not product_id:
            return Response({"product": "Select a product."}, status=status.HTTP_400_BAD_REQUEST)
        product = get_owned_product(request, product_id)
        team = None
        agent = None
        campaign = None
        if request.query_params.get("team"):
            team = get_owned_team(request, request.query_params.get("team"))
        if request.query_params.get("agent"):
            agent = User.objects.filter(
                pk=request.query_params.get("agent"),
                role=User.Role.AGENT,
            ).first()
            if agent is None:
                return Response({"agent": "Unknown agent."}, status=status.HTTP_400_BAD_REQUEST)
            if team and not TeamMembership.objects.filter(team=team, agent=agent).exists():
                return Response(
                    {"agent": "This agent is not a member of the selected team."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if request.query_params.get("campaign"):
            campaign = get_owned_campaign(request, request.query_params.get("campaign"))
        return Response(preview_commission(product=product, agent=agent, team=team, campaign=campaign))


class BrandProductCommissionView(APIView):
    permission_classes = [IsBrandOwner]

    def patch(self, request, pk):
        product = get_owned_product(request, pk)
        amount = request.data.get("commission_amount")
        percent = request.data.get("commission")
        if amount is not None:
            try:
                from decimal import Decimal

                value = Decimal(str(amount))
            except Exception:
                return Response(
                    {"commission_amount": "Enter a valid amount."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if value < 0:
                return Response(
                    {"commission_amount": "Fixed commission must be zero or greater."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            product.commission_amount = value
        if percent is not None:
            try:
                from decimal import Decimal

                value = Decimal(str(percent))
            except Exception:
                return Response(
                    {"commission": "Enter a valid percent."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if value < 0 or value > 100:
                return Response(
                    {"commission": "Commission must be between 0 and 100."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            product.commission = value
        product.save(update_fields=["commission_amount", "commission"])
        _audit(
            request,
            "product.commission_updated",
            product,
            {"commission_amount": str(product.commission_amount), "commission": str(product.commission)},
        )
        team = None
        if request.query_params.get("team"):
            team = get_owned_team(request, request.query_params.get("team"))
        preview = preview_commission(product=product, team=team)
        return Response(
            {
                "product_id": product.pk,
                "commission": str(product.commission),
                "commission_amount": str(product.commission_amount),
                "preview": preview,
            }
        )


def _resolve_rule_targets(request, data):
    brand = _default_brand(request, data.get("brand"))
    product = None
    team = None
    agent = None
    if data.get("product"):
        product = get_owned_product(request, data["product"])
        brand = product.brand
    if data.get("team"):
        team = get_owned_team(request, data["team"])
        brand = team.brand
    if data.get("agent"):
        agent = User.objects.filter(pk=data["agent"], role=User.Role.AGENT).first()
        if agent is None:
            raise DjangoValidationError("Select an eligible agent.")
        if team is None:
            if not TeamMembership.objects.filter(
                agent=agent,
                team__brand_id__in=owned_brand_ids(request),
            ).exists():
                raise DjangoValidationError("This agent is not on one of your teams.")
        elif not TeamMembership.objects.filter(team=team, agent=agent).exists():
            raise DjangoValidationError("This agent is not a member of the selected team.")
    return brand, product, team, agent
