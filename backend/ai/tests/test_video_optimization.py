from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from accounts.models import User
from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.services.qa import release_blocking_issues
from ai.services.snapshots import product_snapshot
from ai.services.video import VideoGenerationService
from ai.tests.test_studio import _png
from brands.models import Brand, Category, Product, ProductImage


def _write_clip(dest, data: bytes = b"FAKEMP4"):
    from pathlib import Path

    Path(dest).write_bytes(data)


class SceneConcurrencyTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Kitchen", slug="kitchen-opt")
        self.owner = User.objects.create_user(
            username="opt-owner",
            email="opt@example.com",
            password="password123",
            name="Opt Owner",
            mobile="0123999999",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(
            owner=self.owner,
            category=self.category,
            name="Home Opt",
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

    def _project(self, scenes: int = 5) -> VideoProject:
        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            speaker_gender="female",
            selected_concept_id="opt-demo",
            duration_seconds=30,
            creative_brief={
                "schema_version": 2,
                "objective": "buy",
                "customer": "Busy parents",
                "main_benefit": "Crispy food with less oil",
                "cta": "Buy now",
                "currency": "MYR",
                "price": "199.00",
                "style": "product_demo",
            },
            status=VideoProjectStatus.DRAFT,
        )
        for index in range(1, scenes + 1):
            Scene.objects.create(
                project=project,
                scene_key=f"scene-{index}",
                order=index,
                title=f"Scene {index}",
                visual="Show the product",
                narration="Try this today.",
                caption="Air Fryer",
                duration=6,
                metadata={
                    "presenter_action": "Hold the product to camera.",
                    "presenter_locked": True,
                    "requires_previous_scene_continuity": False,
                    "status": "ready",
                },
            )
        return project

    @override_settings(VIDEO_SCENE_CONCURRENCY=3)
    def test_independent_scenes_record_parallel_metrics(self):
        project = self._project(scenes=5)
        started = []

        def fake_start(prompt, **kwargs):
            started.append(prompt)
            return {"id": f"task-{len(started)}", "file_id": "", "uri": "", "inline": b"FAKEMP4"}

        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda value: int(value or 5)
        omni.model = "gemini-omni-1.1-flash"
        omni.start.side_effect = fake_start
        omni.save_video.side_effect = lambda finished, dest: _write_clip(dest)
        omni.poll_interval.return_value = 0

        with patch("ai.services.video.inspect_audio", return_value={"audible": True, "reason": ""}), patch(
            "ai.services.video.record_usage"
        ), patch.object(VideoGenerationService, "_extract_final_frame", return_value=None):
            VideoGenerationService(omni=omni)._create_videos(project, force=True)

        self.assertEqual(omni.start.call_count, 5)
        project.refresh_from_db()
        metrics = (project.creative_brief or {}).get("generation_metrics") or {}
        self.assertEqual(metrics.get("scene_concurrency"), 3)
        self.assertEqual(metrics.get("scene_count"), 5)
        self.assertIn("scene_generation_parallel_ms", metrics)
        self.assertEqual(len(metrics.get("scenes") or []), 5)

    @override_settings(VIDEO_SCENE_CONCURRENCY=3)
    def test_continuity_scenes_start_in_parallel(self):
        project = self._project(scenes=4)
        for scene in project.scenes.all():
            meta = dict(scene.metadata or {})
            meta["requires_previous_scene_continuity"] = True
            scene.metadata = meta
            scene.save(update_fields=["metadata"])
        started = []

        def fake_start(prompt, **kwargs):
            started.append(prompt)
            return {"id": f"task-{len(started)}", "file_id": "", "uri": "", "inline": b"FAKEMP4"}

        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda value: int(value or 5)
        omni.model = "gemini-omni-1.1-flash"
        omni.start.side_effect = fake_start
        omni.save_video.side_effect = lambda finished, dest: _write_clip(dest)
        omni.poll_interval.return_value = 0

        with patch("ai.services.video.inspect_audio", return_value={"audible": True, "reason": ""}), patch(
            "ai.services.video.record_usage"
        ), patch.object(VideoGenerationService, "_extract_final_frame", return_value=None):
            VideoGenerationService(omni=omni)._create_videos(project, force=True)

        self.assertEqual(omni.start.call_count, 4)
        metrics = (project.creative_brief or {}).get("generation_metrics") or {}
        self.assertEqual(metrics.get("scene_concurrency"), 3)

    def test_locked_scene_skipped_unless_forced(self):
        project = self._project(scenes=3)
        scenes = list(project.scenes.all().order_by("order"))
        locked = scenes[0]
        meta = dict(locked.metadata or {})
        meta["scene_locked"] = True
        locked.metadata = meta
        locked.save(update_fields=["metadata"])

        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda value: 5
        omni.model = "gemini-omni-1.1-flash"
        omni.start.return_value = {"id": "t1", "file_id": "", "uri": "", "inline": b"x"}
        omni.save_video.side_effect = lambda finished, dest: _write_clip(dest, b"x")
        omni.poll_interval.return_value = 0

        with patch("ai.services.video.inspect_audio", return_value={"audible": True}), patch(
            "ai.services.video.record_usage"
        ), patch.object(VideoGenerationService, "_extract_final_frame", return_value=None):
            VideoGenerationService(omni=omni)._create_videos(project, force=False)

        self.assertEqual(omni.start.call_count, 2)
        locked.refresh_from_db()
        self.assertFalse(locked.video_clip)

    def test_regenerate_marks_continuity_dependents_only(self):
        project = self._project(scenes=4)
        scenes = list(project.scenes.all().order_by("order"))
        for scene in scenes[1:3]:
            meta = dict(scene.metadata or {})
            meta["requires_previous_scene_continuity"] = True
            scene.metadata = meta
            scene.save(update_fields=["metadata"])
        target = scenes[1]
        meta = dict(target.metadata or {})
        meta["needs_regeneration"] = True
        target.metadata = meta
        target.save(update_fields=["metadata"])

        with (
            patch.object(VideoGenerationService, "_refresh_snapshot"),
            patch.object(VideoGenerationService, "_create_videos") as videos,
            patch.object(VideoGenerationService, "_create_voice"),
            patch.object(VideoGenerationService, "_assemble"),
        ):
            VideoGenerationService().regenerate_scenes(project.pk, [target.pk])

        rendered = videos.call_args.kwargs.get("scenes") or videos.call_args.args[1]
        self.assertEqual([scene.scene_key for scene in rendered], ["scene-2", "scene-3"])
        scenes[2].refresh_from_db()
        scenes[3].refresh_from_db()
        self.assertTrue((scenes[2].metadata or {}).get("continuity_invalid"))
        self.assertFalse((scenes[3].metadata or {}).get("continuity_invalid"))

    @override_settings(VIDEO_SCENE_CONCURRENCY=6)
    def test_six_independent_scenes_start_together(self):
        import threading
        import time

        project = self._project(scenes=6)
        state = {"current": 0, "peak": 0}
        lock = threading.Lock()

        def fake_start(prompt, **kwargs):
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            time.sleep(0.12)
            with lock:
                state["current"] -= 1
            return {"id": "task", "file_id": "", "uri": "", "inline": b"FAKEMP4"}

        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda value: int(value or 5)
        omni.model = "gemini-omni"
        omni.start.side_effect = fake_start
        omni.save_video.side_effect = lambda finished, dest: _write_clip(dest)
        omni.poll_interval.return_value = 0

        with patch("ai.services.video.inspect_audio", return_value={"audible": True, "reason": ""}), patch(
            "ai.services.video.record_usage"
        ), patch.object(VideoGenerationService, "_extract_final_frame", return_value=None):
            VideoGenerationService(omni=omni)._create_videos(project, force=True)

        self.assertEqual(omni.start.call_count, 6)
        self.assertGreaterEqual(state["peak"], 6)
        self.assertTrue(all(call.kwargs.get("video_path") in (None, "") for call in omni.start.call_args_list))

    def test_continuity_scene_waits_for_previous_clip(self):
        project = self._project(scenes=3)
        lines = ["ALPHA LINE", "BRAVO LINE", "CHARLIE LINE"]
        for scene, line in zip(project.scenes.order_by("order"), lines, strict=True):
            scene.narration = line
            meta = dict(scene.metadata or {})
            meta["requires_previous_scene_continuity"] = scene.order > 1
            scene.metadata = meta
            scene.save(update_fields=["narration", "metadata"])
        started: list[str] = []

        def fake_start(prompt, **kwargs):
            started.append(prompt)
            return {"id": f"task-{len(started)}", "file_id": "", "uri": "", "inline": b"FAKEMP4"}

        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda value: 5
        omni.model = "gemini-omni"
        omni.start.side_effect = fake_start
        omni.save_video.side_effect = lambda finished, dest: _write_clip(dest)
        omni.poll_interval.return_value = 0

        with patch("ai.services.video.inspect_audio", return_value={"audible": True}), patch(
            "ai.services.video.record_usage"
        ), patch.object(VideoGenerationService, "_extract_final_frame", return_value=None):
            VideoGenerationService(omni=omni)._create_videos(project, force=True)

        self.assertEqual(len(started), 3)
        self.assertIn("ALPHA LINE", started[0])
        self.assertIn("BRAVO LINE", started[1])
        self.assertIn("CHARLIE LINE", started[2])

    def test_transient_scene_failure_retries_without_dropping_siblings(self):
        from ai.exceptions import ProviderError

        project = self._project(scenes=3)
        lines = ["KEEP ONE", "RETRY ME", "KEEP THREE"]
        for scene, line in zip(project.scenes.order_by("order"), lines, strict=True):
            scene.narration = line
            scene.save(update_fields=["narration"])
        attempts = {"retry": 0}

        def fake_start(prompt, **kwargs):
            if "RETRY ME" in prompt:
                attempts["retry"] += 1
                if attempts["retry"] == 1:
                    raise ProviderError("temporary timeout", retryable=True)
            return {"id": f"task-{attempts['retry']}", "file_id": "", "uri": "", "inline": b"FAKEMP4"}

        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda value: 5
        omni.model = "gemini-omni"
        omni.start.side_effect = fake_start
        omni.save_video.side_effect = lambda finished, dest: _write_clip(dest)
        omni.poll_interval.return_value = 0

        with patch("ai.services.video.inspect_audio", return_value={"audible": True}), patch(
            "ai.services.video.record_usage"
        ), patch.object(VideoGenerationService, "_extract_final_frame", return_value=None):
            VideoGenerationService(omni=omni)._create_videos(project, force=True)

        self.assertGreaterEqual(attempts["retry"], 2)
        self.assertEqual(project.scenes.exclude(video_clip="").count(), 3)

    @override_settings(VIDEO_SCENE_CONCURRENCY=99, BULK_VIDEO_CONCURRENCY=99, Q_CLUSTER_WORKERS=99)
    def test_concurrency_hard_cap_is_eight(self):
        from ai.services.bulk_studio import bulk_concurrency

        self.assertEqual(bulk_concurrency(), 8)
        project = self._project(scenes=1)
        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda value: 5
        omni.model = "gemini-omni"
        omni.start.return_value = {"id": "t", "file_id": "", "uri": "", "inline": b"x"}
        omni.save_video.side_effect = lambda finished, dest: _write_clip(dest)
        omni.poll_interval.return_value = 0
        with patch("ai.services.video.inspect_audio", return_value={"audible": True}), patch(
            "ai.services.video.record_usage"
        ), patch.object(VideoGenerationService, "_extract_final_frame", return_value=None):
            VideoGenerationService(omni=omni)._create_videos(project, force=True)
        project.refresh_from_db()
        metrics = (project.creative_brief or {}).get("generation_metrics") or {}
        self.assertEqual(metrics.get("scene_concurrency"), 8)

    def test_locked_caption_is_exact_spoken_prompt(self):
        from ai.services.compiler import compile_scene_prompt
        from ai.services.director import DirectorService

        project = self._project(scenes=1)
        scene = project.scenes.get()
        scene.narration = "A different spoken line."
        scene.caption = "This is the exact sentence."
        scene.metadata = {**(scene.metadata or {}), "caption_locked": True}
        scene.save()
        DirectorService()._align_captions_to_speech(project)
        scene.refresh_from_db()
        self.assertEqual(scene.narration, "This is the exact sentence.")
        prompt = compile_scene_prompt(scene, project)
        self.assertIn("This is the exact sentence.", prompt)
        self.assertNotIn("A different spoken line.", prompt)

    def test_reference_analysis_is_style_only_and_not_sent_as_video(self):
        project = self._project(scenes=1)
        project.reference_analysis = {
            "hook": "question hook",
            "camera_style": "handheld close-up",
            "pacing": "fast",
            "cta_structure": "direct CTA",
        }
        project.save(update_fields=["reference_analysis"])
        omni = MagicMock()
        omni.family.return_value = "omni"
        omni.clamp_duration.side_effect = lambda value: 5
        omni.model = "gemini-omni"
        omni.start.return_value = {"id": "t", "file_id": "", "uri": "", "inline": b"x"}
        omni.save_video.side_effect = lambda finished, dest: _write_clip(dest)
        omni.poll_interval.return_value = 0
        with patch("ai.services.video.inspect_audio", return_value={"audible": True}), patch(
            "ai.services.video.record_usage"
        ), patch.object(VideoGenerationService, "_extract_final_frame", return_value=None):
            VideoGenerationService(omni=omni)._create_videos(project, force=True)
        self.assertIsNone(omni.start.call_args.kwargs.get("video_path"))
        self.assertIn("REFERENCE STYLE ONLY", omni.start.call_args.args[0])
        self.assertIn("question hook", omni.start.call_args.args[0])
        self.assertIn("Do not copy the reference presenter", omni.start.call_args.args[0])


class QaSkippedTests(TestCase):
    def test_skipped_is_not_blocking(self):
        checks = [
            {"name": "character_identity", "status": "skipped", "detail": "not run"},
            {"name": "claims", "status": "passed", "detail": "ok"},
        ]
        blocking = release_blocking_issues(checks, has_preview=True)
        self.assertEqual(blocking, [])

    def test_failed_still_blocks(self):
        checks = [
            {"name": "character_identity", "status": "failed", "detail": "mismatch"},
        ]
        blocking = release_blocking_issues(checks, has_preview=True)
        self.assertEqual(len(blocking), 1)


class CompilerCommercialTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Beauty Opt", slug="beauty-opt")
        self.owner = User.objects.create_user(
            username="opt-compiler",
            email="opt-compiler@example.com",
            password="password123",
            name="Opt Compiler",
            mobile="0123888888",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        self.brand = Brand.objects.create(owner=self.owner, category=self.category, name="Beauty")
        self.product = Product.objects.create(
            brand=self.brand,
            name="Serum",
            description="Hydrating serum",
            price="99",
        )
        ProductImage.objects.create(product=self.product, image=_png())

    def test_prompt_separates_price_currency_duration(self):
        from ai.services.compiler import compile_scene_prompt

        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            creative_brief={
                "price": "99",
                "currency": "USD",
                "product_duration": "60 minutes",
                "cta": "Buy now",
                "continuity_state": {"location": "studio", "lighting": "soft"},
            },
        )
        scene = Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="Presenter holds product",
            narration="Try this serum.",
            caption="Serum",
            duration=5,
        )
        prompt = compile_scene_prompt(scene, project)
        self.assertIn("price: 99", prompt)
        self.assertIn("currency: USD", prompt)
        self.assertIn("duration: 60 minutes", prompt)
        self.assertIn("locale: en-US", prompt)

    def test_prompt_continues_from_previous_shot(self):
        from ai.services.compiler import compile_scene_prompt

        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            creative_brief={"continuity_state": {"location": "kitchen", "lighting": "warm", "wardrobe": "black shirt"}},
        )
        scene = Scene.objects.create(
            project=project,
            scene_key="scene-2",
            order=2,
            visual="Presenter holds product",
            narration="Try this serum.",
            caption="Serum",
            duration=5,
            metadata={"requires_previous_scene_continuity": True, "location": "kitchen", "presenter_locked": True},
        )
        prompt = compile_scene_prompt(scene, project)
        self.assertIn("CONTINUE NATURALLY FROM THE PREVIOUS SHOT", prompt)
        self.assertIn("black shirt", prompt)
        self.assertIn("Keep the approved location", prompt)

    def test_chinese_variety_speech_is_locked(self):
        from ai.services.compiler import compile_scene_prompt
        from ai.services.script import LANGUAGE_GUIDE, speech_lock

        for language, must, forbidden in (
            ("chinese", "Mandarin", "Cantonese ONLY"),
            ("cantonese", "CANTONESE ONLY", "Putonghua"),
            ("hokkien", "HOKKIEN ONLY", "Cantonese ONLY"),
        ):
            project = VideoProject.objects.create(
                owner=self.owner,
                product=self.product,
                product_snapshot=product_snapshot(self.product),
                language=language,
            )
            scene = Scene.objects.create(
                project=project,
                scene_key=f"{language}-1",
                order=1,
                visual="Presenter holds product",
                narration="講呢個產品。",
                caption="講呢個產品。",
                duration=5,
            )
        prompt = compile_scene_prompt(scene, project)
        self.assertTrue(prompt.startswith("SPOKEN AUDIO — LOCKED LANGUAGE"))
        self.assertIn(LANGUAGE_GUIDE[language], prompt)
        self.assertIn(speech_lock(language), prompt)
        self.assertIn(must, prompt)
        self.assertIn(f"Spoken language id: {language}", prompt)
        self.assertNotIn(LANGUAGE_GUIDE["english"], prompt)
        if language != "cantonese":
            self.assertNotIn("SPEECH LOCK — CANTONESE ONLY", prompt)
        if language == "cantonese":
            self.assertIn("Jyutping", prompt)
            self.assertIn("係 hai", prompt)

    def test_amendment_text_locks_locale_and_reaches_prompt(self):
        from ai.services.compiler import compile_scene_prompt
        from ai.services.correction import CorrectionService
        from ai.services.script import locale_from_instruction

        self.assertEqual(locale_from_instruction("Speak Cantonese 粵語, not Mandarin"), "cantonese")
        self.assertEqual(locale_from_instruction("Use Hokkien 福建話"), "hokkien")
        self.assertEqual(locale_from_instruction("Chinese Mandarin only"), "chinese")

        project = VideoProject.objects.create(
            owner=self.owner,
            product=self.product,
            product_snapshot=product_snapshot(self.product),
            language="english",
            creative_brief={},
            status=VideoProjectStatus.READY_FOR_REVIEW,
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            visual="Presenter holds product",
            narration="Try this serum.",
            caption="Try this serum.",
            duration=5,
        )
        parsed = CorrectionService().prepare_regenerate(project, "Speak Cantonese, not Mandarin. Match captions to audio.")
        project.refresh_from_db()
        self.assertEqual(project.language, "cantonese")
        self.assertIn("Cantonese", project.merchant_instructions)
        self.assertIn("Cantonese", (project.creative_brief or {}).get("legacy_instructions", ""))
        self.assertIn("script", parsed["regenerate"])
        prompt = compile_scene_prompt(project.scenes.get(), project)
        self.assertIn("CANTONESE ONLY", prompt)
        self.assertIn("Speak Cantonese", prompt)
