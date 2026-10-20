from __future__ import annotations

import logging

from ai.exceptions import GoogleProviderError

from .client import require_speech_credentials

logger = logging.getLogger(__name__)

LANGUAGE_VOICE = {
    "conversational_bm": {
        "language_code": "ms-MY",
        "speaking_rate": 1.05,
    },
    "formal_bm": {
        "language_code": "ms-MY",
        "speaking_rate": 0.95,
    },
    "bm_english": {
        "language_code": "ms-MY",
        "speaking_rate": 1.0,
    },
    "english": {
        "language_code": "en-US",
        "speaking_rate": 1.0,
    },
    "chinese": {
        "language_code": "cmn-CN",
        "speaking_rate": 1.0,
    },
    "cantonese": {
        "language_code": "yue-HK",
        "speaking_rate": 1.0,
    },
    "hokkien": {
        "language_code": "cmn-TW",
        "speaking_rate": 1.0,
    },
    "mandarin_my": {
        "language_code": "cmn-CN",
        "speaking_rate": 1.0,
    },
    "tamil_my": {
        "language_code": "ta-IN",
        "speaking_rate": 1.0,
    },
}

GENDER_VOICE = {
    "female": {
        "ms-MY": "ms-MY-Wavenet-A",
        "en-US": "en-US-Wavenet-F",
        "cmn-CN": "cmn-CN-Wavenet-A",
        "cmn-TW": "cmn-TW-Wavenet-A",
        "yue-HK": "yue-HK-Standard-A",
        "ta-IN": "ta-IN-Wavenet-A",
    },
    "male": {
        "ms-MY": "ms-MY-Wavenet-B",
        "en-US": "en-US-Wavenet-D",
        "cmn-CN": "cmn-CN-Wavenet-B",
        "cmn-TW": "cmn-TW-Wavenet-B",
        "yue-HK": "yue-HK-Standard-B",
        "ta-IN": "ta-IN-Wavenet-B",
    },
    "neutral": {
        "ms-MY": "ms-MY-Wavenet-A",
        "en-US": "en-US-Wavenet-F",
        "cmn-CN": "cmn-CN-Wavenet-A",
        "cmn-TW": "cmn-TW-Wavenet-A",
        "yue-HK": "yue-HK-Standard-A",
        "ta-IN": "ta-IN-Wavenet-A",
    },
}


def voice_for(language: str, gender: str = "female", voice_name: str = "") -> dict:
    mapping = dict(LANGUAGE_VOICE.get(language, LANGUAGE_VOICE["conversational_bm"]))
    language_code = mapping["language_code"]
    names = GENDER_VOICE.get(gender) or GENDER_VOICE["female"]
    mapping["name"] = voice_name or names.get(language_code) or GENDER_VOICE["female"][language_code]
    mapping["gender"] = gender or "female"
    return mapping


class SpeechProvider:
    def transcribe(self, audio_bytes: bytes, *, language: str = "conversational_bm") -> str:
        require_speech_credentials()
        try:
            from google.cloud import speech

            mapping = voice_for(language)
            client = speech.SpeechClient()
            audio = speech.RecognitionAudio(content=audio_bytes)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED,
                language_code=mapping["language_code"],
                alternative_language_codes=["en-MY", "en-US", "ms-MY", "cmn-Hans-CN", "yue-Hant-HK", "ta-IN"],
                enable_automatic_punctuation=True,
            )
            response = client.recognize(config=config, audio=audio)
            transcript = " ".join(
                result.alternatives[0].transcript
                for result in response.results
                if result.alternatives
            ).strip()
            if not transcript:
                raise GoogleProviderError("No speech was recognised in the recording.")
            return transcript
        except GoogleProviderError:
            raise
        except Exception as exc:
            logger.exception("Speech-to-Text failed")
            raise GoogleProviderError(
                "Speech transcription failed.",
                retryable=True,
            ) from exc

    def synthesize(
        self,
        text: str,
        *,
        language: str = "conversational_bm",
        voice_name: str = "",
        gender: str = "female",
    ) -> bytes:
        require_speech_credentials()
        try:
            from google.cloud import texttospeech

            mapping = voice_for(language, gender=gender, voice_name=voice_name)
            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code=mapping["language_code"],
                name=mapping["name"],
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=mapping["speaking_rate"],
            )
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )
            if not response.audio_content:
                raise GoogleProviderError("Voice generation returned no audio.")
            return response.audio_content
        except GoogleProviderError:
            raise
        except Exception as exc:
            logger.exception("Text-to-Speech failed")
            raise GoogleProviderError(
                "Voice generation failed.",
                retryable=True,
            ) from exc
