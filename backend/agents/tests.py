from decimal import Decimal

from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from agents.models import AgentProfile
from ai.models import VideoProject, VideoProjectStatus
from brands.models import Brand, Campaign, Category, JoinRequest, Product, Team, TeamMembership
from brands.services.membership import invite_agent
from commerce.models import PayoutAccount, TrackingEvent, TrackingLink
from commerce.services.ledger import record_conversion
from commerce.services.tracking import create_tracking_link
from commerce.tests import CommerceDomainMixin, _user


class AgentWorkspaceAPITest(CommerceDomainMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.token = Token.objects.create(user=self.agent)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.outsider = _user("otheragent", User.Role.AGENT)
        self.outsider_token = Token.objects.create(user=self.outsider)

    def test_empty_dashboard_uses_zero_not_fabricated_metrics(self):
        response = self.client.get("/api/agents/dashboard/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_clicks"], 0)
        self.assertEqual(data["total_opens"], 0)
        self.assertEqual(data["total_conversions"], 0)
        self.assertEqual(data["gross_commission"], "0.00")
        self.assertEqual(data["recent_activity"], [])
        self.assertEqual(data["top_products"], [])
        self.assertEqual(len(data["active_teams"]), 1)

    def test_browse_brands_is_public_catalog_only(self):
        Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Hidden Co",
            status=Brand.Status.SUSPENDED,
        )
        response = self.client.get("/api/agents/brands/")
        self.assertEqual(response.status_code, 200)
        names = {row["name"] for row in response.json()}
        self.assertIn("MiSa Co", names)
        self.assertNotIn("Hidden Co", names)
        self.assertNotIn("owner_email", response.json()[0])

    def test_brand_without_teams_join_waits_for_owner_approval(self):
        open_brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Open Brand",
        )
        outsider = APIClient()
        outsider.credentials(HTTP_AUTHORIZATION=f"Token {self.outsider_token.key}")
        response = outsider.post(
            f"/api/agents/brands/{open_brand.pk}/join/",
            {"message": "I can represent this brand."},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(response.json()["brand_name"], "Open Brand")
        self.assertEqual(response.json()["team_name"], "Agents")
        self.assertFalse(
            TeamMembership.objects.filter(agent=self.outsider, team__brand=open_brand).exists()
        )
        duplicate = outsider.post(f"/api/agents/brands/{open_brand.pk}/join/", {}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        owner = APIClient()
        owner_token, _created = Token.objects.get_or_create(user=self.owner)
        owner.credentials(HTTP_AUTHORIZATION=f"Token {owner_token.key}")
        approved = owner.post(f"/api/brands/join-requests/{response.json()['id']}/approve/")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "accepted")
        self.assertTrue(
            TeamMembership.objects.filter(
                agent=self.outsider,
                team__brand=open_brand,
                status=TeamMembership.Status.ACTIVE,
            ).exists()
        )

    def test_brand_join_requires_a_team_when_several_exist(self):
        second = Team.objects.create(brand=self.brand, name="Second open team")
        outsider = APIClient()
        outsider.credentials(HTTP_AUTHORIZATION=f"Token {self.outsider_token.key}")
        missing = outsider.post(f"/api/agents/brands/{self.brand.pk}/join/", {}, format="json")
        self.assertEqual(missing.status_code, 400)
        chosen = outsider.post(
            f"/api/agents/brands/{self.brand.pk}/join/",
            {"team": second.pk},
            format="json",
        )
        self.assertEqual(chosen.status_code, 201)
        self.assertEqual(chosen.json()["team_id"], second.pk)
        self.assertEqual(chosen.json()["status"], JoinRequest.Status.PENDING)

    def test_join_request_and_duplicate_blocked(self):
        other_team = Team.objects.create(brand=self.brand, name="Second team")
        first = self.client.post(f"/api/agents/teams/{other_team.pk}/join/", {"message": "Hi"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["status"], "pending")
        duplicate = self.client.post(f"/api/agents/teams/{other_team.pk}/join/", {}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        cancel = self.client.post(f"/api/agents/join-requests/{first.json()['id']}/cancel/")
        self.assertEqual(cancel.status_code, 200)
        self.assertEqual(cancel.json()["status"], "cancelled")

    def test_accept_invitation(self):
        other = _user("invitee", User.Role.AGENT)
        token = Token.objects.create(user=other)
        invite = invite_agent(team=self.team, agent=other, invited_by=self.owner)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = client.post(f"/api/agents/invitations/{invite.pk}/accept/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")
        again = client.post(f"/api/agents/invitations/{invite.pk}/accept/")
        self.assertEqual(again.status_code, 400)

    def test_create_tracking_link_uses_backend_code(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            status=VideoProjectStatus.EXPORTED,
        )
        campaign = Campaign.objects.create(brand=self.brand, team=self.team, name="Launch")
        response = self.client.post(
            "/api/agents/links/",
            {
                "product": self.product.pk,
                "team": self.team.pk,
                "content": project.pk,
                "campaign": campaign.pk,
                "code": "frontendcode",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.json()["code"], "frontendcode")
        self.assertTrue(response.json()["url"].endswith(f"/s/{response.json()['code']}"))
        self.assertEqual(TrackingLink.objects.filter(agent=self.agent).count(), 1)

    def test_agent_cannot_see_another_agents_links(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        outsider = APIClient()
        outsider.credentials(HTTP_AUTHORIZATION=f"Token {self.outsider_token.key}")
        listed = outsider.get("/api/agents/links/")
        self.assertEqual(listed.json(), [])
        detail = outsider.get(f"/api/agents/links/{link.pk}/")
        self.assertEqual(detail.status_code, 404)
        share = outsider.post(f"/api/agents/links/{link.pk}/share-intent/")
        self.assertEqual(share.status_code, 404)

    def test_agent_cannot_modify_brand_or_commission(self):
        brand_patch = self.client.patch(
            f"/api/brands/{self.brand.pk}/",
            {"name": "Hacked"},
            format="json",
        )
        self.assertEqual(brand_patch.status_code, 403)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.name, "MiSa Co")
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        entry = record_conversion(tracking_link=link, settle=True)
        mutate = self.client.patch(
            f"/api/agents/earnings/",
            {"id": entry.pk, "agent_net_amount": "99.00"},
            format="json",
        )
        self.assertEqual(mutate.status_code, 405)
        entry.refresh_from_db()
        self.assertEqual(entry.agent_net_amount, Decimal("0.97"))

    def test_product_detail_hides_marketing_until_member(self):
        outsider = APIClient()
        outsider.credentials(HTTP_AUTHORIZATION=f"Token {self.outsider_token.key}")
        response = outsider.get(f"/api/agents/products/{self.product.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["can_share"], False)
        self.assertEqual(response.json()["content"], [])
        self.assertEqual(response.json()["commissions"], [])
        member = self.client.get(f"/api/agents/products/{self.product.pk}/")
        self.assertTrue(member.json()["can_share"])
        self.assertTrue(member.json()["commissions"])
        self.assertEqual(member.json()["commissions"][0]["net"], "0.97")

    def test_link_filters_and_share_intent_label(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        listed = self.client.get(
            f"/api/agents/links/?product={self.product.pk}&brand={self.brand.pk}&team={self.team.pk}&status=active"
        )
        self.assertEqual(len(listed.json()), 1)
        copied = self.client.post(f"/api/agents/links/{link.pk}/share-intent/")
        self.assertEqual(copied.status_code, 201)
        self.assertEqual(copied.json()["event_type"], TrackingEvent.EventType.SHARE_INTENT)
        self.assertIn("copied", copied.json()["label"].lower())
        performance = self.client.get("/api/agents/performance/").json()
        self.assertEqual(performance["share_intents"], 1)
        self.assertEqual(performance["opens"], 0)

    def test_earnings_and_withdrawal_use_backend_balance(self):
        link = create_tracking_link(agent=self.agent, team=self.team, product=self.product)
        record_conversion(tracking_link=link, settle=True)
        earnings = self.client.get("/api/agents/earnings/").json()
        self.assertEqual(earnings["available_balance"], "0.97")
        self.assertEqual(earnings["transactions"][0]["gross_amount"], "1.00")
        self.assertEqual(earnings["transactions"][0]["platform_fee_amount"], "0.03")
        self.assertEqual(earnings["transactions"][0]["agent_net_amount"], "0.97")
        payout = self.client.post(
            "/api/agents/payout-accounts/",
            {"label": "Bank", "destination_ref": "acct-9", "is_default": True},
            format="json",
        )
        self.assertEqual(payout.status_code, 201)
        too_much = self.client.post(
            "/api/agents/withdrawals/",
            {"amount": "50.00", "payout_account": payout.json()["id"]},
            format="json",
        )
        self.assertEqual(too_much.status_code, 400)
        ok = self.client.post(
            "/api/agents/withdrawals/",
            {"amount": "0.97", "payout_account": payout.json()["id"]},
            format="json",
        )
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.json()["status"], "requested")
        wallet = self.client.get("/api/agents/wallet/").json()
        self.assertEqual(wallet["available_balance"], "0.00")

    def test_producer_cannot_use_agent_workspace(self):
        token = Token.objects.create(user=self.owner)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = client.get("/api/agents/dashboard/")
        self.assertEqual(response.status_code, 403)

    def test_suspended_agent_cannot_login(self):
        profile, _ = AgentProfile.objects.get_or_create(user=self.agent)
        profile.status = AgentProfile.Status.SUSPENDED
        profile.save(update_fields=["status"])
        client = APIClient()
        response = client.post(
            "/api/agents/login/",
            {"identifier": self.agent.username, "password": "password123"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
