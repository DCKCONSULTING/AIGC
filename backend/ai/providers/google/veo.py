"""Veo 3.1 video generation via the Gemini API generate_videos operation.

Studio uses this only when VIDEO_PROVIDER=veo. There is no Omni fallback.
Initial clips are 8 seconds (required with reference images). Each extension
adds 7 seconds, up to 20 extensions (~148 seconds).
"""

from __future__ import annotations

import logging
import math
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from django.conf import settings

from ai.exceptions import GoogleProviderError, MissingAPIKeyError, ProviderError
from ai.services.cancel import GenerationCancelled

from .client import get_genai_client, require_gemini_api_key

logger = logging.getLogger(__name__)

VEO_INITIAL_SECONDS = 8
VEO_EXTENSION_SECONDS = 7
VEO_MAX_EXTENSIONS = 20
VEO_MAX_CONTINUOUS_DURATION_SECONDS = VEO_INITIAL_SECONDS + (VEO_MAX_EXTENSIONS * VEO_EXTENSION_SECONDS)
VEO_MAX_REFERENCE_IMAGES = 3
VEO_POLL_SECONDS = 10
VEO_EXTENSION_NOT_READY_ATTEMPTS = 4
VEO_EXTENSION_NOT_READY_WAIT_SECONDS = 20

_limiter: threading.BoundedSemaphore | None = None
_limiter_size = 0
_limiter_guard = threading.Lock()


def veo_operation_timeout() -> int:
    try:
        value = int(getattr(settings, "VEO_OPERATION_TIMEOUT_SECONDS", 900) or 900)
    except (TypeError, ValueError):
        value = 900
    return max(60, min(value, 1800))


def veo_limiter() -> threading.BoundedSemaphore:
    global _limiter, _limiter_size
    try:
        size = int(getattr(settings, "VEO_MAX_IN_FLIGHT", 3) or 3)
    except (TypeError, ValueError):
        size = 3
    size = max(1, min(size, 8))
    with _limiter_guard:
        if _limiter is None or _limiter_size != size:
            _limiter = threading.BoundedSemaphore(size)
            _limiter_size = size
        return _limiter


def plan_veo_generation(target_duration: int) -> dict[str, int]:
    """Split a product duration into one 8s Veo create plus 7s extensions.

    8 → 8. 15 → 8+7. 30 → 8+7×4=36 then trim. 45 → 50 then trim.
    60 → 64 then trim. 148 → 8+7×20. Longer than 148 is rejected.
    """
    target = int(target_duration)
    if target < 1:
        raise ValueError("Requested duration is too short for Veo.")
    if target > VEO_MAX_CONTINUOUS_DURATION_SECONDS:
        raise ProviderError(
            f"Veo cannot generate more than {VEO_MAX_CONTINUOUS_DURATION_SECONDS} "
            "seconds as one continuous chain.",
            retryable=False,
            code="INVALID_DURATION",
            provider="veo",
            category="configuration",
        )
    if target <= VEO_INITIAL_SECONDS:
        return {
            "initial_duration": VEO_INITIAL_SECONDS,
            "extension_count": 0,
            "generated_duration": VEO_INITIAL_SECONDS,
            "trim_to": 0 if target == VEO_INITIAL_SECONDS else target,
        }
    extension_count = math.ceil((target - VEO_INITIAL_SECONDS) / VEO_EXTENSION_SECONDS)
    extension_count = min(max(extension_count, 0), VEO_MAX_EXTENSIONS)
    generated = VEO_INITIAL_SECONDS + extension_count * VEO_EXTENSION_SECONDS
    return {
        "initial_duration": VEO_INITIAL_SECONDS,
        "extension_count": extension_count,
        "generated_duration": generated,
        "trim_to": target if generated > target else 0,
    }


def select_veo_reference_paths(
    paths: list[str],
    *,
    character_paths: list[str] | None = None,
    product_paths: list[str] | None = None,
    style_paths: list[str] | None = None,
) -> list[str]:
    """Deterministic cap of 3: character, product, then style/environment."""
    chosen: list[str] = []
    seen: set[str] = set()

    def take(candidates: list[str] | None, limit: int = 1) -> None:
        count = 0
        for path in candidates or []:
            key = str(path or "")
            if not key or key in seen:
                continue
            seen.add(key)
            chosen.append(key)
            count += 1
            if count >= limit or len(chosen) >= VEO_MAX_REFERENCE_IMAGES:
                return

    take(character_paths, 1)
    take(product_paths, 1)
    take(style_paths, 1)
    take(paths, VEO_MAX_REFERENCE_IMAGES)
    return chosen[:VEO_MAX_REFERENCE_IMAGES]


def _disable_sdk_retries(client: Any) -> None:
    for attr in ("models", "operations", "_api_client"):
        obj = getattr(client, attr, None)
        config = getattr(obj, "sdk_configuration", None) if obj is not None else None
        retry = getattr(config, "retry_config", None) if config is not None else None
        if retry is None:
            continue
        retry.max_retries = 0
        if hasattr(retry, "retry_connection_errors"):
            retry.retry_connection_errors = False
    api = getattr(client, "_api_client", None)
    retry = getattr(api, "_retry", None) or getattr(api, "retry_config", None)
    if retry is not None and hasattr(retry, "max_retries"):
        retry.max_retries = 0


class VeoProvider:
    """Veo 3.1 generate_videos. Used only when VIDEO_PROVIDER=veo."""

    def __init__(self):
        self.model = getattr(settings, "VEO_MODEL", "") or "veo-3.1-generate-preview"

    def family(self) -> str:
        return "veo"

    def clamp_duration(self, duration_seconds: int) -> int:
        value = int(duration_seconds or VEO_INITIAL_SECONDS)
        if value in {4, 6, 8}:
            return value
        return VEO_INITIAL_SECONDS

    def poll_interval(self) -> int:
        return VEO_POLL_SECONDS

    def prepare_images(
        self,
        paths: list[str | Path] | None,
        *,
        character_paths: list[str] | None = None,
        product_paths: list[str] | None = None,
        style_paths: list[str] | None = None,
    ) -> list[str]:
        string_paths = [str(path) for path in (paths or []) if str(path or "").strip()]
        return select_veo_reference_paths(
            string_paths,
            character_paths=[str(p) for p in (character_paths or [])],
            product_paths=[str(p) for p in (product_paths or [])],
            style_paths=[str(p) for p in (style_paths or [])],
        )

    def start(
        self,
        prompt: str,
        *,
        image_path: str | Path | None = None,
        image_paths: list[str | Path] | None = None,
        video_path: str | Path | None = None,
        previous_video: Any | None = None,
        previous_video_uri: str | None = None,
        duration_seconds: int = 8,
        aspect_ratio: str = "9:16",
        generate_audio: bool = True,
        prepared_images: list[str] | None = None,
        previous_interaction_id: str | None = None,
        store: bool = False,
        task: str | None = None,
        attempt_context: dict[str, Any] | None = None,
        should_stop: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        del previous_interaction_id, store, task
        require_gemini_api_key()
        extending = bool(
            previous_video is not None
            or str(previous_video_uri or "").strip()
            or str(video_path or "").strip()
        )
        duration = VEO_INITIAL_SECONDS if not extending else 0
        if not extending:
            duration = self.clamp_duration(duration_seconds) or VEO_INITIAL_SECONDS
            if prepared_images or image_path or image_paths:
                duration = VEO_INITIAL_SECONDS
        ratio = aspect_ratio if aspect_ratio in {"9:16", "16:9"} else "9:16"
        refs = list(prepared_images or [])
        if not refs:
            ordered = []
            if image_path:
                ordered.append(str(image_path))
            ordered.extend(str(path) for path in (image_paths or []) if path)
            refs = select_veo_reference_paths(ordered)
        if extending:
            refs = []
        context = attempt_context or {}
        started_at = time.perf_counter()
        limiter = veo_limiter()
        limiter.acquire()
        try:
            create_kwargs = {
                "video_path": str(video_path) if extending else None,
                "previous_video": previous_video if extending else None,
                "previous_video_uri": str(previous_video_uri or "").strip() or None,
                "reference_paths": refs,
                "duration_seconds": duration,
                "aspect_ratio": ratio,
                "generate_audio": bool(generate_audio),
            }
            operation = None
            generated = None
            for attempt in (1, 2):
                operation = self._create(prompt, should_stop=should_stop, **create_kwargs)
                operation = self.poll(operation, should_stop=should_stop)
                generated = self._video_from_operation(operation)
                if not self._empty_generation(operation, generated):
                    break
                logger.warning(
                    "VEO_EMPTY_VIDEO film=%s hop=%s attempt=%s retrying=%s",
                    context.get("film_id", ""),
                    context.get("hop_index", ""),
                    attempt,
                    str(attempt < 2).lower(),
                )
                if attempt >= 2:
                    self._raise_if_empty_generation(operation, generated)
            payload = self._result_payload(
                operation,
                prompt=prompt,
                duration=duration or VEO_EXTENSION_SECONDS,
                refs=refs,
                extending=extending,
            )
            downloaded = Path(tempfile.mkstemp(suffix=".mp4")[1])
            self.save_video(
                {**payload, "operation": operation, "generated_video": generated},
                downloaded,
            )
            payload["path"] = str(downloaded)
            payload["inline"] = downloaded.read_bytes()
            payload["generated_video"] = generated
            payload["uri"] = str(getattr(generated, "uri", "") or payload.get("uri") or "")
            payload["file_id"] = payload["uri"]
            payload["operation"] = None
            payload["elapsed_ms"] = int((time.perf_counter() - started_at) * 1000)
            payload["film_id"] = context.get("film_id", "")
            payload["chain_id"] = context.get("chain_id", "")
            payload["hop_index"] = context.get("hop_index", "")
            logger.info(
                "VEO_ATTEMPT_END film=%s hop=%s model=%s elapsed=%.1f success=true extending=%s",
                context.get("film_id", ""),
                context.get("hop_index", ""),
                self.model,
                time.perf_counter() - started_at,
                str(extending).lower(),
            )
            return payload
        except GenerationCancelled:
            logger.info(
                "VEO_ATTEMPT_END film=%s hop=%s success=false code=CANCELLED",
                context.get("film_id", ""),
                context.get("hop_index", ""),
            )
            raise
        except Exception as exc:
            wrapped = self._wrap_error(exc, "Video generation could not be started.")
            logger.info(
                "VEO_ATTEMPT_END film=%s hop=%s success=false code=%s",
                context.get("film_id", ""),
                context.get("hop_index", ""),
                getattr(wrapped, "code", ""),
            )
            raise wrapped from exc
        finally:
            limiter.release()

    def poll(
        self,
        operation: Any,
        *,
        timeout_seconds: int | None = None,
        interval_seconds: int | None = None,
        should_stop: Callable[[], None] | None = None,
    ) -> Any:
        timeout = timeout_seconds if timeout_seconds is not None else veo_operation_timeout()
        interval = interval_seconds if interval_seconds is not None else VEO_POLL_SECONDS
        interval = max(5, min(int(interval or VEO_POLL_SECONDS), 15))
        waited = 0
        current = operation
        if isinstance(operation, str):
            raise GoogleProviderError(
                "Video generation status could not be checked.",
                retryable=False,
                code="PROVIDER_ERROR",
                provider="veo",
            )
        try:
            client = self._client()
            while not bool(getattr(current, "done", False)):
                if callable(should_stop):
                    should_stop()
                if waited >= timeout:
                    raise GoogleProviderError(
                        "Video generation timed out. The worker was released. Please try again.",
                        retryable=False,
                        code="TIMEOUT",
                        provider="veo",
                        category="timeout",
                    )
                time.sleep(interval)
                waited += interval
                current = client.operations.get(current)
            error = getattr(current, "error", None)
            if error:
                message = ""
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("status") or error)
                else:
                    message = str(error)
                raise GoogleProviderError(
                    sanitize_provider_text(message or "Video generation failed."),
                    retryable=False,
                    code="PROVIDER_ERROR",
                    provider="veo",
                    category="provider_rejection",
                )
            return current
        except (GoogleProviderError, MissingAPIKeyError, ProviderError, GenerationCancelled):
            raise
        except Exception as exc:
            raise self._wrap_error(exc, "Video generation status could not be checked.") from exc

    def save_video(self, task: Any, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        uri = ""
        operation = None
        if isinstance(task, dict):
            data = task.get("inline") or b""
            uri = str(task.get("uri") or "")
            saved = task.get("path")
            if saved and Path(saved).exists() and Path(saved).stat().st_size > 0:
                if Path(saved) != dest:
                    dest.write_bytes(Path(saved).read_bytes())
                return dest
            if data:
                dest.write_bytes(data)
                return dest
            operation = task.get("operation")
            extra_video = task.get("generated_video")
        else:
            operation = task
            extra_video = None
        video = self._video_from_operation(operation) or extra_video
        inline = b""
        if video is not None:
            inline = getattr(video, "video_bytes", None) or getattr(video, "data", None) or b""
            uri = uri or str(getattr(video, "uri", "") or "")
        if inline:
            dest.write_bytes(inline)
            return dest
        if video is None and not uri:
            raise GoogleProviderError(
                "Video generation returned no video.",
                retryable=False,
                code="INVALID_VIDEO",
                provider="veo",
                category="provider_rejection",
            )
        try:
            client = self._client()
            target = video if video is not None else uri
            # Official Veo download: files.download(file=generated_video.video, destination=...)
            client.files.download(file=target, destination=str(dest))
            if dest.exists() and dest.stat().st_size > 0:
                return dest
            data = client.files.download(file=target)
            if data:
                dest.write_bytes(data)
                return dest
            filled = getattr(video, "video_bytes", None) if video is not None else None
            if filled:
                dest.write_bytes(filled)
                return dest
        except GoogleProviderError:
            raise
        except Exception as exc:
            logger.warning(
                "VEO_DOWNLOAD_FAILED %s",
                sanitize_provider_text(str(exc))[:300],
            )
            raise GoogleProviderError(
                "The generated video could not be downloaded. The AI clip was not generated again.",
                retryable=True,
                code="DOWNLOAD_FAILED",
                provider="veo",
                category="download",
            ) from exc
        raise GoogleProviderError(
            "Video generation returned no video.",
            retryable=False,
            code="INVALID_VIDEO",
            provider="veo",
            category="provider_rejection",
        )

    def _create(
        self,
        prompt: str,
        *,
        video_path: str | None,
        reference_paths: list[str],
        duration_seconds: int,
        aspect_ratio: str,
        generate_audio: bool,
        previous_video: Any | None = None,
        previous_video_uri: str | None = None,
        should_stop: Callable[[], None] | None = None,
    ) -> Any:
        from google.genai import types

        http = types.HttpOptions(
            timeout=60_000,
            retry_options=types.HttpRetryOptions(attempts=0),
        )
        # Gemini Developer API rejects Vertex-only Veo fields: generate_audio,
        # enhance_prompt. Native audio is always on for Veo 3.1.
        del generate_audio
        config_kwargs: dict[str, Any] = {
            "number_of_videos": 1,
            "aspect_ratio": aspect_ratio,
            "resolution": "720p",
            "http_options": http,
        }
        source_kwargs: dict[str, Any] = {"prompt": prompt}
        extending = (
            previous_video is not None
            or bool(str(previous_video_uri or "").strip())
            or bool(str(video_path or "").strip())
        )
        if extending:
            # Docs: video=operation.response.generated_videos[0].video.
            # Gemini Developer API does not support video bytes. mime_type
            # serializes as `encoding` and Veo 3.1 rejects it. Send URI only.
            source_kwargs["video"] = self._extension_video(
                previous_video=previous_video,
                previous_video_uri=previous_video_uri,
            )
        else:
            if duration_seconds:
                config_kwargs["duration_seconds"] = duration_seconds
            refs = []
            for path in reference_paths[:VEO_MAX_REFERENCE_IMAGES]:
                refs.append(
                    types.VideoGenerationReferenceImage(
                        image=types.Image.from_file(location=str(path)),
                        reference_type=types.VideoGenerationReferenceType.ASSET,
                    )
                )
            if refs:
                config_kwargs["reference_images"] = refs
        client = self._client(http)
        attempts = VEO_EXTENSION_NOT_READY_ATTEMPTS if extending else 1
        for attempt in range(1, attempts + 1):
            try:
                return client.models.generate_videos(
                    model=self.model,
                    source=types.GenerateVideosSource(**source_kwargs),
                    config=types.GenerateVideosConfig(**config_kwargs),
                )
            except Exception as exc:
                if not extending or not _extension_awaiting_processing(exc) or attempt >= attempts:
                    raise
                logger.warning(
                    "VEO_EXTENSION_NOT_READY attempt=%s/%s",
                    attempt,
                    attempts,
                )
                if callable(should_stop):
                    should_stop()
                time.sleep(VEO_EXTENSION_NOT_READY_WAIT_SECONDS)
        raise GoogleProviderError(
            "We couldn't finish the video generation.",
            retryable=False,
            code="PROVIDER_ERROR",
            provider="veo",
            category="provider_rejection",
        )

    def _extension_video(self, *, previous_video: Any | None, previous_video_uri: str | None):
        from google.genai import types

        uri = ""
        if previous_video is not None:
            uri = str(getattr(previous_video, "uri", "") or "").strip()
        uri = uri or str(previous_video_uri or "").strip()
        if not uri:
            raise GoogleProviderError(
                "We couldn't finish the video generation.",
                retryable=False,
                code="PROVIDER_ERROR",
                provider="veo",
                category="provider_rejection",
            )
        return types.Video(uri=uri)

    def _client(self, http_options: Any | None = None) -> Any:
        from google.genai import types

        options = http_options or types.HttpOptions(
            timeout=60_000,
            retry_options=types.HttpRetryOptions(attempts=0),
        )
        client = get_genai_client(http_options=options)
        _disable_sdk_retries(client)
        return client

    def _result_payload(self, operation: Any, *, prompt: str, duration: int, refs: list[str], extending: bool) -> dict[str, Any]:
        video = self._video_from_operation(operation)
        uri = str(getattr(video, "uri", "") or "") if video is not None else ""
        inline = b""
        if video is not None:
            inline = getattr(video, "video_bytes", None) or getattr(video, "data", None) or b""
        return {
            "id": str(getattr(operation, "name", None) or getattr(operation, "id", "") or ""),
            "file_id": uri,
            "uri": uri,
            "inline": inline or b"",
            "model": self.model,
            "duration_requested": duration,
            "resolution": "720p",
            "aspect_ratio": "9:16",
            "reference_count": len(refs),
            "prompt_length": len(prompt or ""),
            "store": False,
            "background": True,
            "stream": False,
            "delivery": "uri" if uri else "inline",
            "task": "extend" if extending else "generate",
            "provider": "veo",
            "operation": operation,
        }

    def _video_from_operation(self, operation: Any) -> Any:
        if operation is None:
            return None
        for attr in ("response", "result"):
            response = getattr(operation, attr, None)
            videos = getattr(response, "generated_videos", None) if response is not None else None
            if not isinstance(videos, (list, tuple)) or not videos:
                continue
            first = videos[0]
            video = getattr(first, "video", None) or first
            if video is not None:
                return video
        return None

    def _empty_generation(self, operation: Any, video: Any) -> bool:
        uri = str(getattr(video, "uri", "") or "") if video is not None else ""
        inline = b""
        if video is not None:
            raw = getattr(video, "video_bytes", None) or getattr(video, "data", None) or b""
            inline = raw if isinstance(raw, (bytes, bytearray)) else b""
        return not (video is not None and (uri or inline))

    def _raise_if_empty_generation(self, operation: Any, video: Any) -> None:
        if not self._empty_generation(operation, video):
            return
        response = getattr(operation, "response", None) or getattr(operation, "result", None)
        filtered = 0
        reasons: list[str] = []
        if response is not None:
            try:
                filtered = int(getattr(response, "rai_media_filtered_count", 0) or 0)
            except (TypeError, ValueError):
                filtered = 0
            reasons = [str(item) for item in (getattr(response, "rai_media_filtered_reasons", None) or []) if item]
        logger.warning(
            "VEO_EMPTY_VIDEO filtered=%s reasons=%s",
            filtered,
            "; ".join(reasons)[:200],
        )
        if filtered or reasons:
            raise GoogleProviderError(
                "The provider blocked this clip. Please try generating again.",
                retryable=True,
                code="PROVIDER_ERROR",
                provider="veo",
                category="provider_rejection",
            )
        raise GoogleProviderError(
            "Video generation returned no video.",
            retryable=False,
            code="INVALID_VIDEO",
            provider="veo",
            category="provider_rejection",
        )

    def _wrap_error(self, exc: Exception, fallback: str) -> ProviderError:
        if isinstance(exc, (GoogleProviderError, MissingAPIKeyError, ProviderError)):
            return exc
        status = 0
        for attr in ("status_code", "code"):
            value = getattr(exc, attr, None)
            if isinstance(value, int) and value >= 400:
                status = value
                break
        message = sanitize_provider_text(str(exc) or fallback)
        lowered = message.lower()
        retry_after = _retry_after_text(message)
        logger.warning("VEO_PROVIDER_ERROR status=%s message=%s", status, message[:300])
        if status == 429 or "quota" in lowered or "rate limit" in lowered:
            wait = f" The provider asked to wait {retry_after}." if retry_after else ""
            return GoogleProviderError(
                "Video generation is temporarily rate limited. "
                "Please try again when the provider quota becomes available."
                + wait,
                retryable=False,
                code="RATE_LIMITED",
                status_code=status or 429,
                provider="veo",
                category="rate_limited",
                retry_after=retry_after,
            )
        if status in {408} or "timed out" in lowered or "timeout" in lowered:
            return GoogleProviderError(
                "Video generation timed out. The worker was released. Please try again.",
                retryable=False,
                code="TIMEOUT",
                status_code=status,
                provider="veo",
                category="timeout",
            )
        if status >= 500 or status == 0:
            return GoogleProviderError(
                "We couldn't finish the video generation.",
                retryable=status >= 500,
                code="PROVIDER_ERROR",
                status_code=status,
                provider="veo",
                category="provider_unavailable" if status >= 500 else "network",
            )
        return GoogleProviderError(
            "We couldn't finish the video generation.",
            retryable=False,
            code="PROVIDER_ERROR",
            status_code=status,
            provider="veo",
            category="provider_rejection",
        )


def _extension_awaiting_processing(exc: Exception) -> bool:
    """Veo can reject a just-finished clip until its own processing finishes."""
    text = str(exc or "").lower()
    return "has been processed" in text and "generated by veo" in text


def sanitize_provider_text(value: str) -> str:
    text = re.sub(r"(api[_-]?key|token|bearer)\s*[:=]\s*\S+", r"\1=[redacted]", str(value or ""), flags=re.I)
    return text.strip()[:500]


def _retry_after_text(message: str) -> str:
    match = re.search(r"retry in ([0-9]+h)?([0-9]+m)?([0-9]+s)?", str(message or ""), flags=re.I)
    if not match:
        return ""
    return "".join(part for part in match.groups() if part)
