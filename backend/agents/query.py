from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q, Sum
from rest_framework.response import Response
from rest_framework import status as http_status

from ai.models import VideoProject, VideoProjectStatus
from brands.models import Brand, Product, Team, TeamMembership
from commerce.models import CommissionEntry, TrackingLink
from commerce.services.commissions import (
    calculate_split,
    current_platform_fee_percent,
    resolve_commission,
)
from commerce.services.ledger import get_or_create_wallet, refresh_wallet
from commerce.services.tracking import annotate_link_stats as annotate_event_stats
from commerce.services.tracking import event_metrics as event_counts

APPROVED_CONTENT_STATUSES = (
    VideoProjectStatus.APPROVED,
    VideoProjectStatus.EXPORTED,
)


def django_error_response(exc: DjangoValidationError) -> Response:
    if getattr(exc, "message_dict", None):
        return Response(exc.message_dict, status=http_status.HTTP_400_BAD_REQUEST)
    messages = list(getattr(exc, "messages", []) or [str(exc)])
    return Response({"detail": messages[0]}, status=http_status.HTTP_400_BAD_REQUEST)


def media_url(request, field) -> str:
    if not field:
        return ""
    url = field.url
    if request is not None:
        return request.build_absolute_uri(url)
    return url


def public_tracking_url(code: str) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/s/{code}"


def active_memberships(user):
    return TeamMembership.objects.filter(
        agent=user,
        status=TeamMembership.Status.ACTIVE,
        team__brand__status=Brand.Status.ACTIVE,
    ).select_related("team", "team__brand", "team__brand__category")


def member_brand_ids(user):
    return active_memberships(user).values_list("team__brand_id", flat=True)


def member_team_ids(user):
    return active_memberships(user).values_list("team_id", flat=True)


def is_active_member(user, team: Team) -> bool:
    return TeamMembership.objects.filter(
        agent=user,
        team=team,
        status=TeamMembership.Status.ACTIVE,
    ).exists()


def available_brands():
    return Brand.objects.filter(status=Brand.Status.ACTIVE).select_related("category")


def available_products_for(user):
    return (
        Product.objects.filter(brand_id__in=member_brand_ids(user), brand__status=Brand.Status.ACTIVE)
        .select_related("brand", "brand__category")
        .prefetch_related("images", "demo_videos")
    )


def approved_videos(product: Product):
    return VideoProject.objects.filter(
        product=product,
        status__in=APPROVED_CONTENT_STATUSES,
    ).order_by("-updated_at")


def commission_payload(product: Product, agent, team: Team) -> dict | None:
    try:
        resolved = resolve_commission(product=product, agent=agent, team=team)
        fee_percent = current_platform_fee_percent()
        gross, fee, net = calculate_split(resolved.gross, fee_percent)
    except DjangoValidationError:
        return None
    return {
        "source": resolved.source,
        "rate_type": resolved.rate_type,
        "rate_value": str(resolved.rate_value),
        "gross": str(gross),
        "platform_fee_percent": str(fee_percent),
        "platform_fee": str(fee),
        "net": str(net),
        "team_id": team.pk,
        "team_name": team.name,
        "team_specific": resolved.source in {"membership_override", "team_rule"},
    }


def annotate_link_stats(queryset):
    return annotate_event_stats(queryset).annotate(
        earnings_net=Sum(
            "commission_entries__agent_net_amount",
            filter=~Q(commission_entries__status=CommissionEntry.Status.REVERSED),
        ),
        earnings_gross=Sum(
            "commission_entries__gross_amount",
            filter=~Q(commission_entries__status=CommissionEntry.Status.REVERSED),
        ),
        earnings_fee=Sum(
            "commission_entries__platform_fee_amount",
            filter=~Q(commission_entries__status=CommissionEntry.Status.REVERSED),
        ),
    )


def money_totals(queryset) -> dict:
    totals = queryset.exclude(status=CommissionEntry.Status.REVERSED).aggregate(
        gross=Sum("gross_amount"),
        fees=Sum("platform_fee_amount"),
        net=Sum("agent_net_amount"),
    )
    return {
        "gross_commission": str(totals["gross"] or Decimal("0.00")),
        "platform_fees": str(totals["fees"] or Decimal("0.00")),
        "net_commission": str(totals["net"] or Decimal("0.00")),
    }


def own_links(user):
    return annotate_link_stats(
        TrackingLink.objects.filter(agent=user).select_related(
            "product",
            "brand",
            "team",
            "campaign",
            "content",
        )
    )


def wallet_payload(user) -> dict:
    wallet = refresh_wallet(get_or_create_wallet(user))
    return {
        "currency": wallet.currency,
        "pending_balance": str(wallet.pending_balance),
        "available_balance": str(wallet.available_balance),
        "withdrawn_balance": str(wallet.withdrawn_balance),
        "paid_balance": str(wallet.paid_balance),
        "updated_at": wallet.updated_at,
    }
