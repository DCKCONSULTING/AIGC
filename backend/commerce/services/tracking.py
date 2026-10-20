import hashlib
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import Http404, HttpResponseRedirect
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.response import Response

from brands.models import Brand, ProductShareLink, TeamMembership
from commerce.models import TrackingEvent, TrackingLink
from commerce.services.audit import record_audit

VISITOR_COOKIE = "misa_vid"
ATTRIBUTION_COOKIE = "misa_tl"
VISITOR_COOKIE_MAX_AGE = 180 * 24 * 60 * 60
ATTRIBUTION_COOKIE_MAX_AGE = 30 * 24 * 60 * 60
SUSPICIOUS_OPEN_WINDOW = timedelta(minutes=10)
SUSPICIOUS_OPEN_LIMIT = 20

# /s/<code>/ is both the tracking URL and the destination click.
# Record OPENED only; analytics expose clicks as an alias of opens.
DESTINATION_EVENT = TrackingEvent.EventType.OPENED


def _ip_hash(ip: str) -> str:
    if not ip:
        return ""
    digest = hashlib.sha256(f"{settings.SECRET_KEY}:ip:{ip}".encode()).hexdigest()
    return digest[:32]


def _hash_value(prefix: str, value: str) -> str:
    digest = hashlib.sha256(f"{settings.SECRET_KEY}:{prefix}:{value}".encode()).hexdigest()
    return digest[:32]


def visitor_id_from_request(request) -> str:
    if request is None:
        return uuid.uuid4().hex
    existing = (request.COOKIES.get(VISITOR_COOKIE) or "").strip()
    if existing:
        return existing[:64]
    return uuid.uuid4().hex


def visitor_key_for(visitor_id: str, ip_hash: str = "", user_agent: str = "") -> str:
    if visitor_id:
        return _hash_value("vid", visitor_id)
    fallback = f"{ip_hash}:{user_agent}"
    if fallback.strip(":"):
        return _hash_value("fallback", fallback)
    return ""


def attribution_code_from_request(request) -> str:
    if request is None:
        return ""
    return (request.COOKIES.get(ATTRIBUTION_COOKIE) or "").strip()


def _request_meta(request, visitor_id: str = "") -> dict:
    if request is None:
        return {
            "session_key": "",
            "referrer": "",
            "user_agent": "",
            "ip_hash": "",
            "visitor_key": visitor_key_for(visitor_id) if visitor_id else "",
        }
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    ip = forwarded or request.META.get("REMOTE_ADDR", "")
    ua = (request.META.get("HTTP_USER_AGENT") or "")[:256]
    referrer = (request.META.get("HTTP_REFERER") or "")[:500]
    session_key = ""
    if hasattr(request, "session"):
        session_key = request.session.session_key or ""
    ip_hash = _ip_hash(ip)
    visitor_id = visitor_id or visitor_id_from_request(request)
    return {
        "session_key": session_key,
        "referrer": referrer,
        "user_agent": ua,
        "ip_hash": ip_hash,
        "visitor_key": visitor_key_for(visitor_id, ip_hash, ua),
    }


def attach_tracking_cookies(response, request, *, visitor_id: str, code: str = ""):
    if response is None or request is None:
        return response
    secure = bool(getattr(request, "is_secure", lambda: False)())
    response.set_cookie(
        VISITOR_COOKIE,
        visitor_id,
        max_age=VISITOR_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=secure,
        path="/",
    )
    if code:
        response.set_cookie(
            ATTRIBUTION_COOKIE,
            code,
            max_age=ATTRIBUTION_COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=secure,
            path="/",
        )
    return response


def record_event(
    *,
    tracking_link: TrackingLink | None,
    event_type: str,
    request=None,
    code: str = "",
    metadata: dict | None = None,
    visitor_id: str = "",
    flagged: bool = False,
) -> TrackingEvent:
    meta = _request_meta(request, visitor_id=visitor_id)
    return TrackingEvent.objects.create(
        tracking_link=tracking_link,
        link_code=code or (tracking_link.code if tracking_link else ""),
        event_type=event_type,
        metadata=metadata or {},
        flagged=flagged,
        **meta,
    )


def agent_is_disabled(agent) -> bool:
    profile = getattr(agent, "agent_profile", None)
    if profile is None:
        return False
    return profile.status == "suspended"


def link_distribution_block_reason(link: TrackingLink | None) -> str:
    if link is None:
        return "unknown_link"
    if link.status != TrackingLink.Status.ACTIVE:
        return "disabled_link"
    brand = getattr(link, "brand", None)
    if brand is not None and brand.status != Brand.Status.ACTIVE:
        return "disabled_brand"
    if agent_is_disabled(link.agent):
        return "disabled_agent"
    if not TeamMembership.objects.filter(
        team_id=link.team_id,
        agent_id=link.agent_id,
        status=TeamMembership.Status.ACTIVE,
    ).exists():
        return "disabled_membership"
    return ""


def create_tracking_link(
    *,
    agent,
    team,
    product,
    campaign=None,
    content=None,
    destination_url: str = "",
    actor=None,
) -> TrackingLink:
    if agent_is_disabled(agent):
        raise ValidationError("This agent account is disabled.")
    if product.brand.status != Brand.Status.ACTIVE:
        raise ValidationError("This brand is disabled.")
    if not TeamMembership.objects.filter(
        team=team, agent=agent, status=TeamMembership.Status.ACTIVE
    ).exists():
        raise ValidationError("Agent must be an active member of the team.")
    if product.brand_id != team.brand_id:
        raise ValidationError("Product does not belong to this team's brand.")
    if campaign and campaign.brand_id != team.brand_id:
        raise ValidationError("Campaign does not belong to this brand.")
    if content and content.product_id != product.pk:
        raise ValidationError("Video content must belong to the same product.")
    lookup = {
        "agent": agent,
        "team": team,
        "product": product,
        "campaign": campaign,
        "content": content,
    }
    existing = TrackingLink.objects.filter(**lookup).first()
    if existing:
        return existing
    link = TrackingLink.objects.create(
        brand=product.brand,
        destination_url=destination_url,
        **lookup,
    )
    record_event(tracking_link=link, event_type=TrackingEvent.EventType.CREATED, code=link.code)
    record_audit(
        action="tracking_link.created",
        actor=actor or agent,
        object_type="TrackingLink",
        object_id=str(link.pk),
        payload={"code": link.code},
    )
    return link


def destination_loops(target: str, code: str) -> bool:
    if not target:
        return True
    parsed = urlparse(target)
    path = (parsed.path or "").rstrip("/")
    if path.endswith(f"/s/{code}"):
        return True
    site = getattr(settings, "SITE_URL", "").rstrip("/")
    if site and target.rstrip("/") in {f"{site}/s/{code}", f"{site}/s/{code}/"}:
        return True
    return False


def _is_suspicious_open(link: TrackingLink, visitor_key: str) -> bool:
    if not visitor_key:
        return False
    window_start = timezone.now() - SUSPICIOUS_OPEN_WINDOW
    recent = TrackingEvent.objects.filter(
        tracking_link=link,
        event_type=TrackingEvent.EventType.OPENED,
        visitor_key=visitor_key,
        created_at__gte=window_start,
    ).count()
    return recent >= SUSPICIOUS_OPEN_LIMIT


@transaction.atomic
def open_public_code(code: str, request=None):
    visitor_id = visitor_id_from_request(request)
    link = (
        TrackingLink.objects.select_related("product", "brand", "agent", "agent__agent_profile", "team")
        .filter(code=code)
        .first()
    )
    if link:
        if link_distribution_block_reason(link):
            raise Http404("Tracking link is not active.")
        target = link.destination()
        if destination_loops(target, code):
            return Response(
                {"detail": "This product has no destination URL."},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        meta = _request_meta(request, visitor_id=visitor_id)
        flagged = _is_suspicious_open(link, meta["visitor_key"])
        record_event(
            tracking_link=link,
            event_type=DESTINATION_EVENT,
            request=request,
            code=link.code,
            visitor_id=visitor_id,
            flagged=flagged,
            metadata={"suspicious_repeat": flagged} if flagged else {},
        )
        response = HttpResponseRedirect(target)
        return attach_tracking_cookies(response, request, visitor_id=visitor_id, code=link.code)

    share = ProductShareLink.objects.select_related("product", "product__brand").filter(code=code).first()
    if not share:
        raise Http404("Unknown share code.")
    if share.product.brand.status != Brand.Status.ACTIVE:
        raise Http404("Tracking link is not active.")
    ProductShareLink.objects.filter(pk=share.pk).update(open_count=F("open_count") + 1)
    target = (share.product.product_url or "").strip()
    if destination_loops(target, code):
        return Response(
            {"detail": "This product has no destination URL."},
            status=http_status.HTTP_404_NOT_FOUND,
        )
    response = HttpResponseRedirect(target)
    return attach_tracking_cookies(response, request, visitor_id=visitor_id, code=share.code)


def record_share_intent(*, tracking_link: TrackingLink, request=None, channel: str = "misa_copy") -> TrackingEvent:
    return record_event(
        tracking_link=tracking_link,
        event_type=TrackingEvent.EventType.SHARE_INTENT,
        request=request,
        code=tracking_link.code,
        metadata={"channel": channel, "confirmed": False},
    )


def record_share_confirmed(
    *,
    tracking_link: TrackingLink,
    platform: str,
    external_ref: str = "",
    request=None,
) -> TrackingEvent:
    return record_event(
        tracking_link=tracking_link,
        event_type=TrackingEvent.EventType.SHARE_CONFIRMED,
        request=request,
        code=tracking_link.code,
        metadata={
            "platform": platform,
            "external_ref": external_ref,
            "confirmed": True,
        },
    )


def resolve_tracking_link(*, tracking_link=None, tracking_code: str = "", request=None) -> TrackingLink | None:
    if tracking_link is not None:
        return tracking_link
    code = (tracking_code or "").strip() or attribution_code_from_request(request)
    if not code:
        return None
    return (
        TrackingLink.objects.select_related("product", "brand", "agent", "agent__agent_profile", "team", "campaign")
        .filter(code=code)
        .first()
    )


def unique_open_count(queryset) -> int:
    return (
        queryset.filter(event_type=TrackingEvent.EventType.OPENED)
        .exclude(visitor_key="")
        .values("visitor_key")
        .distinct()
        .count()
    )


def event_metrics(queryset) -> dict:
    rows = queryset.values("event_type").annotate(total=Count("id"))
    counts = {row["event_type"]: row["total"] for row in rows}
    opens = counts.get(TrackingEvent.EventType.OPENED, 0)
    return {
        "opens": opens,
        "unique_opens": unique_open_count(queryset),
        "clicks": opens,
        "conversions": counts.get(TrackingEvent.EventType.CONVERSION, 0),
        "share_intents": counts.get(TrackingEvent.EventType.SHARE_INTENT, 0),
        "share_confirmed": counts.get(TrackingEvent.EventType.SHARE_CONFIRMED, 0),
        "created": counts.get(TrackingEvent.EventType.CREATED, 0),
    }


def annotate_link_stats(queryset):
    opened = Q(events__event_type=TrackingEvent.EventType.OPENED)
    return queryset.annotate(
        opens=Count("events", filter=opened),
        unique_opens=Count(
            "events__visitor_key",
            filter=opened & ~Q(events__visitor_key=""),
            distinct=True,
        ),
        clicks=Count("events", filter=opened),
        conversions=Count("events", filter=Q(events__event_type=TrackingEvent.EventType.CONVERSION)),
        share_intents=Count(
            "events", filter=Q(events__event_type=TrackingEvent.EventType.SHARE_INTENT)
        ),
        share_confirmed=Count(
            "events", filter=Q(events__event_type=TrackingEvent.EventType.SHARE_CONFIRMED)
        ),
    )
