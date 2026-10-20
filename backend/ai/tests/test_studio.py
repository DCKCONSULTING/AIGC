from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from ai.exceptions import GoogleProviderError, MissingAPIKeyError
from ai.models import MerchantPreference, Scene, VideoProject, VideoProjectStatus
from ai.providers.google.client import require_google_api_key, require_speech_credentials
from ai.services.qa import QAService
from ai.services.snapshots import product_snapshot
from ai.services.validation import missing_product_fields, offer_is_expired
from brands.models import Brand, Category, Product, ProductImage


def _png() -> SimpleUploadedFile:
    return SimpleUploadedFile("shot.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, content_type="image/png")


ANALYSIS = {
    "name": "Serum",
    "summary": "A daily face serum.",
    "variants": ["30ml"],
    "dimensions": "10cm",
    "materials": "glass",
    "price": "39.90",
    "offer": "",
    "offer_expiry": "",
    "approved_claims": ["hydrating"],
    "prohibited_claims": ["cures acne"],
    "certifications": [],
    "unsupported_claims": [],
    "facts": ["Price is RM39.90"],
    "merchant_instructions": "",
}

SCRIPT = {
    "title": "Serum in 40 seconds",
    "full_script": "Cuba serum ini. Harga RM39.90.",
    "unsupported_claims": [],
    "scenes": [
        {
            "scene_key": "scene-1",
            "order": 1,
            "title": "Hook",
            "visual": "Product close-up",
            "narration": "Cuba serum ini.",
            "caption": "Serum 30ml",
            "duration": 5,
        },
        {
            "scene_key": "scene-2",
            "order": 2,
            "title": "Price",
            "visual": "Price card",
            "narration": "Harga RM39.90 sahaja.",
            "caption": "RM39.90",
            "duration": 5,
        },
    ],
}


class StudioAPITest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Beauty", slug="beauty")
        self.owner = User.objects.create_user(
            username="brandowner",
            email="brand@example.com",
            password="password123",
            name="Brand Owner",
            mobile="0123456789",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        self.other = User.objects.create_user(
            username="otherbrand",
            email="other@example.com",
            password="password123",
            name="Other Owner",
            mobile="0123456788",
            location="Penang",
            role=User.Role.PRODUCER,
        )
        self.agent = User.objects.create_user(
            username="agentuser",
            email="agent@example.com",
            password="password123",
            name="Agent User",
            mobile="0123456787",
            location="Johor",
            role=User.Role.AGENT,
        )
        self.brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Dck Beauty",
            description="Skincare",
            location="KL",
        )
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            description="Daily hydrating serum",
            price="39.90",
            variants=["30ml"],
            dimensions="10cm",
            materials="glass",
            approved_claims=["hydrating"],
            prohibited_claims=["cures acne"],
        )
        self.owner_token = Token.objects.create(user=self.owner)
        self.other_token = Token.objects.create(user=self.other)
        self.agent_token = Token.objects.create(user=self.agent)
        self.client = APIClient()

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_unauthenticated_is_rejected(self):
        response = self.client.post("/api/ai/product/analyze/", {"product_id": self.product.id})
        self.assertEqual(response.status_code, 401)

    def test_agent_is_forbidden(self):
        self.auth(self.agent_token)
        response = self.client.post("/api/ai/product/analyze/", {"product_id": self.product.id})
        self.assertEqual(response.status_code, 403)

    def test_other_owner_cannot_view_project(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
        )
        self.auth(self.other_token)
        response = self.client.get(f"/api/ai/video/{project.id}/")
        self.assertEqual(response.status_code, 404)

    def test_owner_can_delete_project(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        self.auth(self.owner_token)
        response = self.client.delete(f"/api/ai/video/{project.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(VideoProject.objects.filter(pk=project.id).exists())

    def test_other_owner_cannot_delete_project(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
        )
        self.auth(self.other_token)
        response = self.client.delete(f"/api/ai/video/{project.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(VideoProject.objects.filter(pk=project.id).exists())

    @override_settings(GOOGLE_API_KEY="", GEMINI_API_KEY="", OPENAI_API_KEY="", CLAW_API_KEY="")
    def test_missing_api_keys(self):
        self.auth(self.owner_token)
        response = self.client.post("/api/ai/product/analyze/", {"product_id": self.product.id})
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.json()["detail"])

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_google_api_failure(self):
        self.auth(self.owner_token)
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            side_effect=GoogleProviderError("down"),
        ):
            response = self.client.post("/api/ai/product/analyze/", {"product_id": self.product.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], self.product.name)
        self.assertIn("snapshot", response.json())

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_product_analysis(self):
        self.auth(self.owner_token)
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            return_value=ANALYSIS,
        ) as mocked:
            response = self.client.post("/api/ai/product/analyze/", {"product_id": self.product.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Serum")
        self.assertIn("snapshot", response.json())
        mocked.assert_called_once()

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_reference_analysis(self):
        self.auth(self.owner_token)
        video = SimpleUploadedFile("ref.mp4", b"0000", content_type="video/mp4")
        with patch(
            "ai.providers.google.gemini.GeminiProvider.generate_json",
            return_value={
                "hook": "Problem first",
                "structure": ["hook", "demo", "cta"],
                "pacing": "fast",
                "shot_sequence": ["close-up", "hands"],
                "camera_style": "handheld",
                "storytelling_pattern": "problem-solution",
                "cta_structure": "price then shop now",
            },
        ):
            response = self.client.post(
                "/api/ai/reference/analyze/",
                {"product_id": self.product.id, "video": video},
                format="multipart",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["hook"], "Problem first")

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_reference_url_analysis(self):
        self.auth(self.owner_token)
        with patch(
            "ai.providers.google.gemini.GeminiProvider.generate_json",
            return_value={
                "hook": "Price first",
                "structure": ["hook"],
                "pacing": "fast",
                "shot_sequence": ["close-up"],
                "camera_style": "static",
                "storytelling_pattern": "offer",
                "cta_structure": "shop now",
                "offer_placement": "second scene",
            },
        ):
            response = self.client.post(
                "/api/ai/reference/analyze/",
                {
                    "product_id": self.product.id,
                    "reference_url": "https://example.com/ref.mp4",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["offer_placement"], "second scene")

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_script_generation(self):
        self.auth(self.owner_token)

        def fake_json(prompt, **kwargs):
            text = str(prompt)
            if "Extract only facts" in text:
                return ANALYSIS
            if "creative brief" in text:
                return {
                    "title": "Brief",
                    "hook": "Hi",
                    "promise": "Glow",
                    "cta": "Shop",
                    "tone": "warm",
                }
            if "Write an original" in text:
                return SCRIPT
            return {
                "shots": [
                    {"scene_key": "scene-1", "image_prompt": "x", "video_prompt": "y"}
                ]
            }

        with patch("ai.providers.google.gemini.GeminiProvider.generate_json", side_effect=fake_json):
            response = self.client.post(
                "/api/ai/script/generate/",
                {"product_id": self.product.id, "language": "conversational_bm"},
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["script"]["title"], "Serum in 40 seconds")
        self.assertEqual(len(body["scenes"]), 2)
        self.assertEqual(body["scenes"][0]["scene_key"], "scene-1")
        self.assertEqual(body["script"]["language"], "ms-MY")
        self.assertIn("duration_seconds", body["script"])

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_brief_generation(self):
        self.auth(self.owner_token)
        with patch(
            "ai.providers.google.gemini.GeminiProvider.generate_json",
            side_effect=[
                ANALYSIS,
                {
                    "title": "Brief",
                    "hook": "Hi",
                    "promise": "Glow",
                    "cta": "Shop",
                    "tone": "warm",
                    "content_ideas": ["Before after"],
                    "customer_objections": ["Is it sticky?"],
                },
            ],
        ):
            response = self.client.post(
                "/api/ai/brief/generate/",
                {"product_id": self.product.id},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["creative_brief"]["hook"], "Hi")

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key")
    def test_video_job_creation(self):
        ProductImage.objects.create(product=self.product, image=_png())
        self.auth(self.owner_token)
        with patch("ai.views.enqueue_video_generation") as enqueue:
            response = self.client.post(
                "/api/ai/video/generate/",
                {
                    "product_id": self.product.id,
                    "language": "formal_bm",
                    "style": "calm",
                    "gender": "male",
                    "duration_seconds": 45,
                },
            )
        self.assertEqual(response.status_code, 202)
        project = VideoProject.objects.get(pk=response.json()["id"])
        self.assertEqual(project.status, VideoProjectStatus.QUEUED)
        self.assertEqual(project.product_snapshot["name"], "Serum")
        self.assertEqual(project.language, "formal_bm")
        enqueue.assert_called_once_with(project.id)
        pref = MerchantPreference.objects.get(user=self.owner)
        self.assertEqual(pref.language, "formal_bm")
        self.assertEqual(pref.speaking_style, "calm")
        self.assertEqual(project.speaker_gender, "male")
        self.assertEqual(pref.speaker_gender, "male")

    def test_save_and_reuse_draft(self):
        self.auth(self.owner_token)
        created = self.client.post(
            "/api/ai/video/draft/",
            {
                "product_id": self.product.id,
                "language": "formal_bm",
                "style": "calm",
                "gender": "male",
                "duration_seconds": 30,
                "instructions": "BM santai. Fokus senang simpan.",
            },
        )
        self.assertEqual(created.status_code, 201)
        draft = VideoProject.objects.get(pk=created.json()["id"])
        self.assertEqual(draft.status, VideoProjectStatus.DRAFT)
        self.assertEqual(draft.merchant_instructions, "BM santai. Fokus senang simpan.")
        self.assertEqual(draft.speaking_style, "calm")

        updated = self.client.post(
            "/api/ai/video/draft/",
            {
                "product_id": self.product.id,
                "draft_id": draft.id,
                "language": "bm_english",
                "style": "bold",
                "gender": "female",
                "duration_seconds": 45,
                "instructions": "Updated draft line.",
            },
        )
        self.assertEqual(updated.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.merchant_instructions, "Updated draft line.")
        self.assertEqual(draft.language, "bm_english")
        self.assertEqual(VideoProject.objects.filter(product=self.product, status="draft").count(), 1)

        listing = self.client.get(f"/api/ai/videos/?product={self.product.id}")
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(any(item["id"] == draft.id and item["status"] == "draft" for item in listing.json()))

    def test_draft_requires_product(self):
        self.auth(self.owner_token)
        response = self.client.post("/api/ai/video/draft/", {"instructions": "Hello"})
        self.assertEqual(response.status_code, 400)

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_transcribe_voice_note(self):
        self.auth(self.owner_token)
        audio = SimpleUploadedFile("note.webm", b"audio-bytes", content_type="audio/webm")
        with patch(
            "ai.providers.intelligence.IntelligenceClient.transcribe",
            return_value="Buat video 35 saat, BM santai.",
        ) as mocked:
            response = self.client.post(
                "/api/ai/transcribe/",
                {"voice": audio, "language": "conversational_bm"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Buat video 35 saat, BM santai.")
        mocked.assert_called_once()

    def test_transcribe_requires_audio(self):
        self.auth(self.owner_token)
        response = self.client.post("/api/ai/transcribe/", {})
        self.assertEqual(response.status_code, 400)

    def test_video_status(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.GENERATING_VIDEO,
            progress=64,
            stage_label="Creating video",
        )
        self.auth(self.owner_token)
        response = self.client.get(f"/api/ai/video/{project.id}/status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["progress"], 64)
        self.assertEqual(response.json()["status"], VideoProjectStatus.GENERATING_VIDEO)

    def test_delete_failed_videos_keeps_ready_and_other_owners(self):
        failed = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.FAILED,
            error_message="Generation failed",
        )
        second = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.FAILED,
            error_message="Stopped",
        )
        ready = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        other = VideoProject.objects.create(
            owner=self.other,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.FAILED,
        )
        self.auth(self.owner_token)
        response = self.client.delete("/api/ai/videos/failed/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted"], 2)
        self.assertFalse(VideoProject.objects.filter(pk__in=[failed.pk, second.pk]).exists())
        self.assertTrue(VideoProject.objects.filter(pk=ready.pk).exists())
        self.assertTrue(VideoProject.objects.filter(pk=other.pk).exists())

    def test_stale_video_status_is_failed(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.GENERATING_VIDEO,
            progress=64,
            stage_label="Creating video",
        )
        VideoProject.objects.filter(pk=project.pk).update(
            updated_at=timezone.now() - timedelta(minutes=21)
        )
        self.auth(self.owner_token)
        response = self.client.get(f"/api/ai/video/{project.id}/status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], VideoProjectStatus.FAILED)
        self.assertIn("stalled", response.json()["error_message"])

    def test_stale_video_with_preview_stays_in_library(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.GENERATING_VIDEO,
            progress=88,
            stage_label="Adding captions",
        )
        project.preview_video.save("preview.mp4", ContentFile(b"0000"), save=True)
        VideoProject.objects.filter(pk=project.pk).update(
            updated_at=timezone.now() - timedelta(minutes=21)
        )
        self.auth(self.owner_token)
        status = self.client.get(f"/api/ai/video/{project.id}/status/")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], VideoProjectStatus.READY_FOR_REVIEW)
        self.assertTrue(status.json().get("preview_url"))
        listing = self.client.get("/api/ai/videos/")
        self.assertEqual(listing.status_code, 200)
        row = next(item for item in listing.json() if item["id"] == project.id)
        self.assertEqual(row["status"], VideoProjectStatus.READY_FOR_REVIEW)
        self.assertTrue(row.get("preview_url"))

    def test_video_library_includes_other_companies_for_the_same_owner(self):
        other_brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Other Company",
        )
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        self.auth(self.owner_token)
        listing = self.client.get("/api/ai/videos/", HTTP_X_ACTING_BRAND=str(other_brand.id))
        self.assertEqual(listing.status_code, 200)
        self.assertIn(project.id, [item["id"] for item in listing.json()])

    def test_video_library_list_is_lightweight(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
            script={"title": "Do not send this on the library list"},
            creative_brief={"objective": "hidden"},
        )
        self.auth(self.owner_token)
        listing = self.client.get("/api/ai/videos/")
        self.assertEqual(listing.status_code, 200)
        row = next(item for item in listing.json() if item["id"] == project.id)
        self.assertEqual(row["product_name"], self.product.name)
        self.assertNotIn("script", row)
        self.assertNotIn("scenes", row)
        self.assertNotIn("creative_brief", row)
        self.assertNotIn("qa_results", row)
        self.assertIn("poster_url", row)

    def test_first_screen_poster_uses_gemini_then_saves(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        project.preview_video.save("preview.mp4", ContentFile(b"0000"), save=True)

        def fake_frame(source, dest):
            dest.write_bytes(b"frame-bytes")
            return dest

        with (
            patch("ai.services.poster.extract_first_frame", side_effect=fake_frame),
            patch("ai.services.poster._gemini_poster", return_value=b"gemini-poster"),
        ):
            from ai.services.poster import save_video_poster

            self.assertTrue(save_video_poster(project, enhance=True, force=True))
        project.refresh_from_db()
        self.assertTrue(project.poster)
        self.assertGreater(project.poster.size, 0)

    def test_async_generating_status(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.GENERATING,
            progress=48,
            stage_label="Creating video",
        )
        self.auth(self.owner_token)
        response = self.client.get(f"/api/ai/video/{project.id}/status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "generating")
        self.auth(self.other_token)
        denied = self.client.get(f"/api/ai/video/{project.id}/status/")
        self.assertEqual(denied.status_code, 404)

    def test_qa(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            script=SCRIPT,
            narration={"lines": [{"text": "Cuba serum ini. Harga 39.90."}]},
            captions={"lines": [{"text": "RM39.90", "duration": 5}]},
        )
        scene = Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="Product",
            narration="Cuba serum ini. Harga 39.90.",
            caption="RM39.90",
            duration=5,
        )
        scene.image.save("scene.png", _png(), save=True)
        self.auth(self.owner_token)
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            return_value={
                "status": "passed",
                "summary": "Looks good",
                "checks": [
                    {"name": "pronunciation", "status": "passed", "detail": "Clear"},
                ],
                "unsupported_claims": [],
                "pronunciation": [],
            },
        ):
            with patch("ai.director_views.enqueue_video_generation") as enqueue:
                with patch("ai.views.enqueue_video_generation") as enqueue_legacy:
                    response = self.client.post(f"/api/ai/video/{project.id}/qa/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()["status"], {"passed", "warning", "failed"})
        project.refresh_from_db()
        self.assertTrue(project.qa_results)
        self.assertTrue(project.qa_status)
        enqueue.assert_not_called()
        enqueue_legacy.assert_not_called()

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_corrections(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            script=SCRIPT,
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-3",
            order=3,
            visual="Old",
            narration="Old",
            caption="Old",
            duration=4,
        )
        self.auth(self.owner_token)
        parsed = {
            "intent": "update_price",
            "instruction": "Change price to RM39.90",
            "fields": {"price": "39.90"},
            "scene_key": "scene-3",
            "regenerate": ["product_snapshot", "script", "scene"],
        }
        with (
            patch("ai.providers.intelligence.IntelligenceClient.generate_json", return_value=parsed),
            patch("ai.views.enqueue_video_correction") as enqueue,
        ):
            response = self.client.post(
                f"/api/ai/video/{project.id}/correct/",
                {"instruction": "Change price to RM39.90"},
            )
        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.product_snapshot["price"], "39.90")
        self.assertEqual(project.status, VideoProjectStatus.CORRECTING)
        enqueue.assert_called_once()

    @override_settings(GEMINI_API_KEY="test-key", GOOGLE_API_KEY="test-key")
    def test_regenerate_uses_amendment_and_product_photos(self):
        ProductImage.objects.create(product=self.product, image=_png())
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
            merchant_instructions="Keep it short.",
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="Show the bottle",
            narration="Hello",
            caption="Hello",
            duration=4,
        )
        self.auth(self.owner_token)
        with patch("ai.views.enqueue_video_correction") as enqueue:
            response = self.client.post(
                f"/api/ai/video/{project.id}/regenerate/",
                {"instruction": "Make the opening more festive."},
            )
        self.assertEqual(response.status_code, 202)
        project.refresh_from_db()
        self.assertEqual(project.status, VideoProjectStatus.CORRECTING)
        self.assertIn("festive", project.merchant_instructions)
        self.assertTrue(project.product_snapshot.get("product_images"))
        enqueue.assert_called_once()
        parsed = enqueue.call_args.args[1]
        self.assertIn("video", parsed["regenerate"])
        self.assertTrue(project.scenes.first().metadata.get("needs_regeneration"))

    @override_settings(GEMINI_API_KEY="test-key", GOOGLE_API_KEY="test-key")
    def test_regenerate_requires_product_photo(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="x",
            narration="x",
            caption="x",
            duration=4,
        )
        self.auth(self.owner_token)
        response = self.client.post(
            f"/api/ai/video/{project.id}/regenerate/",
            {"instruction": "Try again."},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("photo", response.json()["detail"].lower())

    def test_omni_uses_product_photo_not_generated_still(self):
        from ai.services.video import VideoGenerationService

        ProductImage.objects.create(product=self.product, image=_png())
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.GENERATING_VIDEO,
        )
        scene = Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="Show the bottle",
            narration="Hello",
            caption="Hello",
            duration=4,
        )
        scene.image.save("still.png", ContentFile(b"\x89PNG\r\n\x1a\n" + b"1" * 32), save=True)
        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda n: n
        omni.start.return_value = {"id": "t1"}
        omni.poll.return_value = {"id": "t1"}
        omni.save_video.side_effect = lambda task, dest: dest.write_bytes(b"mp4")
        VideoGenerationService(omni=omni)._create_videos(project)
        used = omni.start.call_args.kwargs["image_path"]
        self.assertTrue(used)
        self.assertNotEqual(used, scene.image.path)
        self.assertTrue(omni.start.call_args.kwargs["image_paths"])
        self.assertIsNone(omni.start.call_args.kwargs["video_path"])

    def test_gemini_missing_key_helper(self):
        with override_settings(GOOGLE_API_KEY="", GEMINI_API_KEY=""):
            with self.assertRaises(MissingAPIKeyError):
                require_google_api_key()

    def test_speech_missing_credentials(self):
        with override_settings(GOOGLE_APPLICATION_CREDENTIALS="", GOOGLE_CLOUD_PROJECT=""):
            with self.assertRaises(MissingAPIKeyError):
                require_speech_credentials()

    def test_qa_service_flags_prohibited_claim(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            script={"full_script": "This serum cures acne for RM39.90"},
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="x",
            narration="This serum cures acne for RM39.90",
            caption="cures acne",
            duration=4,
        )
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            side_effect=GoogleProviderError("skip"),
        ):
            result = QAService().run(project)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(check["name"] == "claims" and check["status"] == "failed" for check in result["checks"]))
        self.assertIn("not guaranteed", result["disclaimer"])

    def test_product_validation(self):
        snapshot = {"name": "Serum", "description": "", "price": "39.90"}
        self.assertIn("description", missing_product_fields(snapshot))
        self.assertTrue(offer_is_expired({"offer_expiry": "2020-01-01"}, today=date(2026, 8, 31)))
        self.assertFalse(offer_is_expired({"offer_expiry": "2028-01-01"}, today=date(2026, 8, 31)))

    def test_qa_expired_offer(self):
        snapshot = product_snapshot(self.product)
        snapshot["offer"] = "RM29"
        snapshot["offer_expiry"] = "2020-01-01"
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=snapshot,
            script=SCRIPT,
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="x",
            narration="Cuba serum ini. Harga 39.90.",
            caption="RM39.90",
            duration=4,
        )
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            side_effect=GoogleProviderError("skip"),
        ):
            result = QAService().run(project)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(check["name"] == "expired_offer" for check in result["checks"]))

    @override_settings(GOOGLE_API_KEY="", GEMINI_API_KEY="")
    def test_omni_missing_key(self):
        self.auth(self.owner_token)
        response = self.client.post(
            "/api/ai/video/generate/",
            {"product_id": self.product.id},
        )
        self.assertEqual(response.status_code, 503)

    def test_kalodata_without_key(self):
        from ai.services.intelligence import KalodataService

        data = KalodataService().insights(category="Beauty", product_name="Serum")
        self.assertFalse(data["available"])

    def test_social_publish_requires_authorization(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.APPROVED,
        )
        self.auth(self.owner_token)
        denied = self.client.post(
            f"/api/ai/video/{project.id}/publish/",
            {"platform": "tiktok"},
        )
        self.assertEqual(denied.status_code, 400)
        allowed = self.client.post(
            f"/api/ai/video/{project.id}/publish/",
            {"platform": "tiktok", "authorized": True},
        )
        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(allowed.json()["status"], "authorized")

    def test_usage_is_owner_scoped(self):
        from ai.models import UsageRecord

        UsageRecord.objects.create(
            owner=self.owner,
            provider="seedance",
            operation="video_scene",
            status="succeeded",
        )
        self.auth(self.other_token)
        response = self.client.get("/api/ai/usage/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)

    def test_approve_and_export_without_video(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY,
        )
        self.auth(self.owner_token)
        approve = self.client.post(f"/api/ai/video/{project.id}/approve/")
        self.assertEqual(approve.status_code, 400)
        export = self.client.post(f"/api/ai/video/{project.id}/export/")
        self.assertEqual(export.status_code, 400)

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key")
    def test_generate_requires_product_photo(self):
        self.auth(self.owner_token)
        response = self.client.post(
            "/api/ai/video/generate/",
            {"product_id": self.product.id},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("photo", response.json()["detail"])

    def test_snapshot_parses_json_list_fields(self):
        snapshot = product_snapshot(
            self.product,
            {"variants": '["30ml","50ml"]', "approved_claims": "[]"},
        )
        self.assertEqual(snapshot["variants"], ["30ml", "50ml"])
        self.assertEqual(snapshot["approved_claims"], [])

    def test_qa_flags_seedance_fallback(self):
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            script=SCRIPT,
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="x",
            narration="Cuba serum ini. Harga 39.90.",
            caption="RM39.90",
            duration=4,
            metadata={"seedance_fallback": True},
        )
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            side_effect=GoogleProviderError("skip"),
        ):
            result = QAService().run(project)
        self.assertTrue(
            any(check["name"] == "video_generation" and check["status"] == "failed" for check in result["checks"])
        )

    def test_cancel_stops_generating_video_and_batch(self):
        batch_id = "studio-batch-stop-1"
        primary = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.GENERATING_VIDEO,
            creative_brief={"pipeline": "studio", "bulk_batch_id": batch_id, "bulk_source_project_id": 1},
            stage_label="Creating scenes",
        )
        sibling = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.QUEUED,
            creative_brief={"pipeline": "studio", "bulk_batch_id": batch_id, "bulk_source_project_id": primary.pk},
        )
        Scene.objects.create(
            project=primary,
            scene_key="scene-1",
            order=1,
            visual="x",
            narration="Hello",
            caption="Hello",
            duration=4,
            metadata={"status": "generating"},
            generation_status="running",
        )
        self.auth(self.owner_token)
        response = self.client.post(f"/api/ai/video/{primary.id}/cancel/", {"cancel_batch": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["project"]["status"], "failed")
        self.assertEqual(response.data["project"]["error_message"], "Stopped by you.")
        self.assertCountEqual(response.data["stopped_ids"], [primary.id, sibling.id])
        primary.refresh_from_db()
        sibling.refresh_from_db()
        self.assertTrue((primary.creative_brief or {}).get("cancel_requested"))
        self.assertEqual(sibling.status, VideoProjectStatus.FAILED)
        self.assertEqual(sibling.error_message, "Stopped by you.")
        scene = primary.scenes.get(scene_key="scene-1")
        self.assertEqual(scene.generation_status, "failed")
        self.assertEqual(scene.failure_code, "CANCELLED")
