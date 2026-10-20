import io
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User
from ai.models import (
    BulkGeneration,
    BulkGenerationItem,
    BulkGenerationMode,
    BulkGenerationStatus,
    BulkItemStatus,
    Character,
    CharacterMasterReference,
    MasterReferenceStatus,
    Scene,
    VideoProject,
    VideoProjectStatus,
)
from ai.services.bulk_studio import BulkVideoGenerationService, default_constraints
from ai.services.video import VideoGenerationService
from brands.models import Brand, Category, Product, ProductImage


def _png(name="shot.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 80, 40)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _mp4(name="ref.mp4"):
    return SimpleUploadedFile(name, b"0001", content_type="video/mp4")


class BulkStudioApiTests(APITestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Beauty", slug="bulk-beauty")
        self.owner = User.objects.create_user(
            username="bulk-owner",
            email="bulk-owner@example.com",
            password="password123",
            name="Owner",
            mobile="0123001001",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        self.other = User.objects.create_user(
            username="bulk-other",
            email="bulk-other@example.com",
            password="password123",
            name="Other",
            mobile="0123001002",
            location="Penang",
            role=User.Role.PRODUCER,
        )
        self.agent = User.objects.create_user(
            username="bulk-agent",
            email="bulk-agent@example.com",
            password="password123",
            name="Agent",
            mobile="0123001003",
            location="Johor",
            role=User.Role.AGENT,
        )
        self.brand = Brand.objects.create(owner=self.owner, category=self.category, name="MiSa Home")
        self.other_brand = Brand.objects.create(owner=self.other, category=self.category, name="Other Home")
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            description="Daily face serum.",
            price="39.90",
        )
        ProductImage.objects.create(product=self.product, image=_png("product.png"))
        self.other_product = Product.objects.create(
            brand=self.other_brand,
            name="Other Serum",
            description="Other",
            price="19.90",
        )
        ProductImage.objects.create(product=self.other_product, image=_png("other.png"))
        self.character = self._ready_character("Sarah")
        self.characters = [self.character] + [self._ready_character(f"Talent {index}") for index in range(2, 4)]
        self.owner_token = Token.objects.create(user=self.owner)
        self.other_token = Token.objects.create(user=self.other)
        self.agent_token = Token.objects.create(user=self.agent)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.owner_token.key}")

    def _ready_character(self, name):
        character = Character.objects.create(
            owner=self.owner,
            brand=self.brand,
            name=name,
            gender="female",
            default_language="english",
            default_tone="warm",
            master_reference_status=MasterReferenceStatus.READY,
        )
        master = CharacterMasterReference.objects.create(
            character=character,
            version=1,
            image=_png(f"{name}.png"),
        )
        character.current_master = master
        character.master_reference_image = master.image
        character.master_reference_version = 1
        character.save()
        return character

    def _create(self, **extra):
        payload = {
            "mode": BulkGenerationMode.PRODUCT,
            "product_id": self.product.id,
            "requested_count": 3,
            "language": "english",
            "duration_seconds": 15,
        }
        payload.update(extra)
        return self.client.post("/api/ai/bulk-video/", payload, format="json")

    def test_unauthenticated_is_rejected(self):
        self.client.credentials()
        response = self.client.post("/api/ai/bulk-video/", {"product_id": self.product.id})
        self.assertEqual(response.status_code, 401)

    def test_agent_is_forbidden(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.agent_token.key}")
        response = self._create()
        self.assertEqual(response.status_code, 403)

    def test_other_owner_cannot_use_product(self):
        response = self._create(product_id=self.other_product.id)
        self.assertEqual(response.status_code, 404)

    def test_other_owner_cannot_view_batch(self):
        created = self._create()
        self.assertEqual(created.status_code, 201, created.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.other_token.key}")
        response = self.client.get(f"/api/ai/bulk-video/{created.data['id']}/")
        self.assertEqual(response.status_code, 404)

    def test_invalid_mode_and_missing_product(self):
        response = self.client.post("/api/ai/bulk-video/", {"mode": "character"}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self._create(mode="unknown")
        self.assertEqual(response.status_code, 400)

    def test_character_mode_requires_character(self):
        response = self._create(mode="character")
        self.assertEqual(response.status_code, 400)
        response = self._create(mode="character", character_id=self.character.id)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["mode"], "character")
        self.assertTrue(response.data["locks"]["character"])
        self.assertTrue(response.data["variables"]["story"])

    def test_optional_instruction_is_story_source_of_truth(self):
        created = self._create(requested_count=2, instruction="Show the red lid first.")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["instruction"], "Show the red lid first.")
        empty = self._create(requested_count=2)
        self.assertEqual(empty.status_code, 201, empty.data)
        self.assertEqual(empty.data.get("instruction") or "", "")
        bulk = BulkGeneration.objects.get(pk=created.data["id"])
        BulkVideoGenerationService()._store_plan(
            bulk,
            [
                {"sequence": 1, "title": "Kitchen", "location": "kitchen"},
                {"sequence": 2, "title": "Office", "location": "office"},
            ],
            replace=True,
        )
        item = bulk.items.order_by("sequence").first()
        prepared = BulkVideoGenerationService()._prepare_item_project(item)
        self.assertEqual((prepared.creative_brief or {}).get("legacy_instructions"), "Show the red lid first.")
        self.assertIn("SOURCE OF TRUTH", prepared.merchant_instructions)
        self.assertIn("Show the red lid first.", prepared.merchant_instructions)
        prompt = BulkVideoGenerationService()._plan_prompt(bulk, {"name": "Serum"})
        self.assertIn("SOURCE OF TRUTH", prompt)
        self.assertIn("Show the red lid first.", prompt)
        fallback = BulkVideoGenerationService()._fallback_plan(bulk, {"name": "Serum"})
        self.assertTrue(all(row["story"] == "Show the red lid first." for row in fallback))

    def test_existing_video_clones_master_flow(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot={"name": self.product.name, "price": self.product.price},
            status=VideoProjectStatus.READY_FOR_REVIEW,
            language="english",
            duration_seconds=15,
            merchant_instructions="Show the red lid first.",
            script={"hook": "See this serum", "narrative": "Show the red lid first.", "cta": "Shop Serum"},
            creative_brief={"location": "modern kitchen", "cta": "Shop Serum"},
        )
        project.preview_video.save("master.mp4", _mp4("master.mp4"), save=True)
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            title="Hook",
            narration="See this serum",
            caption="Serum",
            duration=7,
            metadata={"location": "modern kitchen", "shot_description": "Presenter enters kitchen"},
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-2",
            order=2,
            title="CTA",
            narration="Shop Serum",
            caption="Shop Serum",
            duration=8,
            metadata={"location": "modern kitchen", "shot_description": "Hold product to camera"},
        )
        created = self._create(mode="existing_video", source_video_id=project.id, requested_count=3)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["duration_seconds"], 15)
        spec = created.data["master_spec"]
        self.assertTrue(spec.get("from_project"))
        self.assertEqual(spec.get("source_video_id"), project.id)
        self.assertEqual(spec.get("scene_count"), 2)
        self.assertEqual(len(spec.get("scenes") or []), 2)
        plan = self.client.post(f"/api/ai/bulk-video/{created.data['id']}/generate-plan/")
        self.assertEqual(plan.status_code, 200, plan.data)
        self.assertEqual(len(plan.data["items"]), 3)
        self.assertEqual(plan.data["items"][0]["variation_config"].get("story"), "Show the red lid first.")
        bulk = BulkGeneration.objects.get(pk=created.data["id"])
        prepared = BulkVideoGenerationService()._prepare_item_project(bulk.items.order_by("sequence").first())
        self.assertEqual(prepared.scenes.count(), 2)
        self.assertIn("See this serum", prepared.scenes.order_by("order").first().narration)
        self.assertEqual((prepared.creative_brief or {}).get("bulk_source_project_id"), project.id)

    def test_product_mode_locks_product_truth(self):
        response = self._create()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["locks"]["product"])
        self.assertTrue(response.data["locks"]["price"])
        self.assertTrue(response.data["variables"]["hook"])

    def test_reference_modes_require_video(self):
        response = self._create(mode="reference_location")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/ai/bulk-video/",
            {
                "mode": "reference_location",
                "product_id": self.product.id,
                "requested_count": 2,
                "language": "english",
                "duration_seconds": 15,
                "reference_video": _mp4(),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        bad = self.client.post(
            "/api/ai/bulk-video/",
            {
                "mode": "reference_location",
                "product_id": self.product.id,
                "requested_count": 2,
                "reference_video": SimpleUploadedFile("notes.txt", b"nope", content_type="text/plain"),
            },
            format="multipart",
        )
        self.assertEqual(bad.status_code, 400)
        url_only = self._create(mode="reference_location", reference_url="https://example.com/ref.mp4")
        self.assertEqual(url_only.status_code, 400)

    def test_reference_mode_accepts_library_source_video(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot={"name": self.product.name},
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        project.preview_video.save("library.mp4", _mp4("library.mp4"), save=True)
        response = self._create(mode="reference_location", source_video_id=project.id, requested_count=2)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data.get("reference_video_url"))
        missing = self._create(mode="reference_location", source_video_id=99999)
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(response.data.get("character"), None)
        self.assertTrue(response.data["master_spec"].get("generate_character"))
        self.assertEqual(response.data["master_spec"].get("source_video_id"), project.id)

    def test_library_source_inherits_saved_character(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot={"name": self.product.name},
            status=VideoProjectStatus.READY_FOR_REVIEW,
            language="english",
            duration_seconds=15,
            creative_brief={"character_id": self.character.id},
        )
        project.preview_video.save("with-character.mp4", _mp4("with-character.mp4"), save=True)
        response = self._create(mode="reference_location", source_video_id=project.id, requested_count=2)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data.get("character"), self.character.id)

    def test_library_source_without_character_can_prepare_items(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot={"name": self.product.name, "price": self.product.price},
            status=VideoProjectStatus.READY_FOR_REVIEW,
            language="english",
            duration_seconds=15,
        )
        project.preview_video.save("library.mp4", _mp4("library.mp4"), save=True)
        created = self._create(mode="reference_location", source_video_id=project.id, requested_count=2)
        self.assertEqual(created.status_code, 201, created.data)
        bulk = BulkGeneration.objects.get(pk=created.data["id"])
        BulkVideoGenerationService()._store_plan(
            bulk,
            [
                {"sequence": 1, "title": "Office", "location": "office lobby"},
                {"sequence": 2, "title": "Street", "location": "city street"},
            ],
            replace=True,
        )
        item = bulk.items.order_by("sequence").first()
        prepared = BulkVideoGenerationService()._prepare_item_project(item)
        self.assertTrue((prepared.creative_brief or {}).get("generate_character"))
        self.assertTrue(prepared.selected_concept_id)

    def test_reference_character_mode_uses_selected_characters(self):
        response = self.client.post(
            "/api/ai/bulk-video/",
            {
                "mode": "reference_character",
                "product_id": self.product.id,
                "language": "english",
                "duration_seconds": 15,
                "character_ids": [item.id for item in self.characters],
                "reference_video": _mp4(),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["requested_count"], 3)
        self.assertEqual(response.data["character_ids"], [item.id for item in self.characters])

    @override_settings(GEMINI_API_KEY="test-key")
    def test_generate_plan_creates_child_items(self):
        created = self._create(requested_count=3)
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            return_value={
                "variations": [
                    {"title": "Morning routine", "location": "bathroom"},
                    {"title": "Kitchen demo", "location": "kitchen"},
                    {"title": "Cafe UGC", "location": "cafe"},
                ]
            },
        ):
            response = self.client.post(f"/api/ai/bulk-video/{created.data['id']}/generate-plan/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "plan_ready")
        self.assertEqual(len(response.data["items"]), 3)
        self.assertEqual(response.data["items"][0]["title"], "Morning routine")

    @override_settings(GEMINI_API_KEY="test-key")
    def test_plan_edit_remove_and_duplicate_generate_blocked(self):
        created = self._create(requested_count=3)
        service = BulkVideoGenerationService()
        bulk = BulkGeneration.objects.get(pk=created.data["id"])
        with patch.object(service.intelligence, "generate_json", side_effect=RuntimeError("offline")):
            service.generate_plan(bulk)
        response = self.client.patch(
            f"/api/ai/bulk-video/{bulk.pk}/plan/",
            {"remove": [3]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["items"]), 2)
        with (
            patch("ai.services.bulk_studio.require_omni_key"),
            patch("ai.services.bulk_studio.preflight_project"),
            patch("ai.tasks.enqueue_bulk_item") as enqueue,
        ):
            first = self.client.post(f"/api/ai/bulk-video/{bulk.pk}/generate/")
            again = self.client.post(f"/api/ai/bulk-video/{bulk.pk}/generate/")
        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(again.status_code, 400)
        self.assertGreaterEqual(enqueue.call_count, 1)
        self.assertEqual(VideoProject.objects.filter(owner=self.owner).count(), 2)

    @override_settings(GEMINI_API_KEY="test-key", AI_SYNC_TASKS=True, BULK_VIDEO_CONCURRENCY=2)
    def test_generate_starts_two_videos_together(self):
        created = self._create(requested_count=3)
        bulk = BulkGeneration.objects.get(pk=created.data["id"])
        BulkVideoGenerationService()._store_plan(
            bulk,
            [
                {"sequence": 1, "title": "One", "location": "kitchen", "hook": "One"},
                {"sequence": 2, "title": "Two", "location": "garden", "hook": "Two"},
                {"sequence": 3, "title": "Three", "location": "studio", "hook": "Three"},
            ],
            replace=True,
        )
        with (
            patch("ai.services.bulk_studio.require_omni_key"),
            patch("ai.services.bulk_studio.preflight_project"),
            patch("ai.tasks.enqueue_bulk_item") as enqueue,
        ):
            response = self.client.post(f"/api/ai/bulk-video/{bulk.pk}/generate/")
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(enqueue.call_count, 2)

    @override_settings(GEMINI_API_KEY="test-key", AI_SYNC_TASKS=True, BULK_VIDEO_CONCURRENCY=3)
    def test_generate_starts_three_videos_together(self):
        created = self._create(requested_count=3)
        bulk = BulkGeneration.objects.get(pk=created.data["id"])
        BulkVideoGenerationService()._store_plan(
            bulk,
            [
                {"sequence": 1, "title": "One", "location": "kitchen", "hook": "One"},
                {"sequence": 2, "title": "Two", "location": "garden", "hook": "Two"},
                {"sequence": 3, "title": "Three", "location": "studio", "hook": "Three"},
            ],
            replace=True,
        )
        with (
            patch("ai.services.bulk_studio.require_omni_key"),
            patch("ai.services.bulk_studio.preflight_project"),
            patch("ai.tasks.enqueue_bulk_item") as enqueue,
        ):
            response = self.client.post(f"/api/ai/bulk-video/{bulk.pk}/generate/")
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(enqueue.call_count, 3)

    @override_settings(GEMINI_API_KEY="test-key", AI_SYNC_TASKS=True, BULK_VIDEO_CONCURRENCY=1)
    def test_one_item_failure_does_not_fail_batch_and_retry_works(self):
        created = self._create(requested_count=2)
        bulk = BulkGeneration.objects.get(pk=created.data["id"])
        BulkVideoGenerationService()._store_plan(
            bulk,
            [
                {"sequence": 1, "title": "One", "location": "kitchen", "hook": "One"},
                {"sequence": 2, "title": "Two", "location": "garden", "hook": "Two"},
            ],
            replace=True,
        )
        seen = {"count": 0}

        def fake_run(self, project_id):
            project = VideoProject.objects.get(pk=project_id)
            seen["count"] += 1
            if seen["count"] == 1:
                project.mark_failed("Omni rejected this scene.")
                raise RuntimeError("Omni rejected this scene.")
            project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Ready for review")
            return project

        with (
            patch("ai.services.bulk_studio.require_omni_key"),
            patch("ai.services.bulk_studio.preflight_project"),
            patch.object(VideoGenerationService, "run", fake_run),
        ):
            response = self.client.post(f"/api/ai/bulk-video/{bulk.pk}/generate/")
        self.assertEqual(response.status_code, 202, response.data)
        bulk.refresh_from_db()
        statuses = list(bulk.items.order_by("sequence").values_list("status", flat=True))
        self.assertIn(BulkItemStatus.FAILED, statuses)
        self.assertIn(BulkItemStatus.COMPLETED, statuses)
        self.assertEqual(bulk.status, BulkGenerationStatus.COMPLETED_WITH_ERRORS)
        self.assertEqual(VideoProject.objects.filter(owner=self.owner).count(), 2)

        with (
            patch("ai.services.bulk_studio.require_omni_key"),
            patch("ai.services.bulk_studio.preflight_project"),
            patch.object(
                VideoGenerationService,
                "run",
                lambda self, project_id: VideoProject.objects.get(pk=project_id).mark_progress(
                    VideoProjectStatus.READY_FOR_REVIEW, 100, "Ready for review"
                )
                or VideoProject.objects.get(pk=project_id),
            ),
        ):
            retry = self.client.post(f"/api/ai/bulk-video/{bulk.pk}/retry-failed/")
        self.assertEqual(retry.status_code, 202, retry.data)
        bulk.refresh_from_db()
        self.assertEqual(bulk.status, BulkGenerationStatus.COMPLETED)
        self.assertEqual(bulk.items.filter(status=BulkItemStatus.FAILED).count(), 0)

    @override_settings(GEMINI_API_KEY="test-key")
    def test_reference_analysis_is_stored_once_on_parent(self):
        created = self.client.post(
            "/api/ai/bulk-video/",
            {
                "mode": "reference_location",
                "product_id": self.product.id,
                "requested_count": 2,
                "language": "english",
                "duration_seconds": 15,
                "reference_video": _mp4(),
            },
            format="multipart",
        )
        analysis = {
            "hook": "Wake up glow",
            "structure": ["hook", "demo", "cta"],
            "pacing": "fast",
            "shot_sequence": ["face", "product", "cta"],
            "camera_style": "handheld",
            "storytelling_pattern": "problem solution",
            "cta_structure": "buy now",
        }
        with patch(
            "ai.services.reference.ReferenceAnalysisService.analyze",
            return_value=analysis,
        ), patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            return_value={"story": "Glow routine", "cta": "Get Serum RM39.90", "scenes": []},
        ):
            response = self.client.post(f"/api/ai/bulk-video/{created.data['id']}/analyze-reference/")
        self.assertEqual(response.status_code, 200, response.data)
        spec = response.data["master_spec"]
        self.assertEqual(spec["analysis"]["hook"], "Wake up glow")
        self.assertTrue(spec["scenes"])

    def test_default_constraints_match_modes(self):
        character = default_constraints("character")
        self.assertTrue(character["locked"]["character"])
        self.assertTrue(character["variables"]["location"])
        location = default_constraints("reference_location")
        self.assertTrue(location["locked"]["story"])
        self.assertTrue(location["variables"]["location"])
        people = default_constraints("reference_character")
        self.assertTrue(people["locked"]["location"])
        self.assertTrue(people["variables"]["character"])
        existing = default_constraints("existing_video")
        self.assertTrue(existing["locked"]["story"])
        self.assertTrue(existing["locked"]["scenes"])
        self.assertTrue(existing["variables"]["location"])

    def test_cancel_stops_queued_and_generating_items(self):
        created = self._create(requested_count=2)
        bulk = BulkGeneration.objects.get(pk=created.data["id"])
        BulkVideoGenerationService()._store_plan(
            bulk,
            [
                {"sequence": 1, "title": "One", "location": "kitchen"},
                {"sequence": 2, "title": "Two", "location": "garden"},
            ],
            replace=True,
        )
        items = list(bulk.items.order_by("sequence"))
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            status=VideoProjectStatus.GENERATING_VIDEO,
            creative_brief={"pipeline": "studio"},
            language="english",
            duration_seconds=15,
        )
        items[0].video_project = project
        items[0].status = BulkItemStatus.GENERATING
        items[0].save(update_fields=["video_project", "status", "updated_at"])
        items[1].status = BulkItemStatus.QUEUED
        items[1].save(update_fields=["status", "updated_at"])
        bulk.status = BulkGenerationStatus.GENERATING
        bulk.save(update_fields=["status", "updated_at"])

        response = self.client.post(f"/api/ai/bulk-video/{bulk.pk}/cancel/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")
        self.assertTrue(all(item["status"] == "cancelled" for item in response.data["items"]))
        project.refresh_from_db()
        self.assertEqual(project.status, VideoProjectStatus.FAILED)
        self.assertEqual(project.error_message, "Stopped by you.")
        self.assertTrue((project.creative_brief or {}).get("cancel_requested"))
