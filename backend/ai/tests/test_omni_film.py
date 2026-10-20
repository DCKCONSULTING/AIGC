from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.test import TestCase, TransactionTestCase, override_settings

from accounts.models import User
from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.services.compiler import compile_film_prompt, format_beat_span
from ai.services.durations import plan_omni_chains
from ai.services.omni_film import generate_continuous_film
from ai.services.snapshots import product_snapshot
from ai.services.video import VideoGenerationService
from ai.tests.test_studio import _png
from brands.models import Brand, Category, Product, ProductImage


class OmniChainPlanTests(TestCase):
    def test_supported_lengths_use_ten_second_extension_chains(self):
        self.assertEqual(plan_omni_chains(15), [[10, 5]])
        self.assertEqual(plan_omni_chains(30), [[10, 10, 10]])
        self.assertEqual(plan_omni_chains(40), [[10, 10, 10, 10]])
        self.assertEqual(plan_omni_chains(45), [[10, 10, 10, 10], [5]])
        self.assertEqual(plan_omni_chains(60), [[10, 10, 10, 10], [10, 10]])
        self.assertNotEqual(plan_omni_chains(60), [[60]])

    def test_subsecond_scene_overlap_keeps_a_real_span(self):
        self.assertEqual(format_beat_span(0, 7.5), "[0-7.5s]")
        self.assertEqual(format_beat_span(7.5, 8), "[7.5-8s]")
        self.assertNotEqual(format_beat_span(7.5, 8), "[8-8s]")
        self.assertEqual(format_beat_span(0, 10), "[0-10s]")


@override_settings(VIDEO_PROVIDER="omni")
class ContinuousFilmTests(TransactionTestCase):
    def setUp(self):
        category = Category.objects.create(name="Kitchen", slug="kitchen-film")
        owner = User.objects.create_user(
            username="film-owner",
            email="film@example.com",
            password="password123",
            name="Film Owner",
            mobile="0123888777",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        brand = Brand.objects.create(
            owner=owner,
            category=category,
            name="Film Brand",
            description="Kitchen",
            location="KL",
        )
        product = Product.objects.create(brand=brand, name="Air Fryer", description="Crispy food.", price="199.00")
        ProductImage.objects.create(product=product, image=_png())
        self.project = VideoProject.objects.create(
            owner=owner,
            product=product,
            product_snapshot=product_snapshot(product),
            language="english",
            speaker_gender="female",
            selected_concept_id="film-demo",
            duration_seconds=30,
            creative_brief={"schema_version": 2, "objective": "buy", "style": "product_demo"},
            status=VideoProjectStatus.GENERATING_VIDEO,
        )
        for index in range(1, 6):
            Scene.objects.create(
                project=self.project,
                scene_key=f"scene-{index}",
                order=index,
                title=f"Scene {index}",
                visual=f"Show step {index}",
                narration=f"Line {index}.",
                caption="LOCKED LINE" if index == 1 else f"Caption {index}",
                duration=6,
                metadata={"caption_locked": index == 1, "status": "ready"},
            )

    def test_locked_caption_is_exact_dialogue_in_one_prompt(self):
        scenes = list(self.project.scenes.order_by("order"))
        prompt = compile_film_prompt(self.project, scenes, 0, 10, extend=False)
        self.assertIn("Speak the supplied dialogue exactly as written.", prompt)
        self.assertIn("Do not paraphrase.", prompt)
        self.assertIn("LOCKED LINE", prompt)
        self.assertIn("[0-", prompt)
        extension = compile_film_prompt(self.project, scenes, 10, 20, extend=True)
        self.assertIn("Continue this video from the exact last frame.", extension)
        self.assertNotIn("GLOBAL", extension)

    def test_thirty_seconds_is_one_extension_chain_not_five_scenes(self):
        calls = []

        def fake_start(prompt, **kwargs):
            calls.append(kwargs | {"prompt": prompt})
            return {
                "id": f"job-{len(calls)}",
                "file_id": "",
                "uri": "",
                "inline": b"FAKE",
                "model": "gemini-omni-1.1-flash",
                "duration_requested": kwargs.get("duration_seconds"),
                "resolution": "720p",
                "aspect_ratio": "9:16",
                "reference_count": len(kwargs.get("prepared_images") or []),
                "prompt_length": len(prompt),
                "store": kwargs.get("store"),
                "delivery": "inline",
                "task": "extend" if kwargs.get("previous_interaction_id") else "reference_to_video",
                "elapsed_ms": 5,
            }

        omni = MagicMock()
        omni.model = "gemini-omni-1.1-flash"
        omni.prepare_images.return_value = [{"type": "image", "data": "abc", "mime_type": "image/png"}]
        omni.start.side_effect = fake_start
        omni.save_video.side_effect = lambda task, dest: dest.write_bytes(b"FAKEMP4")
        omni.poll_interval.return_value = 0
        service = VideoGenerationService(omni=omni)

        def fake_probe(path):
            return {
                "has_video": True,
                "has_audio": True,
                "duration": 30,
                "audio_codec": "aac",
                "video_codec": "h264",
                "width": 720,
                "height": 1280,
                "fps": 24,
            }

        with (
            patch("ai.services.omni_film.probe_media", side_effect=fake_probe),
            patch("ai.services.omni_film.burn_captions", side_effect=lambda src, captions, dest: dest.write_bytes(b"CAPTIONED")),
            patch("ai.services.omni_film.split_copy", side_effect=lambda src, dest, start, end: dest.write_bytes(b"PART")),
            patch("ai.services.omni_film.concat_clips") as concat,
            patch("ai.services.poster.save_video_poster"),
        ):
            self.assertTrue(generate_continuous_film(service, self.project))

        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[0]["store"])
        self.assertFalse(calls[0].get("previous_interaction_id"))
        self.assertEqual(calls[0]["prepared_images"], [{"type": "image", "data": "abc", "mime_type": "image/png"}])
        self.assertEqual(calls[1]["previous_interaction_id"], "job-1")
        self.assertTrue(calls[1]["store"])
        self.assertIsNone(calls[1]["prepared_images"])
        self.assertEqual(calls[2]["previous_interaction_id"], "job-2")
        self.assertFalse(calls[2]["store"])
        concat.assert_not_called()
        self.project.refresh_from_db()
        self.assertTrue(self.project.preview_video)
        self.assertEqual(self.project.preview_video.read(), b"CAPTIONED")
        metrics = (self.project.creative_brief or {}).get("generation_metrics") or {}
        self.assertEqual(metrics.get("omni_request_count"), 3)
        self.assertEqual(metrics.get("architecture"), "omni_extension_chain")
        self.assertEqual(metrics.get("number_of_chains"), 1)
        self.assertEqual(metrics.get("number_of_omni_calls"), 3)

    def test_second_chain_prompt_is_a_new_generation(self):
        scenes = list(self.project.scenes.order_by("order"))
        prompt = compile_film_prompt(self.project, scenes, 40, 45, extend=False, boundary=True)
        self.assertIn("NEW generation", prompt)
        self.assertIn("GLOBAL STYLE", prompt)
        self.assertIn("CHARACTER STATE", prompt)
        self.assertNotIn("Continue this video from the exact last frame.", prompt)

    def test_forty_five_seconds_starts_a_new_chain_without_previous_interaction(self):
        self.project.duration_seconds = 45
        self.project.save(update_fields=["duration_seconds"])
        calls = []
        call_lock = __import__("threading").Lock()

        def fake_start(prompt, **kwargs):
            with call_lock:
                calls.append(kwargs | {"prompt": prompt})
                job_id = f"job-{len(calls)}"
            return {
                "id": job_id,
                "file_id": "",
                "uri": "",
                "inline": b"FAKE",
                "model": "gemini-omni-1.1-flash",
                "duration_requested": kwargs.get("duration_seconds"),
                "resolution": "720p",
                "aspect_ratio": "9:16",
                "reference_count": len(kwargs.get("prepared_images") or []),
                "prompt_length": len(prompt),
                "store": kwargs.get("store"),
                "delivery": "inline",
                "task": "extend" if kwargs.get("previous_interaction_id") else "reference_to_video",
                "elapsed_ms": 5,
            }

        omni = MagicMock()
        omni.model = "gemini-omni-1.1-flash"
        omni.prepare_images.return_value = [{"type": "image", "data": "abc", "mime_type": "image/png"}]
        omni.start.side_effect = fake_start
        omni.save_video.side_effect = lambda task, dest: dest.write_bytes(b"FAKEMP4")
        omni.poll_interval.return_value = 0
        service = VideoGenerationService(omni=omni)

        def fake_concat(clips, dest, fade=0):
            dest.write_bytes(b"JOINED")
            return dest

        with (
            patch(
                "ai.services.omni_film.probe_media",
                return_value={
                    "has_video": True,
                    "has_audio": True,
                    "duration": 45,
                    "audio_codec": "aac",
                    "video_codec": "h264",
                    "width": 720,
                    "height": 1280,
                    "fps": 24,
                },
            ),
            patch("ai.services.omni_film.burn_captions", side_effect=lambda src, captions, dest: dest.write_bytes(b"CAPTIONED")),
            patch("ai.services.omni_film.split_copy", side_effect=lambda src, dest, start, end: dest.write_bytes(b"PART")),
            patch("ai.services.omni_film.concat_clips", side_effect=fake_concat),
            patch("ai.services.poster.save_video_poster"),
        ):
            self.assertTrue(generate_continuous_film(service, self.project))

        self.assertEqual(len(calls), 5)
        roots = [call for call in calls if not call.get("previous_interaction_id")]
        continued = [call for call in calls if call.get("previous_interaction_id")]
        self.assertEqual(len(roots), 2)
        self.assertEqual(len(continued), 3)
        self.assertTrue(all(call["prepared_images"] is None for call in continued))
        new_chain = [call for call in roots if "NEW generation" in call["prompt"]]
        self.assertEqual(len(new_chain), 1)
        self.assertFalse(new_chain[0]["store"])
        self.assertEqual(new_chain[0]["prepared_images"], [{"type": "image", "data": "abc", "mime_type": "image/png"}])
        self.assertEqual(len([call for call in calls if not call["store"]]), 2)
        metrics = (self.project.creative_brief or {}).get("generation_metrics") or {}
        self.assertEqual(metrics.get("number_of_chains"), 2)
        self.assertEqual(metrics.get("number_of_omni_calls"), 5)
        self.assertEqual(metrics.get("chain_concurrency"), 2)

    @override_settings(VIDEO_SCENE_CONCURRENCY=3, OMNI_MAX_IN_FLIGHT=3)
    def test_independent_chains_overlap(self):
        import threading
        import time

        self.project.duration_seconds = 45
        self.project.save(update_fields=["duration_seconds"])
        state = {"current": 0, "peak": 0, "open_roots": 0, "root_peak": 0, "n": 0}
        lock = threading.Lock()

        def fake_start(prompt, **kwargs):
            root = not kwargs.get("previous_interaction_id")
            with lock:
                state["current"] += 1
                state["n"] += 1
                job_id = f"job-{state['n']}"
                state["peak"] = max(state["peak"], state["current"])
                if root:
                    state["open_roots"] += 1
                    state["root_peak"] = max(state["root_peak"], state["open_roots"])
            time.sleep(0.15)
            with lock:
                state["current"] -= 1
                if root:
                    state["open_roots"] -= 1
            return {
                "id": job_id,
                "file_id": "",
                "uri": "",
                "inline": b"FAKE",
                "model": "gemini-omni-1.1-flash",
                "duration_requested": kwargs.get("duration_seconds"),
                "resolution": "720p",
                "aspect_ratio": "9:16",
                "reference_count": len(kwargs.get("prepared_images") or []),
                "prompt_length": len(prompt),
                "store": kwargs.get("store"),
                "delivery": "inline",
                "task": "reference_to_video",
                "elapsed_ms": 5,
            }

        omni = MagicMock()
        omni.model = "gemini-omni-1.1-flash"
        omni.prepare_images.return_value = [{"type": "image", "data": "abc", "mime_type": "image/png"}]
        omni.start.side_effect = fake_start
        omni.save_video.side_effect = lambda task, dest: dest.write_bytes(b"FAKEMP4")
        omni.poll_interval.return_value = 0
        service = VideoGenerationService(omni=omni)

        def fake_concat(clips, dest, fade=0):
            dest.write_bytes(b"JOINED")
            return dest

        with (
            patch(
                "ai.services.omni_film.probe_media",
                return_value={
                    "has_video": True,
                    "has_audio": True,
                    "duration": 45,
                    "audio_codec": "aac",
                    "video_codec": "h264",
                    "width": 720,
                    "height": 1280,
                    "fps": 24,
                },
            ),
            patch("ai.services.omni_film.burn_captions", side_effect=lambda src, captions, dest: dest.write_bytes(b"CAPTIONED")),
            patch("ai.services.omni_film.split_copy", side_effect=lambda src, dest, start, end: dest.write_bytes(b"PART")),
            patch("ai.services.omni_film.concat_clips", side_effect=fake_concat),
            patch("ai.services.poster.save_video_poster"),
        ):
            self.assertTrue(generate_continuous_film(service, self.project))

        self.assertEqual(omni.start.call_count, 5)
        self.assertGreaterEqual(state["root_peak"], 2)
        self.project.refresh_from_db()
        metrics = (self.project.creative_brief or {}).get("generation_metrics") or {}
        self.assertEqual(metrics.get("chain_concurrency"), 2)
        self.assertEqual(metrics.get("number_of_omni_calls"), 5)

    def test_rate_limited_does_not_retry_omni(self):
        from ai.exceptions import ProviderError

        omni = MagicMock()
        omni.model = "gemini-omni-1.1-flash"
        omni.prepare_images.return_value = []
        omni.start.side_effect = ProviderError(
            "Video generation is temporarily rate limited.",
            retryable=False,
            code="RATE_LIMITED",
            status_code=429,
            category="rate_limited",
        )
        service = VideoGenerationService(omni=omni)
        with self.assertRaises(ProviderError) as ctx:
            generate_continuous_film(service, self.project)
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        self.assertEqual(omni.start.call_count, 1)

