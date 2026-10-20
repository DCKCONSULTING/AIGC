"""MiniMax H3 / H3-Max video generation via the V2 asynchronous API.

Studio uses this only when VIDEO_PROVIDER=minimax. There is no Omni/Veo fallback.

Verified against https://platform.minimax.io/docs/guides/video-generation
and https://platform.minimax.io/docs/api-reference/video-generation-v2-create:

- Host: https://api.minimax.io
- Create: POST /v2/video_generation → task_id
- Query: GET /v2/query/video_generation/{task_id} → task.status / content.url
- Cancel queued: DELETE /v2/video_generation/{task_id} (queued only; running cannot be cancelled)
- Models: MiniMax-H3 (4–15s, 768P/2K), MiniMax-H3-Max (5–15s, 480P/768P)
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from django.conf import settings

from ai.exceptions import MissingAPIKeyError, ProviderError
from ai.services.cancel import GenerationCancelled

logger = logging.getLogger(__name__)

MINIMAX_API_BASE_DEFAULT = "https://api.minimax.io"
MINIMAX_SUPPORTED_MODELS = frozenset({"MiniMax-H3", "MiniMax-H3-Max"})
MINIMAX_MAX_CLIP_SECONDS = 15
MINIMAX_MAX_REFERENCE_IMAGES = 9
MINIMAX_POLL_SECONDS = 10
MINIMAX_PROMPT_MAX_CHARS = 7000
MINIMAX_MAX_IMAGE_BYTES = 30 * 1024 * 1024
# Base64 inflates ~33%; keep request body under the documented 64 MB limit.
MINIMAX_SAFE_INLINE_IMAGE_BYTES = 8 * 1024 * 1024
MINIMAX_MAX_CONTINUOUS_DURATION_SECONDS = 150  # 10 × 15s clips

_limiter: threading.BoundedSemaphore | None = None
_limiter_size = 0
_limiter_guard = threading.Lock()


def require_minimax_api_key() -> str:
    key = str(getattr(settings, "MINIMAX_API_KEY", "") or "").strip()
    if not key:
        raise MissingAPIKeyError(
            "MiniMax is not configured. Add MINIMAX_API_KEY to backend/.env."
        )
    return key


def minimax_operation_timeout() -> int:
    try:
        value = int(getattr(settings, "MINIMAX_OPERATION_TIMEOUT_SECONDS", 900) or 900)
    except (TypeError, ValueError):
        value = 900
    return max(60, min(value, 1800))


def minimax_limiter() -> threading.BoundedSemaphore:
    global _limiter, _limiter_size
    try:
        size = int(getattr(settings, "MINIMAX_MAX_IN_FLIGHT", 3) or 3)
    except (TypeError, ValueError):
        size = 3
    size = max(1, min(size, 8))
    with _limiter_guard:
        if _limiter is None or _limiter_size != size:
            _limiter = threading.BoundedSemaphore(size)
            _limiter_size = size
        return _limiter


def model_duration_bounds(model: str) -> tuple[int, int]:
    name = str(model or "").strip()
    if name == "MiniMax-H3-Max":
        return 5, MINIMAX_MAX_CLIP_SECONDS
    return 4, MINIMAX_MAX_CLIP_SECONDS


def plan_minimax_generation(target_duration: int, *, model: str = "MiniMax-H3") -> dict[str, Any]:
    """Split a product duration into MiniMax clips of at most 15 seconds.

    Clips are filled to the model max (15s) except the last, which is clamped
    to the model minimum when the remainder is shorter. Overshoot is trimmed.
    """
    target = int(target_duration)
    if target < 1:
        raise ValueError("Requested duration is too short for MiniMax.")
    if target > MINIMAX_MAX_CONTINUOUS_DURATION_SECONDS:
        raise ProviderError(
            f"MiniMax cannot generate more than {MINIMAX_MAX_CONTINUOUS_DURATION_SECONDS} "
            "seconds as one Studio film.",
            retryable=False,
            code="INVALID_DURATION",
            provider="minimax",
            category="configuration",
        )
    low, high = model_duration_bounds(model)
    if target <= high:
        clip = max(low, min(target, high))
        if target < low:
            clip = low
        return {
            "clip_durations": [clip],
            "clip_count": 1,
            "generated_duration": clip,
            "trim_to": 0 if clip == target else target,
            "max_clip_seconds": high,
            "min_clip_seconds": low,
        }
    full = target // high
    rem = target % high
    durations = [high] * full
    if rem:
        if rem < low:
            # Borrow from previous full clip so the last segment meets the minimum.
            if durations:
                durations[-1] = high - (low - rem)
                durations.append(low)
            else:
                durations.append(low)
        else:
            durations.append(rem)
    generated = sum(durations)
    return {
        "clip_durations": durations,
        "clip_count": len(durations),
        "generated_duration": generated,
        "trim_to": target if generated > target else 0,
        "max_clip_seconds": high,
        "min_clip_seconds": low,
    }


def select_minimax_reference_paths(
    paths: list[str],
    *,
    character_paths: list[str] | None = None,
    product_paths: list[str] | None = None,
    style_paths: list[str] | None = None,
    limit: int = 4,
) -> list[str]:
    """Prefer character, product, then style; cap below the API max of 9."""
    cap = max(1, min(int(limit or 4), MINIMAX_MAX_REFERENCE_IMAGES))
    chosen: list[str] = []
    seen: set[str] = set()

    def take(candidates: list[str] | None, count: int = 1) -> None:
        taken = 0
        for path in candidates or []:
            key = str(path or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            chosen.append(key)
            taken += 1
            if taken >= count or len(chosen) >= cap:
                return

    take(character_paths, 1)
    take(product_paths, 1)
    take(style_paths, 1)
    take(paths, cap)
    return chosen[:cap]


def sanitize_provider_text(value: str) -> str:
    text = re.sub(
        r"(api[_-]?key|token|bearer|authorization)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        str(value or ""),
        flags=re.I,
    )
    return text.strip()[:500]


class MiniMaxProvider:
    """MiniMax H3 V2 video generation. Used only when VIDEO_PROVIDER=minimax."""

    def __init__(self):
        configured = str(getattr(settings, "MINIMAX_VIDEO_MODEL", "") or "").strip()
        self.model = configured or "MiniMax-H3"
        if self.model not in MINIMAX_SUPPORTED_MODELS:
            raise ProviderError(
                f"MINIMAX_VIDEO_MODEL={self.model!r} is not supported. "
                f"Use one of: {', '.join(sorted(MINIMAX_SUPPORTED_MODELS))}.",
                retryable=False,
                code="INVALID_CONFIGURATION",
                provider="minimax",
                category="configuration",
            )
        self.base = str(
            getattr(settings, "MINIMAX_API_BASE", "") or MINIMAX_API_BASE_DEFAULT
        ).rstrip("/")
        resolution = str(getattr(settings, "MINIMAX_VIDEO_RESOLUTION", "") or "").strip()
        if not resolution:
            resolution = "768P"
        self.resolution = resolution
        if self.model == "MiniMax-H3-Max" and self.resolution == "2K":
            self.resolution = "768P"
        if self.model == "MiniMax-H3" and self.resolution not in {"768P", "2K"}:
            self.resolution = "768P"
        if self.model == "MiniMax-H3-Max" and self.resolution not in {"480P", "768P"}:
            self.resolution = "768P"

    def family(self) -> str:
        return "minimax"

    def clamp_duration(self, duration_seconds: int) -> int:
        low, high = model_duration_bounds(self.model)
        return min(max(int(duration_seconds or low), low), high)

    def poll_interval(self) -> int:
        return MINIMAX_POLL_SECONDS

    def prepare_images(
        self,
        paths: list[str | Path] | None,
        *,
        character_paths: list[str] | None = None,
        product_paths: list[str] | None = None,
        style_paths: list[str] | None = None,
    ) -> list[str]:
        string_paths = [str(path) for path in (paths or []) if str(path or "").strip()]
        return select_minimax_reference_paths(
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
        first_frame_path: str | Path | None = None,
        last_frame_path: str | Path | None = None,
        store: bool = False,
        task: str | None = None,
        attempt_context: dict[str, Any] | None = None,
        should_stop: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        del previous_video, previous_video_uri, previous_interaction_id, store, generate_audio, video_path
        require_minimax_api_key()
        duration = self.clamp_duration(duration_seconds)
        ratio = aspect_ratio if aspect_ratio in {
            "21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"
        } else "9:16"
        text = (prompt or "").strip()[:MINIMAX_PROMPT_MAX_CHARS]
        if not text:
            raise ProviderError(
                "A video prompt is required.",
                retryable=False,
                code="INVALID_REQUEST",
                provider="minimax",
                category="validation",
            )

        first = str(first_frame_path or image_path or "").strip()
        last = str(last_frame_path or "").strip()
        refs = [str(p) for p in (prepared_images or []) if str(p or "").strip()]
        if not refs:
            ordered: list[str] = []
            if image_path and not first:
                ordered.append(str(image_path))
            ordered.extend(str(path) for path in (image_paths or []) if path)
            refs = select_minimax_reference_paths(ordered)

        # Image-to-video and reference-to-video are mutually exclusive per API docs.
        mode = "t2v"
        if first or last:
            mode = "i2v"
            refs = []
        elif refs:
            mode = "r2v"

        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if mode == "i2v":
            if first:
                content.append(self._image_content(Path(first), role="first_frame"))
            if last:
                content.append(self._image_content(Path(last), role="last_frame"))
            ratio = "adaptive"
        elif mode == "r2v":
            for path in refs[:MINIMAX_MAX_REFERENCE_IMAGES]:
                content.append(self._image_content(Path(path), role="reference_image"))

        payload: dict[str, Any] = {
            "model": self.model,
            "content": content,
            "duration": duration,
            "resolution": self.resolution,
        }
        if mode == "t2v":
            payload["ratio"] = ratio if ratio != "adaptive" else "9:16"
        elif mode == "r2v":
            payload["ratio"] = ratio if ratio != "adaptive" else "9:16"

        context = attempt_context or {}
        started_at = time.perf_counter()
        limiter = minimax_limiter()
        limiter.acquire()
        task_id = ""
        try:
            if callable(should_stop):
                should_stop()
            created = self._create(payload)
            task_id = str(created.get("task_id") or "").strip()
            if not task_id:
                raise ProviderError(
                    "Video generation returned no job id.",
                    retryable=True,
                    code="PROVIDER_ERROR",
                    provider="minimax",
                    category="provider_rejection",
                )
            polled = self.poll(
                task_id,
                timeout_seconds=minimax_operation_timeout(),
                interval_seconds=self.poll_interval(),
                should_stop=should_stop,
            )
            url = self._video_url(polled)
            return {
                "id": task_id,
                "file_id": task_id,
                "uri": url,
                "inline": b"",
                "path": "",
                "raw": polled,
                "model": self.model,
                "duration_requested": duration,
                "resolution": self.resolution,
                "aspect_ratio": ratio,
                "reference_count": len(refs) if mode == "r2v" else int(bool(first)) + int(bool(last)),
                "prompt_length": len(text),
                "store": False,
                "background": True,
                "stream": False,
                "delivery": "uri",
                "task": task or ("continue" if mode == "i2v" and not last else "generate"),
                "provider": "minimax",
                "mode": mode,
                "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
                "attempt_context": context,
            }
        except GenerationCancelled:
            self._try_cancel_queued(task_id)
            raise
        except (MissingAPIKeyError, ProviderError):
            raise
        except Exception as exc:
            raise self._wrap_error(exc, "Video generation could not be started.") from exc
        finally:
            limiter.release()

    def poll(
        self,
        task_id: str,
        *,
        timeout_seconds: int | None = None,
        interval_seconds: int | None = None,
        should_stop: Callable[[], None] | None = None,
        operation: Any = None,
    ) -> dict[str, Any]:
        del operation
        import httpx

        key = require_minimax_api_key()
        timeout = int(timeout_seconds or minimax_operation_timeout())
        interval = max(5, int(interval_seconds or self.poll_interval()))
        deadline = time.perf_counter() + timeout
        consecutive_errors = 0
        while time.perf_counter() < deadline:
            if callable(should_stop):
                should_stop()
            try:
                response = httpx.get(
                    f"{self.base}/v2/query/video_generation/{task_id}",
                    headers=self._headers(key),
                    timeout=30,
                )
                status_code = response.status_code
                data = response.json() if response.content else {}
                if status_code >= 400:
                    raise self._http_error(status_code, data, "Video generation status could not be checked.")
                consecutive_errors = 0
            except GenerationCancelled:
                self._try_cancel_queued(task_id)
                raise
            except ProviderError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                logger.warning(
                    "MINIMAX_POLL_ERROR count=%s/%s task_id=%s",
                    consecutive_errors,
                    3,
                    task_id,
                )
                if consecutive_errors >= 3:
                    raise self._wrap_error(exc, "Video generation status could not be checked.") from exc
                time.sleep(interval)
                continue

            task = data.get("task") if isinstance(data, dict) else None
            if not isinstance(task, dict):
                raise ProviderError(
                    "Video generation status response was invalid.",
                    retryable=True,
                    code="PROVIDER_ERROR",
                    provider="minimax",
                    category="provider_rejection",
                )
            status = str(task.get("status") or "").lower()
            if status == "succeeded":
                if not self._video_url({"task": task, **task}):
                    raise ProviderError(
                        "Video generation returned no download URL.",
                        retryable=False,
                        code="INVALID_VIDEO",
                        provider="minimax",
                        category="provider_rejection",
                    )
                return {"task": task, **task}
            if status in {"failed", "cancelled"}:
                error = task.get("error") if isinstance(task.get("error"), dict) else {}
                detail = sanitize_provider_text(
                    str(error.get("message") or error.get("code") or status)
                )
                code = "PROVIDER_ERROR"
                if status == "cancelled":
                    code = "CANCELLED"
                raise ProviderError(
                    f"Video generation did not succeed: {detail}",
                    retryable=False,
                    code=code,
                    provider="minimax",
                    category="provider_rejection",
                )
            time.sleep(interval)
        raise ProviderError(
            "Video generation timed out. The worker was released. Please try again.",
            retryable=False,
            code="TIMEOUT",
            provider="minimax",
            category="timeout",
        )

    def save_video(self, task: dict[str, Any], dest: Path) -> Path:
        import httpx

        dest.parent.mkdir(parents=True, exist_ok=True)
        inline = task.get("inline")
        if isinstance(inline, (bytes, bytearray)) and inline:
            dest.write_bytes(inline)
            return dest
        local = str(task.get("path") or "").strip()
        if local and Path(local).exists() and Path(local).stat().st_size > 0:
            dest.write_bytes(Path(local).read_bytes())
            return dest
        url = str(task.get("uri") or self._video_url(task) or "").strip()
        if not url:
            raise ProviderError(
                "Video generation returned no video.",
                retryable=False,
                code="INVALID_VIDEO",
                provider="minimax",
                category="provider_rejection",
            )
        try:
            response = httpx.get(url, timeout=120, follow_redirects=True)
            response.raise_for_status()
            if not response.content:
                raise ProviderError(
                    "The generated video could not be downloaded.",
                    retryable=True,
                    code="DOWNLOAD_FAILED",
                    provider="minimax",
                    category="download",
                )
            dest.write_bytes(response.content)
            return dest
        except ProviderError:
            raise
        except Exception as exc:
            logger.warning(
                "MINIMAX_DOWNLOAD_FAILED %s",
                sanitize_provider_text(str(exc))[:300],
            )
            raise ProviderError(
                "The generated video could not be downloaded. The AI clip was not generated again.",
                retryable=True,
                code="DOWNLOAD_FAILED",
                provider="minimax",
                category="download",
            ) from exc

    def _create(self, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        key = require_minimax_api_key()
        try:
            response = httpx.post(
                f"{self.base}/v2/video_generation",
                headers=self._headers(key),
                json=payload,
                timeout=120,
            )
            data = response.json() if response.content else {}
            if response.status_code >= 400:
                raise self._http_error(response.status_code, data, "Video generation could not be started.")
            if not isinstance(data, dict):
                raise ProviderError(
                    "Video generation returned an invalid response.",
                    retryable=True,
                    code="PROVIDER_ERROR",
                    provider="minimax",
                    category="provider_rejection",
                )
            # Some error payloads return HTTP 200 with type=error.
            if str(data.get("type") or "").lower() == "error" or (
                isinstance(data.get("error"), dict) and not data.get("task_id")
            ):
                raise self._http_error(400, data, "Video generation could not be started.")
            return data
        except ProviderError:
            raise
        except Exception as exc:
            raise self._wrap_error(exc, "Video generation could not be started.") from exc

    def _try_cancel_queued(self, task_id: str) -> None:
        """Best-effort cancel. Running tasks cannot be cancelled remotely."""
        if not str(task_id or "").strip():
            return
        import httpx

        try:
            key = require_minimax_api_key()
            response = httpx.delete(
                f"{self.base}/v2/video_generation/{task_id}",
                headers=self._headers(key),
                timeout=30,
            )
            if response.status_code < 400:
                action = ""
                try:
                    action = str((response.json() or {}).get("action") or "")
                except Exception:
                    action = ""
                logger.info(
                    "MINIMAX_CANCEL_ATTEMPT task_id=%s http=%s action=%s",
                    task_id,
                    response.status_code,
                    action or "ok",
                )
            else:
                logger.info(
                    "MINIMAX_CANCEL_SKIPPED task_id=%s http=%s (running tasks cannot be cancelled)",
                    task_id,
                    response.status_code,
                )
        except Exception:
            logger.info("MINIMAX_CANCEL_SKIPPED task_id=%s", task_id)

    def _headers(self, key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _image_content(self, path: Path, *, role: str) -> dict[str, Any]:
        resolved = Path(path)
        if not resolved.exists():
            raise ProviderError(
                "A reference image is missing.",
                retryable=False,
                code="INVALID_REQUEST",
                provider="minimax",
                category="validation",
            )
        size = resolved.stat().st_size
        if size > MINIMAX_MAX_IMAGE_BYTES:
            raise ProviderError(
                "A reference image exceeds the MiniMax size limit.",
                retryable=False,
                code="INVALID_REQUEST",
                provider="minimax",
                category="validation",
            )
        if size > MINIMAX_SAFE_INLINE_IMAGE_BYTES:
            logger.warning("MiniMax image is large for inline upload path=%s size=%s", resolved.name, size)
        mime, _ = mimetypes.guess_type(str(resolved))
        mime = (mime or "image/jpeg").lower()
        if mime == "image/jpg":
            mime = "image/jpeg"
        encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
            "role": role,
        }

    def _video_url(self, task: dict[str, Any]) -> str:
        if not isinstance(task, dict):
            return ""
        content = task.get("content")
        if isinstance(content, dict):
            url = content.get("url") or content.get("video_url")
            if url:
                return str(url)
        nested = task.get("task")
        if isinstance(nested, dict):
            nested_content = nested.get("content")
            if isinstance(nested_content, dict):
                url = nested_content.get("url") or nested_content.get("video_url")
                if url:
                    return str(url)
        return str(task.get("url") or task.get("video_url") or "")

    def _http_error(self, status_code: int, data: Any, fallback: str) -> ProviderError:
        detail = ""
        err_type = ""
        request_id = ""
        if isinstance(data, dict):
            request_id = str(data.get("request_id") or "")
            error = data.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message") or "")
                err_type = str(error.get("type") or "")
                status_code = status_code or int(str(error.get("http_code") or 0) or 0)
            elif error:
                detail = str(error)
        message = sanitize_provider_text(detail or fallback)
        lowered = f"{err_type} {message}".lower()
        logger.warning(
            "MINIMAX_PROVIDER_ERROR status=%s type=%s message=%s request_id=%s",
            status_code,
            err_type or "-",
            message[:300],
            request_id or "-",
        )
        if status_code in {401, 403} or "authorized_error" in lowered:
            return ProviderError(
                "The video service could not authorize this request.",
                retryable=False,
                code="AUTHENTICATION",
                status_code=status_code or 401,
                provider="minimax",
                category="authentication",
                request_id=request_id,
            )
        if status_code == 402 or "insufficient_balance" in lowered or "insufficient balance" in lowered:
            return ProviderError(
                "MiniMax quota or balance is insufficient for video generation.",
                retryable=False,
                code="RATE_LIMITED",
                status_code=status_code or 402,
                provider="minimax",
                category="rate_limited",
                request_id=request_id,
            )
        if status_code == 429 or "rate_limit" in lowered:
            return ProviderError(
                "Video generation is temporarily rate limited. "
                "Please try again when the provider quota becomes available.",
                retryable=False,
                code="RATE_LIMITED",
                status_code=status_code or 429,
                provider="minimax",
                category="rate_limited",
                request_id=request_id,
            )
        if status_code == 422 or "sensitive" in lowered or "unprocessable" in lowered:
            return ProviderError(
                "The provider blocked this clip. Please try generating again.",
                retryable=False,
                code="INVALID_REQUEST",
                status_code=status_code or 422,
                provider="minimax",
                category="provider_rejection",
                request_id=request_id,
            )
        if status_code in {400, 422} or "bad_request" in lowered:
            return ProviderError(
                "The video provider rejected this request. Please try again.",
                retryable=False,
                code="INVALID_REQUEST",
                status_code=status_code or 400,
                provider="minimax",
                category="provider_rejection",
                request_id=request_id,
            )
        if status_code in {408} or "timeout" in lowered or "timed out" in lowered:
            return ProviderError(
                "Video generation timed out. The worker was released. Please try again.",
                retryable=False,
                code="TIMEOUT",
                status_code=status_code,
                provider="minimax",
                category="timeout",
                request_id=request_id,
            )
        if status_code >= 500:
            return ProviderError(
                "We couldn't finish the video generation.",
                retryable=True,
                code="PROVIDER_ERROR",
                status_code=status_code,
                provider="minimax",
                category="provider_unavailable",
                request_id=request_id,
            )
        return ProviderError(
            "We couldn't finish the video generation.",
            retryable=False,
            code="PROVIDER_ERROR",
            status_code=status_code,
            provider="minimax",
            category="provider_rejection",
            request_id=request_id,
        )

    def _wrap_error(self, exc: Exception, fallback: str) -> ProviderError:
        if isinstance(exc, (MissingAPIKeyError, ProviderError)):
            return exc
        response = getattr(exc, "response", None)
        status = int(getattr(response, "status_code", 0) or getattr(exc, "status_code", 0) or 0)
        data: Any = {}
        if response is not None:
            try:
                data = response.json()
            except Exception:
                data = {"error": {"message": getattr(response, "text", "")[:400]}}
        if status or data:
            return self._http_error(status, data, fallback)
        message = sanitize_provider_text(str(exc) or fallback)
        lowered = message.lower()
        logger.warning("MINIMAX_PROVIDER_ERROR status=%s message=%s", status, message[:300])
        if "timed out" in lowered or "timeout" in lowered:
            return ProviderError(
                "Video generation timed out. The worker was released. Please try again.",
                retryable=False,
                code="TIMEOUT",
                provider="minimax",
                category="timeout",
            )
        return ProviderError(
            "We couldn't finish the video generation.",
            retryable=True,
            code="PROVIDER_ERROR",
            provider="minimax",
            category="network",
        )
