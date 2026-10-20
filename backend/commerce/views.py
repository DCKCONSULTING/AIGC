from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsBrandOwner, IsBrandOwnerOrAdmin, IsSuperuser
from brands.query import django_error_response, owned_brand_ids, scoped_links
from commerce.models import CommissionEntry, Conversion, TrackingEvent, TrackingLink
from commerce.serializers import (
    ConversionIngestSerializer,
    ConversionSerializer,
    TrackingEventPublicSerializer,
    TrackingLinkStatsSerializer,
)
from commerce.services.conversions import ingest_conversion
from commerce.services.tracking import (
    annotate_link_stats,
    event_metrics,
    record_share_confirmed,
    resolve_tracking_link,
)


class ConversionIngestView(APIView):
    permission_classes = [IsBrandOwnerOrAdmin]

    def get(self, request):
        rows = Conversion.objects.select_related(
            "tracking_link", "product", "brand", "agent", "team", "campaign", "commission_entry"
        )
        if not request.user.is_superuser:
            rows = rows.filter(brand_id__in=owned_brand_ids(request))
        source = request.query_params.get("source")
        status_filter = request.query_params.get("status")
        if source:
            rows = rows.filter(source=source)
        if status_filter:
            rows = rows.filter(status=status_filter)
        return Response(ConversionSerializer(rows[:200], many=True).data)

    def post(self, request):
        serializer = ConversionIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tracking_link = None
        if data.get("tracking_link"):
            links = TrackingLink.objects.select_related(
                "product", "brand", "agent", "agent__agent_profile", "team", "campaign"
            )
            if not request.user.is_superuser:
                links = links.filter(brand_id__in=owned_brand_ids(request))
            tracking_link = get_object_or_404(links, pk=data["tracking_link"])
        elif data.get("tracking_code"):
            tracking_link = resolve_tracking_link(tracking_code=data["tracking_code"])
            if tracking_link is None:
                return Response({"tracking_code": "Unknown tracking code."}, status=status.HTTP_404_NOT_FOUND)
            if not request.user.is_superuser and tracking_link.brand_id not in set(owned_brand_ids(request)):
                return Response({"tracking_code": "Unknown tracking code."}, status=status.HTTP_404_NOT_FOUND)
        try:
            conversion = ingest_conversion(
                tracking_link=tracking_link,
                tracking_code=data.get("tracking_code") or "",
                request=request,
                source=data.get("source") or Conversion.Source.BRAND,
                source_name=data.get("source_name") or "",
                external_id=data.get("external_id") or "",
                idempotency_key=data.get("idempotency_key") or "",
                gross_value=data.get("gross_value"),
                currency=data.get("currency") or "",
                settle=data.get("settle") if request.user.is_superuser else None,
                actor=request.user,
            )
        except DjangoValidationError as exc:
            return django_error_response(exc)
        return Response(ConversionSerializer(conversion).data)


class ShareConfirmedView(APIView):
    permission_classes = [IsSuperuser]

    def post(self, request):
        code = (request.data.get("tracking_code") or "").strip()
        link_id = request.data.get("tracking_link")
        platform = (request.data.get("platform") or "").strip()
        if not platform:
            return Response({"platform": "Platform is required."}, status=status.HTTP_400_BAD_REQUEST)
        link = resolve_tracking_link(tracking_code=code)
        if link is None and link_id:
            link = get_object_or_404(TrackingLink, pk=link_id)
        if link is None:
            return Response({"tracking_code": "Unknown tracking code."}, status=status.HTTP_404_NOT_FOUND)
        event = record_share_confirmed(
            tracking_link=link,
            platform=platform,
            external_ref=(request.data.get("external_ref") or "").strip(),
            request=request,
        )
        return Response(TrackingEventPublicSerializer(event).data, status=status.HTTP_201_CREATED)


class PlatformAnalyticsView(APIView):
    permission_classes = [IsSuperuser]

    def get(self, request):
        links = TrackingLink.objects.all()
        events = TrackingEvent.objects.all()
        conversions = Conversion.objects.all()
        commissions = CommissionEntry.objects.exclude(status=CommissionEntry.Status.REVERSED)
        counts = event_metrics(events)
        money = commissions.aggregate(
            gross=Sum("gross_amount"),
            fees=Sum("platform_fee_amount"),
            net=Sum("agent_net_amount"),
        )
        by_brand = list(
            links.values("brand_id", "brand__name")
            .annotate(
                link_count=Count("id"),
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
            .order_by("-opens")[:20]
        )
        return Response(
            {
                "links": links.count(),
                "opens": counts["opens"],
                "unique_opens": counts["unique_opens"],
                "clicks": counts["clicks"],
                "conversions": counts["conversions"],
                "share_intents": counts["share_intents"],
                "share_confirmed": counts["share_confirmed"],
                "conversion_records": conversions.count(),
                "gross_commission": str(money["gross"] or "0.00"),
                "platform_fees": str(money["fees"] or "0.00"),
                "agent_payouts": str(money["net"] or "0.00"),
                "by_brand": [
                    {
                        "id": row["brand_id"],
                        "name": row["brand__name"],
                        "links": row["link_count"],
                        "opens": row["opens"],
                        "unique_opens": row["unique_opens"],
                        "clicks": row["opens"],
                        "conversions": row["conversions"],
                    }
                    for row in by_brand
                ],
            }
        )


class BrandLinkListView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        links = annotate_link_stats(scoped_links(request))
        status_filter = request.query_params.get("status")
        if status_filter:
            links = links.filter(status=status_filter)
        return Response(TrackingLinkStatsSerializer(links, many=True).data)


class BrandEventListView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        link_ids = scoped_links(request).values_list("pk", flat=True)
        events = TrackingEvent.objects.filter(tracking_link_id__in=link_ids).order_by("-created_at")
        event_type = request.query_params.get("event_type")
        if event_type:
            events = events.filter(event_type=event_type)
        return Response(TrackingEventPublicSerializer(events[:200], many=True).data)
