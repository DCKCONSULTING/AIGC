from datetime import datetime
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.response import Response
from rest_framework import status as http_status

from accounts.authentication import acting_brand_id
from ai.models import VideoProject, VideoProjectStatus
from brands.models import Brand, Campaign, Product, Team, TeamMembership
from commerce.models import CommissionEntry, TrackingEvent, TrackingLink
from commerce.services.commissions import money as as_money
from commerce.services.tracking import event_metrics as event_counts

APPROVED_CONTENT_STATUSES = (
    VideoProjectStatus.APPROVED,
    VideoProjectStatus.EXPORTED,
)

MEMBER_SORTS = {
    "agent": "agent_name",
    "status": "status",
    "joined_at": "joined_at",
    "links": "links",
    "opens": "opens",
    "unique_opens": "unique_opens",
    "clicks": "clicks",
    "conversions": "conversions",
    "gross_commission": "gross_commission",
    "misa_fee": "misa_fee",
    "agent_net_earnings": "agent_net_earnings",
}


def django_error_response(exc) -> Response:
    if getattr(exc, "message_dict", None):
        return Response(exc.message_dict, status=http_status.HTTP_400_BAD_REQUEST)
    messages = list(getattr(exc, "messages", []) or [str(exc)])
    return Response({"detail": messages[0]}, status=http_status.HTTP_400_BAD_REQUEST)


def owned_brands(request):
    brands = Brand.objects.filter(owner=request.user)
    acting = acting_brand_id(request)
    if acting:
        brands = brands.filter(pk=acting)
    return brands


def owned_brand_ids(request):
    return owned_brands(request).values_list("pk", flat=True)


def owned_teams(request):
    return Team.objects.filter(brand_id__in=owned_brand_ids(request)).select_related("brand")


def owned_products(request):
    return Product.objects.filter(brand_id__in=owned_brand_ids(request)).select_related("brand")


def owned_campaigns(request):
    return Campaign.objects.filter(brand_id__in=owned_brand_ids(request)).select_related(
        "brand", "product", "team", "content"
    )


def get_owned_team(request, pk) -> Team:
    return get_object_or_404(owned_teams(request), pk=pk)


def get_owned_product(request, pk) -> Product:
    return get_object_or_404(owned_products(request), pk=pk)


def get_owned_campaign(request, pk) -> Campaign:
    return get_object_or_404(owned_campaigns(request), pk=pk)


def require_owned_brand(request, brand: Brand | None):
    if brand is None:
        raise Http404
    if brand.pk not in set(owned_brand_ids(request)):
        raise Http404
    return brand


def parse_filter_date(value):
    if not value:
        return None
    parsed = parse_datetime(value) or parse_date(value)
    return parsed


def apply_date_filter(queryset, request, field="created_at"):
    date_from = parse_filter_date(request.query_params.get("date_from"))
    date_to = parse_filter_date(request.query_params.get("date_to"))
    if date_from:
        if isinstance(date_from, datetime):
            queryset = queryset.filter(**{f"{field}__gte": date_from})
        else:
            queryset = queryset.filter(**{f"{field}__date__gte": date_from})
    if date_to:
        if isinstance(date_to, datetime):
            queryset = queryset.filter(**{f"{field}__lte": date_to})
        else:
            queryset = queryset.filter(**{f"{field}__date__lte": date_to})
    return queryset


def scoped_links(request):
    links = TrackingLink.objects.filter(brand_id__in=owned_brand_ids(request))
    team = request.query_params.get("team")
    agent = request.query_params.get("agent")
    product = request.query_params.get("product")
    campaign = request.query_params.get("campaign")
    if team:
        links = links.filter(team_id=team, team__brand_id__in=owned_brand_ids(request))
    if agent:
        links = links.filter(agent_id=agent)
    if product:
        links = links.filter(product_id=product, product__brand_id__in=owned_brand_ids(request))
    if campaign:
        links = links.filter(campaign_id=campaign, campaign__brand_id__in=owned_brand_ids(request))
    return links.select_related("product", "brand", "team", "campaign", "content", "agent")


def money_totals(queryset) -> dict:
    totals = queryset.exclude(status=CommissionEntry.Status.REVERSED).aggregate(
        gross=Sum("gross_amount"),
        fees=Sum("platform_fee_amount"),
        net=Sum("agent_net_amount"),
    )
    return {
        "gross_commission": str(as_money(totals["gross"] or Decimal("0.00"))),
        "platform_fees": str(as_money(totals["fees"] or Decimal("0.00"))),
        "agent_payouts": str(as_money(totals["net"] or Decimal("0.00"))),
    }


def performance_payload(request, links=None) -> dict:
    links = links if links is not None else scoped_links(request)
    link_ids = list(links.values_list("pk", flat=True))
    events = TrackingEvent.objects.filter(tracking_link_id__in=link_ids)
    commissions = CommissionEntry.objects.filter(tracking_link_id__in=link_ids)
    events = apply_date_filter(events, request)
    commissions = apply_date_filter(commissions, request)
    counts = event_counts(events)
    money = money_totals(commissions)
    memberships = TeamMembership.objects.filter(team__brand_id__in=owned_brand_ids(request))
    team = request.query_params.get("team")
    agent = request.query_params.get("agent")
    if team:
        memberships = memberships.filter(team_id=team, team__brand_id__in=owned_brand_ids(request))
    if agent:
        memberships = memberships.filter(agent_id=agent)
    total_agents = memberships.exclude(status=TeamMembership.Status.REMOVED).values("agent_id").distinct().count()
    active_agents = memberships.filter(status=TeamMembership.Status.ACTIVE).values("agent_id").distinct().count()
    dated_links = apply_date_filter(links, request)
    return {
        "total_agents": total_agents,
        "active_agents": active_agents,
        "links": dated_links.count(),
        "opens": counts["opens"],
        "unique_opens": counts["unique_opens"],
        "clicks": counts["clicks"],
        "conversions": counts["conversions"],
        "share_intents": counts["share_intents"],
        "share_confirmed": counts["share_confirmed"],
        "gross_commissions": money["gross_commission"],
        "platform_fees": money["platform_fees"],
        "agent_payouts": money["agent_payouts"],
    }


def content_ref(project: VideoProject, request=None) -> dict:
    def url(field):
        if not field:
            return ""
        value = field.url
        if request is not None:
            return request.build_absolute_uri(value)
        return value

    return {
        "id": project.pk,
        "status": project.status,
        "duration_seconds": project.duration_seconds,
        "language": project.language,
        "preview_url": url(project.preview_video),
        "final_url": url(project.final_video),
        "export_url": url(project.export_file),
        "updated_at": project.updated_at,
        "available": project.status in APPROVED_CONTENT_STATUSES,
    }


def member_performance_rows(team: Team, request, memberships=None) -> list[dict]:
    memberships = memberships if memberships is not None else team.memberships.select_related("agent")
    agent_ids = [row.agent_id for row in memberships]
    links = TrackingLink.objects.filter(team=team, agent_id__in=agent_ids)
    events = apply_date_filter(
        TrackingEvent.objects.filter(tracking_link__in=links),
        request,
    )
    commissions = apply_date_filter(
        CommissionEntry.objects.filter(tracking_link__in=links).exclude(
            status=CommissionEntry.Status.REVERSED
        ),
        request,
    )
    link_counts = {
        row["agent_id"]: row["total"]
        for row in links.values("agent_id").annotate(total=Count("id"))
    }
    event_rows = events.values("tracking_link__agent_id", "event_type").annotate(total=Count("id"))
    opens = {}
    conversions = {}
    for row in event_rows:
        agent_id = row["tracking_link__agent_id"]
        if row["event_type"] == TrackingEvent.EventType.OPENED:
            opens[agent_id] = row["total"]
        elif row["event_type"] == TrackingEvent.EventType.CONVERSION:
            conversions[agent_id] = row["total"]
    unique_rows = (
        events.filter(event_type=TrackingEvent.EventType.OPENED)
        .exclude(visitor_key="")
        .values("tracking_link__agent_id", "visitor_key")
        .distinct()
    )
    unique_opens = {}
    for row in unique_rows:
        agent_id = row["tracking_link__agent_id"]
        unique_opens[agent_id] = unique_opens.get(agent_id, 0) + 1
    money_rows = commissions.values("agent_id").annotate(
        gross=Sum("gross_amount"),
        fees=Sum("platform_fee_amount"),
        net=Sum("agent_net_amount"),
    )
    money_map = {row["agent_id"]: row for row in money_rows}

    payload = []
    for membership in memberships:
        agent = membership.agent
        totals = money_map.get(agent.pk) or {}
        payload.append(
            {
                "id": membership.pk,
                "agent_id": agent.pk,
                "agent_name": agent.name or agent.username,
                "agent_username": agent.username,
                "agent_email": agent.email,
                "status": membership.status,
                "joined_at": membership.joined_at,
                "links": link_counts.get(agent.pk, 0),
                "opens": opens.get(agent.pk, 0),
                "unique_opens": unique_opens.get(agent.pk, 0),
                "clicks": opens.get(agent.pk, 0),
                "conversions": conversions.get(agent.pk, 0),
                "gross_commission": str(as_money(totals.get("gross") or Decimal("0.00"))),
                "misa_fee": str(as_money(totals.get("fees") or Decimal("0.00"))),
                "agent_net_earnings": str(as_money(totals.get("net") or Decimal("0.00"))),
                "commission_override_type": membership.commission_override_type,
                "commission_override_value": (
                    str(membership.commission_override_value)
                    if membership.commission_override_value is not None
                    else None
                ),
            }
        )
    return payload


def sort_member_rows(rows: list[dict], sort: str | None) -> list[dict]:
    descending = False
    key = sort or "joined_at"
    if key.startswith("-"):
        descending = True
        key = key[1:]
    field = MEMBER_SORTS.get(key, "joined_at")
    if field == "joined_at":
        return sorted(rows, key=lambda row: row.get("joined_at") or datetime.min, reverse=not descending)
    if field in {"links", "opens", "unique_opens", "clicks", "conversions"}:
        return sorted(rows, key=lambda row: row.get(field) or 0, reverse=not descending)
    if field in {"gross_commission", "misa_fee", "agent_net_earnings"}:
        return sorted(
            rows,
            key=lambda row: Decimal(row.get(field) or "0"),
            reverse=not descending,
        )
    return sorted(rows, key=lambda row: (row.get(field) or "").lower(), reverse=descending)
