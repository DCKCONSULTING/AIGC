from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from ai.models import VideoProject, VideoProjectStatus
from brands.models import (
    Brand,
    Campaign,
    Category,
    JoinRequest,
    Product,
    ProductShareLink,
    Team,
    TeamInvitation,
    TeamMembership,
)
from brands.services.membership import (
    accept_invitation,
    accept_join_request,
    create_join_request,
    decline_invitation,
    invite_agent,
    reject_join_request,
)
from commerce.models import CommissionRule
from commerce.services.ledger import record_conversion
from commerce.services.tracking import create_tracking_link


def _user(username, role, **kwargs):
    defaults = {
        "email": f"{username}@example.com",
        "password": "password123",
        "name": username.title(),
        "mobile": "0123456789",
        "location": "KL",
        "role": role,
    }
    defaults.update(kwargs)
    password = defaults.pop("password")
    return User.objects.create_user(username=username, password=password, **defaults)


class TeamDomainTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Home", slug="home")
        self.owner = _user("brandowner", User.Role.PRODUCER)
        self.agent = _user("agentone", User.Role.AGENT)
        self.other = _user("agenttwo", User.Role.AGENT)
        self.brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Acme",
        )
        self.team = Team.objects.create(brand=self.brand, name="Field team")

    def test_membership_uniqueness(self):
        TeamMembership.objects.create(team=self.team, agent=self.agent)
        with self.assertRaises(IntegrityError):
            TeamMembership.objects.create(team=self.team, agent=self.agent)

    def test_invite_and_accept_creates_membership(self):
        invite = invite_agent(team=self.team, agent=self.agent, invited_by=self.owner)
        self.assertEqual(invite.status, TeamInvitation.Status.PENDING)
        membership = accept_invitation(invite, agent=self.agent)
        self.assertEqual(membership.status, TeamMembership.Status.ACTIVE)
        invite.refresh_from_db()
        self.assertEqual(invite.status, TeamInvitation.Status.ACCEPTED)
        self.assertIsNotNone(invite.responded_at)

    def test_duplicate_pending_invite_rejected(self):
        invite_agent(team=self.team, agent=self.agent, invited_by=self.owner)
        with self.assertRaises(ValidationError):
            invite_agent(team=self.team, agent=self.agent, invited_by=self.owner)

    def test_expired_invite_cannot_be_accepted(self):
        invite = invite_agent(team=self.team, agent=self.agent, invited_by=self.owner)
        invite.expires_at = timezone.now()
        invite.save(update_fields=["expires_at"])
        with self.assertRaises(ValidationError):
            accept_invitation(invite, agent=self.agent)
        invite.refresh_from_db()
        self.assertEqual(invite.status, TeamInvitation.Status.EXPIRED)

    def test_join_request_duplicate_pending_blocked(self):
        create_join_request(team=self.team, agent=self.agent, message="Please")
        with self.assertRaises(ValidationError):
            create_join_request(team=self.team, agent=self.agent)
        reject_join_request(
            JoinRequest.objects.get(agent=self.agent, team=self.team),
            reviewed_by=self.owner,
        )
        second = create_join_request(team=self.team, agent=self.agent)
        self.assertEqual(second.status, JoinRequest.Status.PENDING)

    def test_accept_join_request_activates_membership(self):
        request = create_join_request(team=self.team, agent=self.agent)
        membership = accept_join_request(request, reviewed_by=self.owner)
        self.assertEqual(membership.agent, self.agent)
        request.refresh_from_db()
        self.assertEqual(request.status, JoinRequest.Status.ACCEPTED)
        self.assertEqual(request.reviewed_by, self.owner)

    def test_decline_invitation(self):
        invite = invite_agent(team=self.team, agent=self.agent, invited_by=self.owner)
        decline_invitation(invite, agent=self.agent)
        self.assertEqual(TeamMembership.objects.count(), 0)

    def test_brand_can_have_multiple_teams(self):
        other = Team.objects.create(brand=self.brand, name="Retail team")
        self.assertEqual(self.brand.teams.count(), 2)
        self.assertNotEqual(other.pk, self.team.pk)

    def test_campaign_belongs_to_brand_product_team(self):
        product = Product.objects.create(
            brand=self.brand,
            name="Bottle",
            product_url="https://example.com/bottle",
            commission_amount=Decimal("1.00"),
        )
        campaign = Campaign.objects.create(
            brand=self.brand,
            product=product,
            team=self.team,
            name="Launch",
            status=Campaign.Status.ACTIVE,
            commission_type=Campaign.CommissionType.FIXED,
            commission_value=Decimal("1.00"),
        )
        self.assertEqual(campaign.brand, self.brand)
        self.assertTrue(campaign.has_commission())


class BrandShareRedirectCompatTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        category = Category.objects.create(name="Share", slug="share")
        owner = _user("shareowner", User.Role.PRODUCER)
        brand = Brand.objects.create(owner=owner, category=category, name="ShareCo")
        self.product = Product.objects.create(
            brand=brand,
            name="Lamp",
            product_url="https://example.com/lamp",
        )
        self.link = ProductShareLink.objects.create(
            product=self.product,
            code="brandshare1",
        )

    def test_existing_share_code_still_redirects_and_counts_open(self):
        response = self.client.get("/s/brandshare1/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com/lamp")
        self.link.refresh_from_db()
        self.assertEqual(self.link.open_count, 1)
        from commerce.models import TrackingEvent

        self.assertEqual(TrackingEvent.objects.count(), 0)

    def test_unknown_code_is_404(self):
        response = self.client.get("/s/missingcode/")
        self.assertEqual(response.status_code, 404)


class BrandManagementPermissionTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Mgmt", slug="mgmt")
        self.owner_a = _user("ownera", User.Role.PRODUCER)
        self.owner_b = _user("ownerb", User.Role.PRODUCER)
        self.agent = _user("fieldagent", User.Role.AGENT)
        self.agent_b = _user("otherfield", User.Role.AGENT)
        self.brand_a = Brand.objects.create(
            owner=self.owner_a, category=self.category, name="Brand A Co"
        )
        self.brand_b = Brand.objects.create(
            owner=self.owner_b, category=self.category, name="Brand B Co"
        )
        self.team_a = Team.objects.create(brand=self.brand_a, name="A Team")
        self.team_b = Team.objects.create(brand=self.brand_b, name="B Team")
        self.product_a = Product.objects.create(
            brand=self.brand_a,
            name="Serum A",
            product_url="https://a.example.com/serum",
            price=Decimal("40.00"),
            commission_amount=Decimal("1.00"),
        )
        self.product_b = Product.objects.create(
            brand=self.brand_b,
            name="Serum B",
            product_url="https://b.example.com/serum",
            price=Decimal("40.00"),
            commission_amount=Decimal("5.00"),
        )
        invite = invite_agent(team=self.team_a, agent=self.agent, invited_by=self.owner_a)
        accept_invitation(invite, agent=self.agent)
        invite_b = invite_agent(team=self.team_b, agent=self.agent_b, invited_by=self.owner_b)
        accept_invitation(invite_b, agent=self.agent_b)
        self.client_a = APIClient()
        self.client_b = APIClient()
        self.client_a.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.owner_a).key}"
        )
        self.client_b.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.owner_b).key}"
        )

    def test_multi_brand_owner_must_choose_the_team_brand(self):
        second = Brand.objects.create(
            owner=self.owner_a, category=self.category, name="Brand A Second"
        )
        missing = self.client_a.post(
            "/api/brands/teams/",
            {"name": "Unscoped"},
            format="json",
        )
        self.assertEqual(missing.status_code, 400)
        created = self.client_a.post(
            "/api/brands/teams/",
            {"name": "Scoped", "brand": second.pk},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["brand_id"], second.pk)
        self.assertEqual(created.json()["brand_name"], "Brand A Second")

    def test_create_rename_and_deactivate_own_team(self):
        created = self.client_a.post(
            "/api/brands/teams/",
            {"name": "Retail", "description": "Stores"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["brand_id"], self.brand_a.pk)
        team_id = created.json()["id"]
        renamed = self.client_a.patch(
            f"/api/brands/teams/{team_id}/",
            {"name": "Retail East"},
            format="json",
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["name"], "Retail East")
        paused = self.client_a.patch(
            f"/api/brands/teams/{team_id}/",
            {"status": Team.Status.PAUSED},
            format="json",
        )
        self.assertEqual(paused.json()["status"], Team.Status.PAUSED)
        active = self.client_a.patch(
            f"/api/brands/teams/{team_id}/",
            {"status": Team.Status.ACTIVE},
            format="json",
        )
        self.assertEqual(active.json()["status"], Team.Status.ACTIVE)

    def test_brand_cannot_see_or_manage_other_brand_team(self):
        listed = self.client_a.get("/api/brands/teams/")
        names = {row["name"] for row in listed.json()}
        self.assertIn("A Team", names)
        self.assertNotIn("B Team", names)
        hidden = self.client_a.get(f"/api/brands/teams/{self.team_b.pk}/")
        self.assertEqual(hidden.status_code, 404)
        invite = self.client_a.post(
            f"/api/brands/teams/{self.team_b.pk}/invite/",
            {"agent": self.agent.pk},
            format="json",
        )
        self.assertEqual(invite.status_code, 404)
        performance = self.client_a.get(
            f"/api/brands/performance/?team={self.team_b.pk}"
        )
        self.assertEqual(performance.status_code, 200)
        self.assertEqual(performance.json()["links"], 0)
        self.assertEqual(performance.json()["conversions"], 0)

    def test_invite_appears_in_agent_workspace(self):
        outsider = _user("invitee2", User.Role.AGENT)
        response = self.client_a.post(
            f"/api/brands/teams/{self.team_a.pk}/invite/",
            {"agent": outsider.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        agent_client = APIClient()
        agent_client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=outsider).key}"
        )
        inbox = agent_client.get("/api/agents/invitations/")
        self.assertEqual(inbox.status_code, 200)
        self.assertEqual(inbox.json()[0]["team_id"], self.team_a.pk)
        self.assertTrue(inbox.json()[0]["can_accept"])

    def test_approve_and_reject_join_requests_are_scoped(self):
        request_a = create_join_request(team=self.team_a, agent=self.agent_b, message="Hi A")
        request_b = create_join_request(team=self.team_b, agent=self.agent, message="Hi B")
        stolen = self.client_a.post(f"/api/brands/join-requests/{request_b.pk}/approve/")
        self.assertEqual(stolen.status_code, 404)
        request_b.refresh_from_db()
        self.assertEqual(request_b.status, JoinRequest.Status.PENDING)
        inbox = self.client_a.get("/api/brands/join-requests/")
        ids = {row["id"] for row in inbox.json()}
        self.assertIn(request_a.pk, ids)
        self.assertNotIn(request_b.pk, ids)
        approved = self.client_a.post(f"/api/brands/join-requests/{request_a.pk}/approve/")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], JoinRequest.Status.ACCEPTED)
        other = _user("pendingagent", User.Role.AGENT)
        pending = create_join_request(team=self.team_a, agent=other)
        rejected = self.client_a.post(f"/api/brands/join-requests/{pending.pk}/reject/")
        self.assertEqual(rejected.json()["status"], JoinRequest.Status.REJECTED)

    def test_suspend_and_remove_own_member_only(self):
        membership = TeamMembership.objects.get(team=self.team_a, agent=self.agent)
        other = TeamMembership.objects.get(team=self.team_b, agent=self.agent_b)
        stolen = self.client_a.patch(
            f"/api/brands/memberships/{other.pk}/",
            {"status": TeamMembership.Status.SUSPENDED},
            format="json",
        )
        self.assertEqual(stolen.status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.status, TeamMembership.Status.ACTIVE)
        suspended = self.client_a.patch(
            f"/api/brands/memberships/{membership.pk}/",
            {"status": TeamMembership.Status.SUSPENDED},
            format="json",
        )
        self.assertEqual(suspended.json()["status"], TeamMembership.Status.SUSPENDED)
        removed = self.client_a.patch(
            f"/api/brands/memberships/{membership.pk}/",
            {"status": TeamMembership.Status.REMOVED},
            format="json",
        )
        self.assertEqual(removed.json()["status"], TeamMembership.Status.REMOVED)

    def test_team_detail_member_metrics_are_factual(self):
        link = create_tracking_link(agent=self.agent, team=self.team_a, product=self.product_a)
        record_conversion(tracking_link=link, settle=True)
        detail = self.client_a.get(f"/api/brands/teams/{self.team_a.pk}/?sort=-gross_commission")
        self.assertEqual(detail.status_code, 200)
        member = detail.json()["members"][0]
        self.assertEqual(member["agent_id"], self.agent.pk)
        self.assertEqual(member["links"], 1)
        self.assertEqual(member["conversions"], 1)
        self.assertEqual(member["gross_commission"], "1.00")
        self.assertEqual(member["misa_fee"], "0.03")
        self.assertEqual(member["agent_net_earnings"], "0.97")
        empty_team = Team.objects.create(brand=self.brand_a, name="Empty")
        empty = self.client_a.get(f"/api/brands/teams/{empty_team.pk}/")
        self.assertEqual(empty.json()["members"], [])

    def test_commission_stack_and_historical_entries_stay_frozen(self):
        link = create_tracking_link(agent=self.agent, team=self.team_a, product=self.product_a)
        entry = record_conversion(tracking_link=link, settle=True)
        default = self.client_a.get(
            f"/api/brands/commissions/preview/?product={self.product_a.pk}&team={self.team_a.pk}"
        )
        self.assertEqual(default.json()["layers"]["default"]["gross"], "1.00")
        self.assertTrue(default.json()["layers"]["default"]["effective"])
        team_rule = self.client_a.post(
            "/api/brands/commission-rules/",
            {
                "scope": CommissionRule.Scope.TEAM,
                "team": self.team_a.pk,
                "rate_type": CommissionRule.RateType.FIXED,
                "rate_value": "1.10",
            },
            format="json",
        )
        self.assertEqual(team_rule.status_code, 201)
        agent_rule = self.client_a.post(
            "/api/brands/commission-rules/",
            {
                "scope": CommissionRule.Scope.AGENT,
                "agent": self.agent.pk,
                "team": self.team_a.pk,
                "rate_type": CommissionRule.RateType.FIXED,
                "rate_value": "1.25",
            },
            format="json",
        )
        self.assertEqual(agent_rule.status_code, 201)
        preview = self.client_a.get(
            f"/api/brands/commissions/preview/?product={self.product_a.pk}&team={self.team_a.pk}&agent={self.agent.pk}"
        )
        data = preview.json()
        self.assertEqual(data["layers"]["default"]["gross"], "1.00")
        self.assertEqual(data["layers"]["team"]["gross"], "1.10")
        self.assertEqual(data["layers"]["agent"]["gross"], "1.25")
        self.assertTrue(data["layers"]["agent"]["effective"])
        self.assertFalse(data["layers"]["team"]["effective"])
        self.assertEqual(data["effective"]["gross"], "1.25")
        self.assertEqual(data["effective"]["layer"], "agent")
        entry.refresh_from_db()
        self.assertEqual(entry.gross_amount, Decimal("1.00"))
        self.assertEqual(entry.agent_net_amount, Decimal("0.97"))
        stolen = self.client_a.post(
            "/api/brands/commission-rules/",
            {
                "scope": CommissionRule.Scope.TEAM,
                "team": self.team_b.pk,
                "rate_type": CommissionRule.RateType.FIXED,
                "rate_value": "9.00",
            },
            format="json",
        )
        self.assertEqual(stolen.status_code, 404)

    def test_empty_performance_is_zero_not_fabricated(self):
        response = self.client_a.get("/api/brands/performance/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["opens"], 0)
        self.assertEqual(data["clicks"], 0)
        self.assertEqual(data["conversions"], 0)
        self.assertEqual(data["gross_commissions"], "0.00")
        self.assertEqual(data["platform_fees"], "0.00")
        self.assertEqual(data["agent_payouts"], "0.00")
        self.assertEqual(data["by_product"], [])
        self.assertEqual(data["active_agents"], 1)

    def test_performance_and_distribution_hide_other_brand(self):
        link_a = create_tracking_link(agent=self.agent, team=self.team_a, product=self.product_a)
        link_b = create_tracking_link(agent=self.agent_b, team=self.team_b, product=self.product_b)
        record_conversion(tracking_link=link_a, settle=True)
        record_conversion(tracking_link=link_b, settle=True)
        project = VideoProject.objects.create(
            owner=self.owner_a,
            product=self.product_a,
            status=VideoProjectStatus.EXPORTED,
        )
        VideoProject.objects.create(
            owner=self.owner_b,
            product=self.product_b,
            status=VideoProjectStatus.EXPORTED,
        )
        performance = self.client_a.get("/api/brands/performance/").json()
        self.assertEqual(performance["links"], 1)
        self.assertEqual(performance["conversions"], 1)
        self.assertEqual(performance["gross_commissions"], "1.00")
        distribution = self.client_a.get("/api/brands/distribution/").json()
        names = {row["product_name"] for row in distribution}
        self.assertIn("Serum A", names)
        self.assertNotIn("Serum B", names)
        row = next(item for item in distribution if item["product_id"] == self.product_a.pk)
        self.assertEqual(row["generated_content"], 1)
        self.assertEqual(row["available_videos"], 1)
        self.assertEqual(row["content"][0]["id"], project.pk)
        self.assertEqual(row["conversions"], 1)
        other_perf = self.client_a.get(f"/api/brands/performance/?agent={self.agent_b.pk}")
        self.assertEqual(other_perf.json()["conversions"], 0)
        self.assertEqual(other_perf.json()["links"], 0)

    def test_campaign_crud_and_content_reference(self):
        project = VideoProject.objects.create(
            owner=self.owner_a,
            product=self.product_a,
            status=VideoProjectStatus.EXPORTED,
        )
        foreign = VideoProject.objects.create(
            owner=self.owner_b,
            product=self.product_b,
            status=VideoProjectStatus.EXPORTED,
        )
        created = self.client_a.post(
            "/api/brands/campaigns/",
            {
                "name": "Launch",
                "product": self.product_a.pk,
                "team": self.team_a.pk,
                "content": project.pk,
                "status": Campaign.Status.ACTIVE,
                "commission_type": Campaign.CommissionType.FIXED,
                "commission_value": "1.15",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["content_id"], project.pk)
        campaign_id = created.json()["id"]
        blocked = self.client_a.patch(
            f"/api/brands/campaigns/{campaign_id}/",
            {"content": foreign.pk},
            format="json",
        )
        self.assertEqual(blocked.status_code, 400)
        hidden = self.client_b.get(f"/api/brands/campaigns/{campaign_id}/")
        self.assertEqual(hidden.status_code, 404)
        paused = self.client_a.patch(
            f"/api/brands/campaigns/{campaign_id}/",
            {"status": Campaign.Status.PAUSED},
            format="json",
        )
        self.assertEqual(paused.json()["status"], Campaign.Status.PAUSED)
        perf = self.client_a.get(f"/api/brands/campaigns/{campaign_id}/performance/")
        self.assertEqual(perf.json()["conversions"], 0)
        self.assertEqual(perf.json()["gross_commissions"], "0.00")

    def test_agent_cannot_use_brand_management(self):
        agent_client = APIClient()
        agent_client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.agent).key}"
        )
        response = agent_client.get("/api/brands/teams/")
        self.assertEqual(response.status_code, 403)
        response = agent_client.get("/api/brands/performance/")
        self.assertEqual(response.status_code, 403)
        response = agent_client.post(
            "/api/brands/commission-rules/",
            {"scope": "team", "team": self.team_a.pk, "rate_type": "fixed", "rate_value": "9.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
