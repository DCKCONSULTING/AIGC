from datetime import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsActiveAgent
from ai.models import VideoProject
from brands.models import Brand, Campaign, JoinRequest, Product, Team, TeamInvitation, TeamMembership
from brands.services.membership import (
    accept_invitation,
    cancel_join_request,
    create_join_request,
    decline_invitation,
    request_to_join_brand,
)
from commerce.models import CommissionEntry, LedgerEntry, PayoutAccount, TrackingEvent, TrackingLink, WithdrawalRequest
from commerce.services.ledger import cancel_withdrawal, request_withdrawal
from commerce.services.tracking import create_tracking_link, record_share_intent

from .query import (
    active_memberships,
    available_brands,
    available_products_for,
    django_error_response,
    event_counts,
    is_active_member,
    money_totals,
    own_links,
    wallet_payload,
)
from .serializers import (
    AgentBrandCardSerializer,
    AgentInvitationSerializer,
    AgentJoinRequestSerializer,
    AgentProductCardSerializer,
    AgentProductDetailSerializer,
    AgentTeamSerializer,
    CommissionTransactionSerializer,
    LedgerSerializer,
    PayoutAccountSerializer,
    TrackingEventSerializer,
    TrackingLinkCreateSerializer,
    TrackingLinkSerializer,
    WithdrawalCreateSerializer,
    WithdrawalSerializer,
)


def _attach_team_state(team: Team, user, membership=None, join_request=None, invitation=None):
    membership_status = membership.status if membership else ""
    request_status = join_request.status if join_request else ""
    invitation_status = invitation.status if invitation else ""
    expired_invite = bool(invitation and invitation.is_expired())
    pending_invite = invitation_status == TeamInvitation.Status.PENDING and not expired_invite
    pending_request = request_status == JoinRequest.Status.PENDING
    active = membership_status == TeamMembership.Status.ACTIVE
    team.membership_status = membership_status
    team.join_request_status = request_status
    team.invitation_status = TeamInvitation.Status.EXPIRED if expired_invite and invitation_status == TeamInvitation.Status.PENDING else invitation_status
    team.join_request_id = join_request.pk if join_request else None
    team.invitation_id = invitation.pk if invitation else None
    team.can_join = bool(
        team.status == Team.Status.ACTIVE
        and team.brand.status == Brand.Status.ACTIVE
        and not active
        and not pending_request
        and not pending_invite
    )
    team.can_cancel_request = pending_request
    team.can_accept_invitation = pending_invite
    if not hasattr(team, "member_count") or team.member_count is None:
        team.member_count = team.memberships.filter(status=TeamMembership.Status.ACTIVE).count()
    return team


def _team_maps(user, teams):
    team_ids = [team.pk for team in teams]
    memberships = {
        row.team_id: row
        for row in TeamMembership.objects.filter(agent=user, team_id__in=team_ids)
    }
    requests = {}
    for row in JoinRequest.objects.filter(agent=user, team_id__in=team_ids).order_by("created_at"):
        current = requests.get(row.team_id)
        if current is None or row.status == JoinRequest.Status.PENDING:
            requests[row.team_id] = row
    invitations = {}
    for row in TeamInvitation.objects.filter(agent=user, team_id__in=team_ids).order_by("created_at"):
        current = invitations.get(row.team_id)
        if current is None or row.status == TeamInvitation.Status.PENDING:
            invitations[row.team_id] = row
    return memberships, requests, invitations


def _serialize_teams(teams, user, request):
    memberships, requests, invitations = _team_maps(user, teams)
    payload = []
    for team in teams:
        _attach_team_state(
            team,
            user,
            memberships.get(team.pk),
            requests.get(team.pk),
            invitations.get(team.pk),
        )
        payload.append(AgentTeamSerializer(team, context={"request": request}).data)
    return payload


def _member_teams_for_brand(user, brand):
    return [
        row.team
        for row in active_memberships(user).filter(team__brand=brand)
    ]


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


class AgentDashboardView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        links = TrackingLink.objects.filter(agent=request.user)
        events = TrackingEvent.objects.filter(tracking_link__agent=request.user)
        commissions = CommissionEntry.objects.filter(agent=request.user)
        counts = event_counts(events)
        money = money_totals(commissions)
        wallet = wallet_payload(request.user)
        recent = (
            events.select_related("tracking_link", "tracking_link__product")
            .order_by("-created_at")[:20]
        )
        top_products = list(
            links.values("product_id", "product__name", "brand__name")
            .annotate(
                opens=Count("events", filter=Q(events__event_type=TrackingEvent.EventType.OPENED)),
                conversions=Count(
                    "events", filter=Q(events__event_type=TrackingEvent.EventType.CONVERSION)
                ),
            )
            .order_by("-conversions", "-opens")[:5]
        )
        teams = [
            {
                "id": row.team_id,
                "name": row.team.name,
                "brand_id": row.team.brand_id,
                "brand_name": row.team.brand.name,
                "status": row.status,
            }
            for row in active_memberships(request.user)
        ]
        return Response(
            {
                "total_clicks": counts["clicks"],
                "total_opens": counts["opens"],
                "unique_opens": counts["unique_opens"],
                "total_conversions": counts["conversions"],
                "gross_commission": money["gross_commission"],
                "platform_fees": money["platform_fees"],
                "net_earnings": money["net_commission"],
                "available_balance": wallet["available_balance"],
                "pending_balance": wallet["pending_balance"],
                "withdrawn_balance": wallet["withdrawn_balance"],
                "paid_balance": wallet["paid_balance"],
                "currency": wallet["currency"],
                "recent_activity": TrackingEventSerializer(recent, many=True).data,
                "top_products": [
                    {
                        "id": row["product_id"],
                        "name": row["product__name"],
                        "brand_name": row["brand__name"],
                        "opens": row["opens"],
                        "conversions": row["conversions"],
                    }
                    for row in top_products
                    if row["opens"] or row["conversions"]
                ],
                "active_teams": teams,
            }
        )


class AgentPerformanceView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        links = TrackingLink.objects.filter(agent=request.user)
        events = TrackingEvent.objects.filter(tracking_link__agent=request.user)
        commissions = CommissionEntry.objects.filter(agent=request.user)
        counts = event_counts(events)
        money = money_totals(commissions)
        return Response(
            {
                "links": links.count(),
                "opens": counts["opens"],
                "unique_opens": counts["unique_opens"],
                "clicks": counts["clicks"],
                "conversions": counts["conversions"],
                "share_intents": counts["share_intents"],
                "share_confirmed": counts["share_confirmed"],
                "gross_commission": money["gross_commission"],
                "platform_fees": money["platform_fees"],
                "net_commission": money["net_commission"],
            }
        )


class AgentBrandListView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        brands = available_brands().annotate(
            product_count=Count("products", distinct=True),
            team_count=Count("teams", filter=Q(teams__status=Team.Status.ACTIVE), distinct=True),
        )
        member_ids = set(active_memberships(request.user).values_list("team__brand_id", flat=True))
        payload = []
        for brand in brands:
            brand.membership_status = "active" if brand.pk in member_ids else ""
            payload.append(AgentBrandCardSerializer(brand, context={"request": request}).data)
        return Response(payload)


class AgentBrandDetailView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request, pk):
        brand = get_object_or_404(
            available_brands().annotate(
                product_count=Count("products", distinct=True),
                team_count=Count("teams", filter=Q(teams__status=Team.Status.ACTIVE), distinct=True),
            ),
            pk=pk,
        )
        member_ids = set(active_memberships(request.user).values_list("team__brand_id", flat=True))
        brand.membership_status = "active" if brand.pk in member_ids else ""
        teams = (
            Team.objects.filter(brand=brand)
            .exclude(status=Team.Status.ARCHIVED)
            .select_related("brand")
            .prefetch_related("campaigns")
            .annotate(member_count=Count("memberships", filter=Q(memberships__status=TeamMembership.Status.ACTIVE)))
        )
        products = (
            Product.objects.filter(brand=brand)
            .select_related("brand", "brand__category")
            .prefetch_related("images")
        )
        for product in products:
            product.can_share = brand.pk in member_ids
        return Response(
            {
                "brand": AgentBrandCardSerializer(brand, context={"request": request}).data,
                "teams": _serialize_teams(list(teams), request.user, request),
                "products": AgentProductCardSerializer(
                    products, many=True, context={"request": request}
                ).data,
            }
        )


class AgentProductListView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        products = available_products_for(request.user)
        brand_id = request.query_params.get("brand")
        team_id = request.query_params.get("team")
        if brand_id:
            products = products.filter(brand_id=brand_id)
        if team_id:
            products = products.filter(
                brand__teams__id=team_id,
                brand__teams__memberships__agent=request.user,
                brand__teams__memberships__status=TeamMembership.Status.ACTIVE,
            )
        member_brand_set = set(active_memberships(request.user).values_list("team__brand_id", flat=True))
        rows = []
        for product in products.distinct():
            product.can_share = product.brand_id in member_brand_set
            rows.append(product)
        return Response(AgentProductCardSerializer(rows, many=True, context={"request": request}).data)


class AgentProductDetailView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request, pk):
        product = get_object_or_404(
            Product.objects.select_related("brand", "brand__category").prefetch_related(
                "images", "demo_videos"
            ),
            pk=pk,
            brand__status=Brand.Status.ACTIVE,
        )
        member_teams = _member_teams_for_brand(request.user, product.brand)
        is_member = bool(member_teams)
        product.can_share = is_member
        serializer = AgentProductDetailSerializer(
            product,
            context={
                "request": request,
                "agent": request.user,
                "is_member": is_member,
                "member_teams": member_teams,
            },
        )
        return Response(serializer.data)


class AgentTeamListView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        member_ids = list(active_memberships(request.user).values_list("team_id", flat=True))
        request_ids = list(
            JoinRequest.objects.filter(agent=request.user, status=JoinRequest.Status.PENDING).values_list(
                "team_id", flat=True
            )
        )
        invite_ids = list(
            TeamInvitation.objects.filter(
                agent=request.user, status=TeamInvitation.Status.PENDING
            ).values_list("team_id", flat=True)
        )
        teams = (
            Team.objects.filter(pk__in=set(member_ids + request_ids + invite_ids))
            .select_related("brand")
            .prefetch_related("campaigns")
            .annotate(member_count=Count("memberships", filter=Q(memberships__status=TeamMembership.Status.ACTIVE)))
        )
        return Response(_serialize_teams(list(teams), request.user, request))


class AgentTeamDetailView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request, pk):
        team = get_object_or_404(
            Team.objects.select_related("brand").prefetch_related("campaigns").annotate(
                member_count=Count("memberships", filter=Q(memberships__status=TeamMembership.Status.ACTIVE))
            ),
            pk=pk,
        )
        if team.brand.status != Brand.Status.ACTIVE and not is_active_member(request.user, team):
            raise Http404
        return Response(_serialize_teams([team], request.user, request)[0])


class AgentBrandJoinView(APIView):
    permission_classes = [IsActiveAgent]

    def post(self, request, pk):
        brand = get_object_or_404(Brand, pk=pk, status=Brand.Status.ACTIVE)
        team_id = request.data.get("team") or request.data.get("team_id") or None
        try:
            team_id = int(team_id) if team_id not in (None, "") else None
        except (TypeError, ValueError):
            return Response({"team": "Choose a team to join."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            join_request = request_to_join_brand(
                brand=brand,
                agent=request.user,
                message=(request.data.get("message") or "").strip(),
                team_id=team_id,
            )
        except DjangoValidationError as exc:
            return django_error_response(exc)
        return Response(AgentJoinRequestSerializer(join_request).data, status=status.HTTP_201_CREATED)


class AgentTeamJoinView(APIView):
    permission_classes = [IsActiveAgent]

    def post(self, request, pk):
        team = get_object_or_404(Team, pk=pk, status=Team.Status.ACTIVE, brand__status=Brand.Status.ACTIVE)
        try:
            join_request = create_join_request(
                team=team,
                agent=request.user,
                message=(request.data.get("message") or "").strip(),
            )
        except DjangoValidationError as exc:
            return django_error_response(exc)
        return Response(AgentJoinRequestSerializer(join_request).data, status=status.HTTP_201_CREATED)


class AgentJoinRequestListView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        rows = JoinRequest.objects.filter(agent=request.user).select_related("team", "team__brand")
        return Response(AgentJoinRequestSerializer(rows, many=True).data)


class AgentJoinRequestCancelView(APIView):
    permission_classes = [IsActiveAgent]

    def post(self, request, pk):
        join_request = get_object_or_404(JoinRequest, pk=pk, agent=request.user)
        try:
            join_request = cancel_join_request(join_request, agent=request.user)
        except DjangoValidationError as exc:
            return django_error_response(exc)
        return Response(AgentJoinRequestSerializer(join_request).data)


class AgentInvitationListView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        rows = TeamInvitation.objects.filter(agent=request.user).select_related("team", "team__brand")
        return Response(AgentInvitationSerializer(rows, many=True).data)


class AgentInvitationAcceptView(APIView):
    permission_classes = [IsActiveAgent]

    def post(self, request, pk):
        invitation = get_object_or_404(TeamInvitation, pk=pk, agent=request.user)
        try:
            accept_invitation(invitation, agent=request.user)
        except DjangoValidationError as exc:
            return django_error_response(exc)
        invitation.refresh_from_db()
        return Response(AgentInvitationSerializer(invitation).data)


class AgentInvitationDeclineView(APIView):
    permission_classes = [IsActiveAgent]

    def post(self, request, pk):
        invitation = get_object_or_404(TeamInvitation, pk=pk, agent=request.user)
        try:
            decline_invitation(invitation, agent=request.user)
        except DjangoValidationError as exc:
            return django_error_response(exc)
        return Response(AgentInvitationSerializer(invitation).data)


class AgentLinkListCreateView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        links = own_links(request.user)
        product = request.query_params.get("product")
        brand = request.query_params.get("brand")
        team = request.query_params.get("team")
        campaign = request.query_params.get("campaign")
        status_filter = request.query_params.get("status")
        date_from = _parse_date(request.query_params.get("date_from"))
        date_to = _parse_date(request.query_params.get("date_to"))
        if product:
            links = links.filter(product_id=product)
        if brand:
            links = links.filter(brand_id=brand)
        if team:
            links = links.filter(team_id=team)
        if campaign:
            links = links.filter(campaign_id=campaign)
        if status_filter:
            links = links.filter(status=status_filter)
        if date_from:
            links = links.filter(created_at__date__gte=date_from)
        if date_to:
            links = links.filter(created_at__date__lte=date_to)
        return Response(TrackingLinkSerializer(links, many=True, context={"request": request}).data)

    def post(self, request):
        serializer = TrackingLinkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product = get_object_or_404(Product, pk=data["product"], brand__status=Brand.Status.ACTIVE)
        team = get_object_or_404(Team, pk=data["team"], brand=product.brand)
        content = None
        campaign = None
        if data.get("content"):
            content = get_object_or_404(VideoProject, pk=data["content"], product=product)
        if data.get("campaign"):
            campaign = get_object_or_404(Campaign, pk=data["campaign"], brand=product.brand)
        try:
            link = create_tracking_link(
                agent=request.user,
                team=team,
                product=product,
                campaign=campaign,
                content=content,
                destination_url=data.get("destination_url") or "",
                actor=request.user,
            )
        except DjangoValidationError as exc:
            return django_error_response(exc)
        link = own_links(request.user).get(pk=link.pk)
        return Response(
            TrackingLinkSerializer(link, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class AgentLinkDetailView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request, pk):
        link = get_object_or_404(own_links(request.user), pk=pk)
        events = TrackingEvent.objects.filter(tracking_link=link).order_by("-created_at")[:50]
        payload = TrackingLinkSerializer(link, context={"request": request}).data
        payload["activity"] = TrackingEventSerializer(events, many=True).data
        return Response(payload)


class AgentLinkShareIntentView(APIView):
    permission_classes = [IsActiveAgent]

    def post(self, request, pk):
        link = get_object_or_404(TrackingLink, pk=pk, agent=request.user)
        event = record_share_intent(tracking_link=link, request=request)
        return Response(TrackingEventSerializer(event).data, status=status.HTTP_201_CREATED)


class AgentEventListView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        events = TrackingEvent.objects.filter(tracking_link__agent=request.user).order_by("-created_at")
        event_type = request.query_params.get("event_type")
        link_id = request.query_params.get("link")
        if event_type:
            events = events.filter(event_type=event_type)
        if link_id:
            events = events.filter(tracking_link_id=link_id)
        date_from = _parse_date(request.query_params.get("date_from"))
        date_to = _parse_date(request.query_params.get("date_to"))
        if date_from:
            events = events.filter(created_at__date__gte=date_from)
        if date_to:
            events = events.filter(created_at__date__lte=date_to)
        return Response(TrackingEventSerializer(events[:200], many=True).data)


class AgentWalletView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        return Response(wallet_payload(request.user))


class AgentEarningsView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        commissions = CommissionEntry.objects.filter(agent=request.user).select_related(
            "product", "brand", "team", "tracking_link"
        )
        ledger = LedgerEntry.objects.filter(wallet__agent=request.user).order_by("-created_at")
        wallet = wallet_payload(request.user)
        return Response(
            {
                **wallet,
                "pending": CommissionTransactionSerializer(
                    commissions.filter(status=CommissionEntry.Status.PENDING), many=True
                ).data,
                "available": CommissionTransactionSerializer(
                    commissions.filter(status=CommissionEntry.Status.SETTLED), many=True
                ).data,
                "paid": CommissionTransactionSerializer(
                    commissions.filter(
                        ledger_entries__entry_type=LedgerEntry.EntryType.WITHDRAWAL_PAID
                    ).distinct(),
                    many=True,
                ).data,
                "transactions": CommissionTransactionSerializer(commissions, many=True).data,
                "ledger": LedgerSerializer(ledger, many=True).data,
            }
        )


class AgentPayoutAccountListCreateView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        rows = PayoutAccount.objects.filter(agent=request.user)
        return Response(PayoutAccountSerializer(rows, many=True).data)

    def post(self, request):
        serializer = PayoutAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("is_default"):
            PayoutAccount.objects.filter(agent=request.user, is_default=True).update(is_default=False)
        account = serializer.save(agent=request.user)
        return Response(PayoutAccountSerializer(account).data, status=status.HTTP_201_CREATED)


class AgentWithdrawalListCreateView(APIView):
    permission_classes = [IsActiveAgent]

    def get(self, request):
        rows = WithdrawalRequest.objects.filter(agent=request.user).select_related("payout_account")
        wallet = wallet_payload(request.user)
        return Response(
            {
                **wallet,
                "withdrawals": WithdrawalSerializer(rows, many=True).data,
            }
        )

    def post(self, request):
        serializer = WithdrawalCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payout = None
        payout_id = serializer.validated_data.get("payout_account")
        if payout_id:
            payout = get_object_or_404(PayoutAccount, pk=payout_id, agent=request.user)
        try:
            withdrawal = request_withdrawal(
                agent=request.user,
                amount=serializer.validated_data["amount"],
                payout_account=payout,
            )
        except DjangoValidationError as exc:
            return django_error_response(exc)
        return Response(WithdrawalSerializer(withdrawal).data, status=status.HTTP_201_CREATED)


class AgentWithdrawalCancelView(APIView):
    permission_classes = [IsActiveAgent]

    def post(self, request, pk):
        withdrawal = get_object_or_404(WithdrawalRequest, pk=pk, agent=request.user)
        try:
            withdrawal = cancel_withdrawal(withdrawal, actor=request.user)
        except DjangoValidationError as exc:
            return django_error_response(exc)
        return Response(WithdrawalSerializer(withdrawal).data)
