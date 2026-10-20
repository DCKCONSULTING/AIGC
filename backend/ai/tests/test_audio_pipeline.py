from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from ai.exceptions import ProviderError
from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.services.captions import wrap_caption
from ai.services.compiler import compile_scene_prompt, distinctive_features
from ai.services.director import DirectorService, commercial_cta, is_studio_project, normalize_brief
from ai.services.ffmpeg import (
    assemble_project,
    clip_is_assembly_ready,
    inspect_audio,
    normalize_clip,
    prepare_scene_clip,
    run_ffmpeg,
)
from ai.services.script import ScriptService
from ai.services.qa import QAService, release_blocking_issues
from ai.services.snapshots import product_snapshot
from ai.services.video import VideoGenerationService
from brands.models import Brand, Category, Product, ProductImage


def _fill_storyboard(project):
    from ai.services.durations import scene_count_for_duration

    count = scene_count_for_duration(project.duration_seconds)
    each = round(project.duration_seconds / count, 2)
    for index in range(count):
        Scene.objects.create(
            project=project,
            scene_key=f"scene-{index + 1}",
            order=index + 1,
            visual="Hero mug from the supplied product photo.",
            narration="Rutin kopi pagi.",
            caption="Clay Mug",
            duration=each if index < count - 1 else round(project.duration_seconds - each * (count - 1), 2),
        )


def _png():
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("mug.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, content_type="image/png")


def _write_clip(path: Path, *, silent: bool, duration: float = 1.0) -> Path:
    audio = (
        ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        if silent
        else ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"]
    )
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=1080x1920:d={duration}:r=30",
            *audio,
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-shortest",
            str(path),
        ]
    )
    return path


TEST_MEDIA = mkdtemp(prefix="studio-audio-")


@override_settings(MEDIA_ROOT=TEST_MEDIA, VIDEO_PROVIDER="omni")
class AudioPipelineTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Home", slug="home-audio")
        self.owner = User.objects.create_user(
            username="audiomerchant",
            email="audio@example.com",
            password="password123",
            name="Audio Owner",
            mobile="0123000111",
            location="KL",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Clay Co",
            description="Stoneware",
            location="KL",
        )
        self.product = Product.objects.create(
            brand=self.brand,
            name="Clay Mug",
            description=(
                "Seramik stoneware buatan tangan, dengan bibir berglaz coklat dan badan krim. "
                "Pemegang bulat, selesa di tangan."
            ),
            price="59.00",
            materials="stoneware",
        )
        ProductImage.objects.create(product=self.product, image=_png())
        self.project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="conversational_bm",
            selected_concept_id="mug-concept",
            creative_brief=normalize_brief(
                {
                    "objective": "buy",
                    "customer": "Peminat kopi pagi",
                    "main_benefit": "Rutin kopi pagi, lebih istimewa.",
                    "offer_price": "59.00",
                    "cta": "Dapatkan Clay Mug hari ini",
                    "must_remain_exact": ["product_appearance"],
                    "duration": 30,
                },
                None,
            ),
            duration_seconds=30,
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        self.project.creative_brief = normalize_brief(self.project.creative_brief, self.project)
        self.project.save()

    def test_studio_uses_seedance_audio_not_tts(self):
        self.assertTrue(is_studio_project(self.project))
        speech = MagicMock()
        service = VideoGenerationService(speech=speech)
        service._create_voice(self.project)
        speech.synthesize.assert_not_called()
        self.assertFalse(self.project.narration_audio)

    def test_seedance_called_with_audio_and_product_photo(self):
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            order=1,
            visual="Hero mug",
            narration="Rutin kopi pagi, lebih istimewa.",
            caption="Clay Mug",
            duration=4,
        )
        scene.image.save("still.png", ContentFile(b"\x89PNG\r\n\x1a\n" + b"1" * 32), save=True)
        seedance = MagicMock()
        seedance.family.return_value = "2.0"
        seedance.clamp_duration.side_effect = lambda n: n
        seedance.start.return_value = {"id": "task-audio"}
        seedance.poll.return_value = {"id": "task-audio"}

        def _save(task, dest):
            _write_clip(Path(dest), silent=False)

        seedance.save_video.side_effect = _save
        VideoGenerationService(seedance=seedance)._create_videos(self.project)
        kwargs = seedance.start.call_args.kwargs
        self.assertTrue(kwargs["generate_audio"])
        self.assertNotEqual(kwargs["image_path"], scene.image.path)
        self.assertTrue(Path(kwargs["image_path"]).exists())

    def test_studio_auth_error_does_not_create_silent_fallback(self):
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            order=1,
            visual="Hero mug",
            narration="Rutin kopi pagi, lebih istimewa.",
            caption="Clay Mug",
            duration=4,
        )
        seedance = MagicMock()
        seedance.family.return_value = "1.x"
        seedance.clamp_duration.side_effect = lambda n: max(n, 4)
        seedance.start.side_effect = ProviderError(
            "The video service could not authorize this request.",
            retryable=False,
        )
        with self.assertRaises(ProviderError) as ctx:
            VideoGenerationService(seedance=seedance)._create_videos(self.project)
        self.assertIn("authorize", str(ctx.exception).lower())
        scene.refresh_from_db()
        self.assertFalse(scene.video_clip)
        self.assertEqual((scene.metadata or {}).get("status"), "failed")
        self.assertFalse((scene.metadata or {}).get("seedance_fallback"))

    def test_missing_clip_file_is_regenerated(self):
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            order=1,
            visual="Hero mug",
            narration="Rutin kopi pagi, lebih istimewa.",
            caption="Clay Mug",
            duration=4,
            metadata={"status": "generated"},
        )
        scene.video_clip.name = "ai/scenes/clips/2026/09/gone.mp4"
        scene.save(update_fields=["video_clip", "metadata"])
        seedance = MagicMock()
        seedance.family.return_value = "2.0"
        seedance.clamp_duration.side_effect = lambda n: n
        seedance.start.return_value = {"id": "task-retry"}
        seedance.poll.return_value = {"id": "task-retry"}

        def _save(task, dest):
            _write_clip(Path(dest), silent=False)

        seedance.save_video.side_effect = _save
        VideoGenerationService(seedance=seedance)._create_videos(self.project)
        seedance.start.assert_called_once()
        scene.refresh_from_db()
        self.assertTrue(scene.video_clip)
        self.assertTrue(Path(scene.video_clip.path).exists())

    def test_silent_audio_is_detected_and_blocks_qa(self):
        with TemporaryDirectory() as tmp:
            silent = _write_clip(Path(tmp) / "silent.mp4", silent=True)
            loud = _write_clip(Path(tmp) / "loud.mp4", silent=False)
            silent_report = inspect_audio(silent)
            loud_report = inspect_audio(loud)
        self.assertTrue(silent_report["has_audio"])
        self.assertTrue(silent_report["silent"] or not silent_report["audible"])
        self.assertLessEqual(silent_report.get("mean_volume") or -90, -80)
        self.assertTrue(loud_report["audible"])
        self.assertGreater(loud_report.get("mean_volume") or -90, -80)

        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            order=1,
            visual="Hook",
            narration="Rutin kopi pagi, lebih istimewa.",
            caption="Clay Mug · RM59 · Dapatkan hari ini",
            duration=4,
        )
        with TemporaryDirectory() as tmp:
            silent_clip = _write_clip(Path(tmp) / "silent.mp4", silent=True)
            scene.video_clip.save("silent.mp4", ContentFile(silent_clip.read_bytes()), save=True)
            self.project.preview_video.save("preview.mp4", ContentFile(silent_clip.read_bytes()), save=True)
        with patch("ai.providers.intelligence.IntelligenceClient.generate_json", return_value={"status": "warning", "summary": "x", "checks": []}):
            with patch("ai.services.visual_qa.VisualQAService.analyze_project", return_value=[]):
                result = QAService().run(self.project)
        self.assertTrue(
            any(item["name"] in {"audio_silent", "assembled_audio"} and item["status"] == "failed" for item in result["checks"])
        )
        blocked = release_blocking_issues(result["checks"], has_preview=True)
        self.assertTrue(blocked)
        self.assertIn("silent", (blocked[0].get("reason") or blocked[0].get("detail") or "").lower())

    def test_normalize_preserves_audible_audio(self):
        with TemporaryDirectory() as tmp:
            source = _write_clip(Path(tmp) / "src.mp4", silent=False)
            dest = Path(tmp) / "norm.mp4"
            normalize_clip(source, dest)
            report = inspect_audio(dest)
            self.assertTrue(report["has_audio"])
            self.assertTrue(report["audible"])
            assembled = Path(tmp) / "out.mp4"
            assemble_project(
                [source],
                None,
                [{"text": "Clay Mug\nRM59 · Dapatkan hari ini", "duration": 1, "placement": "bottom"}],
                assembled,
                mix_external_audio=False,
            )
            final = inspect_audio(assembled)
            self.assertTrue(final["has_video"])
            self.assertTrue(final["has_audio"])
            self.assertTrue(final["audible"])

    def test_prepare_scene_clip_burns_caption_during_generation(self):
        with TemporaryDirectory() as tmp:
            source = _write_clip(Path(tmp) / "src.mp4", silent=False)
            dest = Path(tmp) / "captioned.mp4"
            prepare_scene_clip(source, dest, caption="Clay Mug · RM59", duration=1, placement="bottom")
            report = inspect_audio(dest)
            self.assertTrue(report["has_audio"])
            self.assertTrue(report["audible"])
            self.assertTrue(clip_is_assembly_ready(dest))

    def test_assemble_copy_joins_already_captioned_clips(self):
        with TemporaryDirectory() as tmp:
            first = prepare_scene_clip(
                _write_clip(Path(tmp) / "a.mp4", silent=False),
                Path(tmp) / "a-ready.mp4",
                caption="First scene",
                duration=1,
            )
            second = prepare_scene_clip(
                _write_clip(Path(tmp) / "b.mp4", silent=False),
                Path(tmp) / "b-ready.mp4",
                caption="Second scene",
                duration=1,
            )
            assembled = Path(tmp) / "out.mp4"
            assemble_project(
                [first, second],
                None,
                [{"text": "First scene", "duration": 1}, {"text": "Second scene", "duration": 1}],
                assembled,
                mix_external_audio=False,
                captions_already_burned=True,
            )
            final = inspect_audio(assembled)
            self.assertTrue(final["has_video"])
            self.assertTrue(final["has_audio"])
            self.assertTrue(final["audible"])

    def test_studio_run_skips_checking_the_video(self):
        _fill_storyboard(self.project)
        self.project.preview_video.save("preview.mp4", ContentFile(b"0000"), save=True)
        service = VideoGenerationService()
        quality = MagicMock()
        recommend = MagicMock()
        with patch("ai.services.preflight.preflight_project"), patch.object(
            service, "_refresh_snapshot"
        ), patch.object(service, "_analyze"), patch.object(service, "_plan"), patch(
            "ai.services.video.generate_continuous_film", return_value=True
        ), patch.object(service, "_create_voice"), patch.object(service, "_assemble"), patch.object(
            service, "_quality", quality
        ), patch.object(service, "_recommend", recommend):
            result = service.run(self.project.pk)
        result.refresh_from_db()
        self.assertEqual(result.status, VideoProjectStatus.READY_FOR_REVIEW)
        quality.assert_not_called()
        recommend.assert_not_called()

    def test_compiler_locks_mug_features_and_asks_for_audio(self):
        scene = Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            visual="Close-up of the rounded handle",
            narration="Pemegang bulat, selesa di tangan.",
            caption="Pemegang bulat, selesa di tangan.",
            duration=6,
            metadata={"product_locked": True, "scene_role": "product_detail"},
        )
        prompt = compile_scene_prompt(scene, self.project)
        self.assertIn("AUDIO", prompt)
        self.assertIn("original product photographs", prompt.lower())
        self.assertIn("handle", prompt.lower())
        features = distinctive_features(self.project.product_snapshot or {}, self.project.creative_brief or {})
        self.assertTrue(any("glaz" in item.lower() or "handle" in item.lower() or "pemegang" in item.lower() for item in features))

    def test_captions_wrap_without_cutting_words(self):
        spoken = "Seramik stoneware buatan tangan dengan bibir berglaz coklat dan badan krim untuk rutin pagi"
        text = wrap_caption(spoken)
        self.assertLessEqual(len([line for line in text.split("\n") if line.strip()]), 3)
        flat = text.replace("\n", " ")
        for word in spoken.split():
            self.assertIn(word, flat)
        self.assertNotIn("…", text)

    def test_cantonese_caption_wraps_without_losing_the_spoken_sentence(self):
        spoken = "呢個產品真係好用，而家買就得，我哋幫你搞掂成個流程。"
        text = wrap_caption(spoken)
        self.assertLessEqual(len([line for line in text.split("\n") if line.strip()]), 3)
        self.assertEqual(text.replace("\n", "").replace(" ", ""), spoken.replace(" ", ""))
        self.assertNotIn("…", text)

    def test_commercial_cta_omits_price_when_brief_removes_it(self):
        cta = commercial_cta(
            {
                "objective": "buy",
                "offer_price": "RM2599",
                "legacy_instructions": "Remove price and URL.",
            },
            {"name": "Coach CC", "product_link": "https://coachcc.my"},
            "english",
        )
        self.assertNotIn("2599", cta)
        self.assertNotIn("coachcc", cta.lower())

    def test_commercial_cta_does_not_invent_a_website(self):
        cta = commercial_cta(self.project.creative_brief, self.project.product_snapshot, "conversational_bm")
        self.assertIn("Clay Mug", cta)
        self.assertIn("59", cta)
        self.assertIn("Dapatkan", cta)
        self.assertNotIn("http", cta.lower())

    def test_single_scene_regeneration_does_not_call_tts(self):
        Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            order=1,
            visual="Hook",
            narration="Rutin kopi pagi, lebih istimewa.",
            caption="Rutin kopi pagi",
            duration=4,
            metadata={"needs_regeneration": True},
        )
        Scene.objects.create(
            project=self.project,
            scene_key="scene-2",
            order=2,
            visual="Hero",
            narration="Dapatkan Clay Mug hari ini.",
            caption="Clay Mug · RM59 · Dapatkan hari ini",
            duration=4,
        )
        seedance = MagicMock()
        seedance.family.return_value = "2.0"
        seedance.clamp_duration.side_effect = lambda n: n
        seedance.start.return_value = {"id": "only-one"}
        seedance.poll.return_value = {"id": "only-one"}
        seedance.save_video.side_effect = lambda task, dest: _write_clip(Path(dest), silent=False)
        speech = MagicMock()
        service = VideoGenerationService(seedance=seedance, speech=speech)
        with patch.object(service, "_assemble"), patch.object(service, "_quality"), patch.object(service, "_recommend"):
            service.regenerate_scenes(self.project.pk, list(self.project.scenes.values_list("pk", flat=True)))
        speech.synthesize.assert_not_called()
        self.assertEqual(seedance.start.call_count, 1)

    def test_approval_blocks_silent_audio(self):
        token = Token.objects.create(user=self.owner)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.project.preview_video.save("preview.mp4", ContentFile(b"0000"), save=True)
        self.project.qa_results = {
            "checks": [
                {
                    "name": "audio_silent",
                    "status": "failed",
                    "detail": "Audio: FAILED. Reason: Audio track is present but effectively silent. Stage: assembly.",
                    "reason": "Audio track is present but effectively silent",
                    "stage": "assembly",
                    "source": "ffmpeg",
                    "severity": "high",
                }
            ]
        }
        self.project.save()
        denied = client.post(f"/api/ai/video/{self.project.id}/approve/", {"confirm": True}, format="json")
        self.assertEqual(denied.status_code, 400)
        self.assertTrue(denied.json().get("blocked"))

    def test_preview_stays_in_library_when_qa_fails(self):
        _fill_storyboard(self.project)
        self.project.preview_video.save("preview.mp4", ContentFile(b"0000"), save=True)
        service = VideoGenerationService()
        with patch("ai.services.preflight.preflight_project"), patch.object(
            service, "_refresh_snapshot"
        ), patch.object(service, "_analyze"), patch.object(service, "_plan"), patch(
            "ai.services.video.generate_continuous_film", return_value=True
        ), patch.object(service, "_create_voice"), patch.object(service, "_assemble"), patch.object(
            service, "_quality", side_effect=RuntimeError("qa down")
        ), patch.object(service, "_recommend"):
            result = service.run(self.project.pk)
        result.refresh_from_db()
        self.assertEqual(result.status, VideoProjectStatus.READY_FOR_REVIEW)
        self.assertTrue(result.preview_video)

    def test_script_fallback_when_intelligence_is_down(self):
        self.project.merchant_instructions = (
            "Create a 60-second vertical TikTok video using only the two supplied "
            "Gurney Rose Tint product photos. Do not generate a presenter, hands, "
            "packaging, new product views, or unapproved claims."
        )
        self.project.product_snapshot["name"] = "Gurney Rose Tint"
        self.project.product_snapshot["price"] = "49"
        self.project.save()
        service = ScriptService()
        with patch.object(
            service.gemini,
            "generate_json",
            side_effect=ProviderError("The AI service could not complete this request.", retryable=True),
        ):
            brief = service.build_brief(self.project)
            self.project.creative_brief = brief
            script = service.generate_script(self.project)
            self.project.script = script
            shots = service.plan_shots(self.project)
        self.assertEqual(brief.get("duration"), 60)
        self.assertIn("presenter", (brief.get("must_not_show") or "").lower())
        self.assertGreaterEqual(len(script.get("scenes") or []), 4)
        self.assertFalse(any((item.get("title") or "") == "Presenter" for item in script["scenes"]))
        self.assertTrue(
            any("product photo" in (item.get("visual") or "").lower() for item in script["scenes"])
        )
        self.assertTrue(shots.get("shots"))

    def test_correction_continues_when_intelligence_is_down(self):
        Scene.objects.create(
            project=self.project,
            scene_key="scene-1",
            order=1,
            visual="Hook",
            narration="Rutin pagi.",
            caption="Clay Mug",
            duration=4,
        )
        seedance = MagicMock()
        seedance.family.return_value = "2.0"
        seedance.clamp_duration.side_effect = lambda n: n
        seedance.start.return_value = {"id": "corr-1"}
        seedance.poll.return_value = {"id": "corr-1"}
        seedance.save_video.side_effect = lambda task, dest: _write_clip(Path(dest), silent=False)
        service = VideoGenerationService(seedance=seedance, speech=MagicMock())
        parsed = {
            "intent": "other",
            "instruction": (
                "Create a 60-second vertical TikTok video using only the two supplied "
                "Gurney Rose Tint product photos. Do not generate a presenter, hands, "
                "packaging, new product views, or unapproved claims."
            ),
            "regenerate": ["brief", "script", "shot_plan", "scene", "video", "narration", "captions"],
        }
        with patch.object(
            service.script_service.gemini,
            "generate_json",
            side_effect=ProviderError("The AI service could not complete this request.", retryable=True),
        ), patch.object(service, "_assemble"), patch.object(service, "_quality"), patch.object(
            service, "_recommend"
        ):
            result = service.apply_correction(self.project, parsed)
        result.refresh_from_db()
        self.assertEqual(result.status, VideoProjectStatus.READY_FOR_REVIEW)
        self.assertEqual(result.duration_seconds, 60)
        self.assertGreaterEqual(result.scenes.count(), 4)
        self.assertGreaterEqual(seedance.start.call_count, 1)

    def test_generate_continues_when_product_analysis_is_down(self):
        _fill_storyboard(self.project)
        seedance = MagicMock()
        seedance.family.return_value = "2.0"
        seedance.clamp_duration.side_effect = lambda n: n
        seedance.start.return_value = {"id": "gen-1"}
        seedance.poll.return_value = {"id": "gen-1"}
        seedance.save_video.side_effect = lambda task, dest: _write_clip(Path(dest), silent=False)
        service = VideoGenerationService(seedance=seedance, speech=MagicMock())
        with patch("ai.services.preflight.preflight_project"), patch.object(
            service.product_service.gemini,
            "generate_json",
            side_effect=ProviderError("The AI service could not complete this request.", retryable=True),
        ), patch.object(service, "_assemble"), patch.object(service, "_quality"), patch.object(
            service, "_recommend"
        ):
            result = service.run(self.project.pk)
        result.refresh_from_db()
        self.assertEqual(result.status, VideoProjectStatus.READY_FOR_REVIEW)
        self.assertTrue(result.product_analysis)
        self.assertGreaterEqual(seedance.start.call_count, 1)


class DirectorCopyHelpersTest(TestCase):
    def test_normalize_assigns_scene_roles(self):
        from ai.services.director import DirectorService

        raw = [
            {
                "scene_key": "scene-1",
                "duration": 5,
                "shot_description": "Hook on a breakfast table",
                "voice_over": "Pagi ni rasa kosong.",
                "on_screen_caption": "Pagi kopi",
            },
            {
                "scene_key": "scene-2",
                "duration": 25,
                "shot_description": "Coffee poured into the exact mug",
                "voice_over": "Jadikan rutin kopi pagi lebih istimewa.",
                "on_screen_caption": "RM59",
            },
        ]
        scenes = DirectorService()._normalize_concept_scenes(
            raw, 30, "59.00", "", "59.00", {"name": "Clay Mug", "price": "59.00"}
        )
        self.assertEqual(scenes[0]["scene_role"], "hook")
        self.assertTrue(scenes[-1]["cta"])
        self.assertIn("Jadikan rutin kopi pagi", scenes[-1]["on_screen_caption"].replace("\n", " "))
        self.assertLessEqual(len(scenes[-1]["on_screen_caption"].split("\n")), 3)
