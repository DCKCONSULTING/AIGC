from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from ai.exceptions import MissingAPIKeyError, ProviderError
from ai.providers.google.omni import GeminiOmniProvider, require_omni_key
from ai.providers.intelligence import IntelligenceClient, require_intelligence
from ai.providers.kalodata import KalodataProvider
from ai.services.intelligence import KalodataService
from ai.tasks import enqueue_video_generation


class GeminiOmniProviderTest(SimpleTestCase):
    @override_settings(GOOGLE_API_KEY="", GEMINI_API_KEY="")
    def test_missing_key(self):
        with self.assertRaises(MissingAPIKeyError):
            require_omni_key()

    @override_settings(
        GOOGLE_API_KEY="test-key",
        GEMINI_API_KEY="test-key",
        GEMINI_OMNI_MODEL="gemini-omni-1.1-flash",
        GEMINI_OMNI_RESOLUTION="720p",
        OMNI_REQUEST_TIMEOUT_SECONDS=300,
    )
    def test_start_and_poll(self):
        video = MagicMock(
            uri="https://generativelanguage.googleapis.com/v1beta/files/abc123:download?alt=media",
            data=None,
        )
        created = MagicMock(id="v1_task", status="completed", output_video=video)
        active = MagicMock(state="ACTIVE", error=None)
        client = MagicMock()
        client.interactions.create.return_value = created
        client.files.get.return_value = active
        with patch("ai.providers.google.omni.get_genai_client", return_value=client) as get_genai:
            started = GeminiOmniProvider().start("Show the product", duration_seconds=8)
            polled = GeminiOmniProvider().poll("files/abc123", interval_seconds=0)
        self.assertEqual(started["id"], "v1_task")
        self.assertEqual(started["file_id"], "files/abc123")
        self.assertEqual(polled.state, "ACTIVE")
        kwargs = client.interactions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-omni-1.1-flash")
        self.assertFalse(kwargs["background"])
        self.assertEqual(kwargs["response_format"]["delivery"], "uri")
        self.assertEqual(kwargs["response_format"]["duration"], "8s")
        self.assertEqual(kwargs["response_format"]["aspect_ratio"], "9:16")
        self.assertEqual(kwargs["generation_config"]["video_config"]["task"], "text_to_video")
        self.assertTrue(kwargs["store"])
        self.assertFalse(kwargs["stream"])
        self.assertFalse(kwargs["background"])
        self.assertNotIn("previous_interaction_id", kwargs)
        options = get_genai.call_args_list[0].kwargs["http_options"]
        self.assertEqual(options.retry_options.attempts, 0)
        self.assertEqual(options.timeout, 300000)
        client.files.get.assert_called_with(name="files/abc123")
        client.interactions.get.assert_not_called()

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key", GEMINI_OMNI_RESOLUTION="1080p")
    def test_extension_stores_previous_interaction_and_does_not_upscale(self):
        video = MagicMock(
            uri="https://generativelanguage.googleapis.com/v1beta/files/abc123:download?alt=media",
            data=None,
        )
        created = MagicMock(id="v1_extend", output_video=video)
        client = MagicMock()
        client.interactions.create.return_value = created
        with patch("ai.providers.google.omni.get_genai_client", return_value=client):
            GeminiOmniProvider().start(
                "Continue from the previous shot.",
                duration_seconds=10,
                previous_interaction_id="interaction-prev",
                store=True,
                image_paths=["/tmp/should-not-be-sent.png"],
            )
        payload = client.interactions.create.call_args.kwargs
        self.assertEqual(payload["previous_interaction_id"], "interaction-prev")
        self.assertTrue(payload["store"])
        self.assertFalse(payload["background"])
        self.assertFalse(payload["stream"])
        self.assertNotIn("generation_config", payload)
        self.assertEqual(payload["response_format"]["resolution"], "720p")
        self.assertEqual(payload["response_format"]["duration"], "10s")
        self.assertEqual([item for item in payload["input"] if item.get("type") == "image"], [])

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key", OMNI_REQUEST_TIMEOUT_SECONDS=1)
    def test_hung_create_is_stopped_at_the_wall_clock_limit(self):
        import time

        client = MagicMock()

        def hang(**kwargs):
            time.sleep(30)

        client.interactions.create.side_effect = hang
        started = time.perf_counter()
        with (
            patch("ai.providers.google.omni.get_genai_client", return_value=client),
            patch("ai.providers.google.omni.omni_request_timeout", return_value=1),
        ):
            with self.assertRaises(ProviderError) as ctx:
                GeminiOmniProvider().start("Show the product", duration_seconds=3)
        elapsed = time.perf_counter() - started
        self.assertEqual(ctx.exception.code, "TIMEOUT")
        self.assertFalse(ctx.exception.retryable)
        self.assertLess(elapsed, 12)

    def test_429_is_rate_limited_and_not_retryable(self):
        class TooMany(Exception):
            status_code = 429

            def __str__(self):
                return "Rate limit exceeded for model gemini-omni-1.1-flash. Please retry in 8h16m28s."

        wrapped = GeminiOmniProvider()._wrap_error(TooMany(), "fallback", request_id="req-429")
        self.assertEqual(wrapped.code, "RATE_LIMITED")
        self.assertFalse(wrapped.retryable)
        self.assertEqual(wrapped.status_code, 429)
        self.assertIn("temporarily rate limited", str(wrapped))
        self.assertIn("8h16m28s", wrapped.retry_after)

    def test_clamp_duration(self):
        provider = GeminiOmniProvider()
        self.assertEqual(provider.family(), "omni")
        self.assertEqual(provider.clamp_duration(15), 10)
        self.assertEqual(provider.clamp_duration(1), 3)
        self.assertEqual(provider.clamp_duration(8), 8)

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key")
    def test_sends_product_photos_as_images(self):
        import tempfile
        from pathlib import Path

        video = MagicMock(
            uri="https://generativelanguage.googleapis.com/v1beta/files/abc123:download?alt=media",
            data=None,
        )
        created = MagicMock(id="v1_task", status="completed", output_video=video)
        client = MagicMock()
        client.interactions.create.return_value = created
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.png"
            extra = Path(tmp) / "b.png"
            video = Path(tmp) / "ref.mp4"
            first.write_bytes(png)
            extra.write_bytes(png)
            video.write_bytes(b"fake")
            with patch("ai.providers.google.omni.get_genai_client", return_value=client):
                GeminiOmniProvider().start(
                    "Show the product",
                    image_path=first,
                    image_paths=[extra],
                    video_path=video,
                    duration_seconds=8,
                )
        payload = client.interactions.create.call_args.kwargs
        images = [item for item in payload["input"] if item.get("type") == "image"]
        videos = [item for item in payload["input"] if item.get("type") == "video"]
        texts = [item for item in payload["input"] if item.get("type") == "text"]
        self.assertEqual(len(images), 2)
        self.assertEqual(len(videos), 1)
        self.assertEqual(len(texts), 1)
        self.assertEqual(payload["generation_config"]["video_config"]["task"], "reference_to_video")
        self.assertEqual(payload["response_format"]["duration"], "8s")
        self.assertEqual(payload["response_format"]["delivery"], "uri")
        self.assertEqual(payload["response_format"]["aspect_ratio"], "9:16")
        self.assertEqual(payload["response_format"]["resolution"], "720p")
        self.assertTrue(payload["store"])

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key")
    def test_provider_failure(self):
        client = MagicMock()
        client.interactions.create.side_effect = RuntimeError("down")
        with patch("ai.providers.google.omni.get_genai_client", return_value=client):
            with self.assertRaises(ProviderError) as ctx:
                GeminiOmniProvider().start("prompt")
        self.assertTrue(ctx.exception.retryable)

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_API_KEY="test-key")
    def test_400_is_not_retryable(self):
        class BadRequest(Exception):
            status_code = 400

        client = MagicMock()
        client.interactions.create.side_effect = BadRequest("bad payload")
        with patch("ai.providers.google.omni.get_genai_client", return_value=client):
            with self.assertRaises(ProviderError) as ctx:
                GeminiOmniProvider().start("prompt")
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("bad payload", ctx.exception.args[0])
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")

    def test_invalid_api_key_is_an_authentication_error(self):
        class BadRequest(Exception):
            status_code = 400

            def __str__(self):
                return (
                    "Error code: 400 - {'error': {'message': "
                    "'API key not valid. Please pass a valid API key.', 'code': 'invalid_request'}}"
                )

        wrapped = GeminiOmniProvider()._wrap_error(BadRequest(), "fallback", request_id="req-key")
        self.assertEqual(wrapped.code, "INVALID_REQUEST")
        self.assertFalse(wrapped.retryable)
        self.assertEqual(str(wrapped), "API key not valid. Please pass a valid API key.")
        self.assertEqual(wrapped.category, "invalid_request")

    @override_settings(GOOGLE_API_KEY="wrong-value", GEMINI_API_KEY="valid-value")
    def test_omni_client_uses_gemini_key_when_both_are_set(self):
        import os
        from unittest.mock import patch

        from ai.providers.google.client import gemini_credential_status, get_genai_client

        env = {"GOOGLE_API_KEY": "wrong-value", "GEMINI_API_KEY": "valid-value"}
        with patch.dict(os.environ, env, clear=False):
            client = get_genai_client()
            sent = client._api_client.api_key
            header = client._api_client._http_options.headers["x-goog-api-key"]
            report = gemini_credential_status()
        self.assertEqual(sent, "valid-value")
        self.assertEqual(header, "valid-value")
        self.assertNotEqual(sent, "wrong-value")
        self.assertNotIn("GOOGLE_API_KEY", os.environ)
        self.assertTrue(report["gemini_api_key"]["configured"])
        self.assertTrue(report["gemini_api_key"]["used_by_gemini_omni"])
        self.assertFalse(report["google_api_key"]["configured"])
        self.assertFalse(report["google_api_key"]["used_by_gemini_omni"])
        self.assertNotIn("valid-value", str(report))
        self.assertNotIn("wrong-value", str(report))


class KalodataProviderTest(SimpleTestCase):
    @override_settings(KALODATA_API_KEY="", KALODATA_API_BASE="")
    def test_missing_key(self):
        with self.assertRaises(MissingAPIKeyError):
            KalodataProvider().category_intelligence(category="Beauty")

    @override_settings(KALODATA_API_KEY="k", KALODATA_API_BASE="https://api.kalodata.test")
    def test_authorized_payload(self):
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "scripts": ["hook then demo"],
            "structures": ["problem-solution"],
            "objections": ["Is it sticky?"],
            "ideas": ["Show storage"],
        }
        with patch("httpx.get", return_value=response):
            data = KalodataProvider().category_intelligence(category="Beauty", product_name="Serum")
        self.assertTrue(data["available"])
        self.assertEqual(data["category_scripts"], ["hook then demo"])
        self.assertEqual(data["customer_objections"], ["Is it sticky?"])

    @override_settings(KALODATA_API_KEY="k", KALODATA_API_BASE="https://api.kalodata.test")
    def test_missing_endpoint_is_empty(self):
        response = MagicMock()
        response.status_code = 404
        with patch("httpx.get", return_value=response):
            data = KalodataProvider().category_intelligence(category="Beauty")
        self.assertFalse(data["available"])

    def test_service_continues_without_key(self):
        data = KalodataService().insights(category="Beauty")
        self.assertFalse(data["available"])


class IntelligenceClientTest(SimpleTestCase):
    @override_settings(GOOGLE_API_KEY="", GEMINI_API_KEY="", OPENAI_API_KEY="", CLAW_API_KEY="")
    def test_missing_credentials(self):
        with self.assertRaises(MissingAPIKeyError):
            require_intelligence()

    @override_settings(
        INTELLIGENCE_PROVIDER="openai",
        GOOGLE_API_KEY="",
        OPENAI_API_KEY="sk-test",
        OPENAI_MODEL="gpt-4.1",
    )
    def test_openai_json(self):
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content='{"hook":"Hi"}'))]
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        with patch("openai.OpenAI", return_value=client):
            data = IntelligenceClient().generate_json("prompt")
        self.assertEqual(data["hook"], "Hi")

    @override_settings(
        INTELLIGENCE_PROVIDER="gemini",
        GOOGLE_API_KEY="",
        GEMINI_API_KEY="",
        OPENAI_API_KEY="",
        CLAW_API_KEY="claw",
        CLAW_API_BASE="https://claw.test/v1",
        CLAW_MODEL="openclaw/default",
    )
    def test_claw_fallback(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        with patch("httpx.post", return_value=response):
            data = IntelligenceClient().generate_json("prompt")
        self.assertTrue(data["ok"])


class QueueFallbackTest(SimpleTestCase):
    @override_settings(AI_SYNC_TASKS=False)
    def test_enqueue_uses_django_q(self):
        with patch("django_q.tasks.async_task") as async_task:
            enqueue_video_generation(99)
        async_task.assert_called_once_with("ai.tasks.generate_video_project", 99)

    @override_settings(AI_SYNC_TASKS=False)
    def test_enqueue_uses_thread_when_async_task_fails(self):
        with (
            patch("django_q.tasks.async_task", side_effect=RuntimeError("down")),
            patch("ai.tasks.threading.Thread") as thread_cls,
        ):
            thread = MagicMock()
            thread_cls.return_value = thread
            enqueue_video_generation(99)
        thread_cls.assert_called_once()
        thread.start.assert_called_once()
        self.assertTrue(thread_cls.call_args.kwargs.get("daemon"))
