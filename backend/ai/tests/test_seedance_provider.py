import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from ai.exceptions import MissingAPIKeyError, ProviderError
from ai.providers.seedance import (
    SEEDANCE_MAX_CONTINUOUS_DURATION_SECONDS,
    SEEDANCE_MODEL_2_0_FAST,
    SEEDANCE_MODEL_2_5,
    SeedanceProvider,
    extract_task_timing,
    plan_seedance_generation,
    resolve_seedance_model,
    select_seedance_reference_paths,
)
from ai.providers.video import get_video_generation_provider, video_provider_name


class SeedanceConfigTests(SimpleTestCase):
    @override_settings(VIDEO_PROVIDER="seedance", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_seedance_is_selected_from_env(self):
        self.assertEqual(video_provider_name(), "seedance")
        provider = get_video_generation_provider()
        self.assertEqual(provider.family(), "seedance")
        self.assertEqual(provider.model, SEEDANCE_MODEL_2_5)
        self.assertEqual(provider.api_version(), "2.5")

    @override_settings(VIDEO_PROVIDER="omni")
    def test_default_remains_omni(self):
        self.assertEqual(video_provider_name(), "omni")
        self.assertNotEqual(get_video_generation_provider().family(), "seedance")

    @override_settings(VIDEO_PROVIDER="both")
    def test_invalid_provider_still_fails(self):
        with self.assertRaises(ImproperlyConfigured):
            video_provider_name()

    @override_settings(SEEDANCE_API_KEY="")
    def test_missing_credentials(self):
        with self.assertRaises(MissingAPIKeyError):
            SeedanceProvider().start("Show the product", duration_seconds=5)


class SeedanceDurationPlanTests(SimpleTestCase):
    def test_single_clip_up_to_thirty(self):
        fifteen = plan_seedance_generation(15, model=SEEDANCE_MODEL_2_5)
        self.assertEqual(fifteen["clip_durations"], [15])
        self.assertEqual(fifteen["clip_count"], 1)
        self.assertEqual(fifteen["trim_to"], 0)

        thirty = plan_seedance_generation(30, model=SEEDANCE_MODEL_2_5)
        self.assertEqual(thirty["clip_durations"], [30])
        self.assertEqual(thirty["clip_count"], 1)

    def test_short_request_uses_minimum_then_trims(self):
        plan = plan_seedance_generation(3, model=SEEDANCE_MODEL_2_5)
        self.assertEqual(plan["clip_durations"], [4])
        self.assertEqual(plan["trim_to"], 3)

    def test_multi_clip_plans(self):
        forty_five = plan_seedance_generation(45, model=SEEDANCE_MODEL_2_5)
        self.assertEqual(forty_five["clip_durations"], [30, 15])
        self.assertEqual(forty_five["generated_duration"], 45)

        sixty = plan_seedance_generation(60, model=SEEDANCE_MODEL_2_5)
        self.assertEqual(sixty["clip_durations"], [30, 30])
        self.assertEqual(sixty["generated_duration"], 60)

    def test_clamp_duration_allows_thirty_on_2_5(self):
        with override_settings(SEEDANCE_MODEL=SEEDANCE_MODEL_2_5):
            provider = SeedanceProvider()
        self.assertEqual(provider.clamp_duration(30), 30)
        self.assertEqual(provider.clamp_duration(31), 30)
        self.assertEqual(provider.clamp_duration(2), 4)

    def test_over_max_is_rejected(self):
        with self.assertRaises(ProviderError) as ctx:
            plan_seedance_generation(SEEDANCE_MAX_CONTINUOUS_DURATION_SECONDS + 1)
        self.assertEqual(ctx.exception.code, "INVALID_DURATION")

    def test_fast_model_caps_at_fifteen(self):
        fifteen = plan_seedance_generation(15, model=SEEDANCE_MODEL_2_0_FAST)
        self.assertEqual(fifteen["clip_durations"], [15])
        thirty = plan_seedance_generation(30, model=SEEDANCE_MODEL_2_0_FAST)
        self.assertEqual(thirty["clip_durations"], [15, 15])
        sixty = plan_seedance_generation(60, model=SEEDANCE_MODEL_2_0_FAST)
        self.assertEqual(sixty["clip_durations"], [15, 15, 15, 15])

    def test_resolve_seedance_model_aliases(self):
        self.assertEqual(resolve_seedance_model("fast"), SEEDANCE_MODEL_2_0_FAST)
        self.assertEqual(resolve_seedance_model("2.0-fast"), SEEDANCE_MODEL_2_0_FAST)
        self.assertEqual(resolve_seedance_model(SEEDANCE_MODEL_2_0_FAST), SEEDANCE_MODEL_2_0_FAST)
        self.assertEqual(resolve_seedance_model("2.5"), SEEDANCE_MODEL_2_5)
        self.assertEqual(resolve_seedance_model(None), SEEDANCE_MODEL_2_5)
        with self.assertRaises(ProviderError):
            resolve_seedance_model("veo-3")

    @override_settings(SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_provider_accepts_per_job_model_override(self):
        provider = SeedanceProvider(model="fast")
        self.assertEqual(provider.model, SEEDANCE_MODEL_2_0_FAST)
        self.assertEqual(provider.api_version(), "2.0")
        default = SeedanceProvider()
        self.assertEqual(default.model, SEEDANCE_MODEL_2_5)

    def test_fast_model_clamps_1080p(self):
        with override_settings(
            SEEDANCE_MODEL=SEEDANCE_MODEL_2_0_FAST,
            SEEDANCE_RESOLUTION="1080p",
        ):
            provider = SeedanceProvider()
        self.assertEqual(provider.resolution, "720p")
        self.assertEqual(provider.api_version(), "2.0")
        self.assertEqual(provider.clamp_duration(20), 15)


class SeedanceReferenceTests(SimpleTestCase):
    def test_priority_and_cap(self):
        chosen = select_seedance_reference_paths(
            ["p1", "p2", "c1", "s1", "extra"],
            character_paths=["c1"],
            product_paths=["p1", "p2"],
            style_paths=["s1"],
            limit=3,
        )
        self.assertEqual(chosen, ["c1", "p1", "s1"])


class SeedanceProviderApiTests(SimpleTestCase):
    @override_settings(
        SEEDANCE_API_KEY="test-key",
        SEEDANCE_MODEL=SEEDANCE_MODEL_2_5,
        SEEDANCE_API_BASE="https://ark.ap-southeast.bytepluses.com/api/v3",
        SEEDANCE_RESOLUTION="720p",
        SEEDANCE_PRIORITY=7,
    )
    def test_start_poll_download_lifecycle(self):
        provider = SeedanceProvider()
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-1"}')
        create_response.json.return_value = {"id": "cgt-1"}
        query_queued = MagicMock(status_code=200, content=b"{}")
        query_queued.json.return_value = {"id": "cgt-1", "status": "queued"}
        query_running = MagicMock(status_code=200, content=b"{}")
        query_running.json.return_value = {"id": "cgt-1", "status": "running"}
        query_done = MagicMock(status_code=200, content=b"{}")
        query_done.json.return_value = {
            "id": "cgt-1",
            "status": "succeeded",
            "content": {"video_url": "https://cdn.example.com/out.mp4"},
            "model": SEEDANCE_MODEL_2_5,
            "duration": 15,
            "created_at": 1_000_000,
            "updated_at": 1_000_120,
            "service_tier": "default",
            "priority": 7,
        }
        download = MagicMock(status_code=200, content=b"MP4DATA", raise_for_status=MagicMock())
        with patch("httpx.post", return_value=create_response) as post, patch(
            "httpx.get", side_effect=[query_queued, query_running, query_done, download]
        ) as get, patch("ai.providers.seedance.time.sleep"):
            started = provider.start(
                "A product demo",
                duration_seconds=15,
                aspect_ratio="9:16",
                wait=True,
            )
            dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
            provider.save_video(started, dest)
        self.assertEqual(started["id"], "cgt-1")
        self.assertEqual(started["provider"], "seedance")
        self.assertEqual(started["uri"], "https://cdn.example.com/out.mp4")
        self.assertEqual(started["api_wall_seconds"], 120)
        self.assertEqual(started["first_status"], "queued")
        self.assertEqual(dest.read_bytes(), b"MP4DATA")
        dest.unlink(missing_ok=True)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], SEEDANCE_MODEL_2_5)
        self.assertEqual(payload["duration"], 15)
        self.assertEqual(payload["resolution"], "720p")
        self.assertEqual(payload["ratio"], "9:16")
        self.assertEqual(payload["service_tier"], "default")
        self.assertEqual(payload["priority"], 7)
        self.assertTrue(payload["generate_audio"])
        self.assertFalse(payload["watermark"])
        self.assertTrue(post.call_args.kwargs["headers"]["Authorization"].startswith("Bearer "))
        self.assertGreaterEqual(get.call_count, 4)

    @override_settings(
        SEEDANCE_API_KEY="test-key",
        SEEDANCE_MODEL=SEEDANCE_MODEL_2_0_FAST,
        SEEDANCE_RESOLUTION="720p",
        SEEDANCE_PRIORITY=9,
    )
    def test_fast_model_omits_service_tier(self):
        """ModelArk rejects service_tier for dreamina-seedance-2-0-fast t2v."""
        provider = SeedanceProvider()
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-fast"}')
        create_response.json.return_value = {"id": "cgt-fast"}
        with patch("httpx.post", return_value=create_response) as post, patch("httpx.get"):
            provider.start("A product demo", duration_seconds=4, wait=False)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], SEEDANCE_MODEL_2_0_FAST)
        self.assertNotIn("service_tier", payload)
        self.assertEqual(payload["priority"], 9)
        self.assertEqual(payload["resolution"], "720p")
        self.assertTrue(payload["generate_audio"])

    def test_extract_task_timing_from_api_timestamps(self):
        timing = extract_task_timing(
            {
                "created_at": 100,
                "updated_at": 250,
                "service_tier": "default",
                "priority": 5,
                "_queued_observed_ms": 10,
                "_running_observed_ms": 140_000,
                "_first_status": "running",
                "_poll_count": 12,
                "_local_poll_ms": 141_000,
            }
        )
        self.assertEqual(timing["api_wall_seconds"], 150)
        self.assertEqual(timing["first_status"], "running")
        self.assertEqual(timing["queued_observed_ms"], 10)

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_start_without_wait_returns_task_id_only(self):
        provider = SeedanceProvider()
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-async"}')
        create_response.json.return_value = {"id": "cgt-async"}
        with patch("httpx.post", return_value=create_response), patch("httpx.get") as get:
            started = provider.start("Show product", duration_seconds=8, wait=False)
        self.assertEqual(started["id"], "cgt-async")
        self.assertEqual(started["uri"], "")
        get.assert_not_called()

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_first_frame_i2v_forces_adaptive_ratio(self):
        provider = SeedanceProvider()
        frame = Path(tempfile.mkstemp(suffix=".jpg")[1])
        frame.write_bytes(b"\xff\xd8\xff" + b"1" * 64)
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-i2v"}')
        create_response.json.return_value = {"id": "cgt-i2v"}
        with patch("httpx.post", return_value=create_response) as post, patch("httpx.get"):
            started = provider.start(
                "Keep the product identical",
                first_frame_path=str(frame),
                duration_seconds=12,
                aspect_ratio="9:16",
                return_last_frame=True,
                wait=False,
            )
        frame.unlink(missing_ok=True)
        payload = post.call_args.kwargs["json"]
        roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
        self.assertEqual(roles, ["first_frame"])
        self.assertEqual(payload["ratio"], "adaptive")
        self.assertEqual(started["aspect_ratio"], "adaptive")
        self.assertEqual(started["mode"], "i2v")
        self.assertTrue(payload.get("return_last_frame"))
        self.assertNotIn("omni_reference_task_type", payload)

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_first_last_frame_uses_adaptive_ratio(self):
        provider = SeedanceProvider()
        first = Path(tempfile.mkstemp(suffix=".jpg")[1])
        last = Path(tempfile.mkstemp(suffix=".jpg")[1])
        first.write_bytes(b"\xff\xd8\xff" + b"1" * 64)
        last.write_bytes(b"\xff\xd8\xff" + b"2" * 64)
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-fl"}')
        create_response.json.return_value = {"id": "cgt-fl"}
        with patch("httpx.post", return_value=create_response) as post, patch("httpx.get"):
            provider.start(
                "Morph between frames",
                first_frame_path=str(first),
                last_frame_path=str(last),
                duration_seconds=8,
                aspect_ratio="9:16",
                wait=False,
            )
        first.unlink(missing_ok=True)
        last.unlink(missing_ok=True)
        payload = post.call_args.kwargs["json"]
        roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
        self.assertEqual(roles, ["first_frame", "last_frame"])
        self.assertEqual(payload["ratio"], "adaptive")

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_reference_image_r2v_structure(self):
        provider = SeedanceProvider()
        ref = Path(tempfile.mkstemp(suffix=".jpg")[1])
        ref.write_bytes(b"\xff\xd8\xff" + b"2" * 64)
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-r2v"}')
        create_response.json.return_value = {"id": "cgt-r2v"}
        with patch("httpx.post", return_value=create_response) as post, patch("httpx.get"):
            started = provider.start(
                "Keep the product identical",
                prepared_images=[str(ref)],
                duration_seconds=12,
                aspect_ratio="9:16",
                wait=False,
            )
        ref.unlink(missing_ok=True)
        payload = post.call_args.kwargs["json"]
        roles = [item.get("role") for item in payload["content"] if item.get("type") == "image_url"]
        self.assertEqual(roles, ["reference_image"])
        self.assertEqual(payload["ratio"], "9:16")
        self.assertEqual(payload.get("omni_reference_task_type"), "reference")
        self.assertEqual(started["mode"], "r2v")

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_0_FAST)
    def test_fast_r2v_omits_omni_reference_task_type(self):
        provider = SeedanceProvider()
        ref = Path(tempfile.mkstemp(suffix=".jpg")[1])
        ref.write_bytes(b"\xff\xd8\xff" + b"2" * 64)
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-fast-r2v"}')
        create_response.json.return_value = {"id": "cgt-fast-r2v"}
        with patch("httpx.post", return_value=create_response) as post, patch("httpx.get"):
            provider.start(
                "Product demo",
                prepared_images=[str(ref)],
                duration_seconds=4,
                generate_audio=False,
                wait=False,
            )
        ref.unlink(missing_ok=True)
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("service_tier", payload)
        self.assertNotIn("omni_reference_task_type", payload)
        self.assertFalse(payload["generate_audio"])
        self.assertEqual(payload["ratio"], "9:16")

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_mixed_first_frame_and_reference_rejected_before_api(self):
        provider = SeedanceProvider()
        frame = Path(tempfile.mkstemp(suffix=".jpg")[1])
        ref = Path(tempfile.mkstemp(suffix=".jpg")[1])
        frame.write_bytes(b"\xff\xd8\xff" + b"1" * 64)
        ref.write_bytes(b"\xff\xd8\xff" + b"2" * 64)
        with patch("httpx.post") as post:
            with self.assertRaises(ProviderError) as ctx:
                provider.start(
                    "Keep the product identical",
                    prepared_images=[str(ref)],
                    first_frame_path=str(frame),
                    duration_seconds=12,
                    wait=False,
                )
        frame.unlink(missing_ok=True)
        ref.unlink(missing_ok=True)
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")
        post.assert_not_called()

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_continuity_first_frame_keeps_return_last_frame(self):
        provider = SeedanceProvider()
        frame = Path(tempfile.mkstemp(suffix=".jpg")[1])
        frame.write_bytes(b"\xff\xd8\xff" + b"1" * 64)
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-cont"}')
        create_response.json.return_value = {"id": "cgt-cont"}
        query_done = MagicMock(status_code=200, content=b"{}")
        query_done.json.return_value = {
            "id": "cgt-cont",
            "status": "succeeded",
            "content": {
                "video_url": "https://cdn.example.com/out.mp4",
                "last_frame_url": "https://cdn.example.com/last.jpg",
            },
        }
        with patch("httpx.post", return_value=create_response) as post, patch(
            "httpx.get", return_value=query_done
        ), patch("ai.providers.seedance.time.sleep"):
            started = provider.start(
                "Continue the scene",
                first_frame_path=str(frame),
                duration_seconds=12,
                aspect_ratio="9:16",
                return_last_frame=True,
                wait=True,
            )
        frame.unlink(missing_ok=True)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["ratio"], "adaptive")
        self.assertTrue(payload.get("return_last_frame"))
        self.assertEqual(started["last_frame_url"], "https://cdn.example.com/last.jpg")
        self.assertEqual(started["mode"], "i2v")

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_explicit_silent_generation_payload(self):
        provider = SeedanceProvider()
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-silent"}')
        create_response.json.return_value = {"id": "cgt-silent"}
        with patch("httpx.post", return_value=create_response) as post, patch("httpx.get"):
            provider.start(
                "Silent product shot",
                duration_seconds=4,
                generate_audio=False,
                wait=False,
            )
        payload = post.call_args.kwargs["json"]
        self.assertFalse(payload["generate_audio"])
        self.assertEqual(payload["ratio"], "9:16")

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_rate_limit_maps_correctly(self):
        provider = SeedanceProvider()
        response = MagicMock(status_code=429, content=b"{}")
        response.json.return_value = {"error": {"message": "rate limit exceeded"}}
        with patch("httpx.post", return_value=response):
            with self.assertRaises(ProviderError) as ctx:
                provider.start("Show the product", duration_seconds=5)
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        self.assertFalse(ctx.exception.retryable)

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_auth_failure_maps_correctly(self):
        provider = SeedanceProvider()
        response = MagicMock(status_code=401, content=b"{}")
        response.json.return_value = {"error": {"message": "unauthorized"}}
        with patch("httpx.post", return_value=response):
            with self.assertRaises(ProviderError) as ctx:
                provider.start("Show the product", duration_seconds=5)
        self.assertEqual(ctx.exception.code, "AUTHENTICATION")

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_failed_task_status(self):
        provider = SeedanceProvider()
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-fail"}')
        create_response.json.return_value = {"id": "cgt-fail"}
        query_fail = MagicMock(status_code=200, content=b"{}")
        query_fail.json.return_value = {
            "id": "cgt-fail",
            "status": "failed",
            "error": {"message": "content filtered"},
        }
        with patch("httpx.post", return_value=create_response), patch(
            "httpx.get", return_value=query_fail
        ), patch("ai.providers.seedance.time.sleep"):
            with self.assertRaises(ProviderError) as ctx:
                provider.start("Show the product", duration_seconds=5, wait=True)
        self.assertEqual(ctx.exception.provider, "seedance")

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_cancel_during_poll_attempts_delete(self):
        from ai.services.cancel import CANCEL_MESSAGE, GenerationCancelled

        provider = SeedanceProvider()
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-cancel"}')
        create_response.json.return_value = {"id": "cgt-cancel"}
        delete_response = MagicMock(status_code=200, content=b"{}")
        checks = {"n": 0}

        def stop():
            checks["n"] += 1
            if checks["n"] > 1:
                raise GenerationCancelled(CANCEL_MESSAGE)

        with patch("httpx.post", return_value=create_response), patch(
            "httpx.delete", return_value=delete_response
        ) as delete, patch("httpx.get"), patch("ai.providers.seedance.time.sleep"):
            with self.assertRaises(GenerationCancelled):
                provider.start(
                    "Show the product",
                    duration_seconds=5,
                    wait=True,
                    should_stop=stop,
                )
        delete.assert_called_once()

    @override_settings(SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
    def test_timeout_is_not_retryable(self):
        provider = SeedanceProvider()
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-hang"}')
        create_response.json.return_value = {"id": "cgt-hang"}
        query_running = MagicMock(status_code=200, content=b"{}")
        query_running.json.return_value = {"id": "cgt-hang", "status": "running"}
        with patch("httpx.post", return_value=create_response), patch(
            "httpx.get", return_value=query_running
        ), patch("ai.providers.seedance.time.sleep"), patch(
            "ai.providers.seedance.seedance_operation_timeout", return_value=0
        ):
            with self.assertRaises(ProviderError) as ctx:
                provider.start("Show the product", duration_seconds=5, wait=True)
        self.assertEqual(ctx.exception.code, "TIMEOUT")
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("cgt-hang", str(ctx.exception))
        self.assertIn("not cancelled", str(ctx.exception).lower())


@override_settings(VIDEO_PROVIDER="seedance", SEEDANCE_API_KEY="test-key", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
class SeedanceIsolationTests(SimpleTestCase):
    def test_seedance_never_calls_google_or_minimax(self):
        create_response = MagicMock(status_code=200, content=b'{"id":"cgt-iso"}')
        create_response.json.return_value = {"id": "cgt-iso"}
        query_done = MagicMock(status_code=200, content=b"{}")
        query_done.json.return_value = {
            "id": "cgt-iso",
            "status": "succeeded",
            "content": {"video_url": "https://cdn.example.com/out.mp4"},
        }
        with patch("httpx.post", return_value=create_response), patch(
            "httpx.get", return_value=query_done
        ), patch("ai.providers.seedance.time.sleep"), patch(
            "ai.providers.google.omni.get_genai_client"
        ) as omni_client, patch("ai.providers.google.veo.get_genai_client") as veo_client:
            SeedanceProvider().start("Show the product", duration_seconds=5, wait=True)
        omni_client.assert_not_called()
        veo_client.assert_not_called()


@override_settings(VIDEO_PROVIDER="seedance", SEEDANCE_MODEL=SEEDANCE_MODEL_2_5)
class SeedanceFilmRoutingTests(SimpleTestCase):
    def test_generate_continuous_film_routes_to_seedance(self):
        from ai.services.omni_film import generate_continuous_film

        service = MagicMock()
        project = MagicMock()
        with patch(
            "ai.services.seedance_film.generate_continuous_seedance_film",
            return_value=True,
        ) as seedance_film, patch(
            "ai.services.veo_film.generate_continuous_veo_film"
        ) as veo_film, patch(
            "ai.services.minimax_film.generate_continuous_minimax_film"
        ) as minimax_film:
            self.assertTrue(generate_continuous_film(service, project))
        seedance_film.assert_called_once_with(service, project)
        veo_film.assert_not_called()
        minimax_film.assert_not_called()

    def test_seedance_429_does_not_start_other_providers(self):
        from ai.services.seedance_film import generate_continuous_seedance_film
        from ai.services.video import VideoGenerationService

        project = MagicMock()
        project.duration_seconds = 15
        project.scenes.all.return_value.order_by.return_value = [MagicMock()]
        project.creative_brief = {}
        seedance = MagicMock()
        seedance.family.return_value = "seedance"
        seedance.model = SEEDANCE_MODEL_2_5
        seedance.api_version.return_value = "2.5"
        seedance.resolution = "720p"
        seedance.priority = 5
        seedance.prepare_images.return_value = ["ref.jpg"]
        seedance.start.side_effect = ProviderError(
            "Video generation is temporarily rate limited.",
            retryable=False,
            code="RATE_LIMITED",
            status_code=429,
            provider="seedance",
        )
        service = VideoGenerationService(omni=seedance)
        service._product_first_frame = MagicMock(return_value="product.jpg")
        service._reference_images = MagicMock(return_value=["ref.jpg"])
        with patch("ai.services.seedance_film.is_studio_project", return_value=True), patch(
            "ai.services.seedance_film.raise_if_cancelled"
        ), patch("ai.services.seedance_film.presenter_image_paths", return_value=[]), patch(
            "ai.services.seedance_film.snapshot_paths", return_value=[]
        ), patch("ai.services.seedance_film.compile_film_prompt", return_value="prompt"), patch(
            "ai.providers.google.omni.GeminiOmniProvider.start"
        ) as omni_start, patch("ai.providers.google.veo.VeoProvider.start") as veo_start, patch(
            "ai.providers.minimax.MiniMaxProvider.start"
        ) as minimax_start, patch("ai.services.seedance_film._Heartbeat"):
            with self.assertRaises(ProviderError) as ctx:
                generate_continuous_seedance_film(service, project)
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        omni_start.assert_not_called()
        veo_start.assert_not_called()
        minimax_start.assert_not_called()

    def test_film_separates_r2v_and_continuity_i2v(self):
        """Hop 0 uses reference images; hop 1 uses first_frame continuity only."""
        from ai.services.seedance_film import generate_continuous_seedance_film
        from ai.services.video import VideoGenerationService

        project = MagicMock()
        project.duration_seconds = 45  # 2.5 → [30, 15]
        project.scenes.all.return_value.order_by.return_value = [MagicMock()]
        project.creative_brief = {}
        project.pk = 42

        calls = []

        def fake_start(*args, **kwargs):
            calls.append(kwargs)
            hop = kwargs.get("attempt_context", {}).get("hop_index", 0)
            dest_ok = {
                "id": f"cgt-{hop}",
                "uri": f"https://cdn.example.com/{hop}.mp4",
                "mode": "r2v" if hop == 0 else "i2v",
                "aspect_ratio": "9:16" if hop == 0 else "adaptive",
                "duration_requested": kwargs.get("duration_seconds"),
                "submit_ms": 1,
                "provider_wait_ms": 1,
                "last_frame_url": "https://cdn.example.com/last.jpg" if hop == 0 else "",
                "task": "generate" if hop == 0 else "continue",
            }
            return dest_ok

        seedance = MagicMock()
        seedance.family.return_value = "seedance"
        seedance.model = SEEDANCE_MODEL_2_5
        seedance.api_version.return_value = "2.5"
        seedance.resolution = "720p"
        seedance.priority = 5
        seedance.prepare_images.return_value = ["product.jpg", "character.jpg"]
        seedance.start.side_effect = fake_start
        def _save_video(task, dest):
            path = Path(dest)
            path.write_bytes(b"MP4")
            return path

        def _download_last_frame(url, dest):
            path = Path(dest)
            path.write_bytes(b"\xff\xd8\xff" + b"x" * 64)
            return path

        seedance.save_video.side_effect = _save_video
        seedance.download_last_frame.side_effect = _download_last_frame

        service = VideoGenerationService(omni=seedance)
        service._product_first_frame = MagicMock(return_value="product.jpg")
        service._reference_images = MagicMock(return_value=["product.jpg", "character.jpg"])

        with patch("ai.services.seedance_film.is_studio_project", return_value=True), patch(
            "ai.services.seedance_film.raise_if_cancelled"
        ), patch("ai.services.seedance_film.presenter_image_paths", return_value=["character.jpg"]), patch(
            "ai.services.seedance_film.snapshot_paths", return_value=["product.jpg"]
        ), patch("ai.services.seedance_film.compile_film_prompt", return_value="prompt"), patch(
            "ai.services.seedance_film._Heartbeat"
        ), patch(
            "ai.services.seedance_film._log_probe",
            return_value={"has_video": True, "has_audio": True, "duration": 15},
        ), patch(
            "ai.services.seedance_film.concat_clips",
            side_effect=lambda clips, dest, fade=0: Path(dest).write_bytes(b"MP4JOINED"),
        ), patch(
            "ai.services.seedance_film.probe_media", return_value={"duration": 45}
        ), patch("ai.services.seedance_film._split_scene_clips"), patch(
            "ai.services.seedance_film._burn_preview",
            side_effect=lambda p, s, path: Path(path),
        ), patch("ai.services.seedance_film._store_duration_report"), patch(
            "ai.services.seedance_film.media_exists", return_value=True
        ), patch("ai.services.seedance_film.ContentFile", return_value=MagicMock()), patch(
            "ai.services.poster.save_video_poster"
        ):
            self.assertTrue(generate_continuous_seedance_film(service, project))

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["prepared_images"], ["product.jpg", "character.jpg"])
        self.assertIsNone(calls[0]["first_frame_path"])
        self.assertTrue(calls[0]["generate_audio"])
        self.assertTrue(calls[0]["return_last_frame"])
        self.assertIsNotNone(calls[1]["first_frame_path"])
        self.assertIsNone(calls[1]["prepared_images"])
        self.assertFalse(calls[1]["return_last_frame"])
