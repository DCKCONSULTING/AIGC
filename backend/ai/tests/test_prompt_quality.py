"""Prompt / storyboard quality: no workflow-label leakage into narration."""

from __future__ import annotations

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import User
from ai.models import (
    BulkGeneration,
    BulkGenerationMode,
    LanguageChoice,
    Scene,
    StyleChoice,
    VideoProject,
    VideoProjectStatus,
)
from ai.services.bulk_studio import (
    BulkVideoGenerationService,
    contains_workflow_label,
    scrub_workflow_text,
)
from ai.services.compiler import compile_film_prompt, sanitize_spoken_line
from brands.models import Brand, Category, Product, ProductImage


def _png(name="shot.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 80, 40)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(VIDEO_PROVIDER="seedance")
class PromptQualityTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Drinkware", slug="prompt-drinkware")
        self.owner = User.objects.create_user(
            username="prompt-qa",
            email="prompt-qa@example.com",
            password="password123",
            name="Prompt QA",
            mobile="0123999001",
            location="KL",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(owner=self.owner, category=self.category, name="Prompt Brand")
        self.product = Product.objects.create(
            brand=self.brand,
            name="Chill Tumbler 900ml",
            price="48.90",
        )
        ProductImage.objects.create(product=self.product, image=_png("product.png"))

    def test_scrub_removes_bulk_existing_video(self):
        dirty = "Chill Tumbler 900ml bulk existing video. Chill Tumbler 900ml."
        self.assertTrue(contains_workflow_label(dirty))
        cleaned = scrub_workflow_text(dirty, fallback="Keep cool longer")
        self.assertNotIn("bulk existing", cleaned.lower())
        self.assertEqual(sanitize_spoken_line(dirty).lower().find("bulk existing"), -1)

    def test_existing_video_inherits_source_duration(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot={"name": self.product.name},
            language=LanguageChoice.CONVERSATIONAL_BM,
            speaking_style=StyleChoice.WARM,
            duration_seconds=30,
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        project.preview_video.save(
            "source.mp4",
            SimpleUploadedFile("source.mp4", b"0001", content_type="video/mp4"),
            save=True,
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            title="Hook",
            narration="Cuaca panas.",
            duration=30,
        )
        bulk = BulkVideoGenerationService().create(
            self.owner,
            {
                "mode": BulkGenerationMode.EXISTING_VIDEO,
                "product": self.product,
                "source_video_id": project.id,
                "requested_count": 2,
                "language": LanguageChoice.CONVERSATIONAL_BM,
                "duration_seconds": 15,  # UI default must not override locked source length
            },
        )
        self.assertEqual(bulk.duration_seconds, 30)

    def test_clone_duration_change_preserves_source_dialogue(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot={"name": self.product.name, "price": "48.90", "currency": "MYR"},
            language=LanguageChoice.CONVERSATIONAL_BM,
            speaking_style=StyleChoice.WARM,
            duration_seconds=30,
            status=VideoProjectStatus.READY_FOR_REVIEW,
            merchant_instructions="light, stainless steel, modern pastel colour",
            creative_brief={"hook": "Cuaca panas dekat Malaysia ni?", "main_benefit": "tahan sejuk"},
            script={"hook": "Cuaca panas dekat Malaysia ni?", "narrative": "light stainless steel"},
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            title="Hook",
            visual="Presenter wiping brow in warm kitchen holding a cup.",
            narration="Cuaca panas dekat Malaysia ni, penat kan bila minuman cepat suam?",
            duration=6,
            metadata={"location": "Kitchen", "shot_description": "Presenter wiping brow in warm kitchen."},
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-2",
            order=2,
            title="Reveal",
            visual="Presenter reveals the tumbler.",
            narration="Nasib baik ada Chill Tumbler ni!",
            duration=6,
            metadata={"location": "Kitchen", "shot_description": "Presenter reveals the tumbler."},
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-3",
            order=3,
            title="Features",
            visual="Close-up stainless steel texture.",
            narration="Rekaan stainless steel tahan sejuk dan warna pastel cantik.",
            duration=6,
            metadata={"location": "Kitchen", "shot_description": "Close-up stainless steel."},
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-4",
            order=4,
            title="Lifestyle",
            visual="Carrying tumbler by handle.",
            narration="Ada pemegang selesa, senang nak bawa jalan-jalan.",
            duration=6,
            metadata={"location": "Kitchen", "shot_description": "Carrying tumbler by handle."},
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-5",
            order=5,
            title="CTA",
            visual="Product hero with CTA.",
            narration="Dapatkan Chill Tumbler sekarang. Tekan beg kuning!",
            duration=6,
            metadata={"location": "Kitchen", "shot_description": "Product hero with CTA."},
        )

        service = BulkVideoGenerationService()
        bulk = BulkGeneration.objects.create(
            owner=self.owner,
            product=self.product,
            mode=BulkGenerationMode.EXISTING_VIDEO,
            title=f"{self.product.name} bulk existing video",
            language=LanguageChoice.CONVERSATIONAL_BM,
            speaking_style=StyleChoice.WARM,
            duration_seconds=15,
            requested_count=2,
            locks={"product": True, "price": True},
            variables={"location": True},
            master_spec={
                "from_project": True,
                "source_video_id": project.pk,
                "duration": 30,
                "location": "Kitchen",
                "hook": "Cuaca panas dekat Malaysia ni?",
                "story": "light, stainless steel, modern pastel colour",
                "scenes": [
                    {
                        "order": scene.order,
                        "title": scene.title,
                        "duration": scene.duration,
                        "shot_description": (scene.metadata or {}).get("shot_description") or scene.visual,
                        "voice_over": scene.narration,
                        "location": "Kitchen",
                    }
                    for scene in project.scenes.all().order_by("order")
                ],
            },
        )
        plan = service._clone_flow_plan(bulk, {"name": self.product.name, "price": "48.90"})
        self.assertEqual(len(plan), 2)
        scenes = plan[0]["scenes"]
        # Same-flow preserves creative scene count and scales timings (30s → 15s).
        self.assertEqual(len(scenes), 5)
        self.assertAlmostEqual(sum(float(item.get("duration") or 0) for item in scenes), 15.0, places=1)
        joined = " ".join(str(item.get("voice_over") or "") for item in scenes).lower()
        self.assertNotIn("bulk existing", joined)
        self.assertTrue(
            any("cuaca panas" in str(item.get("voice_over") or "").lower() for item in scenes)
            or any("chill tumbler" in str(item.get("voice_over") or "").lower() for item in scenes)
        )
        for item in scenes:
            self.assertFalse(contains_workflow_label(item.get("voice_over") or ""))
            self.assertFalse(contains_workflow_label(item.get("shot_description") or ""))

        # Fallback must not echo the contaminated bulk title into dialogue or visuals.
        fallback = service._fallback_scenes(bulk, {"location": "Kitchen", "title": bulk.title})
        for item in fallback:
            self.assertNotIn("bulk existing", str(item.get("voice_over") or "").lower())
            self.assertNotIn("bulk existing", str(item.get("shot_description") or "").lower())

    def test_compile_film_prompt_strips_workflow_labels(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot={"name": self.product.name, "price": "48.90", "currency": "MYR"},
            language=LanguageChoice.CONVERSATIONAL_BM,
            speaking_style=StyleChoice.WARM,
            duration_seconds=15,
            status=VideoProjectStatus.DRAFT,
            creative_brief={"main_benefit": "tahan sejuk", "offer_price": "48.90"},
        )
        scene = Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            title="Hook",
            visual="Presenter holds tumbler in kitchen.",
            narration="Chill Tumbler 900ml bulk existing video. Chill Tumbler 900ml.",
            duration=15,
            metadata={
                "shot_description": "Chill Tumbler bulk existing video in Kitchen.",
                "voice_over": "Chill Tumbler 900ml bulk existing video. Chill Tumbler 900ml.",
            },
        )
        prompt = compile_film_prompt(
            project,
            [scene],
            0,
            15,
            extend=False,
            provider="seedance",
        )
        self.assertNotIn("bulk existing", prompt.lower())
        self.assertIn("Speak exactly:", prompt)
        self.assertIn("Chill Tumbler", prompt)
