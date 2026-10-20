import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from ai.exceptions import MissingAPIKeyError, ProviderError
from ai.providers.minimax import (
    MiniMaxProvider,
    plan_minimax_generation,
    select_minimax_reference_paths,
)
from ai.providers.minimax.video import MINIMAX_MAX_CONTINUOUS_DURATION_SECONDS
from ai.providers.video import get_video_generation_provider, video_provider_name


class MiniMaxConfigTests(SimpleTestCase):
    @override_settings(VIDEO_PROVIDER="minimax", MINIMAX_VIDEO_MODEL="MiniMax-H3")
    def test_minimax_is_selected_from_env(self):
        self.assertEqual(video_provider_name(), "minimax")
        provider = get_video_generation_provider()
        self.assertEqual(provider.family(), "minimax")
        self.assertEqual(provider.model, "MiniMax-H3")

    @override_settings(VIDEO_PROVIDER="omni")
    def test_default_remains_omni(self):
        self.assertEqual(video_provider_name(), "omni")

    @override_settings(VIDEO_PROVIDER="chatgpt")
    def test_invalid_provider_still_fails(self):
        with self.assertRaises(ImproperlyConfigured):
            video_provider_name()

    @override_settings(
        VIDEO_PROVIDER="minimax",
        MINIMAX_VIDEO_MODEL="not-a-real-model",
        MINIMAX_API_KEY="test-key",
    )
    def test_unsupported_model_fails(self):
        with self.assertRaises(ProviderError) as ctx:
            get_video_generation_provider()
        self.assertEqual(ctx.exception.code, "INVALID_CONFIGURATION")

    @override_settings(MINIMAX_API_KEY="")
    def test_missing_credentials(self):
        with self.assertRaises(MissingAPIKeyError):
            MiniMaxProvider().start("Show the product", duration_seconds=5)


class MiniMaxDurationPlanTests(SimpleTestCase):
    def test_single_clip_within_max(self):
        plan = plan_minimax_generation(8, model="MiniMax-H3")
        self.assertEqual(plan["clip_durations"], [8])
        self.assertEqual(plan["generated_duration"], 8)
        self.assertEqual(plan["trim_to"], 0)

    def test_short_request_uses_model_minimum_then_trims(self):
        plan = plan_minimax_generation(3, model="MiniMax-H3")
        self.assertEqual(plan["clip_durations"], [4])
        self.assertEqual(plan["trim_to"], 3)

        max_plan = plan_minimax_generation(4, model="MiniMax-H3-Max")
        self.assertEqual(max_plan["clip_durations"], [5])
        self.assertEqual(max_plan["trim_to"], 4)

    def test_multi_clip_split(self):
        thirty = plan_minimax_generation(30, model="MiniMax-H3")
        self.assertEqual(thirty["clip_durations"], [15, 15])
        self.assertEqual(thirty["generated_duration"], 30)

        forty_five = plan_minimax_generation(45, model="MiniMax-H3")
        self.assertEqual(forty_five["clip_durations"], [15, 15, 15])

        seventeen = plan_minimax_generation(17, model="MiniMax-H3")
        self.assertEqual(sum(seventeen["clip_durations"]), 17)
        self.assertTrue(all(4 <= d <= 15 for d in seventeen["clip_durations"]))

    def test_over_max_is_rejected(self):
        with self.assertRaises(ProviderError) as ctx:
            plan_minimax_generation(MINIMAX_MAX_CONTINUOUS_DURATION_SECONDS + 1)
        self.assertEqual(ctx.exception.code, "INVALID_DURATION")


class MiniMaxReferenceTests(SimpleTestCase):
    def test_priority_and_cap(self):
        chosen = select_minimax_reference_paths(
            ["p1", "p2", "c1", "s1", "extra"],
            character_paths=["c1"],
            product_paths=["p1", "p2"],
            style_paths=["s1"],
            limit=3,
        )
        self.assertEqual(chosen, ["c1", "p1", "s1"])


class MiniMaxProviderApiTests(SimpleTestCase):
    @override_settings(
        MINIMAX_API_KEY="test-key",
        MINIMAX_VIDEO_MODEL="MiniMax-H3",
        MINIMAX_API_BASE="https://api.minimax.io",
        MINIMAX_VIDEO_RESOLUTION="768P",
    )
    def test_start_poll_download_lifecycle(self):
        provider = MiniMaxProvider()
        create_response = MagicMock(status_code=200, content=b'{"task_id":"tid-1"}')
        create_response.json.return_value = {"task_id": "tid-1"}
        query_running = MagicMock(status_code=200, content=b"{}")
        query_running.json.return_value = {
            "task": {"id": "tid-1", "status": "running", "content": {}}
        }
        query_done = MagicMock(status_code=200, content=b"{}")
        query_done.json.return_value = {
            "task": {
                "id": "tid-1",
                "status": "succeeded",
                "content": {"url": "https://cdn.example.com/out.mp4"},
                "model": "MiniMax-H3",
                "duration": 5,
            }
        }
        download = MagicMock(status_code=200, content=b"MP4DATA", raise_for_status=MagicMock())
        with patch("httpx.post", return_value=create_response) as post, patch(
            "httpx.get", side_effect=[query_running, query_done, download]
        ) as get, patch("ai.providers.minimax.video.time.sleep"):
            started = provider.start("A product demo", duration_seconds=5, aspect_ratio="9:16")
            dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
            provider.save_video(started, dest)
        self.assertEqual(started["id"], "tid-1")
        self.assertEqual(started["provider"], "minimax")
        self.assertEqual(started["uri"], "https://cdn.example.com/out.mp4")
        self.assertEqual(dest.read_bytes(), b"MP4DATA")
        dest.unlink(missing_ok=True)
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "MiniMax-H3")
        self.assertEqual(payload["duration"], 5)
        self.assertEqual(payload["resolution"], "768P")
        self.assertEqual(payload["ratio"], "9:16")
        self.assertEqual(payload["content"][0]["type"], "text")
        self.assertIn("Authorization", post.call_args.kwargs["headers"])
        self.assertTrue(post.call_args.kwargs["headers"]["Authorization"].startswith("Bearer "))
        self.assertGreaterEqual(get.call_count, 3)

    @override_settings(MINIMAX_API_KEY="test-key", MINIMAX_VIDEO_MODEL="MiniMax-H3")
    def test_reference_images_use_r2v_mode(self):
        provider = MiniMaxProvider()
        image = Path(tempfile.mkstemp(suffix=".jpg")[1])
        image.write_bytes(b"\xff\xd8\xff" + b"0" * 64)
        create_response = MagicMock(status_code=200, content=b'{"task_id":"tid-ref"}')
        create_response.json.return_value = {"task_id": "tid-ref"}
        query_done = MagicMock(status_code=200, content=b"{}")
        query_done.json.return_value = {
            "task": {
                "id": "tid-ref",
                "status": "succeeded",
                "content": {"url": "https://cdn.example.com/out.mp4"},
            }
        }
        with patch("httpx.post", return_value=create_response) as post, patch(
            "httpx.get", return_value=query_done
        ), patch("ai.providers.minimax.video.time.sleep"):
            started = provider.start(
                "Keep the product identical",
                prepared_images=[str(image)],
                duration_seconds=6,
            )
        image.unlink(missing_ok=True)
        payload = post.call_args.kwargs["json"]
        roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
        self.assertEqual(roles, ["reference_image"])
        self.assertEqual(started["mode"], "r2v")

    @override_settings(MINIMAX_API_KEY="test-key", MINIMAX_VIDEO_MODEL="MiniMax-H3")
    def test_first_frame_uses_i2v_and_ignores_refs(self):
        provider = MiniMaxProvider()
        frame = Path(tempfile.mkstemp(suffix=".jpg")[1])
        ref = Path(tempfile.mkstemp(suffix=".jpg")[1])
        frame.write_bytes(b"\xff\xd8\xff" + b"1" * 64)
        ref.write_bytes(b"\xff\xd8\xff" + b"2" * 64)
        create_response = MagicMock(status_code=200, content=b'{"task_id":"tid-i2v"}')
        create_response.json.return_value = {"task_id": "tid-i2v"}
        query_done = MagicMock(status_code=200, content=b"{}")
        query_done.json.return_value = {
            "task": {
                "id": "tid-i2v",
                "status": "succeeded",
                "content": {"url": "https://cdn.example.com/out.mp4"},
            }
        }
        with patch("httpx.post", return_value=create_response) as post, patch(
            "httpx.get", return_value=query_done
        ), patch("ai.providers.minimax.video.time.sleep"):
            started = provider.start(
                "Continue from this frame",
                prepared_images=[str(ref)],
                first_frame_path=str(frame),
                duration_seconds=6,
            )
        frame.unlink(missing_ok=True)
        ref.unlink(missing_ok=True)
        payload = post.call_args.kwargs["json"]
        roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
        self.assertEqual(roles, ["first_frame"])
        self.assertNotIn("ratio", payload)  # i2v ratio is adaptive / omitted
        self.assertEqual(started["mode"], "i2v")

    @override_settings(MINIMAX_API_KEY="test-key", MINIMAX_VIDEO_MODEL="MiniMax-H3")
    def test_rate_limit_maps_correctly(self):
        provider = MiniMaxProvider()
        response = MagicMock(status_code=429, content=b"{}")
        response.json.return_value = {
            "type": "error",
            "error": {"type": "rate_limit_error", "message": "rate limit (1002)", "http_code": "429"},
        }
        with patch("httpx.post", return_value=response):
            with self.assertRaises(ProviderError) as ctx:
                provider.start("Show the product", duration_seconds=5)
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        self.assertFalse(ctx.exception.retryable)

    @override_settings(MINIMAX_API_KEY="test-key", MINIMAX_VIDEO_MODEL="MiniMax-H3")
    def test_auth_failure_maps_correctly(self):
        provider = MiniMaxProvider()
        response = MagicMock(status_code=401, content=b"{}")
        response.json.return_value = {
            "type": "error",
            "error": {"type": "authorized_error", "message": "login fail (1004)", "http_code": "401"},
        }
        with patch("httpx.post", return_value=response):
            with self.assertRaises(ProviderError) as ctx:
                provider.start("Show the product", duration_seconds=5)
        self.assertEqual(ctx.exception.code, "AUTHENTICATION")

    @override_settings(MINIMAX_API_KEY="test-key", MINIMAX_VIDEO_MODEL="MiniMax-H3")
    def test_failed_task_status(self):
        provider = MiniMaxProvider()
        create_response = MagicMock(status_code=200, content=b'{"task_id":"tid-fail"}')
        create_response.json.return_value = {"task_id": "tid-fail"}
        query_fail = MagicMock(status_code=200, content=b"{}")
        query_fail.json.return_value = {
            "task": {
                "id": "tid-fail",
                "status": "failed",
                "error": {"code": "1026", "message": "sensitive content"},
            }
        }
        with patch("httpx.post", return_value=create_response), patch(
            "httpx.get", return_value=query_fail
        ), patch("ai.providers.minimax.video.time.sleep"):
            with self.assertRaises(ProviderError) as ctx:
                provider.start("Show the product", duration_seconds=5)
        self.assertEqual(ctx.exception.provider, "minimax")
        self.assertIn("sensitive", str(ctx.exception).lower())

    @override_settings(MINIMAX_API_KEY="test-key", MINIMAX_VIDEO_MODEL="MiniMax-H3")
    def test_cancel_during_poll_attempts_delete_without_wrapping(self):
        from ai.services.cancel import CANCEL_MESSAGE, GenerationCancelled

        provider = MiniMaxProvider()
        create_response = MagicMock(status_code=200, content=b'{"task_id":"tid-cancel"}')
        create_response.json.return_value = {"task_id": "tid-cancel"}
        delete_response = MagicMock(status_code=200, content=b"{}")
        delete_response.json.return_value = {"action": "cancelled", "status": "cancelled"}
        checks = {"n": 0}

        def stop():
            checks["n"] += 1
            if checks["n"] > 1:
                raise GenerationCancelled(CANCEL_MESSAGE)

        with patch("httpx.post", return_value=create_response), patch(
            "httpx.delete", return_value=delete_response
        ) as delete, patch("httpx.get") as get, patch("ai.providers.minimax.video.time.sleep"):
            with self.assertRaises(GenerationCancelled):
                provider.start(
                    "Show the product",
                    duration_seconds=5,
                    should_stop=stop,
                )
        delete.assert_called_once()
        get.assert_not_called()

    @override_settings(MINIMAX_API_KEY="test-key", MINIMAX_VIDEO_MODEL="MiniMax-H3")
    def test_timeout_is_not_retryable(self):
        provider = MiniMaxProvider()
        create_response = MagicMock(status_code=200, content=b'{"task_id":"tid-hang"}')
        create_response.json.return_value = {"task_id": "tid-hang"}
        query_running = MagicMock(status_code=200, content=b"{}")
        query_running.json.return_value = {"task": {"id": "tid-hang", "status": "running"}}
        with patch("httpx.post", return_value=create_response), patch(
            "httpx.get", return_value=query_running
        ), patch("ai.providers.minimax.video.time.sleep"), patch(
            "ai.providers.minimax.video.minimax_operation_timeout", return_value=0
        ):
            with self.assertRaises(ProviderError) as ctx:
                provider.start("Show the product", duration_seconds=5)
        self.assertEqual(ctx.exception.code, "TIMEOUT")
        self.assertFalse(ctx.exception.retryable)


@override_settings(VIDEO_PROVIDER="minimax", MINIMAX_API_KEY="test-key", MINIMAX_VIDEO_MODEL="MiniMax-H3")
class MiniMaxIsolationTests(SimpleTestCase):
    def test_minimax_never_calls_google_clients(self):
        create_response = MagicMock(status_code=200, content=b'{"task_id":"tid-iso"}')
        create_response.json.return_value = {"task_id": "tid-iso"}
        query_done = MagicMock(status_code=200, content=b"{}")
        query_done.json.return_value = {
            "task": {
                "id": "tid-iso",
                "status": "succeeded",
                "content": {"url": "https://cdn.example.com/out.mp4"},
            }
        }
        with patch("httpx.post", return_value=create_response), patch(
            "httpx.get", return_value=query_done
        ), patch("ai.providers.minimax.video.time.sleep"), patch(
            "ai.providers.google.omni.get_genai_client"
        ) as omni_client, patch("ai.providers.google.veo.get_genai_client") as veo_client:
            MiniMaxProvider().start("Show the product", duration_seconds=5)
        omni_client.assert_not_called()
        veo_client.assert_not_called()

    @override_settings(VIDEO_PROVIDER="omni", GEMINI_API_KEY="test-key")
    def test_omni_selection_does_not_construct_minimax(self):
        self.assertEqual(video_provider_name(), "omni")
        provider = get_video_generation_provider()
        self.assertNotEqual(provider.family(), "minimax")


@override_settings(VIDEO_PROVIDER="minimax", MINIMAX_VIDEO_MODEL="MiniMax-H3")
class MiniMaxFilmRoutingTests(SimpleTestCase):
    def test_generate_continuous_film_routes_to_minimax(self):
        from ai.services.omni_film import generate_continuous_film

        service = MagicMock()
        project = MagicMock()
        with patch(
            "ai.services.minimax_film.generate_continuous_minimax_film",
            return_value=True,
        ) as minimax_film, patch(
            "ai.services.veo_film.generate_continuous_veo_film"
        ) as veo_film:
            self.assertTrue(generate_continuous_film(service, project))
        minimax_film.assert_called_once_with(service, project)
        veo_film.assert_not_called()

    def test_minimax_429_does_not_start_omni_or_veo(self):
        from ai.services.minimax_film import generate_continuous_minimax_film
        from ai.services.video import VideoGenerationService

        project = MagicMock()
        project.duration_seconds = 15
        project.scenes.all.return_value.order_by.return_value = [MagicMock()]
        project.creative_brief = {}
        minimax = MagicMock()
        minimax.family.return_value = "minimax"
        minimax.model = "MiniMax-H3"
        minimax.prepare_images.return_value = ["ref.jpg"]
        minimax.start.side_effect = ProviderError(
            "Video generation is temporarily rate limited.",
            retryable=False,
            code="RATE_LIMITED",
            status_code=429,
            provider="minimax",
        )
        service = VideoGenerationService(omni=minimax)
        service._product_first_frame = MagicMock(return_value="product.jpg")
        service._reference_images = MagicMock(return_value=["ref.jpg"])
        with patch("ai.services.minimax_film.is_studio_project", return_value=True), patch(
            "ai.services.minimax_film.raise_if_cancelled"
        ), patch("ai.services.minimax_film.presenter_image_paths", return_value=[]), patch(
            "ai.services.minimax_film.snapshot_paths", return_value=[]
        ), patch("ai.services.minimax_film.compile_film_prompt", return_value="prompt"), patch(
            "ai.providers.google.omni.GeminiOmniProvider.start"
        ) as omni_start, patch("ai.providers.google.veo.VeoProvider.start") as veo_start, patch(
            "ai.services.minimax_film._Heartbeat"
        ):
            with self.assertRaises(ProviderError) as ctx:
                generate_continuous_minimax_film(service, project)
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        omni_start.assert_not_called()
        veo_start.assert_not_called()
