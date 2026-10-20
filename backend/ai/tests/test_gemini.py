from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from ai.exceptions import GoogleProviderError, MissingAPIKeyError
from ai.providers.google.client import require_google_api_key, speech_configured
from ai.providers.google.gemini import GeminiProvider
from ai.providers.google.speech import voice_for


class GeminiProviderTest(SimpleTestCase):
    @override_settings(GOOGLE_API_KEY="", GEMINI_API_KEY="")
    def test_missing_api_key(self):
        with self.assertRaises(MissingAPIKeyError):
            require_google_api_key()

    def test_parse_json(self):
        provider = GeminiProvider()
        self.assertEqual(provider._parse_json('{"ok": true}'), {"ok": True})
        with self.assertRaises(GoogleProviderError):
            provider._parse_json("not-json")
        with self.assertRaises(GoogleProviderError):
            provider._parse_json("[]")

    @override_settings(GOOGLE_API_KEY="test-key", GEMINI_MODEL="test-model")
    def test_generate_json_uses_structured_response(self):
        response = MagicMock()
        response.text = '{"name": "Serum"}'
        client = MagicMock()
        client.models.generate_content.return_value = response
        with patch("ai.providers.google.gemini.get_genai_client", return_value=client):
            data = GeminiProvider().generate_json("prompt", schema={"type": "object"})
        self.assertEqual(data["name"], "Serum")
        client.models.generate_content.assert_called_once()

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_transcribe_returns_spoken_words(self):
        response = MagicMock()
        response.text = "Buat video 35 saat."
        client = MagicMock()
        client.models.generate_content.return_value = response
        with (
            patch("ai.providers.google.gemini.get_genai_client", return_value=client),
            patch.object(GeminiProvider, "_file_part", return_value="audio"),
        ):
            text = GeminiProvider().transcribe("voice.webm", language="conversational_bm")
        self.assertEqual(text, "Buat video 35 saat.")

    @override_settings(GOOGLE_API_KEY="test-key")
    def test_google_failure(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("quota")
        with patch("ai.providers.google.gemini.get_genai_client", return_value=client):
            with self.assertRaises(GoogleProviderError):
                GeminiProvider().generate_json("prompt")


class SpeechVoiceTest(SimpleTestCase):
    def test_male_malay_voice(self):
        mapping = voice_for("conversational_bm", gender="male")
        self.assertEqual(mapping["language_code"], "ms-MY")
        self.assertEqual(mapping["name"], "ms-MY-Wavenet-B")

    def test_female_mandarin_voice(self):
        mapping = voice_for("mandarin_my", gender="female")
        self.assertEqual(mapping["name"], "cmn-CN-Wavenet-A")

    @override_settings(GOOGLE_APPLICATION_CREDENTIALS="", GOOGLE_CLOUD_PROJECT="")
    def test_speech_not_configured(self):
        self.assertFalse(speech_configured())

    @override_settings(GOOGLE_CLOUD_PROJECT="demo")
    def test_speech_configured(self):
        self.assertTrue(speech_configured())
