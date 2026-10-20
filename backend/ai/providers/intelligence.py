from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from django.conf import settings

from ai.exceptions import MissingAPIKeyError, ProviderError
from ai.services.usage import record_usage

logger = logging.getLogger(__name__)


def require_intelligence() -> None:
    if (
        (getattr(settings, "GOOGLE_API_KEY", "") or getattr(settings, "GEMINI_API_KEY", ""))
        or getattr(settings, "OPENAI_API_KEY", "")
        or getattr(settings, "CLAW_API_KEY", "")
    ):
        return
    raise MissingAPIKeyError(
        "AI intelligence is not configured. Add GEMINI_API_KEY, OPENAI_API_KEY, or CLAW_API_KEY."
    )


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderError("The AI returned an invalid response.") from exc
    if not isinstance(data, dict):
        raise ProviderError("The AI returned an invalid response.")
    return data


class IntelligenceClient:
    """Gemini, OpenAI, or Claw (OpenAI-compatible) structured JSON."""

    def generate_json(
        self,
        prompt: str,
        *,
        schema: dict | None = None,
        files: list[str | Path] | None = None,
        system: str | None = None,
        operation: str = "intelligence",
        project=None,
        owner=None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        for name in self._order():
            try:
                data = self._call(name, prompt, schema=schema, files=files, system=system)
                record_usage(
                    owner=owner or getattr(project, "owner", None),
                    project=project,
                    provider=name,
                    operation=operation,
                    status="succeeded",
                )
                return data
            except MissingAPIKeyError as exc:
                errors.append(str(exc))
            except ProviderError as exc:
                errors.append(str(exc))
                if not exc.retryable:
                    raise
        if all("not configured" in item.lower() for item in errors):
            raise MissingAPIKeyError(
                "AI intelligence is not configured. Add GEMINI_API_KEY, OPENAI_API_KEY, or CLAW_API_KEY."
            )
        raise ProviderError("The AI service could not complete this request.", retryable=True)

    def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str = "",
        operation: str = "transcribe",
        owner=None,
        project=None,
    ) -> str:
        from ai.providers.google.client import require_google_api_key
        from ai.providers.google.gemini import GeminiProvider

        require_google_api_key()
        text = GeminiProvider().transcribe(audio_path, language=language)
        record_usage(
            owner=owner or getattr(project, "owner", None),
            project=project,
            provider="gemini",
            operation=operation,
            status="succeeded",
        )
        return text

    def _order(self) -> list[str]:
        preferred = (getattr(settings, "INTELLIGENCE_PROVIDER", "gemini") or "gemini").lower()
        names = ["gemini", "openai", "claw"]
        if preferred in names:
            names.remove(preferred)
            names.insert(0, preferred)
        return names

    def _call(
        self,
        name: str,
        prompt: str,
        *,
        schema: dict | None,
        files: list[str | Path] | None,
        system: str | None,
    ) -> dict[str, Any]:
        if name == "gemini":
            from ai.providers.google.client import require_google_api_key
            from ai.providers.google.gemini import GeminiProvider

            require_google_api_key()
            return GeminiProvider().generate_json(
                prompt, schema=schema, files=files, system=system
            )
        if name == "openai":
            return self._openai(prompt, schema=schema, system=system)
        return self._claw(prompt, schema=schema, system=system)

    def _openai(self, prompt: str, *, schema: dict | None, system: str | None) -> dict[str, Any]:
        key = (getattr(settings, "OPENAI_API_KEY", "") or "").strip()
        if not key:
            raise MissingAPIKeyError("OpenAI is not configured. Add OPENAI_API_KEY to backend/.env.")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=key)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            extra = ""
            if schema:
                extra = f"\nReturn JSON matching this schema:\n{json.dumps(schema)}"
            messages.append({"role": "user", "content": prompt + extra})
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content or ""
            return _parse_json(text)
        except MissingAPIKeyError:
            raise
        except Exception as exc:
            logger.exception("OpenAI request failed")
            raise ProviderError("The AI service could not complete this request.", retryable=True) from exc

    def _claw(self, prompt: str, *, schema: dict | None, system: str | None) -> dict[str, Any]:
        key = (getattr(settings, "CLAW_API_KEY", "") or "").strip()
        base = (getattr(settings, "CLAW_API_BASE", "") or "").rstrip("/")
        if not key or not base:
            raise MissingAPIKeyError(
                "Claw is not configured. Add CLAW_API_KEY and CLAW_API_BASE to backend/.env."
            )
        try:
            import httpx

            extra = f"\nReturn JSON matching this schema:\n{json.dumps(schema)}" if schema else ""
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt + extra})
            response = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": settings.CLAW_MODEL,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                },
                timeout=120,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            return _parse_json(text)
        except MissingAPIKeyError:
            raise
        except Exception as exc:
            logger.exception("Claw request failed")
            raise ProviderError("The AI service could not complete this request.", retryable=True) from exc
