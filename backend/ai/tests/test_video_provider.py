from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from ai.exceptions import ProviderError
from ai.providers.google.veo import (
    VEO_MAX_CONTINUOUS_DURATION_SECONDS,
    VeoProvider,
    plan_veo_generation,
    select_veo_reference_paths,
)
from ai.providers.video import get_video_generation_provider, video_provider_name
from ai.providers.google.omni import GeminiOmniProvider
from ai.services.omni_film import generate_continuous_film
from ai.services.video import VideoGenerationService


class VideoProviderConfigTests(SimpleTestCase):
    @override_settings(VIDEO_PROVIDER="omni")
    def test_omni_is_the_default_provider(self):
        self.assertEqual(video_provider_name(), "omni")
        self.assertIsInstance(get_video_generation_provider(), GeminiOmniProvider)

    @override_settings(VIDEO_PROVIDER="veo", VEO_MODEL="veo-3.1-generate-preview")
    def test_veo_is_selected_from_env(self):
        self.assertEqual(video_provider_name(), "veo")
        provider = get_video_generation_provider()
        self.assertEqual(provider.family(), "veo")
        self.assertEqual(provider.model, "veo-3.1-generate-preview")

    @override_settings(VIDEO_PROVIDER="minimax", MINIMAX_VIDEO_MODEL="MiniMax-H3")
    def test_minimax_is_selected_from_env(self):
        self.assertEqual(video_provider_name(), "minimax")
        provider = get_video_generation_provider()
        self.assertEqual(provider.family(), "minimax")
        self.assertEqual(provider.model, "MiniMax-H3")

    @override_settings(VIDEO_PROVIDER="seedance", SEEDANCE_MODEL="dreamina-seedance-2-5-260628")
    def test_seedance_is_selected_from_env(self):
        self.assertEqual(video_provider_name(), "seedance")
        provider = get_video_generation_provider()
        self.assertEqual(provider.family(), "seedance")
        self.assertEqual(provider.model, "dreamina-seedance-2-5-260628")

    @override_settings(VIDEO_PROVIDER="both")
    def test_invalid_provider_fails_configuration(self):
        with self.assertRaises(ImproperlyConfigured):
            video_provider_name()


class VeoDurationPlanTests(SimpleTestCase):
    def test_official_hop_sizes(self):
        eight = plan_veo_generation(8)
        self.assertEqual(eight["initial_duration"], 8)
        self.assertEqual(eight["extension_count"], 0)
        self.assertEqual(eight["generated_duration"], 8)
        self.assertEqual(eight["trim_to"], 0)

        short = plan_veo_generation(5)
        self.assertEqual(short["generated_duration"], 8)
        self.assertEqual(short["trim_to"], 5)

        fifteen = plan_veo_generation(15)
        self.assertEqual(fifteen["extension_count"], 1)
        self.assertEqual(fifteen["generated_duration"], 15)

        thirty = plan_veo_generation(30)
        self.assertEqual(thirty["extension_count"], 4)
        self.assertEqual(thirty["generated_duration"], 36)
        self.assertEqual(thirty["trim_to"], 30)

        forty_five = plan_veo_generation(45)
        self.assertEqual(forty_five["extension_count"], 6)
        self.assertEqual(forty_five["generated_duration"], 50)
        self.assertEqual(forty_five["trim_to"], 45)

        sixty = plan_veo_generation(60)
        self.assertEqual(sixty["extension_count"], 8)
        self.assertEqual(sixty["generated_duration"], 64)
        self.assertEqual(sixty["trim_to"], 60)

        maxed = plan_veo_generation(148)
        self.assertEqual(maxed["extension_count"], 20)
        self.assertEqual(maxed["generated_duration"], VEO_MAX_CONTINUOUS_DURATION_SECONDS)

    def test_over_max_is_rejected(self):
        with self.assertRaises(ProviderError) as ctx:
            plan_veo_generation(149)
        self.assertEqual(ctx.exception.code, "INVALID_DURATION")


class VeoReferenceTests(SimpleTestCase):
    def test_caps_at_three_with_character_product_style_priority(self):
        chosen = select_veo_reference_paths(
            ["p1", "p2", "c1", "s1", "extra"],
            character_paths=["c1"],
            product_paths=["p1", "p2"],
            style_paths=["s1"],
        )
        self.assertEqual(chosen, ["c1", "p1", "s1"])
        self.assertEqual(len(chosen), 3)


class VeoProviderErrorTests(SimpleTestCase):
    def test_429_is_rate_limited(self):
        class TooMany(Exception):
            status_code = 429

            def __str__(self):
                return "Rate limit exceeded. Please retry in 2h10m5s."

        wrapped = VeoProvider()._wrap_error(TooMany(), "fallback")
        self.assertEqual(wrapped.code, "RATE_LIMITED")
        self.assertFalse(wrapped.retryable)
        self.assertIn("temporarily rate limited", str(wrapped))
        self.assertEqual(wrapped.retry_after, "2h10m5s")

    def test_timeout_is_not_retryable(self):
        class Hung(Exception):
            status_code = 408

            def __str__(self):
                return "timed out"

        wrapped = VeoProvider()._wrap_error(Hung(), "fallback")
        self.assertEqual(wrapped.code, "TIMEOUT")
        self.assertFalse(wrapped.retryable)

    def test_5xx_is_provider_error(self):
        class Boom(Exception):
            status_code = 503

            def __str__(self):
                return "unavailable"

        wrapped = VeoProvider()._wrap_error(Boom(), "fallback")
        self.assertEqual(wrapped.code, "PROVIDER_ERROR")

    def test_empty_result_is_invalid_video(self):
        from pathlib import Path
        import tempfile

        dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
        dest.unlink(missing_ok=True)
        with self.assertRaises(ProviderError) as ctx:
            VeoProvider().save_video({"inline": b"", "uri": "", "path": ""}, dest)
        self.assertEqual(ctx.exception.code, "INVALID_VIDEO")

    def test_rai_filtered_clip_is_blocked(self):
        operation = MagicMock(done=True, error=None, name="ops/rai")
        operation.response = MagicMock(
            generated_videos=[],
            rai_media_filtered_count=1,
            rai_media_filtered_reasons=["AUDIO"],
        )
        with self.assertRaises(ProviderError) as ctx:
            VeoProvider()._raise_if_empty_generation(operation, None)
        self.assertIn("blocked", str(ctx.exception).lower())
        self.assertEqual(ctx.exception.code, "PROVIDER_ERROR")

    @override_settings(VIDEO_PROVIDER="veo", GEMINI_API_KEY="test-key")
    def test_rai_block_retries_once_then_succeeds(self):
        blocked = MagicMock(done=True, error=None, name="ops/rai")
        blocked.response = MagicMock(
            generated_videos=[],
            rai_media_filtered_count=1,
            rai_media_filtered_reasons=["AUDIO"],
        )
        blocked.result = blocked.response
        ok = MagicMock(done=True, error=None, name="ops/ok")
        video = MagicMock(uri="", video_bytes=b"MP4", data=b"MP4", save=None)
        ok.response = MagicMock(generated_videos=[MagicMock(video=video)])
        ok.result = ok.response
        provider = VeoProvider()
        with patch.object(provider, "_create", side_effect=[blocked, ok]) as create:
            started = provider.start("Show the product", duration_seconds=8)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(started["inline"], b"MP4")

    @override_settings(VIDEO_PROVIDER="veo", GEMINI_API_KEY="test-key")
    def test_rai_block_fails_after_one_retry(self):
        blocked = MagicMock(done=True, error=None, name="ops/rai")
        blocked.response = MagicMock(
            generated_videos=[],
            rai_media_filtered_count=1,
            rai_media_filtered_reasons=["AUDIO"],
        )
        blocked.result = blocked.response
        provider = VeoProvider()
        with patch.object(provider, "_create", return_value=blocked) as create:
            with self.assertRaises(ProviderError) as ctx:
                provider.start("Show the product", duration_seconds=8)
        self.assertEqual(create.call_count, 2)
        self.assertIn("blocked", str(ctx.exception).lower())

    def test_cancel_during_poll_is_not_wrapped(self):
        from ai.services.cancel import CANCEL_MESSAGE, GenerationCancelled

        operation = MagicMock(done=False, error=None, name="ops/cancel")
        with self.assertRaises(GenerationCancelled):
            VeoProvider().poll(
                operation,
                timeout_seconds=30,
                interval_seconds=5,
                should_stop=lambda: (_ for _ in ()).throw(GenerationCancelled(CANCEL_MESSAGE)),
            )

    @override_settings(VIDEO_PROVIDER="veo", GEMINI_API_KEY="test-key")
    def test_start_does_not_wrap_cancel(self):
        from ai.services.cancel import CANCEL_MESSAGE, GenerationCancelled

        operation = MagicMock(done=False, error=None, name="ops/cancel")
        provider = VeoProvider()
        with patch.object(provider, "_create", return_value=operation), patch.object(
            provider, "poll", side_effect=GenerationCancelled(CANCEL_MESSAGE)
        ):
            with self.assertRaises(GenerationCancelled):
                provider.start("Show the product", duration_seconds=8)


@override_settings(VIDEO_PROVIDER="omni", GEMINI_API_KEY="test-key")
class ProviderIsolationTests(SimpleTestCase):
    def test_omni_never_calls_generate_videos(self):
        from ai.providers.google.omni import GeminiOmniProvider

        client = MagicMock()
        video = MagicMock(uri="https://generativelanguage.googleapis.com/v1beta/files/abc123:download?alt=media", data=None)
        client.interactions.create.return_value = MagicMock(id="v1", status="completed", output_video=video)
        with patch("ai.providers.google.omni.get_genai_client", return_value=client), patch(
            "ai.providers.google.veo.get_genai_client"
        ) as veo_client:
            GeminiOmniProvider().start("Show the product", duration_seconds=8)
        veo_client.assert_not_called()
        client.models.generate_videos.assert_not_called()
        client.interactions.create.assert_called_once()

    @override_settings(VIDEO_PROVIDER="veo", VEO_MODEL="veo-3.1-generate-preview")
    def test_veo_never_calls_interactions_create(self):
        operation = MagicMock(done=True, error=None, name="ops/1")
        video = MagicMock(uri="", video_bytes=b"MP4", data=b"MP4", save=None)
        generated = MagicMock(video=video)
        operation.response = MagicMock(generated_videos=[generated])
        client = MagicMock()
        client.models.generate_videos.return_value = operation
        with patch("ai.providers.google.veo.get_genai_client", return_value=client), patch(
            "ai.providers.google.omni.get_genai_client"
        ) as omni_client:
            started = VeoProvider().start("Show the product", duration_seconds=8)
        omni_client.assert_not_called()
        client.interactions.create.assert_not_called()
        client.models.generate_videos.assert_called_once()
        self.assertEqual(started["task"], "generate")
        self.assertEqual(started["inline"], b"MP4")
        kwargs = client.models.generate_videos.call_args.kwargs
        self.assertEqual(kwargs["model"], "veo-3.1-generate-preview")
        self.assertEqual(kwargs["config"].duration_seconds, 8)
        self.assertIsNone(kwargs["config"].generate_audio)
        self.assertIsNone(kwargs["config"].enhance_prompt)
        self.assertIsNone(kwargs["config"].person_generation)

    @override_settings(VIDEO_PROVIDER="veo", GEMINI_API_KEY="test-key")
    def test_uri_only_video_is_downloaded_via_files_api(self):
        from pathlib import Path
        import tempfile

        operation = MagicMock(done=True, error=None, name="ops/dl")
        video = MagicMock(
            uri="https://generativelanguage.googleapis.com/v1beta/files/abc123:download?alt=media",
            video_bytes=None,
            data=None,
        )
        video.save.side_effect = NotImplementedError("Saving remote videos is not supported.")
        operation.response = MagicMock(generated_videos=[MagicMock(video=video)])
        operation.result = operation.response
        dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
        dest.unlink(missing_ok=True)
        client = MagicMock()
        client.files.download.return_value = b"VEOMP4"
        with patch("ai.providers.google.veo.get_genai_client", return_value=client):
            saved = VeoProvider().save_video({"operation": operation, "inline": b"", "uri": ""}, dest)
        self.assertEqual(saved.read_bytes(), b"VEOMP4")
        client.files.download.assert_called()
        self.assertIs(client.files.download.call_args.kwargs["file"], video)

    @override_settings(VIDEO_PROVIDER="veo")
    def test_extension_sends_previous_video_and_no_references(self):
        operation = MagicMock(done=True, error=None, name="ops/2")
        video = MagicMock(uri="", video_bytes=b"EXT", data=b"EXT", save=None)
        operation.response = MagicMock(generated_videos=[MagicMock(video=video)])
        provider = VeoProvider()
        with patch.object(provider, "_create", return_value=operation) as create:
            provider.start("Continue", video_path="/tmp/prev.mp4", prepared_images=["/tmp/a.png"])
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["video_path"], "/tmp/prev.mp4")
        self.assertEqual(kwargs["reference_paths"], [])
        self.assertEqual(kwargs["duration_seconds"], 0)

    @override_settings(VIDEO_PROVIDER="veo")
    def test_extension_forwards_previous_generated_video(self):
        operation = MagicMock(done=True, error=None, name="ops/2")
        video = MagicMock(uri="https://files/next", video_bytes=b"EXT", data=b"EXT", save=None)
        operation.response = MagicMock(generated_videos=[MagicMock(video=video)])
        previous = MagicMock(uri="https://generativelanguage.googleapis.com/files/abc")
        provider = VeoProvider()
        with patch.object(provider, "_create", return_value=operation) as create:
            provider.start(
                "Continue",
                video_path="/tmp/prev.mp4",
                previous_video=previous,
                previous_video_uri="https://generativelanguage.googleapis.com/files/abc",
            )
        self.assertIs(create.call_args.kwargs["previous_video"], previous)
        self.assertEqual(
            create.call_args.kwargs["previous_video_uri"],
            "https://generativelanguage.googleapis.com/files/abc",
        )

    @override_settings(VIDEO_PROVIDER="veo", GEMINI_API_KEY="test-key")
    def test_extension_create_sends_previous_uri_only(self):
        from google.genai import types

        operation = MagicMock(done=True, error=None, name="ops/ext")
        video = MagicMock(uri="", video_bytes=b"EXT", data=b"EXT")
        operation.response = MagicMock(generated_videos=[MagicMock(video=video)])
        client = MagicMock()
        client.models.generate_videos.return_value = operation
        previous = types.Video(
            uri="https://generativelanguage.googleapis.com/files/abc",
            video_bytes=b"PREVMP4",
            mime_type="video/mp4",
        )
        with patch("ai.providers.google.veo.get_genai_client", return_value=client):
            VeoProvider()._create(
                "Continue",
                video_path="/tmp/prev.mp4",
                previous_video=previous,
                previous_video_uri="https://generativelanguage.googleapis.com/files/abc",
                reference_paths=["/tmp/a.png"],
                duration_seconds=0,
                aspect_ratio="9:16",
                generate_audio=True,
            )
        source = client.models.generate_videos.call_args.kwargs["source"]
        config = client.models.generate_videos.call_args.kwargs["config"]
        self.assertEqual(source.video.uri, "https://generativelanguage.googleapis.com/files/abc")
        self.assertIsNone(source.video.video_bytes)
        self.assertIsNone(source.video.mime_type)
        self.assertIsNone(config.duration_seconds)
        self.assertIsNone(config.reference_images)
        self.assertEqual(config.resolution, "720p")
        self.assertEqual(config.number_of_videos, 1)

    @override_settings(VIDEO_PROVIDER="veo", GEMINI_API_KEY="test-key")
    def test_extension_waits_when_previous_veo_video_is_not_processed(self):
        from google.genai.errors import ClientError

        operation = MagicMock(done=True, error=None, name="ops/ext")
        not_ready = ClientError(
            400,
            {
                "error": {
                    "code": 400,
                    "message": "Input video must be a video that was generated by VEO that has been processed.",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )
        client = MagicMock()
        client.models.generate_videos.side_effect = [not_ready, operation]
        with (
            patch("ai.providers.google.veo.get_genai_client", return_value=client),
            patch("ai.providers.google.veo.time.sleep") as sleep,
        ):
            result = VeoProvider()._create(
                "Continue",
                video_path=None,
                previous_video=None,
                previous_video_uri="https://generativelanguage.googleapis.com/files/abc",
                reference_paths=[],
                duration_seconds=0,
                aspect_ratio="9:16",
                generate_audio=True,
            )
        self.assertIs(result, operation)
        self.assertEqual(client.models.generate_videos.call_count, 2)
        sleep.assert_called_once()
        self.assertIsNone(client.models.generate_videos.call_args.kwargs["source"].video.video_bytes)

    @override_settings(VIDEO_PROVIDER="veo", GEMINI_API_KEY="test-key")
    def test_other_extension_rejection_is_not_retried(self):
        from google.genai.errors import ClientError

        rejected = ClientError(400, {"error": {"code": 400, "message": "encoding isn't supported", "status": "INVALID_ARGUMENT"}})
        client = MagicMock()
        client.models.generate_videos.side_effect = rejected
        with (
            patch("ai.providers.google.veo.get_genai_client", return_value=client),
            patch("ai.providers.google.veo.time.sleep") as sleep,
        ):
            with self.assertRaises(ClientError):
                VeoProvider()._create(
                    "Continue",
                    video_path=None,
                    previous_video=None,
                    previous_video_uri="https://generativelanguage.googleapis.com/files/abc",
                    reference_paths=[],
                    duration_seconds=0,
                    aspect_ratio="9:16",
                    generate_audio=True,
                )
        self.assertEqual(client.models.generate_videos.call_count, 1)
        sleep.assert_not_called()

    @override_settings(VIDEO_PROVIDER="veo", GEMINI_API_KEY="test-key")
    def test_extension_without_generated_uri_is_rejected(self):
        with self.assertRaises(ProviderError) as ctx:
            VeoProvider()._create(
                "Continue",
                video_path="/tmp/prev.mp4",
                previous_video=None,
                previous_video_uri="",
                reference_paths=[],
                duration_seconds=0,
                aspect_ratio="9:16",
                generate_audio=True,
            )
        self.assertEqual(ctx.exception.code, "PROVIDER_ERROR")


@override_settings(VIDEO_PROVIDER="omni")
class NoFallbackTests(TestCase):
    def test_omni_429_does_not_start_veo(self):
        from ai.models import Scene, VideoProject, VideoProjectStatus
        from ai.services.omni_film import generate_continuous_film
        from ai.services.video import VideoGenerationService
        from ai.tests.test_studio import _png
        from accounts.models import User
        from brands.models import Brand, Category, Product, ProductImage
        from ai.services.snapshots import product_snapshot

        category = Category.objects.create(name="Kitchen", slug="kitchen-provider")
        owner = User.objects.create_user(
            username="provider-owner",
            email="provider@example.com",
            password="password123",
            name="Owner",
            mobile="0123999000",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        brand = Brand.objects.create(owner=owner, category=category, name="Brand", description="K", location="KL")
        product = Product.objects.create(brand=brand, name="Pan", description="Steel.", price="10.00")
        ProductImage.objects.create(product=product, image=_png())
        project = VideoProject.objects.create(
            owner=owner,
            product=product,
            product_snapshot=product_snapshot(product),
            language="english",
            speaker_gender="female",
            selected_concept_id="demo",
            duration_seconds=15,
            creative_brief={"schema_version": 2},
            status=VideoProjectStatus.GENERATING_VIDEO,
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            title="Open",
            visual="Show pan",
            narration="Hello.",
            caption="Hello.",
            duration=5,
            metadata={"status": "ready"},
        )
        omni = MagicMock()
        omni.model = "gemini-omni-1.1-flash"
        omni.family.return_value = "omni"
        omni.prepare_images.return_value = []
        omni.start.side_effect = ProviderError(
            "Video generation is temporarily rate limited.",
            retryable=False,
            code="RATE_LIMITED",
            status_code=429,
        )
        with patch("ai.providers.google.veo.VeoProvider.start") as veo_start:
            with self.assertRaises(ProviderError) as ctx:
                generate_continuous_film(VideoGenerationService(omni=omni), project)
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        veo_start.assert_not_called()


@override_settings(VIDEO_PROVIDER="veo", VEO_MODEL="veo-3.1-generate-preview")
class VeoFilmTests(TestCase):
    def test_fifteen_seconds_is_one_create_and_one_extension(self):
        from ai.models import Scene, VideoProject, VideoProjectStatus
        from ai.services.omni_film import generate_continuous_film
        from ai.services.video import VideoGenerationService
        from ai.tests.test_studio import _png
        from accounts.models import User
        from brands.models import Brand, Category, Product, ProductImage
        from ai.services.snapshots import product_snapshot

        category = Category.objects.create(name="Kitchen", slug="kitchen-veo-film")
        owner = User.objects.create_user(
            username="veo-owner",
            email="veo@example.com",
            password="password123",
            name="Owner",
            mobile="0123999111",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        brand = Brand.objects.create(owner=owner, category=category, name="Brand", description="K", location="KL")
        product = Product.objects.create(brand=brand, name="Pan", description="Steel.", price="10.00")
        ProductImage.objects.create(product=product, image=_png())
        project = VideoProject.objects.create(
            owner=owner,
            product=product,
            product_snapshot=product_snapshot(product),
            language="english",
            speaker_gender="female",
            selected_concept_id="demo",
            duration_seconds=15,
            creative_brief={"schema_version": 2},
            status=VideoProjectStatus.GENERATING_VIDEO,
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            title="Open",
            visual="Show pan",
            narration="Hello.",
            caption="Hello.",
            duration=15,
            metadata={"caption_locked": True, "status": "ready"},
        )
        calls = []

        def fake_start(prompt, **kwargs):
            calls.append(kwargs | {"prompt": prompt})
            hop = len(calls)
            return {
                "id": f"op-{hop}",
                "inline": b"VEOMP4",
                "uri": f"https://generativelanguage.googleapis.com/files/hop-{hop}",
                "generated_video": MagicMock(uri=f"https://generativelanguage.googleapis.com/files/hop-{hop}"),
                "model": "veo-3.1-generate-preview",
                "task": "extend" if kwargs.get("video_path") else "generate",
                "duration_requested": 8 if not kwargs.get("video_path") else 7,
            }

        veo = MagicMock()
        veo.model = "veo-3.1-generate-preview"
        veo.family.return_value = "veo"
        veo.prepare_images.side_effect = lambda paths, **kwargs: list(paths)[:3]
        veo.start.side_effect = fake_start
        veo.save_video.side_effect = lambda task, dest: dest.write_bytes(b"VEOMP4")
        service = VideoGenerationService(omni=veo)
        with (
            patch(
                "ai.services.veo_film.probe_media",
                return_value={
                    "has_video": True,
                    "has_audio": True,
                    "duration": 15,
                    "audio_codec": "aac",
                    "video_codec": "h264",
                    "width": 720,
                    "height": 1280,
                    "fps": 24,
                },
            ),
            patch("ai.services.omni_film.burn_captions", side_effect=lambda src, captions, dest: dest.write_bytes(b"CAPTIONED")),
            patch("ai.services.omni_film.split_copy", side_effect=lambda src, dest, start, end: dest.write_bytes(b"PART")),
            patch("ai.services.omni_film.probe_media", return_value={"has_video": True, "has_audio": True, "duration": 15, "audio_codec": "aac", "video_codec": "h264", "width": 720, "height": 1280, "fps": 24}),
            patch("ai.services.poster.save_video_poster"),
            patch("ai.providers.google.omni.GeminiOmniProvider.start") as omni_start,
        ):
            self.assertTrue(generate_continuous_film(service, project))
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[0].get("video_path"))
        self.assertTrue(calls[0].get("prepared_images"))
        self.assertTrue(calls[1].get("video_path"))
        self.assertEqual(
            calls[1].get("previous_video_uri"),
            "https://generativelanguage.googleapis.com/files/hop-1",
        )
        self.assertIsNotNone(calls[1].get("previous_video"))
        self.assertIsNone(calls[1].get("prepared_images"))
        self.assertIn("The presenter says exactly", calls[0]["prompt"])
        omni_start.assert_not_called()
        metrics = (project.creative_brief or {}).get("generation_metrics") or {}
        self.assertEqual(metrics.get("video_provider"), "veo")
        self.assertEqual(metrics.get("veo_extension_count"), 1)

    def test_download_failure_is_download_failed(self):
        project = self._project("veo-dl", duration=8)
        veo = self._veo_mock()
        veo.save_video.side_effect = ProviderError(
            "The generated video could not be downloaded.",
            retryable=False,
            code="DOWNLOAD_FAILED",
        )
        with patch("ai.providers.google.omni.GeminiOmniProvider.start") as omni_start:
            with self.assertRaises(ProviderError) as ctx:
                generate_continuous_film(VideoGenerationService(omni=veo), project)
        self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")
        omni_start.assert_not_called()

    def test_missing_audio_is_classified(self):
        project = self._project("veo-audio", duration=8)
        veo = self._veo_mock()
        silent = {
            "has_video": True,
            "has_audio": False,
            "duration": 8,
            "audio_codec": "",
            "video_codec": "h264",
            "width": 720,
            "height": 1280,
            "fps": 24,
        }
        with (
            patch("ai.services.veo_film.probe_media", return_value=silent),
            patch("ai.services.omni_film.probe_media", return_value=silent),
            patch("ai.providers.google.omni.GeminiOmniProvider.start") as omni_start,
        ):
            with self.assertRaises(ProviderError) as ctx:
                generate_continuous_film(VideoGenerationService(omni=veo), project)
        self.assertEqual(ctx.exception.code, "MISSING_AUDIO")
        omni_start.assert_not_called()

    def test_invalid_video_is_classified(self):
        project = self._project("veo-invalid", duration=8)
        veo = self._veo_mock()
        empty = {
            "has_video": False,
            "has_audio": False,
            "duration": 0,
            "audio_codec": "",
            "video_codec": "",
            "width": 0,
            "height": 0,
            "fps": 0,
        }
        with (
            patch("ai.services.veo_film.probe_media", return_value=empty),
            patch("ai.services.omni_film.probe_media", return_value=empty),
            patch("ai.providers.google.omni.GeminiOmniProvider.start") as omni_start,
        ):
            with self.assertRaises(ProviderError) as ctx:
                generate_continuous_film(VideoGenerationService(omni=veo), project)
        self.assertEqual(ctx.exception.code, "INVALID_VIDEO")
        omni_start.assert_not_called()

    def test_thirty_seconds_trims_to_requested_duration(self):
        project = self._project("veo-trim", duration=30)
        veo = self._veo_mock()
        trim = MagicMock(side_effect=lambda src, dest, duration: dest.write_bytes(b"TRIM"))
        probe = {
            "has_video": True,
            "has_audio": True,
            "duration": 36,
            "audio_codec": "aac",
            "video_codec": "h264",
            "width": 720,
            "height": 1280,
            "fps": 24,
        }
        with (
            patch("ai.services.veo_film.probe_media", return_value=probe),
            patch("ai.services.omni_film.probe_media", return_value=probe),
            patch("ai.services.veo_film.trim_copy", trim),
            patch("ai.services.omni_film.burn_captions", side_effect=lambda src, captions, dest: dest.write_bytes(b"CAPTIONED")),
            patch("ai.services.omni_film.split_copy", side_effect=lambda src, dest, start, end: dest.write_bytes(b"PART")),
            patch("ai.services.poster.save_video_poster"),
            patch("ai.providers.google.omni.GeminiOmniProvider.start") as omni_start,
        ):
            self.assertTrue(generate_continuous_film(VideoGenerationService(omni=veo), project))
        self.assertEqual(len(veo.start.call_args_list), 5)
        self.assertTrue(trim.called)
        self.assertEqual(trim.call_args.args[2], 30)
        omni_start.assert_not_called()
        metrics = (project.creative_brief or {}).get("generation_metrics") or {}
        self.assertEqual(metrics.get("veo_generated_duration"), 36)
        self.assertEqual(metrics.get("veo_extension_count"), 4)

    def test_veo_429_does_not_start_omni(self):
        project = self._project("veo-429", duration=8)
        veo = MagicMock()
        veo.model = "veo-3.1-generate-preview"
        veo.family.return_value = "veo"
        veo.prepare_images.return_value = []
        veo.start.side_effect = ProviderError(
            "Video generation is temporarily rate limited.",
            retryable=False,
            code="RATE_LIMITED",
            status_code=429,
        )
        with patch("ai.providers.google.omni.GeminiOmniProvider.start") as omni_start:
            with self.assertRaises(ProviderError) as ctx:
                generate_continuous_film(VideoGenerationService(omni=veo), project)
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        omni_start.assert_not_called()

    def _project(self, suffix, duration=8):
        from ai.models import Scene, VideoProject, VideoProjectStatus
        from ai.tests.test_studio import _png
        from accounts.models import User
        from brands.models import Brand, Category, Product, ProductImage
        from ai.services.snapshots import product_snapshot

        category = Category.objects.create(name="Kitchen", slug=f"kitchen-{suffix}")
        owner = User.objects.create_user(
            username=f"owner-{suffix}",
            email=f"{suffix}@example.com",
            password="password123",
            name="Owner",
            mobile=f"01{abs(hash(suffix)) % 10**8:08d}",
            location="Kuala Lumpur",
            role=User.Role.PRODUCER,
        )
        brand = Brand.objects.create(owner=owner, category=category, name="Brand", description="K", location="KL")
        product = Product.objects.create(brand=brand, name="Pan", description="Steel.", price="10.00")
        ProductImage.objects.create(product=product, image=_png())
        project = VideoProject.objects.create(
            owner=owner,
            product=product,
            product_snapshot=product_snapshot(product),
            language="english",
            speaker_gender="female",
            selected_concept_id="demo",
            duration_seconds=duration,
            creative_brief={"schema_version": 2},
            status=VideoProjectStatus.GENERATING_VIDEO,
        )
        Scene.objects.create(
            project=project,
            scene_key="scene-1",
            order=1,
            title="Open",
            visual="Show pan",
            narration="Hello.",
            caption="Hello.",
            duration=duration,
            metadata={"status": "ready"},
        )
        return project

    def _veo_mock(self):
        calls = []

        def fake_start(prompt, **kwargs):
            calls.append(kwargs | {"prompt": prompt})
            hop = len(calls)
            return {
                "id": f"op-{hop}",
                "inline": b"VEOMP4",
                "uri": f"https://generativelanguage.googleapis.com/files/hop-{hop}",
                "generated_video": MagicMock(uri=f"https://generativelanguage.googleapis.com/files/hop-{hop}"),
                "model": "veo-3.1-generate-preview",
                "task": "extend" if kwargs.get("video_path") else "generate",
                "duration_requested": 8 if not kwargs.get("video_path") else 7,
            }

        veo = MagicMock()
        veo.model = "veo-3.1-generate-preview"
        veo.family.return_value = "veo"
        veo.prepare_images.side_effect = lambda paths, **kwargs: list(paths)[:3]
        veo.start.side_effect = fake_start
        veo.save_video.side_effect = lambda task, dest: dest.write_bytes(b"VEOMP4")
        veo._calls = calls
        return veo

