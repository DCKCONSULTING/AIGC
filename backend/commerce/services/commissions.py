from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

from brands.models import Campaign, Product, Team, TeamMembership
from commerce.models import CommissionRule, PlatformSettings

TWOPLACES = Decimal("0.01")

PRECEDENCE = (
    "1. Agent CommissionRule (highest)",
    "2. TeamMembership commission override",
    "3. Campaign commission on the tracking link's campaign",
    "4. Team CommissionRule",
    "5. Product CommissionRule, else Product.commission_amount (fixed), else Product.commission % of price",
    "6. Brand CommissionRule",
    "7. Platform CommissionRule (lowest)",
)


class ResolvedCommission:
    def __init__(
        self,
        *,
        rate_type: str,
        rate_value: Decimal,
        gross: Decimal,
        source: str,
        rule: CommissionRule | None = None,
    ):
        self.rate_type = rate_type
        self.rate_value = rate_value
        self.gross = gross
        self.source = source
        self.rule = rule


def money(value) -> Decimal:
    if isinstance(value, float):
        raise ValidationError("Money values must use Decimal, not float.")
    if value is None:
        raise ValidationError("Money value is required.")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        amount = Decimal(value)
    else:
        raise ValidationError("Money values must use Decimal.")
    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def supported_currency() -> str:
    return (PlatformSettings.load().default_currency or "USD").strip().upper()


def require_currency(currency: str | None = "") -> str:
    expected = supported_currency()
    value = (currency or "").strip().upper()
    if not value:
        return expected
    if value != expected:
        raise ValidationError(
            f"MISA wallets support {expected} only. {value} cannot be mixed."
        )
    return value


def commission_hold_days() -> int:
    return int(PlatformSettings.load().commission_hold_days or 0)


def calculate_split(gross: Decimal, fee_percent: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    gross = money(gross)
    if isinstance(fee_percent, float):
        raise ValidationError("Platform fee must use Decimal, not float.")
    fee_percent = Decimal(fee_percent) if not isinstance(fee_percent, Decimal) else fee_percent
    if fee_percent < 0 or fee_percent > 100:
        raise ValidationError("Platform fee must be between 0 and 100.")
    fee = money(gross * fee_percent / Decimal("100"))
    net = money(gross - fee)
    if net < 0:
        raise ValidationError("Platform fee exceeds gross commission.")
    return gross, fee, net


def _gross_from(rate_type: str, rate_value: Decimal, product: Product) -> Decimal:
    if rate_type == CommissionRule.RateType.FIXED:
        return money(rate_value)
    if rate_type == CommissionRule.RateType.PERCENT:
        return money(Decimal(product.price) * Decimal(rate_value) / Decimal("100"))
    raise ValidationError("Unknown commission rate type.")


def _active_rule(*, scope: str, **filters) -> CommissionRule | None:
    return (
        CommissionRule.objects.filter(scope=scope, is_active=True, **filters)
        .order_by("-updated_at")
        .first()
    )


def _from_rule(rule: CommissionRule, product: Product, source: str) -> ResolvedCommission:
    return ResolvedCommission(
        rate_type=rule.rate_type,
        rate_value=rule.rate_value,
        gross=_gross_from(rule.rate_type, rule.rate_value, product),
        source=source,
        rule=rule,
    )


def resolve_agent_layer(*, product: Product, agent, team: Team | None = None) -> ResolvedCommission | None:
    if agent is None:
        return None
    rule = _active_rule(
        scope=CommissionRule.Scope.AGENT,
        agent=agent,
        product=product,
    ) or _active_rule(scope=CommissionRule.Scope.AGENT, agent=agent, product__isnull=True)
    if rule:
        return _from_rule(rule, product, "agent_rule")
    if team is not None:
        membership = TeamMembership.objects.filter(team=team, agent=agent).first()
        if membership and membership.has_commission_override():
            return ResolvedCommission(
                rate_type=membership.commission_override_type,
                rate_value=membership.commission_override_value,
                gross=_gross_from(
                    membership.commission_override_type,
                    membership.commission_override_value,
                    product,
                ),
                source="membership_override",
            )
    return None


def resolve_campaign_layer(*, product: Product, campaign: Campaign | None) -> ResolvedCommission | None:
    if campaign and campaign.has_commission():
        return ResolvedCommission(
            rate_type=campaign.commission_type,
            rate_value=campaign.commission_value,
            gross=_gross_from(campaign.commission_type, campaign.commission_value, product),
            source="campaign",
        )
    return None


def resolve_team_layer(*, product: Product, team: Team | None) -> ResolvedCommission | None:
    if team is None:
        return None
    rule = _active_rule(scope=CommissionRule.Scope.TEAM, team=team)
    if rule:
        return _from_rule(rule, product, "team_rule")
    return None


def resolve_default_layer(*, product: Product) -> ResolvedCommission | None:
    rule = _active_rule(scope=CommissionRule.Scope.PRODUCT, product=product)
    if rule:
        return _from_rule(rule, product, "product_rule")
    if product.commission_amount and product.commission_amount > 0:
        return ResolvedCommission(
            rate_type=CommissionRule.RateType.FIXED,
            rate_value=product.commission_amount,
            gross=money(product.commission_amount),
            source="product_fixed",
        )
    if product.commission and product.commission > 0:
        return ResolvedCommission(
            rate_type=CommissionRule.RateType.PERCENT,
            rate_value=product.commission,
            gross=_gross_from(CommissionRule.RateType.PERCENT, product.commission, product),
            source="product_percent",
        )
    rule = _active_rule(scope=CommissionRule.Scope.BRAND, brand=product.brand)
    if rule:
        return _from_rule(rule, product, "brand_rule")
    rule = _active_rule(scope=CommissionRule.Scope.PLATFORM)
    if rule:
        return _from_rule(rule, product, "platform_rule")
    return None


def resolve_commission(
    *,
    product: Product,
    agent=None,
    team: Team,
    campaign: Campaign | None = None,
    sale_amount=None,
) -> ResolvedCommission:
    resolved = (
        resolve_agent_layer(product=product, agent=agent, team=team)
        or resolve_campaign_layer(product=product, campaign=campaign)
        or resolve_team_layer(product=product, team=team)
        or resolve_default_layer(product=product)
    )
    if resolved is None:
        raise ValidationError("No commission rule applies to this conversion.")
    if sale_amount is not None and resolved.rate_type == CommissionRule.RateType.PERCENT:
        resolved.gross = money(Decimal(sale_amount) * Decimal(resolved.rate_value) / Decimal("100"))
    return resolved


SOURCE_TO_LAYER = {
    "agent_rule": "agent",
    "membership_override": "agent",
    "campaign": "campaign",
    "team_rule": "team",
    "product_rule": "default",
    "product_fixed": "default",
    "product_percent": "default",
    "brand_rule": "default",
    "platform_rule": "default",
}


def _layer_payload(label: str, resolved: ResolvedCommission | None, fee_percent: Decimal) -> dict:
    if resolved is None:
        return {
            "label": label,
            "configured": False,
            "effective": False,
            "source": "",
            "rate_type": "",
            "rate_value": None,
            "gross": None,
            "platform_fee": None,
            "net": None,
            "rule_id": None,
        }
    gross, fee, net = calculate_split(resolved.gross, fee_percent)
    return {
        "label": label,
        "configured": True,
        "effective": False,
        "source": resolved.source,
        "rate_type": resolved.rate_type,
        "rate_value": str(resolved.rate_value),
        "gross": str(gross),
        "platform_fee": str(fee),
        "net": str(net),
        "rule_id": resolved.rule.pk if resolved.rule else None,
    }


def preview_commission(
    *,
    product: Product,
    agent=None,
    team: Team | None = None,
    campaign: Campaign | None = None,
) -> dict:
    fee_percent = current_platform_fee_percent()
    layers = {
        "default": _layer_payload("Default", resolve_default_layer(product=product), fee_percent),
        "team": _layer_payload("Team", resolve_team_layer(product=product, team=team), fee_percent),
        "agent": _layer_payload(
            "Agent",
            resolve_agent_layer(product=product, agent=agent, team=team),
            fee_percent,
        ),
        "campaign": _layer_payload(
            "Campaign",
            resolve_campaign_layer(product=product, campaign=campaign),
            fee_percent,
        ),
    }
    effective = None
    resolved = None
    if team is not None:
        try:
            resolved = resolve_commission(product=product, agent=agent, team=team, campaign=campaign)
        except ValidationError:
            resolved = None
    else:
        resolved = resolve_default_layer(product=product)
    if resolved:
        layer_key = SOURCE_TO_LAYER.get(resolved.source, "default")
        if layer_key in layers:
            layers[layer_key]["effective"] = True
        gross, fee, net = calculate_split(resolved.gross, fee_percent)
        effective = {
            "layer": layer_key,
            "source": resolved.source,
            "rate_type": resolved.rate_type,
            "rate_value": str(resolved.rate_value),
            "gross": str(gross),
            "platform_fee_percent": str(fee_percent),
            "platform_fee": str(fee),
            "net": str(net),
            "rule_id": resolved.rule.pk if resolved.rule else None,
        }
    return {
        "currency": PlatformSettings.load().default_currency,
        "platform_fee_percent": str(fee_percent),
        "layers": layers,
        "effective": effective,
        "precedence": list(PRECEDENCE),
    }


def upsert_commission_rule(
    *,
    scope: str,
    rate_type: str,
    rate_value,
    brand=None,
    product=None,
    team=None,
    agent=None,
    name: str = "",
    currency: str = "USD",
) -> CommissionRule:
    if scope not in CommissionRule.Scope.values:
        raise ValidationError("Unknown commission scope.")
    if rate_type not in CommissionRule.RateType.values:
        raise ValidationError("Unknown commission rate type.")
    value = money(rate_value)
    if value < 0:
        raise ValidationError("Commission must be zero or greater.")
    if rate_type == CommissionRule.RateType.PERCENT and value > 100:
        raise ValidationError("Percent commission must be between 0 and 100.")
    if scope == CommissionRule.Scope.PLATFORM:
        raise ValidationError("Brand owners cannot change the platform default rule.")

    lookup = {"scope": scope, "is_active": True}
    if scope == CommissionRule.Scope.BRAND:
        if brand is None:
            raise ValidationError("Brand is required for a brand commission rule.")
        lookup.update(brand=brand, product=None, team=None, agent=None)
    elif scope == CommissionRule.Scope.PRODUCT:
        if product is None:
            raise ValidationError("Product is required for a product commission rule.")
        lookup.update(product=product, team=None, agent=None)
    elif scope == CommissionRule.Scope.TEAM:
        if team is None:
            raise ValidationError("Team is required for a team commission rule.")
        lookup.update(team=team, product=None, agent=None)
    elif scope == CommissionRule.Scope.AGENT:
        if agent is None:
            raise ValidationError("Agent is required for an agent commission rule.")
        lookup.update(agent=agent, product=product, team=None)
    else:
        raise ValidationError("This commission scope cannot be managed here.")

    existing = CommissionRule.objects.filter(**lookup).order_by("-updated_at").first()
    if existing:
        existing.rate_type = rate_type
        existing.rate_value = value
        existing.currency = currency
        if name:
            existing.name = name
        if brand is not None:
            existing.brand = brand
        existing.save()
        return existing
    return CommissionRule.objects.create(
        name=name,
        scope=scope,
        brand=brand,
        product=product,
        team=team,
        agent=agent,
        rate_type=rate_type,
        rate_value=value,
        currency=currency,
        is_active=True,
    )


def current_platform_fee_percent() -> Decimal:
    return PlatformSettings.load().platform_fee_percent
