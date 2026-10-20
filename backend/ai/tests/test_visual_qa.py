from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from ai.exceptions import GoogleProviderError
from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.services.amendments import AmendmentService
from ai.services.ffmpeg import FFmpegError, sample_frames, sample_plan
from ai.services.qa import QAService
from ai.services.snapshots import product_snapshot
from ai.services.visual_qa import (
    VisualQAService,
    generation_key,
    serious_visual_issues,
    transcription_similarity,
)
from brands.models import Brand, Category, Product, ProductImage


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 32


class FrameSamplingTest(SimpleTestCase):
    def test_short_scene_uses_fewer_frames(self):
        plan = sample_plan(2)
        self.assertEqual(len(plan), 2)

    def test_long_scene_uses_representative_frames(self):
        plan = sample_plan(12)
        self.assertGreaterEqual(len(plan), 5)

    def test_failed_extraction_returns_empty(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "clip.mp4"
            source.write_bytes(b"not-a-video")
            dest = Path(tmp) / "frames"
            with patch("ai.services.ffmpeg.probe_duration", return_value=8):
                with patch("ai.services.ffmpeg.run_ffmpeg", side_effect=FFmpegError("no")):
                    self.assertEqual(sample_frames(source, dest), [])


TEST_MEDIA = mkdtemp(prefix="visual-qa-")


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class VisualQAServiceTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Beauty", slug="beauty-visual")
        self.owner = User.objects.create_user(
            username="visualqa",
            email="visual@example.com",
            password="password123",
            name="Visual Owner",
            mobile="0123999000",
            location="KL",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Visual Brand",
            description="Skincare",
            location="KL",
        )
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            description="Daily hydrating serum",
            price="39.90",
            variants=["30ml"],
            approved_claims=["hydrating"],
            prohibited_claims=["cures acne"],
        )
        ProductImage.objects.create(
            product=self.product,
            image=SimpleUploadedFile("product.png", _png(), content_type="image/png"),
        )
        self.project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="conversational_bm",
        )

    def _scene(self, key="scene_4", clip_name=None, **meta):
        scene = Scene.objects.create(
            project=self.project,
            scene_key=key,
            order=int(key[-1]) if key[-1].isdigit() else 1,
            visual="Product close-up in a Penang apartment",
            narration="Cuba serum ini. Harga RM39.90.",
            caption="RM39.90",
            duration=6,
            metadata={
                "start_time": 24,
                "end_time": 30,
                "product_locked": True,
                "presenter_locked": True,
                "location": "Penang apartment",
                "shot_description": "product close-up",
                "presenter_action": "presenter loads ingredients",
                "seedance_task_id": f"task-{key}",
                **meta,
            },
        )
        scene.video_clip.save(clip_name or f"{key}.png", ContentFile(_png()), save=True)
        return scene

    def _service(self, visual=None, transcript="Cuba serum ini. Harga RM39.90."):
        gemini = MagicMock()
        gemini.generate_json.return_value = visual or {
            "product": {
                "checked": True,
                "match": True,
                "confidence": 0.92,
                "message": "Product matches the approved reference.",
            },
            "presenter": {
                "checked": True,
                "match": True,
                "confidence": 0.92,
                "message": "Presenter matches the reference.",
            },
            "scene": {
                "checked": True,
                "match": True,
                "confidence": 0.8,
                "message": "Scene matches the planned shot.",
            },
            "caption": {
                "checked": True,
                "visible": True,
                "clipped": False,
                "outside_safe_area": False,
                "overlaps_product": False,
                "contrast_ok": True,
                "confidence": 0.7,
                "message": "Caption is readable.",
            },
        }
        gemini.transcribe.return_value = transcript
        return VisualQAService(gemini)

    def test_matching_product(self):
        scene = self._scene()
        result = self._service().analyze_scene(self.project, scene)
        check = next(item for item in result["checks"] if item["name"] == "product_visual_consistency")
        self.assertEqual(check["status"], "passed")
        self.assertGreaterEqual(check["confidence"], 0.9)
        self.assertEqual(check["source"], "multimodal")

    def test_obvious_product_mismatch(self):
        scene = self._scene()
        visual = {
            "product": {
                "checked": True,
                "match": False,
                "confidence": 0.91,
                "message": "Generated product appears visually different from the approved reference.",
                "timestamp": 2,
            }
        }
        result = self._service(visual=visual).analyze_scene(self.project, scene)
        check = next(item for item in result["checks"] if item["name"] == "product_visual_consistency")
        self.assertEqual(check["status"], "failed")
        self.assertEqual(check["severity"], "high")
        self.assertGreaterEqual(check["confidence"], 0.85)
        self.assertIn("approved product", check["recommended_action"].lower())

    def test_missing_product_reference(self):
        self.project.product_snapshot = {"name": "Serum", "product_images": []}
        self.project.save()
        ProductImage.objects.all().delete()
        scene = self._scene()
        result = self._service().analyze_scene(self.project, scene)
        self.assertFalse(any(item["name"] == "product_visual_consistency" for item in result["checks"]))

    def test_low_confidence_does_not_fail(self):
        scene = self._scene()
        visual = {
            "product": {
                "checked": True,
                "match": False,
                "confidence": 0.4,
                "message": "Possible colour difference.",
            }
        }
        result = self._service(visual=visual).analyze_scene(self.project, scene)
        check = next(item for item in result["checks"] if item["name"] == "product_visual_consistency")
        self.assertEqual(check["status"], "warning")
        self.assertLess(check["confidence"], 0.6)

    def test_presenter_match(self):
        scene = self._scene()
        with TemporaryDirectory() as tmp:
            photo = Path(tmp) / "presenter.png"
            photo.write_bytes(_png())
            scene.metadata["presenter_reference"] = str(photo)
            scene.save()
            result = self._service().analyze_scene(self.project, scene)
        check = next(item for item in result["checks"] if item["name"] == "presenter_visual_consistency")
        self.assertEqual(check["status"], "passed")

    def test_presenter_mismatch(self):
        scene = self._scene()
        visual = {
            "presenter": {
                "checked": True,
                "match": False,
                "confidence": 0.9,
                "message": "A different presenter appears in this scene.",
            }
        }
        with TemporaryDirectory() as tmp:
            photo = Path(tmp) / "presenter.png"
            photo.write_bytes(_png())
            scene.metadata["presenter_reference"] = str(photo)
            scene.save()
            result = self._service(visual=visual).analyze_scene(self.project, scene)
        check = next(item for item in result["checks"] if item["name"] == "presenter_visual_consistency")
        self.assertIn(check["status"], {"failed", "warning"})
        self.assertGreaterEqual(check["confidence"], 0.85)

    def test_presenter_no_reference(self):
        scene = self._scene(presenter_locked=False)
        visual = {"presenter": {"checked": False, "match": True, "confidence": 0}}
        result = self._service(visual=visual).analyze_scene(self.project, scene)
        self.assertFalse(
            any(item["name"] == "presenter_visual_consistency" for item in result["checks"])
        )

    def test_caption_present(self):
        scene = self._scene()
        result = self._service().analyze_scene(self.project, scene)
        check = next(item for item in result["checks"] if item["name"] == "caption_visual")
        self.assertEqual(check["status"], "passed")
        self.assertEqual(check["source"], "multimodal")

    def test_caption_missing(self):
        scene = self._scene()
        visual = {
            "caption": {
                "checked": True,
                "visible": False,
                "confidence": 0.8,
                "message": "Caption does not appear to be visible.",
            }
        }
        result = self._service(visual=visual).analyze_scene(self.project, scene)
        check = next(item for item in result["checks"] if item["name"] == "caption_visual")
        self.assertEqual(check["status"], "warning")

    def test_caption_unavailable_is_not_faked(self):
        scene = self._scene()
        visual = {"caption": {"checked": False, "unavailable": True, "confidence": 0}}
        result = self._service(visual=visual).analyze_scene(self.project, scene)
        self.assertFalse(any(item["name"] == "caption_visual" for item in result["checks"]))

    def test_audio_matching_transcription(self):
        scene = self._scene(clip_name="scene.mp4")
        with TemporaryDirectory() as tmp:
            frame = Path(tmp) / "frame.png"
            frame.write_bytes(_png())
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"audio")
            with patch.object(VisualQAService, "_collect_frames", return_value=[(0.05, frame)]):
                with patch("ai.services.visual_qa.extract_audio", return_value=audio):
                    result = self._service().analyze_scene(self.project, scene)
        check = next(item for item in result["checks"] if item["name"] == "voiceover_mismatch")
        self.assertEqual(check["status"], "passed")
        self.assertEqual(check["source"], "transcription")

    def test_audio_mismatch(self):
        scene = self._scene(clip_name="scene.mp4", script_locked=True)
        with TemporaryDirectory() as tmp:
            frame = Path(tmp) / "frame.png"
            frame.write_bytes(_png())
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"audio")
            with patch.object(VisualQAService, "_collect_frames", return_value=[(0.05, frame)]):
                with patch("ai.services.visual_qa.extract_audio", return_value=audio):
                    result = self._service(
                        transcript="Hello this is a totally different script"
                    ).analyze_scene(self.project, scene)
        check = next(item for item in result["checks"] if item["name"] == "voiceover_mismatch")
        self.assertEqual(check["status"], "failed")
        self.assertEqual(check["source"], "transcription")

    def test_transcription_unavailable_is_not_faked(self):
        scene = self._scene(clip_name="scene.mp4")
        service = self._service()
        service.gemini.transcribe.side_effect = GoogleProviderError("no speech")
        with TemporaryDirectory() as tmp:
            frame = Path(tmp) / "frame.png"
            frame.write_bytes(_png())
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"audio")
            with patch.object(VisualQAService, "_collect_frames", return_value=[(0.05, frame)]):
                with patch("ai.services.visual_qa.extract_audio", return_value=audio):
                    with patch("ai.services.visual_qa.speech_configured", return_value=False):
                        result = service.analyze_scene(self.project, scene)
        self.assertFalse(any(item["name"] == "voiceover_mismatch" for item in result["checks"]))
        self.assertFalse(any(item["source"] == "transcription" for item in result["checks"]))

    def test_cache_reuses_unchanged_scene(self):
        scene = self._scene()
        service = self._service()
        first = service.analyze_scene(self.project, scene)
        self.assertEqual(service.gemini.generate_json.call_count, 1)
        second = service.analyze_project(self.project, scenes=[scene])
        self.assertEqual(service.gemini.generate_json.call_count, 1)
        self.assertEqual(len(second), len(first["checks"]))
        service.analyze_project(self.project, scenes=[scene], force=True)
        self.assertEqual(service.gemini.generate_json.call_count, 2)

    def test_only_regenerated_scene_is_reanalyzed(self):
        one = self._scene("scene_1")
        two = self._scene("scene_2")
        service = self._service()
        service.analyze_project(self.project, scenes=[one, two])
        self.assertEqual(service.gemini.generate_json.call_count, 2)
        two.metadata["seedance_task_id"] = "task-scene_2-new"
        two.metadata["needs_regeneration"] = False
        two.save()
        service.analyze_project(self.project, scenes=[one, two])
        self.assertEqual(service.gemini.generate_json.call_count, 3)
        one.refresh_from_db()
        self.assertEqual(one.metadata["visual_qa"]["generation_id"], generation_key(one))

    def test_amendment_targets_only_the_affected_scene(self):
        scene = self._scene()
        Scene.objects.create(
            project=self.project,
            scene_key="scene_5",
            order=5,
            visual="Ending",
            narration="Shop now",
            caption="Shop",
            duration=4,
        )
        self.project.qa_results = {
            "checks": [
                {
                    "name": "product_visual_consistency",
                    "status": "failed",
                    "detail": "Generated product appears visually different from the approved reference.",
                    "recommended_action": (
                        "Regenerate Scene 4 using the approved product reference. "
                        "Keep the current script, presenter, location and caption locked."
                    ),
                    "source": "multimodal",
                    "severity": "high",
                    "confidence": 0.91,
                    "affected_scenes": ["scene_4"],
                    "scene_id": "scene_4",
                    "start": 24,
                    "end": 30,
                }
            ]
        }
        self.project.save()
        recs = AmendmentService().recommend(self.project)
        self.assertEqual(recs[0]["affected_scenes"], ["scene_4"])
        self.assertIn("approved product reference", recs[0]["suggested_amendment"].lower())
        AmendmentService().apply(self.project, [recs[0]["id"]])
        scene.refresh_from_db()
        other = self.project.scenes.get(scene_key="scene_5")
        self.assertTrue((scene.metadata or {}).get("needs_regeneration"))
        self.assertTrue((scene.metadata or {}).get("product_locked"))
        self.assertFalse((other.metadata or {}).get("needs_regeneration"))
        self.assertEqual(scene.narration, "Cuba serum ini. Harga RM39.90.")

    def test_structural_qa_survives_visual_skip(self):
        scene = Scene.objects.create(
            project=self.project,
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
            result = QAService().run(self.project)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(item["name"] == "claims" and item["status"] == "failed" for item in result["checks"]))
        self.assertTrue(result.get("layers"))
        self.assertEqual(result["layers"]["product"]["visual"]["status"], "not_checked")
        scene.refresh_from_db()
        self.assertTrue((scene.metadata or {}).get("visual_qa"))

    def test_incomplete_language_and_product_visual_are_honest(self):
        Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            order=1,
            visual="Product shot",
            narration="Cuba serum ini. Harga RM39.90",
            caption="RM39.90",
            duration=5,
        )
        self.project.preview_video.save("preview.mp4", ContentFile(b"0000"), save=True)
        with patch(
            "ai.providers.intelligence.IntelligenceClient.generate_json",
            side_effect=GoogleProviderError("skip"),
        ):
            result = QAService().run(self.project)
        language = next(item for item in result["checks"] if item["name"] == "ai_review")
        product_visual = next(
            item for item in result["checks"] if item["name"] == "product_visual_consistency"
        )
        self.assertEqual(language["status"], "warning")
        self.assertIn("unavailable", language["detail"].lower())
        self.assertEqual(product_visual["status"], "not_checked")
        self.assertIsNone(product_visual.get("confidence"))
        self.assertFalse(product_visual.get("checked"))
        self.assertTrue(
            any(item["name"] == "product_visual_consistency" for item in result["release_blocking"])
        )
        recs = AmendmentService().recommend(self.project)
        self.assertFalse(
            any(item.get("issue") == "product_visual_consistency" for item in recs)
        )


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class VisualQAApprovalTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Beauty", slug="beauty-approve")
        self.owner = User.objects.create_user(
            username="visualapprove",
            email="approve@example.com",
            password="password123",
            name="Approve Owner",
            mobile="0123999001",
            location="KL",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Approve Brand",
            description="Skincare",
            location="KL",
        )
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            description="Daily hydrating serum",
            price="39.90",
        )
        self.token = Token.objects.create(user=self.owner)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            status=VideoProjectStatus.READY_FOR_REVIEW,
            qa_results={
                "checks": [
                    {
                        "name": "product_visual_consistency",
                        "status": "failed",
                        "detail": "Generated product appears visually different from the approved reference.",
                        "source": "multimodal",
                        "confidence": 0.91,
                        "severity": "high",
                        "scene_id": "scene_4",
                    }
                ]
            },
        )
        self.project.preview_video.save("preview.mp4", ContentFile(b"0000"), save=True)

    def test_high_confidence_product_issue_blocks_approval(self):
        denied = self.client.post(f"/api/ai/video/{self.project.id}/approve/")
        self.assertEqual(denied.status_code, 400)
        self.assertTrue(denied.json().get("blocked"))
        self.assertFalse(denied.json().get("requires_confirm"))
        still = self.client.post(
            f"/api/ai/video/{self.project.id}/approve/",
            {"confirm": True},
            format="json",
        )
        self.assertEqual(still.status_code, 400)
        self.assertTrue(still.json().get("blocked"))

    def test_low_confidence_warning_does_not_block(self):
        self.project.qa_results = {
            "checks": [
                {
                    "name": "product_visual_consistency",
                    "status": "warning",
                    "detail": "Possible colour difference.",
                    "source": "multimodal",
                    "confidence": 0.4,
                    "severity": "low",
                }
            ]
        }
        self.project.save()
        self.assertFalse(serious_visual_issues(self.project.qa_results["checks"]))
        allowed = self.client.post(f"/api/ai/video/{self.project.id}/approve/")
        self.assertEqual(allowed.status_code, 200)


class TranscriptionHelperTest(SimpleTestCase):
    def test_similarity(self):
        self.assertGreater(
            transcription_similarity("Cuba serum ini. Harga RM39.90.", "Cuba serum ini harga 39.90"),
            0.45,
        )
        self.assertLess(transcription_similarity("Buy this serum now", "hello world"), 0.2)
