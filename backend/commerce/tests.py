from decimal import Decimal
import threading

from django.core.exceptions import ValidationError
from django.db import OperationalError, connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from accounts.models import User
from ai.models import VideoProject
from brands.models import Brand, Campaign, Category, Product, ProductShareLink, Team, TeamMembership
from brands.services.membership import accept_invitation, invite_agent
from commerce.models import (
    AuditLog,
    CommissionEntry,
    CommissionRule,
    Conversion,
    LedgerEntry,
    PayoutAccount,
    PlatformSettings,
    TrackingEvent,
    TrackingLink,
    Wallet,
    WithdrawalRequest,
)
from commerce.services.commissions import calculate_split, money, require_currency, resolve_commission
from commerce.services.conversions import ingest_conversion
from commerce.services.ledger import (
    approve_withdrawal,
    cancel_withdrawal,
    mark_withdrawal_paid,
    post_adjustment,
    record_conversion,
    reject_withdrawal,
    request_withdrawal,
    reverse_commission,
    settle_commission,
)
from commerce.services.tracking import create_tracking_link


def _user(username, role):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="password123",
        name=username.title(),
        mobile="0123456789",
        location="KL",
        role=role,
    )


class CommerceDomainMixin:
    def setUp(self):
        self.category = Category.objects.create(name="Commerce", slug="commerce")
        self.owner = _user("cbrand", User.Role.PRODUCER)
        self.agent = _user("cagent", User.Role.AGENT)
        self.admin = User.objects.create_superuser(
            username="cadmin",
            email="cadmin@example.com",
            password="password123",
            name="Admin",
            mobile="0100000000",
            location="KL",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(owner=self.owner, category=self.category, name="MiSa Co")
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            product_url="https://shop.example.com/serum",
            price=Decimal("40.00"),
            commission=Decimal("10.00"),
            commission_amount=Decimal("1.00"),
        )
        self.team = Team.objects.create(brand=self.brand, name="Affiliate team")
        invite = invite_agent(team=self.team, agent=self.agent, invited_by=self.owner)
        self.membership = accept_invitation(invite, agent=self.agent)
        PlatformSettings.load()


class TrackingAttributionTest(CommerceDomainMixin, TestCase):
    def test_tracking_link_identifies_agent_product_brand_team(self):
        project = VideoProject.objects.create(owner=self.owner, product=self.product)
        campaign = Campaign.objects.create(
            brand=self.brand,
            product=self.product,
            team=self.team,
            name="Q1",
            status=Campaign.Status.ACTIVE,
        )
        link = create_tracking_link(
            agent=self.agent,
            team=self.team,
            product=self.product,
            campaign=campaign,
            content=project,
        )
        self.assertEqual(link.agent, self.agent)
        self.assertEqual(link.product, self.product)
        self.assertEqual(link.brand, self.brand)
        self.assertEqual(link.team, self.team)
        self.assertEqual(link.content, project)
        self.assertEqual(link.campaign, campaign)
        self.assertTrue(link.code)
        self.assertEqual(
            TrackingEvent.objects.filter(
                tracking_link=link, event_type=TrackingEvent.EventType.CREATED
            ).count(),
            1,
        )

    def test_duplicate_attribution_returns_same_link(self):
        first = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        second = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        self.assertEqual(first.pk, second.pk)

    def test_non_member_cannot_create_link(self):
        outsider = _user("outsider", User.Role.AGENT)
        with self.assertRaises(ValidationError):
            create_tracking_link(agent=outsider, team=self.team, product=self.product)

    def test_public_open_records_event_and_redirects(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        client = APIClient()
        response = client.get(f"/s/{link.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://shop.example.com/serum")
        self.assertTrue(
            TrackingEvent.objects.filter(
                tracking_link=link, event_type=TrackingEvent.EventType.OPENED
            ).exists()
        )

    def test_tracking_code_does_not_collide_with_brand_share(self):
        ProductShareLink.objects.create(product=self.product, code="taken12345")
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        self.assertNotEqual(link.code, "taken12345")

    def test_self_redirect_is_rejected(self):
        link = create_tracking_link(
            agent=self.agent,
            team=self.team,
            product=self.product,
            destination_url="https://brand.dckwebgen.com/s/loopcode01",
        )
        TrackingLink.objects.filter(pk=link.pk).update(code="loopcode01")
        client = APIClient()
        response = client.get("/s/loopcode01/")
        self.assertEqual(response.status_code, 404)

    def test_paused_link_is_not_public(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        link.status = TrackingLink.Status.PAUSED
        link.save(update_fields=["status"])
        response = APIClient().get(f"/s/{link.code}/")
        self.assertEqual(response.status_code, 404)


class CommissionCalculationTest(CommerceDomainMixin, TestCase):
    def test_platform_fee_not_hardcoded_and_example_split(self):
        settings = PlatformSettings.load()
        self.assertEqual(settings.platform_fee_percent, Decimal("3.00"))
        gross, fee, net = calculate_split(Decimal("1.00"), settings.platform_fee_percent)
        self.assertEqual(gross, Decimal("1.00"))
        self.assertEqual(fee, Decimal("0.03"))
        self.assertEqual(net, Decimal("0.97"))

    def test_product_fixed_amount_used_when_no_override(self):
        resolved = resolve_commission(product=self.product, agent=self.agent, team=self.team)
        self.assertEqual(resolved.source, "product_fixed")
        self.assertEqual(resolved.gross, Decimal("1.00"))

    def test_agent_rule_beats_product(self):
        CommissionRule.objects.create(
            scope=CommissionRule.Scope.AGENT,
            agent=self.agent,
            rate_type=CommissionRule.RateType.FIXED,
            rate_value=Decimal("2.00"),
        )
        resolved = resolve_commission(product=self.product, agent=self.agent, team=self.team)
        self.assertEqual(resolved.source, "agent_rule")
        self.assertEqual(resolved.gross, Decimal("2.00"))

    def test_membership_override_beats_team_rule(self):
        CommissionRule.objects.create(
            scope=CommissionRule.Scope.TEAM,
            team=self.team,
            rate_type=CommissionRule.RateType.FIXED,
            rate_value=Decimal("5.00"),
        )
        self.membership.commission_override_type = TeamMembership.OverrideType.FIXED
        self.membership.commission_override_value = Decimal("1.50")
        self.membership.save()
        resolved = resolve_commission(product=self.product, agent=self.agent, team=self.team)
        self.assertEqual(resolved.source, "membership_override")
        self.assertEqual(resolved.gross, Decimal("1.50"))

    def test_team_rule_beats_product(self):
        CommissionRule.objects.create(
            scope=CommissionRule.Scope.TEAM,
            team=self.team,
            rate_type=CommissionRule.RateType.FIXED,
            rate_value=Decimal("3.00"),
        )
        resolved = resolve_commission(product=self.product, agent=self.agent, team=self.team)
        self.assertEqual(resolved.source, "team_rule")
        self.assertEqual(resolved.gross, Decimal("3.00"))

    def test_historical_snapshot_survives_config_change(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        entry = record_conversion(tracking_link=link, actor=self.owner)
        self.assertEqual(entry.gross_amount, Decimal("1.00"))
        self.assertEqual(entry.platform_fee_percent, Decimal("3.00"))
        self.assertEqual(entry.platform_fee_amount, Decimal("0.03"))
        self.assertEqual(entry.agent_net_amount, Decimal("0.97"))
        self.product.commission_amount = Decimal("9.00")
        self.product.save(update_fields=["commission_amount"])
        settings = PlatformSettings.load()
        settings.platform_fee_percent = Decimal("10.00")
        settings.save(update_fields=["platform_fee_percent"])
        entry.refresh_from_db()
        self.assertEqual(entry.gross_amount, Decimal("1.00"))
        self.assertEqual(entry.platform_fee_percent, Decimal("3.00"))
        self.assertEqual(entry.agent_net_amount, Decimal("0.97"))
        later = record_conversion(tracking_link=link, actor=self.owner)
        self.assertEqual(later.gross_amount, Decimal("9.00"))
        self.assertEqual(later.platform_fee_percent, Decimal("10.00"))

    def test_commission_money_fields_are_immutable(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        entry = record_conversion(tracking_link=link)
        entry.gross_amount = Decimal("50.00")
        with self.assertRaises(ValidationError):
            entry.save()


class WalletLedgerTest(CommerceDomainMixin, TestCase):
    def test_conversion_credits_wallet_from_ledger(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_conversion(tracking_link=link, settle=True)
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.pending_balance, Decimal("0.00"))
        self.assertEqual(wallet.available_balance, Decimal("0.97"))
        self.assertEqual(wallet.paid_balance, Decimal("0.00"))
        self.assertGreaterEqual(wallet.entries.count(), 2)

    def test_unsettled_conversion_stays_pending(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_conversion(tracking_link=link, settle=False)
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.pending_balance, Decimal("0.97"))
        self.assertEqual(wallet.available_balance, Decimal("0.00"))

    def test_reverse_settled_commission(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        entry = record_conversion(tracking_link=link, settle=True)
        reverse_commission(entry)
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.00"))
        entry.refresh_from_db()
        self.assertEqual(entry.status, CommissionEntry.Status.REVERSED)
        self.assertEqual(entry.agent_net_amount, Decimal("0.97"))
        self.assertTrue(
            TrackingEvent.objects.filter(
                event_type=TrackingEvent.EventType.CONVERSION_REVERSED
            ).exists()
        )

    def test_ledger_entries_are_immutable(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_conversion(tracking_link=link)
        ledger = LedgerEntry.objects.first()
        ledger.amount = Decimal("99.00")
        with self.assertRaises(ValidationError):
            ledger.save()
        with self.assertRaises(ValidationError):
            ledger.delete()


class WithdrawalFlowTest(CommerceDomainMixin, TestCase):
    def setUp(self):
        super().setUp()
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_conversion(tracking_link=link, settle=True)
        self.payout = PayoutAccount.objects.create(
            agent=self.agent,
            label="Bank",
            destination_ref="acct-1",
            is_default=True,
        )

    def test_request_approve_pay(self):
        withdrawal = request_withdrawal(
            agent=self.agent,
            amount=Decimal("0.97"),
            payout_account=self.payout,
        )
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.00"))
        self.assertEqual(withdrawal.status, withdrawal.Status.REQUESTED)
        approve_withdrawal(withdrawal, reviewer=self.admin)
        mark_withdrawal_paid(withdrawal, reviewer=self.admin)
        wallet.refresh_from_db()
        self.assertEqual(wallet.paid_balance, Decimal("0.97"))
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, withdrawal.Status.PAID)
        self.assertIsNotNone(withdrawal.processed_at)

    def test_reject_releases_hold(self):
        withdrawal = request_withdrawal(agent=self.agent, amount=Decimal("0.97"))
        reject_withdrawal(withdrawal, reviewer=self.admin, reason="Docs")
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.97"))
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, withdrawal.Status.REJECTED)
        self.assertEqual(withdrawal.rejection_reason, "Docs")

    def test_cancel_from_requested(self):
        withdrawal = request_withdrawal(agent=self.agent, amount=Decimal("0.97"))
        cancel_withdrawal(withdrawal, actor=self.agent)
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.97"))

    def test_insufficient_balance(self):
        with self.assertRaises(ValidationError):
            request_withdrawal(agent=self.agent, amount=Decimal("50.00"))

    def test_cannot_pay_from_requested_without_approval(self):
        withdrawal = request_withdrawal(agent=self.agent, amount=Decimal("0.97"))
        with self.assertRaises(ValidationError):
            mark_withdrawal_paid(withdrawal, reviewer=self.admin)

    def test_cannot_pay_rejected(self):
        withdrawal = request_withdrawal(agent=self.agent, amount=Decimal("0.97"))
        reject_withdrawal(withdrawal, reviewer=self.admin, reason="no")
        with self.assertRaises(ValidationError):
            mark_withdrawal_paid(withdrawal, reviewer=self.admin)


class UniqueOpenAndDisabledLinkTest(CommerceDomainMixin, TestCase):
    def test_refresh_counts_total_but_not_unique_opens(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        client = APIClient()
        first = client.get(f"/s/{link.code}/")
        second = client.get(f"/s/{link.code}/")
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertTrue(first.cookies.get("misa_vid"))
        self.assertEqual(first.cookies.get("misa_tl").value, link.code)
        opens = TrackingEvent.objects.filter(
            tracking_link=link, event_type=TrackingEvent.EventType.OPENED
        )
        self.assertEqual(opens.count(), 2)
        self.assertEqual(opens.values("visitor_key").distinct().count(), 1)
        self.assertFalse(
            TrackingEvent.objects.filter(
                tracking_link=link, event_type=TrackingEvent.EventType.CLICKED
            ).exists()
        )
        performance = APIClient()
        from rest_framework.authtoken.models import Token

        token = Token.objects.create(user=self.agent)
        performance.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        data = performance.get("/api/agents/performance/").json()
        self.assertEqual(data["opens"], 2)
        self.assertEqual(data["unique_opens"], 1)
        self.assertEqual(data["clicks"], 2)

    def test_different_visitors_are_unique(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        APIClient().get(f"/s/{link.code}/")
        APIClient().get(f"/s/{link.code}/")
        opens = TrackingEvent.objects.filter(
            tracking_link=link, event_type=TrackingEvent.EventType.OPENED
        )
        self.assertEqual(opens.count(), 2)
        self.assertEqual(opens.values("visitor_key").distinct().count(), 2)

    def test_disabled_brand_and_agent_are_not_public(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        self.brand.status = Brand.Status.SUSPENDED
        self.brand.save(update_fields=["status"])
        self.assertEqual(APIClient().get(f"/s/{link.code}/").status_code, 404)
        self.brand.status = Brand.Status.ACTIVE
        self.brand.save(update_fields=["status"])
        from agents.models import AgentProfile

        profile, _ = AgentProfile.objects.get_or_create(user=self.agent)
        profile.status = AgentProfile.Status.SUSPENDED
        profile.save(update_fields=["status"])
        self.assertEqual(APIClient().get(f"/s/{link.code}/").status_code, 404)


class ShareIntentSemanticsTest(CommerceDomainMixin, TestCase):
    def test_share_intent_is_not_confirmed_share(self):
        from rest_framework.authtoken.models import Token

        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.agent).key}")
        copied = client.post(f"/api/agents/links/{link.pk}/share-intent/")
        self.assertEqual(copied.status_code, 201)
        self.assertEqual(copied.json()["event_type"], TrackingEvent.EventType.SHARE_INTENT)
        self.assertFalse(copied.json()["metadata"].get("confirmed"))
        self.assertIn("intent", copied.json()["label"].lower())
        self.assertFalse(
            TrackingEvent.objects.filter(
                event_type=TrackingEvent.EventType.SHARE_CONFIRMED
            ).exists()
        )

    def test_share_confirmed_is_a_separate_event(self):
        from rest_framework.authtoken.models import Token
        from commerce.services.tracking import record_share_confirmed

        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_share_confirmed(tracking_link=link, platform="tiktok", external_ref="post-1")
        admin = APIClient()
        admin.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.admin).key}")
        response = admin.post(
            "/api/commerce/share-confirmed/",
            {"tracking_code": link.code, "platform": "instagram", "external_ref": "ig-9"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["event_type"], TrackingEvent.EventType.SHARE_CONFIRMED)
        self.assertTrue(response.json()["metadata"].get("confirmed"))
        self.assertEqual(
            TrackingEvent.objects.filter(
                tracking_link=link, event_type=TrackingEvent.EventType.SHARE_CONFIRMED
            ).count(),
            2,
        )


class ConversionIdempotencyTest(CommerceDomainMixin, TestCase):
    def test_same_external_id_does_not_pay_twice(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        first = ingest_conversion(
            tracking_link=link,
            source=Conversion.Source.WEBHOOK,
            external_id="order-100",
            gross_value=Decimal("40.00"),
            settle=True,
        )
        second = ingest_conversion(
            tracking_link=link,
            source=Conversion.Source.WEBHOOK,
            external_id="order-100",
            gross_value=Decimal("40.00"),
            settle=True,
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Conversion.objects.count(), 1)
        self.assertEqual(
            CommissionEntry.objects.filter(tracking_link=link).count(),
            1,
        )
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.97"))

    def test_idempotency_key_replays_the_same_conversion(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        first = ingest_conversion(
            tracking_link=link,
            idempotency_key="idem-1",
            settle=True,
        )
        second = ingest_conversion(
            tracking_link=link,
            idempotency_key="idem-1",
            settle=True,
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.commission_entry_id, second.commission_entry_id)

    def test_percent_commission_uses_reported_sale_value(self):
        self.product.commission_amount = Decimal("0.00")
        self.product.commission = Decimal("10.00")
        self.product.save(update_fields=["commission_amount", "commission"])
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        conversion = ingest_conversion(
            tracking_link=link,
            gross_value=Decimal("80.00"),
            currency="USD",
            settle=True,
        )
        entry = conversion.commission_entry
        self.assertEqual(entry.sale_amount, Decimal("80.00"))
        self.assertEqual(entry.gross_amount, Decimal("8.00"))
        self.assertEqual(entry.platform_fee_percent, Decimal("3.00"))
        self.assertEqual(entry.platform_fee_amount, Decimal("0.24"))
        self.assertEqual(entry.agent_net_amount, Decimal("7.76"))
        self.assertEqual(entry.currency, "USD")

    def test_disabled_link_conversion_is_rejected(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        link.status = TrackingLink.Status.REVOKED
        link.save(update_fields=["status"])
        conversion = ingest_conversion(tracking_link=link, external_id="ord-disabled")
        self.assertEqual(conversion.status, Conversion.Status.REJECTED)
        self.assertEqual(conversion.rejection_reason, "disabled_link")
        self.assertIsNone(conversion.commission_entry_id)

    def test_brand_conversion_endpoint_and_admin_analytics(self):
        from rest_framework.authtoken.models import Token

        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        owner = APIClient()
        owner.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.owner).key}")
        created = owner.post(
            "/api/commerce/conversions/",
            {
                "tracking_code": link.code,
                "source": "brand",
                "external_id": "shop-55",
                "gross_value": "40.00",
                "currency": "USD",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["status"], Conversion.Status.PROCESSED)
        replay = owner.post(
            "/api/commerce/conversions/",
            {
                "tracking_code": link.code,
                "source": "brand",
                "external_id": "shop-55",
                "gross_value": "40.00",
            },
            format="json",
        )
        self.assertEqual(replay.json()["id"], created.json()["id"])
        self.assertEqual(CommissionEntry.objects.filter(tracking_link=link).count(), 1)
        links = owner.get("/api/brands/links/").json()
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["code"], link.code)
        events = owner.get("/api/brands/events/").json()
        self.assertTrue(any(row["event_type"] == TrackingEvent.EventType.CONVERSION for row in events))
        agent = APIClient()
        agent.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.agent).key}")
        self.assertEqual(agent.post("/api/commerce/conversions/", {}, format="json").status_code, 403)
        self.assertTrue(agent.get("/api/agents/events/").json())
        admin = APIClient()
        admin.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.admin).key}")
        analytics = admin.get("/api/commerce/analytics/").json()
        self.assertEqual(analytics["conversions"], 1)
        self.assertEqual(analytics["links"], 1)
        self.assertIn("unique_opens", analytics)

    def test_conversion_ingest_requires_idempotency_key(self):
        from rest_framework.authtoken.models import Token

        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        owner = APIClient()
        owner.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.owner).key}")
        missing = owner.post(
            "/api/commerce/conversions/",
            {"tracking_code": link.code, "source": "brand", "gross_value": "40.00"},
            format="json",
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(CommissionEntry.objects.filter(tracking_link=link).count(), 0)

    def test_brand_cannot_force_settle_during_hold(self):
        from rest_framework.authtoken.models import Token

        settings = PlatformSettings.load()
        settings.commission_hold_days = 7
        settings.save(update_fields=["commission_hold_days"])
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        owner = APIClient()
        owner.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.owner).key}")
        created = owner.post(
            "/api/commerce/conversions/",
            {
                "tracking_code": link.code,
                "source": "brand",
                "external_id": "held-1",
                "settle": True,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 200)
        entry = CommissionEntry.objects.get(tracking_link=link)
        self.assertEqual(entry.status, CommissionEntry.Status.PENDING)
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.pending_balance, Decimal("0.97"))
        self.assertEqual(wallet.available_balance, Decimal("0.00"))


class FinancialAccountingTest(CommerceDomainMixin, TestCase):
    def test_platform_fee_split_uses_decimal_exactness(self):
        cases = [
            (Decimal("1.00"), Decimal("3.00"), Decimal("0.03"), Decimal("0.97")),
            (Decimal("10.00"), Decimal("3.00"), Decimal("0.30"), Decimal("9.70")),
            (Decimal("100.00"), Decimal("3.00"), Decimal("3.00"), Decimal("97.00")),
            (Decimal("1.00"), Decimal("0.00"), Decimal("0.00"), Decimal("1.00")),
            (Decimal("1.00"), Decimal("10.00"), Decimal("0.10"), Decimal("0.90")),
            (Decimal("0.00"), Decimal("3.00"), Decimal("0.00"), Decimal("0.00")),
        ]
        for gross, fee_percent, expected_fee, expected_net in cases:
            with self.subTest(gross=gross, fee_percent=fee_percent):
                got_gross, fee, net = calculate_split(gross, fee_percent)
                self.assertIsInstance(got_gross, Decimal)
                self.assertIsInstance(fee, Decimal)
                self.assertIsInstance(net, Decimal)
                self.assertEqual(got_gross, gross)
                self.assertEqual(fee, expected_fee)
                self.assertEqual(net, expected_net)

    def test_money_rejects_float(self):
        with self.assertRaises(ValidationError):
            money(1.0)
        with self.assertRaises(ValidationError):
            calculate_split(Decimal("1.00"), 3.0)

    def test_currency_cannot_be_mixed(self):
        with self.assertRaises(ValidationError):
            require_currency("EUR")
        self.assertEqual(require_currency(""), "USD")
        self.assertEqual(require_currency("usd"), "USD")
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        with self.assertRaises(ValidationError):
            ingest_conversion(tracking_link=link, currency="EUR")

    def test_commission_posts_earned_and_fee_ledger_lines(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        entry = record_conversion(tracking_link=link, settle=True)
        types = list(
            LedgerEntry.objects.filter(commission=entry).values_list("entry_type", "bucket", "amount")
        )
        self.assertIn((LedgerEntry.EntryType.COMMISSION_EARNED, LedgerEntry.Bucket.PENDING, Decimal("1.00")), types)
        self.assertIn((LedgerEntry.EntryType.PLATFORM_FEE, LedgerEntry.Bucket.PENDING, Decimal("-0.03")), types)
        self.assertEqual(entry.currency, "USD")
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.97"))
        self.assertEqual(wallet.withdrawn_balance, Decimal("0.00"))
        self.assertEqual(wallet.entries.filter(agent=self.agent).count(), wallet.entries.count())

    def test_zero_commission_is_snapshot_not_skipped_silently(self):
        self.product.commission_amount = Decimal("0.00")
        self.product.commission = Decimal("0.00")
        self.product.save(update_fields=["commission_amount", "commission"])
        CommissionRule.objects.create(
            scope=CommissionRule.Scope.PLATFORM,
            rate_type=CommissionRule.RateType.FIXED,
            rate_value=Decimal("0.00"),
        )
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        entry = record_conversion(tracking_link=link, settle=True)
        self.assertEqual(entry.gross_amount, Decimal("0.00"))
        self.assertEqual(entry.platform_fee_amount, Decimal("0.00"))
        self.assertEqual(entry.agent_net_amount, Decimal("0.00"))
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.00"))
        self.assertEqual(wallet.pending_balance, Decimal("0.00"))

    def test_override_snapshot_is_independent_of_later_config(self):
        self.membership.commission_override_type = TeamMembership.OverrideType.FIXED
        self.membership.commission_override_value = Decimal("10.00")
        self.membership.save()
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        entry = record_conversion(tracking_link=link, settle=True)
        self.assertEqual(entry.gross_amount, Decimal("10.00"))
        self.assertEqual(entry.platform_fee_amount, Decimal("0.30"))
        self.assertEqual(entry.agent_net_amount, Decimal("9.70"))
        self.membership.commission_override_value = Decimal("1.00")
        self.membership.save()
        settings = PlatformSettings.load()
        settings.platform_fee_percent = Decimal("50.00")
        settings.save(update_fields=["platform_fee_percent"])
        entry.refresh_from_db()
        self.assertEqual(entry.gross_amount, Decimal("10.00"))
        self.assertEqual(entry.platform_fee_percent, Decimal("3.00"))
        self.assertEqual(entry.agent_net_amount, Decimal("9.70"))

    def test_reversal_unwinds_available_balance(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        entry = record_conversion(tracking_link=link, settle=True)
        reverse_commission(entry, actor=self.admin, reason="chargeback")
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.00"))
        self.assertTrue(
            LedgerEntry.objects.filter(
                commission=entry, entry_type=LedgerEntry.EntryType.COMMISSION_REVERSED
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="commission.reversed", object_id=str(entry.pk)).exists()
        )
        audit = AuditLog.objects.get(action="commission.reversed", object_id=str(entry.pk))
        self.assertEqual(audit.payload["reason"], "chargeback")
        self.assertEqual(audit.payload["old_value"], CommissionEntry.Status.SETTLED)

    def test_holding_period_keeps_commission_pending(self):
        settings = PlatformSettings.load()
        settings.commission_hold_days = 7
        settings.save(update_fields=["commission_hold_days"])
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        conversion = ingest_conversion(tracking_link=link)
        entry = conversion.commission_entry
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(entry.status, CommissionEntry.Status.PENDING)
        self.assertEqual(wallet.pending_balance, Decimal("0.97"))
        self.assertEqual(wallet.available_balance, Decimal("0.00"))
        with self.assertRaises(ValidationError):
            settle_commission(entry)
        settle_commission(entry, force=True)
        wallet.refresh_from_db()
        self.assertEqual(wallet.pending_balance, Decimal("0.00"))
        self.assertEqual(wallet.available_balance, Decimal("0.97"))

    def test_cannot_withdraw_pending_or_more_than_available(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_conversion(tracking_link=link, settle=False)
        with self.assertRaises(ValidationError):
            request_withdrawal(agent=self.agent, amount=Decimal("0.97"))
        record_conversion(tracking_link=link, settle=True)
        request_withdrawal(agent=self.agent, amount=Decimal("0.97"))
        with self.assertRaises(ValidationError):
            request_withdrawal(agent=self.agent, amount=Decimal("0.01"))
        with self.assertRaises(ValidationError):
            request_withdrawal(agent=self.agent, amount=Decimal("0.00"))
        with self.assertRaises(ValidationError):
            request_withdrawal(agent=self.agent, amount=Decimal("-1.00"))

    def test_paid_withdrawal_uses_withdrawn_bucket_without_claiming_psp(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_conversion(tracking_link=link, settle=True)
        withdrawal = request_withdrawal(agent=self.agent, amount=Decimal("0.97"))
        approve_withdrawal(withdrawal, reviewer=self.admin)
        mark_withdrawal_paid(withdrawal, reviewer=self.admin)
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.00"))
        self.assertEqual(wallet.withdrawn_balance, Decimal("0.97"))
        self.assertEqual(wallet.paid_balance, Decimal("0.97"))
        paid = LedgerEntry.objects.get(entry_type=LedgerEntry.EntryType.WITHDRAWAL_PAID)
        self.assertEqual(paid.bucket, LedgerEntry.Bucket.WITHDRAWN)
        self.assertFalse(paid.metadata.get("psp_confirmed"))
        with self.assertRaises(ValidationError):
            request_withdrawal(agent=self.agent, amount=Decimal("0.97"))

    def test_adjustment_is_auditable(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_conversion(tracking_link=link, settle=True)
        entry = post_adjustment(
            agent=self.agent,
            amount=Decimal("-0.10"),
            reason="Manual correction",
            actor=self.admin,
        )
        self.assertEqual(entry.entry_type, LedgerEntry.EntryType.ADJUSTMENT)
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.available_balance, Decimal("0.87"))
        audit = AuditLog.objects.get(action="ledger.adjustment", object_id=str(entry.pk))
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(audit.payload["reason"], "Manual correction")
        self.assertEqual(audit.payload["old_value"]["available"], "0.97")
        self.assertEqual(audit.payload["new_value"]["available"], "0.87")
        with self.assertRaises(ValidationError):
            post_adjustment(agent=self.agent, amount=Decimal("1.00"), reason="", actor=self.admin)

    def test_zero_hold_days_explicitly_releases_to_available(self):
        settings = PlatformSettings.load()
        self.assertEqual(settings.commission_hold_days, 0)
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        conversion = ingest_conversion(tracking_link=link)
        self.assertEqual(conversion.commission_entry.status, CommissionEntry.Status.SETTLED)
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(wallet.pending_balance, Decimal("0.00"))
        self.assertEqual(wallet.available_balance, Decimal("0.97"))
        self.assertEqual(wallet.withdrawn_balance, Decimal("0.00"))


class ConcurrentWithdrawalTest(CommerceDomainMixin, TransactionTestCase):
    def test_concurrent_withdrawals_do_not_double_spend(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_conversion(tracking_link=link, settle=True)
        barrier = threading.Barrier(2)
        outcomes = []

        def attempt():
            try:
                barrier.wait(timeout=5)
                request_withdrawal(agent=self.agent, amount=Decimal("0.97"))
                outcomes.append("ok")
            except (ValidationError, OperationalError):
                outcomes.append("rejected")
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        wallet = Wallet.objects.get(agent=self.agent)
        self.assertEqual(outcomes.count("ok"), 1)
        self.assertEqual(WithdrawalRequest.objects.filter(agent=self.agent).count(), 1)
        self.assertEqual(wallet.available_balance, Decimal("0.00"))
        self.assertGreaterEqual(wallet.available_balance, Decimal("0.00"))

