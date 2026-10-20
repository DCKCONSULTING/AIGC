from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

from django.conf import settings

from ai.exceptions import GoogleProviderError

from .client import get_genai_client

logger = logging.getLogger(__name__)


class GeminiProvider:
    def generate_json(
        self,
        prompt: str,
        *,
        schema: dict | None = None,
        files: list[str | Path] | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        try:
            from google.genai import types

            client = get_genai_client()
            contents: list[Any] = []
            for path in files or []:
                contents.append(self._file_part(path))
            contents.append(prompt)
            config_kwargs: dict[str, Any] = {
                "response_mime_type": "application/json",
            }
            if schema:
                config_kwargs["response_schema"] = schema
            if system:
                config_kwargs["system_instruction"] = system
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            text = (response.text or "").strip()
            if not text:
                raise GoogleProviderError("The AI returned an empty response.")
            return self._parse_json(text)
        except GoogleProviderError:
            raise
        except Exception as exc:
            logger.exception("Gemini request failed")
            raise GoogleProviderError(
                "The AI service could not complete this request.",
                retryable=True,
            ) from exc

    def transcribe(self, audio_path: str | Path, *, language: str = "") -> str:
        locale = f" The speaker is using {language}." if language else ""
        text = self.generate_text(
            (
                "Transcribe this voice recording exactly. "
                "Return only the spoken words. Do not add commentary, labels, or quotation marks."
                f"{locale}"
            ),
            files=[audio_path],
        )
        if not text:
            raise GoogleProviderError("No speech was recognised in the recording.")
        return text

    def generate_text(self, prompt: str, *, files: list[str | Path] | None = None) -> str:
        try:
            client = get_genai_client()
            contents: list[Any] = []
            for path in files or []:
                contents.append(self._file_part(path))
            contents.append(prompt)
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=contents,
            )
            return (response.text or "").strip()
        except Exception as exc:
            logger.exception("Gemini text request failed")
            raise GoogleProviderError(
                "The AI service could not complete this request.",
                retryable=True,
            ) from exc

    def _file_part(self, path: str | Path):
        from google.genai import types

        file_path = Path(path)
        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        return types.Part.from_bytes(data=file_path.read_bytes(), mime_type=mime)

    def _parse_json(self, text: str) -> dict[str, Any]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GoogleProviderError("The AI returned an invalid response.") from exc
        if not isinstance(data, dict):
            raise GoogleProviderError("The AI returned an invalid response.")
        return data
