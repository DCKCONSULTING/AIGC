from datetime import timedelta
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from commerce.models import CommissionEntry, Conversion, TrackingEvent
from commerce.services.audit import record_audit
from commerce.services.commissions import (
    calculate_split,
    commission_hold_days,
    current_platform_fee_percent,
    money,
    require_currency,
    resolve_commission,
)
from commerce.services.ledger import (
    commission_should_auto_release,
    get_or_create_wallet,
    post_commission_ledger,
    settle_commission,
)
from commerce.services.tracking import (
    link_distribution_block_reason,
    record_event,
    resolve_tracking_link,
)


def _source_value(source: str) -> str:
    source = (source or Conversion.Source.BRAND).strip() or Conversion.Source.BRAND
    if source not in Conversion.Source.values:
        return Conversion.Source.WEBHOOK
    return source


def _find_existing(*, idempotency_key: str, source: str, external_id: str) -> Conversion | None:
    if idempotency_key:
        existing = Conversion.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    if external_id:
        return Conversion.objects.filter(source=source, external_id=external_id).first()
    return None


@transaction.atomic
def process_conversion(conversion: Conversion, *, settle: bool | None = None, actor=None, request=None) -> Conversion:
    conversion = Conversion.objects.select_for_update().select_related(
        "tracking_link",
        "tracking_link__product",
        "tracking_link__brand",
        "tracking_link__agent",
        "tracking_link__agent__agent_profile",
        "tracking_link__team",
        "tracking_link__campaign",
        "commission_entry",
    ).get(pk=conversion.pk)
    if conversion.status == Conversion.Status.PROCESSED and conversion.commission_entry_id:
        return conversion
    if conversion.status in {Conversion.Status.REJECTED, Conversion.Status.DUPLICATE}:
        return conversion

    link = conversion.tracking_link
    reason = link_distribution_block_reason(link)
    if reason:
        conversion.status = Conversion.Status.REJECTED
        conversion.rejection_reason = reason
        conversion.save(update_fields=["status", "rejection_reason"])
        return conversion

    try:
        resolved = resolve_commission(
            product=link.product,
            agent=link.agent,
            team=link.team,
            campaign=link.campaign,
            sale_amount=conversion.gross_value,
        )
    except ValidationError as exc:
        conversion.status = Conversion.Status.REJECTED
        conversion.rejection_reason = "; ".join(getattr(exc, "messages", []) or [str(exc)])
        conversion.save(update_fields=["status", "rejection_reason"])
        return conversion

    fee_percent = current_platform_fee_percent()
    gross, fee, net = calculate_split(resolved.gross, fee_percent)
    currency = require_currency(conversion.currency)
    wallet = get_or_create_wallet(link.agent, currency=currency)
    event = record_event(
        tracking_link=link,
        event_type=TrackingEvent.EventType.CONVERSION,
        request=request,
        code=link.code,
        metadata={
            "conversion_id": conversion.pk,
            "external_id": conversion.external_id,
            "gross_value": str(conversion.gross_value),
            "commission_gross": str(gross),
            "fee": str(fee),
            "net": str(net),
        },
    )
    hold_days = commission_hold_days()
    available_at = timezone.now() + timedelta(days=hold_days)
    entry = CommissionEntry.objects.create(
        agent=link.agent,
        brand=link.brand,
        product=link.product,
        team=link.team,
        campaign=link.campaign,
        tracking_link=link,
        tracking_event=event,
        rule=resolved.rule,
        currency=currency,
        gross_amount=gross,
        platform_fee_percent=fee_percent,
        platform_fee_amount=fee,
        agent_net_amount=net,
        rate_type=resolved.rate_type,
        rate_value=resolved.rate_value,
        product_price_snapshot=money(link.product.price),
        sale_amount=money(conversion.gross_value),
        available_at=available_at,
        status=CommissionEntry.Status.PENDING,
    )
    post_commission_ledger(entry, wallet)
    if settle is None:
        settle = commission_should_auto_release(hold_days)
    if settle:
        settle_commission(entry, force=True)
        entry.refresh_from_db()
    conversion.tracking_event = event
    conversion.commission_entry = entry
    conversion.status = Conversion.Status.PROCESSED
    conversion.processed_at = timezone.now()
    conversion.save(
        update_fields=["tracking_event", "commission_entry", "status", "processed_at"]
    )
    record_audit(
        action="commission.created",
        actor=actor,
        object_type="CommissionEntry",
        object_id=str(entry.pk),
        payload={"gross": str(gross), "fee": str(fee), "net": str(net), "conversion_id": conversion.pk},
    )
    return Conversion.objects.select_related("commission_entry").get(pk=conversion.pk)


@transaction.atomic
def ingest_conversion(
    *,
    tracking_link=None,
    tracking_code: str = "",
    request=None,
    source: str = Conversion.Source.BRAND,
    source_name: str = "",
    external_id: str = "",
    idempotency_key: str = "",
    gross_value=None,
    currency: str = "",
    settle: bool | None = None,
    actor=None,
    metadata: dict | None = None,
) -> Conversion:
    source = _source_value(source)
    external_id = (external_id or "").strip()
    provided_key = (idempotency_key or "").strip()
    existing = _find_existing(
        idempotency_key=provided_key,
        source=source,
        external_id=external_id,
    )
    if existing:
        if existing.status == Conversion.Status.RECEIVED:
            return process_conversion(existing, settle=settle, actor=actor, request=request)
        return existing

    link = resolve_tracking_link(
        tracking_link=tracking_link,
        tracking_code=tracking_code,
        request=request,
    )
    if link is None:
        raise ValidationError("A tracking link or tracking code is required.")

    sale = money(gross_value if gross_value is not None else link.product.price)
    currency = require_currency(currency)
    key = provided_key or uuid.uuid4().hex
    try:
        conversion = Conversion.objects.create(
            tracking_link=link,
            agent=link.agent,
            brand=link.brand,
            product=link.product,
            team=link.team,
            campaign=link.campaign,
            content=link.content,
            source=source,
            source_name=(source_name or "").strip(),
            external_id=external_id,
            idempotency_key=key,
            gross_value=sale,
            currency=currency,
            status=Conversion.Status.RECEIVED,
            metadata=metadata or {},
        )
    except IntegrityError:
        duplicate = _find_existing(idempotency_key=key, source=source, external_id=external_id)
        if duplicate:
            return duplicate
        raise

    return process_conversion(conversion, settle=settle, actor=actor, request=request)
