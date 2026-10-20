from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from ai.models import LanguageChoice, Scene, StyleRecipe, VideoProject, VideoProjectStatus
from ai.services.compiler import compile_scene_prompt
from ai.services.presenter import presenter_identity_text, presenter_should_appear
from ai.services.style_recipes import apply_recipe_to_project, recipe_from_project, save_recipe
from ai.services.video import VideoGenerationService
from brands.models import Brand, Category, Product, ProductImage
from ai.tests.test_studio import _png
from ai.services.snapshots import product_snapshot


class StudioPresenterAndStyleTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Kitchen", slug="kitchen")
        self.owner = User.objects.create_user(
            username="brandowner2",
            email="brand2@example.com",
            password="password123",
            name="Brand Owner",
            mobile="0123456788",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Home",
            description="Kitchen",
            location="KL",
        )
        self.product = Product.objects.create(
            brand=self.brand,
            name="Air Fryer",
            description="Crispy food with less oil.",
            price="199.00",
        )
        ProductImage.objects.create(product=self.product, image=_png())
        self.other = Product.objects.create(
            brand=self.brand,
            name="Toaster",
            description="Even toast every morning.",
            price="89.00",
        )
        ProductImage.objects.create(product=self.other, image=_png())

    def _project(self, **kwargs):
        payload = dict(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaker_gender="female",
            selected_concept_id="style-demo",
            creative_brief={
                "schema_version": 2,
                "objective": "buy",
                "customer": "Busy parents",
                "main_benefit": "Crispy food with less oil",
                "presenter": {"ethnicity": "european", "ethnicity_label": "European", "gender": "female"},
                "location": "a bright modern kitchen",
            },
            status=VideoProjectStatus.DRAFT,
        )
        payload.update(kwargs)
        project = VideoProject.objects.create(**payload)
        for index in range(1, 4):
            Scene.objects.create(
                project=project,
                scene_key=f"scene-{index}",
                order=index,
                title=f"Scene {index}",
                visual="Show the product",
                narration="Try this today.",
                caption="Air Fryer",
                duration=4,
                metadata={"presenter_action": "Hold the product to camera.", "presenter_locked": True},
            )
        return project

    def test_language_choices_include_new_locales(self):
        values = set(LanguageChoice.values)
        for item in ("english", "chinese", "cantonese", "hokkien"):
            self.assertIn(item, values)

    def test_prompt_locks_presenter_identity(self):
        project = self._project()
        scene = project.scenes.first()
        prompt = compile_scene_prompt(scene, project)
        self.assertIn("European", prompt)
        self.assertIn("presenter", prompt.lower())
        self.assertTrue(presenter_identity_text(project))

    def test_scenes_start_together(self):
        project = self._project()
        order = []
        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda n: n

        def start(*args, **kwargs):
            order.append("start")
            return {"id": f"t{len(order)}"}

        def poll(*args, **kwargs):
            order.append("poll")
            return {"id": "done"}

        omni.start.side_effect = start
        omni.poll.side_effect = poll
        omni.check = None
        omni.save_video.side_effect = lambda task, dest: dest.write_bytes(b"mp4")
        images = MagicMock()
        images.generate_image.side_effect = RuntimeError("skip identity still")
        for scene in project.scenes.all():
            if scene.order > 1:
                meta = dict(scene.metadata or {})
                meta["requires_previous_scene_continuity"] = True
                scene.metadata = meta
                scene.save(update_fields=["metadata"])
        with patch("ai.services.video.inspect_audio", return_value={"audible": True, "reason": ""}), patch.object(
            VideoGenerationService, "_extract_final_frame", return_value=None
        ):
            VideoGenerationService(omni=omni, images=images)._create_videos(project)
        self.assertEqual(order.count("start"), 3)
        # Scenes 2 and 3 require the previous clip, so they start after scene 1
        # has been submitted. Independent scenes are covered by the concurrency test.
        self.assertEqual(order[0], "start")
        self.assertLess(order.index("poll"), order.index("start", order.index("start") + 1))

    def test_generate_character_still_requests_an_identity(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaker_gender="female",
            creative_brief={"generate_character": True},
            status=VideoProjectStatus.DRAFT,
        )
        self.assertTrue(presenter_should_appear(project))
        project.creative_brief = {}
        project.save(update_fields=["creative_brief"])
        self.assertFalse(presenter_should_appear(project))

    def test_style_key_bulk_reuses_blueprint(self):
        project = self._project()
        recipe = save_recipe(owner=self.owner, project=project, name="Air fryer kitchen")
        self.assertEqual(recipe.key, "air-fryer-kitchen")
        clone = VideoProject.objects.create(
            owner=self.owner,
            product=self.other,
            product_snapshot=product_snapshot(self.other),
            status=VideoProjectStatus.DRAFT,
        )
        apply_recipe_to_project(clone, recipe, overrides={"location": "a different kitchen", "ethnicity": "malaysian_chinese"})
        clone.refresh_from_db()
        self.assertEqual(clone.duration_seconds, 45)
        self.assertEqual(clone.scenes.count(), 6)
        self.assertEqual(clone.creative_brief.get("location"), "a different kitchen")
        self.assertIn("malaysian", str(clone.creative_brief.get("presenter") or {}).lower())
        payload = recipe_from_project(project)
        self.assertEqual(len(payload["scene_blueprint"]), 3)

    def test_save_style_api(self):
        project = self._project()
        client = APIClient()
        token = Token.objects.create(user=self.owner)
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = client.post(
            f"/api/ai/video/{project.id}/save-style/",
            {"name": "Kitchen UGC"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(StyleRecipe.objects.filter(owner=self.owner, key="kitchen-ugc").count(), 1)
