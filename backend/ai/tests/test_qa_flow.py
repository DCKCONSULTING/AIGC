import io
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User
from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.providers.google.omni import GeminiOmniProvider
from ai.services.director import DirectorService, _retarget_timeline, normalize_brief
from ai.services.preflight import PreflightError, preflight_project
from ai.services.snapshots import product_snapshot
from ai.services.video import VideoGenerationService
from brands.models import Brand, Category, Product, ProductImage


def _jpeg(name="IMG_7070.JPG") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (180, 40, 40)).save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


def _png(name="product.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 80, 40)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class QaFlowTests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Kitchen", slug="qa-kitchen")
        self.owner = User.objects.create_user(
            username="qa-owner",
            email="qa-owner@example.com",
            password="password123",
            name="QA Owner",
            mobile="0123000099",
            location="Penang",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(owner=self.owner, category=self.category, name="MiSa")
        self.token = Token.objects.create(user=self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_brand_create_succeeds_and_stays_in_the_company_list(self):
        created = self.client.post(
            "/api/brands/",
            {"category": self.category.id, "name": "Penang Kitchen Lab"},
            format="json",
            HTTP_X_ACTING_BRAND=str(self.brand.id),
        )
        self.assertEqual(created.status_code, 201, created.data)
        listed = self.client.get("/api/brands/", HTTP_X_ACTING_BRAND=str(self.brand.id))
        names = {item["name"] for item in listed.data}
        self.assertIn("Penang Kitchen Lab", names)
        self.assertIn("MiSa", names)
        self.assertTrue(Brand.objects.filter(owner=self.owner, name="Penang Kitchen Lab").exists())

    def test_brand_create_failure_is_visible(self):
        before = Brand.objects.filter(owner=self.owner).count()
        rejected = self.client.post(
            "/api/brands/",
            {"category": self.category.id, "name": " "},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("name", rejected.data)
        self.assertEqual(Brand.objects.filter(owner=self.owner).count(), before)

    def test_products_page_and_studio_share_one_product(self):
        sibling = Brand.objects.create(owner=self.owner, category=self.category, name="Penang Air Kitchen QA")
        product = Product.objects.create(
            brand=self.brand,
            name="Penang Air Crisp",
            description="Existing air fryer",
            price="1.00",
        )
        catalog = self.client.get("/api/brands/products/")
        filtered = self.client.get("/api/brands/products/", HTTP_X_ACTING_BRAND=str(sibling.id))
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual([item["id"] for item in catalog.data], [product.id])
        self.assertEqual([item["id"] for item in filtered.data], [product.id])
        self.assertEqual(catalog.data[0]["price"], "1.00")
        self.assertEqual(catalog.data[0]["brand"], self.brand.id)
        self.assertEqual(Product.objects.filter(name="Penang Air Crisp").count(), 1)

    def test_character_reference_persists_after_reload(self):
        created = self.client.post(
            "/api/ai/characters/",
            {
                "brand": self.brand.id,
                "name": "Mike Seah QA Presenter",
                "gender": "male",
                "appearance_description": "Short hair, navy shirt.",
                "reference_front": _jpeg(),
                "reference_count": "1",
            },
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(len(created.data["references"]), 1)
        reloaded = self.client.get(f"/api/ai/characters/{created.data['id']}/")
        self.assertEqual(reloaded.status_code, 200)
        self.assertEqual(len(reloaded.data["references"]), 1)
        self.assertTrue(reloaded.data["references"][0]["url"])

    def test_character_upload_mismatch_does_not_leave_a_character(self):
        before = self.client.get("/api/ai/characters/").data
        rejected = self.client.post(
            "/api/ai/characters/",
            {
                "brand": self.brand.id,
                "name": "Missing Photo",
                "gender": "male",
                "appearance_description": "Navy shirt.",
                "reference_count": "1",
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("reference image", str(rejected.data).lower())
        after = self.client.get("/api/ai/characters/").data
        self.assertEqual(len(after), len(before))

    def test_duration_stays_canonical(self):
        project = self._project(15)
        for duration in (15, 30, 45, 60):
            brief = normalize_brief({"objective": "buy", "duration": duration}, project)
            self.assertEqual(brief["duration"], duration)
        with self.assertRaises(ValueError) as caught:
            normalize_brief({"duration": 40}, project)
        self.assertNotIn("Choose 30, 45, or 60", str(caught.exception))
        self.assertIn("15, 30, 45, or 60", str(caught.exception))

    def test_fifteen_second_concepts_and_storyboard(self):
        project = self._project(15)
        project.creative_brief = {
            "objective": "buy",
            "customer": "Home cooks",
            "main_benefit": "Crisp food",
            "duration": 15,
            "platform": "tiktok",
        }
        project.language = "conversational_bm"
        project.speaking_style = "warm"
        project.save()
        service = DirectorService()
        service.gemini.generate_json = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline"))
        concepts = service.generate_concepts(project)
        self.assertEqual(len(concepts), 3)
        for concept in concepts:
            self.assertEqual(concept["estimated_duration"], 15)
            self.assertEqual(len(concept["scenes"]), 3)
            self.assertEqual(sum(scene["duration"] for scene in concept["scenes"]), 15)
        fitted = _retarget_timeline([{"title": "Hook", "duration": 8}] * 5, 15)
        self.assertEqual(len(fitted), 3)
        with self.assertRaises(ValueError) as caught:
            service.adapt_duration(project, 20)
        self.assertNotIn("Choose 30, 45, or 60", str(caught.exception))

    def test_invalid_generation_returns_a_useful_error(self):
        project = self._project(15)
        with patch("ai.director_views.require_intelligence"), patch("ai.director_views.require_omni_key"):
            response = self.client.post(f"/api/ai/video/{project.id}/generate/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("storyboard", response.data["detail"].lower())

    def test_preflight_rejects_a_fifteen_second_storyboard_with_thirty_second_scenes(self):
        project = self._project(15)
        image = ProductImage(product=project.product)
        image.image.save("product.png", _png(), save=True)
        project.product_snapshot = product_snapshot(project.product)
        project.selected_concept_id = "ugc"
        project.language = "conversational_bm"
        project.speaking_style = "warm"
        project.creative_brief = {"duration": 15, "aspect_ratio": "9:16"}
        project.save()
        for index in range(5):
            Scene.objects.create(
                project=project,
                scene_key=f"scene-{index + 1}",
                order=index + 1,
                title="Scene",
                visual="Product on the counter",
                duration=6,
            )
        with patch("ai.services.preflight.require_omni_key"):
            with self.assertRaises(PreflightError) as caught:
                preflight_project(project)
        self.assertIn("3 scenes", str(caught.exception))

    def test_preflight_allows_generation_without_price_when_storyboard_exists(self):
        project = self._project(15)
        project.product.price = "0"
        project.product.save(update_fields=["price"])
        image = ProductImage(product=project.product)
        image.image.save("product.png", _png(), save=True)
        project.product_snapshot = product_snapshot(project.product)
        project.selected_concept_id = "ugc"
        project.language = "conversational_bm"
        project.speaking_style = "warm"
        project.creative_brief = {"duration": 15, "aspect_ratio": "9:16", "cta": "Shop now"}
        project.save()
        for index in range(3):
            Scene.objects.create(
                project=project,
                scene_key=f"scene-{index + 1}",
                order=index + 1,
                title="Scene",
                visual="Product on the counter",
                narration="Try it today.",
                caption="Try it today.",
                duration=5,
            )
        with patch("ai.services.preflight.require_omni_key"):
            preflight_project(project)
        from ai.services.snapshots import generation_blocker

        self.assertEqual(generation_blocker(project.product_snapshot), "")

    def test_provider_failure_is_persisted_and_not_retried(self):
        project = self._project(15)
        scene = Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="Product",
            duration=5,
        )

        class ProviderFailure(Exception):
            status_code = 400
            message = "Request contains an invalid argument. api_key=AIzaSECRETVALUE"

            def __str__(self):
                return "{'error': {'message': 'Request contains an invalid argument.', 'code': 'invalid_request'}}"

        wrapped = GeminiOmniProvider()._wrap_error(ProviderFailure(), "fallback", request_id="req-15")
        self.assertEqual(wrapped.code, "INVALID_REQUEST")
        self.assertFalse(wrapped.retryable)
        self.assertNotIn("AIza", str(wrapped))
        VideoGenerationService()._stamp_pipeline_error(
            scene,
            stage="start",
            provider="omni",
            error_type=wrapped.category,
            detail=str(wrapped),
            code=wrapped.code,
            status_code=wrapped.status_code,
            request_id=wrapped.request_id,
            retryable=wrapped.retryable,
            retry_count=1,
        )
        scene.refresh_from_db()
        self.assertEqual(scene.generation_status, "failed")
        self.assertEqual(scene.failure_code, "INVALID_REQUEST")
        self.assertEqual(scene.provider, "omni")
        self.assertEqual(scene.provider_request_id, "req-15")
        self.assertEqual(scene.retry_count, 1)
        self.assertIsNotNone(scene.failed_at)
        self.assertNotIn("AIza", scene.failure_message)
        blocked = self.client.post(f"/api/ai/video/scenes/{scene.id}/regenerate/")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("cannot be retried", blocked.data["detail"])

    def _project(self, duration: int) -> VideoProject:
        product = Product.objects.create(
            brand=self.brand,
            name="Penang Air Crisp",
            description="Existing air fryer",
            price="1.00",
        )
        return VideoProject.objects.create(
            owner=self.owner,
            product=product,
            product_snapshot=product_snapshot(product),
            duration_seconds=duration,
            language="conversational_bm",
            speaking_style="warm",
            status=VideoProjectStatus.DRAFT,
        )
