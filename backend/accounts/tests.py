from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from accounts.permissions import IsAgent, IsBrandOwner


def _superuser(**kwargs):
    defaults = {
        "username": "admin",
        "email": "admin@example.com",
        "password": "password123",
        "name": "Admin",
        "mobile": "0123456789",
        "location": "Kuala Lumpur",
        "role": User.Role.AGENT,
    }
    defaults.update(kwargs)
    password = defaults.pop("password")
    user = User(**defaults)
    user.is_superuser = True
    user.is_staff = True
    user.set_password(password)
    user.save()
    return user


class SuperuserLoginTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _superuser()
        self.agent = User.objects.create_user(
            username="agent1",
            email="agent@example.com",
            password="password123",
            name="Agent",
            mobile="0111111111",
            location="KL",
            role=User.Role.AGENT,
        )
        self.brand = User.objects.create_user(
            username="brand1",
            email="brand@example.com",
            password="password123",
            name="Brand",
            mobile="0222222222",
            location="KL",
            role=User.Role.PRODUCER,
        )

    def test_superuser_can_use_brand_login(self):
        response = self.client.post(
            "/api/brands/login/",
            {"identifier": "admin", "password": "password123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["user"]["is_superuser"])

    def test_superuser_can_use_agent_login(self):
        response = self.client.post(
            "/api/agents/login/",
            {"identifier": "admin@example.com", "password": "password123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["user"]["is_superuser"])

    def test_regular_agent_cannot_use_brand_login(self):
        response = self.client.post(
            "/api/brands/login/",
            {"identifier": "agent1", "password": "password123"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("agent account", str(response.json()))

    def test_agent_role_superuser_can_use_brand_login(self):
        self.assertEqual(self.admin.role, User.Role.AGENT)
        response = self.client.post(
            "/api/brands/login/",
            {"identifier": "admin", "password": "password123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["user"]["is_superuser"])

    def test_me_includes_is_superuser(self):
        token = Token.objects.create(user=self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_superuser"])

    def test_superuser_passes_both_permissions(self):
        request = type("R", (), {"user": self.admin})()
        self.assertTrue(IsAgent().has_permission(request, None))
        self.assertTrue(IsBrandOwner().has_permission(request, None))
        agent_request = type("R", (), {"user": self.agent})()
        self.assertTrue(IsAgent().has_permission(agent_request, None))
        self.assertFalse(IsBrandOwner().has_permission(agent_request, None))


class SuperuserWorkspaceTest(TestCase):
    def setUp(self):
        from brands.models import Brand, Category

        self.client = APIClient()
        self.admin = _superuser()
        self.admin_token = Token.objects.create(user=self.admin)
        self.agent = User.objects.create_user(
            username="agent1",
            email="agent@example.com",
            password="password123",
            name="Agent One",
            mobile="0111111111",
            location="KL",
            role=User.Role.AGENT,
        )
        self.owner = User.objects.create_user(
            username="brand1",
            email="brand@example.com",
            password="password123",
            name="Brand Owner",
            mobile="0222222222",
            location="KL",
            role=User.Role.PRODUCER,
        )
        category = Category.objects.create(name="Beauty", slug="beauty")
        self.company = Brand.objects.create(
            owner=self.owner,
            category=category,
            name="Company X",
            location="Kuala Lumpur",
        )
        self.other_owner = User.objects.create_user(
            username="brand2",
            email="brand2@example.com",
            password="password123",
            name="Other Owner",
            mobile="0333333333",
            location="Penang",
            role=User.Role.PRODUCER,
        )
        self.other_company = Brand.objects.create(
            owner=self.other_owner,
            category=category,
            name="Company Y",
            location="Penang",
        )

    def test_superuser_lists_brand_companies(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.admin_token.key}")
        response = self.client.get("/api/auth/workspaces/brands/")
        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.json()]
        self.assertEqual(names, ["Company X", "Company Y"])
        self.assertEqual(response.json()[0]["owner_username"], "brand1")

    def test_superuser_lists_agents(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.admin_token.key}")
        response = self.client.get("/api/auth/workspaces/agents/")
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.json()]
        self.assertIn(self.agent.id, ids)
        self.assertNotIn(self.admin.id, ids)

    def test_regular_user_cannot_list_workspaces(self):
        token = Token.objects.create(user=self.agent)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = self.client.get("/api/auth/workspaces/brands/")
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_enter_selected_company(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.admin_token.key}",
            HTTP_X_ACTING_USER=str(self.owner.id),
            HTTP_X_ACTING_BRAND=str(self.company.id),
        )
        response = self.client.get("/api/brands/")
        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.json()]
        self.assertEqual(names, ["Company X"])

    def test_superuser_can_enter_selected_agent(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.admin_token.key}",
            HTTP_X_ACTING_USER=str(self.agent.id),
        )
        response = self.client.get("/api/agents/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["username"], "agent1")
        self.assertFalse(response.json()["user"]["is_superuser"])

    def test_cannot_open_another_owners_company(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.admin_token.key}",
            HTTP_X_ACTING_USER=str(self.owner.id),
            HTTP_X_ACTING_BRAND=str(self.other_company.id),
        )
        response = self.client.get("/api/brands/")
        self.assertEqual(response.status_code, 401)

    def test_me_stays_the_superuser(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.admin_token.key}",
            HTTP_X_ACTING_USER=str(self.owner.id),
        )
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "admin")
        self.assertTrue(response.json()["is_superuser"])


class BrandProfileUpdateTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="brand1",
            email="brand@example.com",
            password="password123",
            name="Brand Owner",
            mobile="0222222222",
            location="KL",
            role=User.Role.PRODUCER,
        )
        self.token = Token.objects.create(user=self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.other = User.objects.create_user(
            username="taken",
            email="taken@example.com",
            password="password123",
            name="Other",
            mobile="0333333333",
            location="Penang",
            role=User.Role.PRODUCER,
        )

    def test_owner_can_update_profile_fields(self):
        response = self.client.patch(
            "/api/brands/me/",
            {
                "name": "New Name",
                "username": "newbrand",
                "email": "newbrand@example.com",
                "mobile": "0188888888",
                "location": "Johor",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "newbrand")
        self.assertEqual(response.json()["name"], "New Name")
        self.assertEqual(response.json()["email"], "newbrand@example.com")
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "newbrand")

    def test_username_must_be_unique(self):
        response = self.client.patch(
            "/api/brands/me/",
            {"username": "taken"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_password_change_requires_current_password(self):
        response = self.client.patch(
            "/api/brands/me/",
            {
                "password": "newpass123",
                "password_confirm": "newpass123",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.patch(
            "/api/brands/me/",
            {
                "current_password": "wrongpass",
                "password": "newpass123",
                "password_confirm": "newpass123",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.patch(
            "/api/brands/me/",
            {
                "current_password": "password123",
                "password": "newpass123",
                "password_confirm": "newpass123",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("newpass123"))

    def test_superuser_can_update_acting_owner(self):
        admin = User(
            username="admin",
            email="admin@example.com",
            name="Admin",
            mobile="0123456789",
            location="Kuala Lumpur",
            role=User.Role.AGENT,
            is_superuser=True,
            is_staff=True,
        )
        admin.set_password("password123")
        admin.save()
        token = Token.objects.create(user=admin)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {token.key}",
            HTTP_X_ACTING_USER=str(self.owner.id),
        )
        response = self.client.patch(
            "/api/brands/me/",
            {"name": "Acting Update"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Acting Update")
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.name, "Acting Update")
        admin.refresh_from_db()
        self.assertEqual(admin.name, "Admin")

    def test_owner_can_update_company_details(self):
        from brands.models import Brand, Category

        category = Category.objects.create(name="Beauty", slug="beauty")
        other = Category.objects.create(name="Food", slug="food")
        brand = Brand.objects.create(
            owner=self.owner,
            category=category,
            name="Old Co",
            website="https://old.example.com",
            description="Old description",
            location="KL",
        )
        response = self.client.patch(
            "/api/brands/me/",
            {
                "name": "Brand Owner",
                "company": {
                    "name": "New Co",
                    "website": "new.example.com",
                    "description": "We sell skincare to Malaysia.",
                    "location": "Penang",
                    "category": other.id,
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        company = response.json()["company"]
        self.assertEqual(company["name"], "New Co")
        self.assertEqual(company["website"], "https://new.example.com")
        self.assertEqual(company["description"], "We sell skincare to Malaysia.")
        self.assertEqual(company["location"], "Penang")
        self.assertEqual(company["category"], other.id)
        brand.refresh_from_db()
        self.assertEqual(brand.name, "New Co")
        self.assertEqual(brand.category_id, other.id)


class AdminRegistrationTest(TestCase):
    def test_all_local_models_are_registered(self):
        from django.apps import apps
        from django.contrib.admin.sites import site

        missing = []
        for app_label in ("accounts", "agents", "brands", "ai"):
            for model in apps.get_app_config(app_label).get_models():
                if model not in site._registry:
                    missing.append(model._meta.label)
        self.assertEqual(missing, [])
