"""BytePlus ModelArk Seedance video generation (1.x / 2.0 / 2.5).

Studio uses this when VIDEO_PROVIDER=seedance. There is no Omni/Veo/MiniMax fallback.

Verified against BytePlus ModelArk docs (ap-southeast-1):
- Host: https://ark.ap-southeast.bytepluses.com
- Create: POST /api/v3/contents/generations/tasks
- Query: GET /api/v3/contents/generations/tasks/{id}
- Cancel/delete: DELETE /api/v3/contents/generations/tasks/{id}
- Seedance 2.5: dreamina-seedance-2-5-260628 (4–30s, 480p/720p/1080p)
- Seedance 2.0 fast: dreamina-seedance-2-0-fast-260128 (4–15s, 480p/720p)
- first_frame / last_frame I2V: ratio must be adaptive (2.0 / 2.5)
- Do not mix first_frame/last_frame with reference_image in one request
- service_tier only for 2.5 (2.0-fast rejects the field)
- priority 0–9 reorders the queue for the same Endpoint; does not interrupt running tasks
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

SEEDANCE_API_BASE_DEFAULT = "https://ark.ap-southeast.bytepluses.com/api/v3"
SEEDANCE_MODEL_2_5 = "dreamina-seedance-2-5-260628"
SEEDANCE_MODEL_2_0_FAST = "dreamina-seedance-2-0-fast-260128"
SEEDANCE_MAX_CLIP_SECONDS_2_5 = 30
SEEDANCE_MAX_CLIP_SECONDS_2_0 = 15
SEEDANCE_MAX_CLIP_SECONDS_1_X = 12
SEEDANCE_MIN_CLIP_SECONDS = 4
SEEDANCE_MAX_REFERENCE_IMAGES = 4  # keep payloads small; API allows more on 2.5
SEEDANCE_MAX_INLINE_BYTES = 4 * 1024 * 1024
SEEDANCE_POLL_SECONDS = 8
SEEDANCE_POLL_FAST_SECONDS = 3
SEEDANCE_MAX_CONTINUOUS_DURATION_SECONDS = 120  # 4 × 30s
SEEDANCE_PROMPT_MAX_CHARS = 8000

_limiter: threading.BoundedSemaphore | None = None
_limiter_size = 0
_limiter_guard = threading.Lock()


def require_seedance_key() -> str:
    key = (getattr(settings, "SEEDANCE_API_KEY", "") or "").strip()
    if not key:
        raise MissingAPIKeyError(
            "Seedance is not configured. Add SEEDANCE_API_KEY to backend/.env."
        )
    return key


def seedance_operation_timeout() -> int:
    try:
        value = int(getattr(settings, "SEEDANCE_OPERATION_TIMEOUT_SECONDS", 1800) or 1800)
    except (TypeError, ValueError):
        value = 1800
    return max(60, min(value, 1800))


def seedance_priority() -> int:
    """ModelArk priority for Dreamina 2.x (0–9). Higher values dequeue sooner."""
    try:
        value = int(getattr(settings, "SEEDANCE_PRIORITY", 5) or 5)
    except (TypeError, ValueError):
        value = 5
    return max(0, min(value, 9))


def extract_task_timing(data: dict[str, Any] | None) -> dict[str, Any]:
    """Pull API wall times and poll observations. Never labels wait as pure render."""
    payload = data if isinstance(data, dict) else {}
    created_at = payload.get("created_at")
    updated_at = payload.get("updated_at")
    api_wall_seconds = None
    try:
        if created_at is not None and updated_at is not None:
            api_wall_seconds = max(0, int(updated_at) - int(created_at))
    except (TypeError, ValueError):
        api_wall_seconds = None
    return {
        "api_created_at": created_at,
        "api_updated_at": updated_at,
        "api_wall_seconds": api_wall_seconds,
        "service_tier": payload.get("service_tier") or "default",
        "priority": payload.get("priority"),
        "queued_observed_ms": payload.get("_queued_observed_ms"),
        "running_observed_ms": payload.get("_running_observed_ms"),
        "first_status": payload.get("_first_status") or "",
        "poll_count": payload.get("_poll_count"),
        "local_poll_ms": payload.get("_local_poll_ms"),
    }


def seedance_limiter() -> threading.BoundedSemaphore:
    global _limiter, _limiter_size
    try:
        size = int(getattr(settings, "SEEDANCE_MAX_IN_FLIGHT", 3) or 3)
    except (TypeError, ValueError):
        size = 3
    size = max(1, min(size, 8))
    with _limiter_guard:
        if _limiter is None or _limiter_size != size:
            _limiter = threading.BoundedSemaphore(size)
            _limiter_size = size
        return _limiter


def seedance_version(model: str) -> str:
    name = (model or "").lower()
    if "2-5" in name or "2.5" in name:
        return "2.5"
    if "2-0" in name or "2.0" in name or "dreamina-seedance-2" in name:
        return "2.0"
    if "dreamina" in name and "seedance" in name:
        return "2.0"
    return "1.x"


def model_duration_bounds(model: str) -> tuple[int, int]:
    version = seedance_version(model)
    if version == "2.5":
        return SEEDANCE_MIN_CLIP_SECONDS, SEEDANCE_MAX_CLIP_SECONDS_2_5
    if version == "2.0":
        return SEEDANCE_MIN_CLIP_SECONDS, SEEDANCE_MAX_CLIP_SECONDS_2_0
    return SEEDANCE_MIN_CLIP_SECONDS, SEEDANCE_MAX_CLIP_SECONDS_1_X


def plan_seedance_generation(target_duration: int, *, model: str = SEEDANCE_MODEL_2_5) -> dict[str, Any]:
    """Prefer the fewest Seedance clips. 2.5 supports up to 30s per clip."""
    target = int(target_duration)
    if target < 1:
        raise ValueError("Requested duration is too short for Seedance.")
    if target > SEEDANCE_MAX_CONTINUOUS_DURATION_SECONDS:
        raise ProviderError(
            f"Seedance cannot generate more than {SEEDANCE_MAX_CONTINUOUS_DURATION_SECONDS} "
            "seconds as one Studio film.",
            retryable=False,
            code="INVALID_DURATION",
            provider="seedance",
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
    # Prefer max-length clips (e.g. 45 → 30+15, 60 → 30+30).
    durations: list[int] = []
    remaining = target
    while remaining > 0:
        if remaining <= high:
            if remaining < low and durations:
                need = low - remaining
                durations[-1] = max(low, durations[-1] - need)
                durations.append(low)
            else:
                durations.append(max(low, remaining))
            break
        durations.append(high)
        remaining -= high
    generated = sum(durations)
    return {
        "clip_durations": durations,
        "clip_count": len(durations),
        "generated_duration": generated,
        "trim_to": target if generated > target else 0,
        "max_clip_seconds": high,
        "min_clip_seconds": low,
    }


def select_seedance_reference_paths(
    paths: list[str],
    *,
    character_paths: list[str] | None = None,
    product_paths: list[str] | None = None,
    style_paths: list[str] | None = None,
    limit: int = SEEDANCE_MAX_REFERENCE_IMAGES,
) -> list[str]:
    cap = max(1, min(int(limit or SEEDANCE_MAX_REFERENCE_IMAGES), SEEDANCE_MAX_REFERENCE_IMAGES))
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


def resolve_seedance_model(value: str | None = None, *, default: str | None = None) -> str:
    """Map UI/API aliases to exact ModelArk model ids. Default remains Seedance 2.5."""
    configured = str(
        default
        if default is not None
        else (getattr(settings, "SEEDANCE_MODEL", "") or SEEDANCE_MODEL_2_5)
    ).strip()
    raw = str(value or "").strip()
    if not raw:
        return configured or SEEDANCE_MODEL_2_5
    key = raw.lower().replace("_", "-").replace(" ", "")
    aliases = {
        SEEDANCE_MODEL_2_5.lower(): SEEDANCE_MODEL_2_5,
        SEEDANCE_MODEL_2_0_FAST.lower(): SEEDANCE_MODEL_2_0_FAST,
        "2.5": SEEDANCE_MODEL_2_5,
        "2-5": SEEDANCE_MODEL_2_5,
        "seedance2.5": SEEDANCE_MODEL_2_5,
        "seedance-2.5": SEEDANCE_MODEL_2_5,
        "dreamina-seedance-2-5": SEEDANCE_MODEL_2_5,
        "2.0-fast": SEEDANCE_MODEL_2_0_FAST,
        "2-0-fast": SEEDANCE_MODEL_2_0_FAST,
        "fast": SEEDANCE_MODEL_2_0_FAST,
        "seedance2.0fast": SEEDANCE_MODEL_2_0_FAST,
        "seedance-2.0-fast": SEEDANCE_MODEL_2_0_FAST,
        "dreamina-seedance-2-0-fast": SEEDANCE_MODEL_2_0_FAST,
    }
    resolved = aliases.get(key) or aliases.get(raw.lower())
    if resolved:
        return resolved
    if "fast" in key and "seedance" in key:
        return SEEDANCE_MODEL_2_0_FAST
    if "2-5" in key or "2.5" in key:
        return SEEDANCE_MODEL_2_5
    raise ProviderError(
        f"Unsupported Seedance model {raw!r}. Use Seedance 2.5 or Seedance 2.0 Fast.",
        retryable=False,
        code="INVALID_MODEL",
        provider="seedance",
        category="configuration",
    )


class SeedanceProvider:
    """BytePlus ModelArk Seedance. Used when VIDEO_PROVIDER=seedance."""

    def __init__(self, model: str | None = None):
        self.base = (
            getattr(settings, "SEEDANCE_API_BASE", "") or SEEDANCE_API_BASE_DEFAULT
        ).rstrip("/")
        configured = str(getattr(settings, "SEEDANCE_MODEL", "") or SEEDANCE_MODEL_2_5).strip()
        self.model = resolve_seedance_model(model, default=configured)
        resolution = str(getattr(settings, "SEEDANCE_RESOLUTION", "") or "720p").strip().lower()
        if resolution not in {"480p", "720p", "1080p"}:
            resolution = "720p"
        # Documented 2.0-fast resolutions: 480p and 720p only.
        if "fast" in self.model.lower() and resolution == "1080p":
            resolution = "720p"
        self.resolution = resolution
        self.priority = seedance_priority()

    def family(self) -> str:
        """Provider id for VIDEO_PROVIDER metrics and routing."""
        return "seedance"

    def api_version(self) -> str:
        return seedance_version(self.model)

    def clamp_duration(self, duration_seconds: int) -> int:
        low, high = model_duration_bounds(self.model)
        return min(max(int(duration_seconds or low), low), high)

    def poll_interval(self) -> int:
        # Faster cadence for the documented 2.0-fast model; 2.5 stays at 8s.
        if "fast" in (self.model or "").lower():
            return SEEDANCE_POLL_FAST_SECONDS
        return SEEDANCE_POLL_SECONDS

    def prepare_images(
        self,
        paths: list[str | Path] | None,
        *,
        character_paths: list[str] | None = None,
        product_paths: list[str] | None = None,
        style_paths: list[str] | None = None,
    ) -> list[str]:
        string_paths = [str(path) for path in (paths or []) if str(path or "").strip()]
        return select_seedance_reference_paths(
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
        return_last_frame: bool = False,
        store: bool = False,
        task: str | None = None,
        attempt_context: dict[str, Any] | None = None,
        should_stop: Callable[[], None] | None = None,
        wait: bool = False,
    ) -> dict[str, Any]:
        """Submit a generation task. When wait=True, poll until terminal status."""
        del previous_video, previous_video_uri, previous_interaction_id, store
        require_seedance_key()
        version = self.api_version()
        duration = self.clamp_duration(duration_seconds)
        requested_ratio = aspect_ratio if aspect_ratio in {
            "21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"
        } else "9:16"
        text = (prompt or "").strip()[:SEEDANCE_PROMPT_MAX_CHARS]
        if not text:
            raise ProviderError(
                "A video prompt is required.",
                retryable=False,
                code="INVALID_REQUEST",
                provider="seedance",
                category="validation",
            )

        first = str(first_frame_path or "").strip()
        last = str(last_frame_path or "").strip()
        frame = str(image_path or "").strip()
        opening = first or frame
        refs = [str(p) for p in (prepared_images or []) if str(p or "").strip()]
        if not refs:
            ordered: list[str] = []
            if image_paths:
                ordered.extend(str(p) for p in image_paths if p)
            refs = select_seedance_reference_paths(ordered)
        frame_paths = {p for p in (opening, last) if p}
        extra_refs = [path for path in refs if path not in frame_paths]
        video = Path(video_path) if str(video_path or "").strip() else None
        has_video_ref = bool(video and video.exists())

        # Dreamina 2.x: first_frame/last_frame I2V is a distinct task type from omni R2V.
        if version in {"2.0", "2.5"} and (opening or last) and extra_refs:
            raise ProviderError(
                "Seedance cannot combine first_frame/last_frame with reference_image in one "
                "request. Use first-frame image-to-video, or reference-image generation.",
                retryable=False,
                code="INVALID_REQUEST",
                provider="seedance",
                category="validation",
            )
        if version in {"2.0", "2.5"} and (opening or last) and has_video_ref:
            raise ProviderError(
                "Seedance cannot combine first_frame/last_frame with reference_video in one "
                "request.",
                retryable=False,
                code="INVALID_REQUEST",
                provider="seedance",
                category="validation",
            )

        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        mode = "t2v"
        ratio = requested_ratio
        if opening or last:
            mode = "i2v"
            # Seedance 2.0 / 2.5 docs: first-frame / first-last-frame require ratio=adaptive.
            if version in {"2.0", "2.5"}:
                ratio = "adaptive"
            if opening:
                item = self._image_item(Path(opening), role="first_frame")
                if item:
                    content.append(item)
            if last and version != "1.x":
                item = self._image_item(Path(last), role="last_frame")
                if item:
                    content.append(item)
        elif extra_refs or has_video_ref:
            mode = "r2v"
            if version == "1.x":
                # Legacy 1.x path: one image as first_frame only.
                for path in (extra_refs or refs)[:1]:
                    item = self._image_item(Path(path), role="first_frame")
                    if item:
                        content.append(item)
                    break
            else:
                for path in extra_refs[:SEEDANCE_MAX_REFERENCE_IMAGES]:
                    item = self._image_item(Path(path), role="reference_image")
                    if item:
                        content.append(item)
                if has_video_ref and video is not None:
                    if video.stat().st_size <= SEEDANCE_MAX_INLINE_BYTES:
                        content.append(
                            self._file_content(video, "video_url", role="reference_video")
                        )
                    else:
                        logger.warning(
                            "Skipping oversized Seedance reference video %s", video.name
                        )

        payload: dict[str, Any] = {
            "model": self.model,
            "content": content,
            "duration": duration,
            "ratio": ratio,
            "resolution": self.resolution,
            "watermark": False,
            "generate_audio": bool(generate_audio),
        }
        # Dreamina 2.5 accepts service_tier=default. 2.0-fast rejects the field ("must be empty").
        if version == "2.5":
            payload["service_tier"] = "default"
        if version in {"2.0", "2.5"}:
            payload["priority"] = self.priority
        # Explicit R2V typing for 2.5 only (documented); avoid edit/extend misclassification.
        if mode == "r2v" and version == "2.5":
            payload["omni_reference_task_type"] = "reference"
        # Continuity helper; supported on Dreamina Seedance create API.
        if return_last_frame and version in {"2.0", "2.5"}:
            payload["return_last_frame"] = True

        context = attempt_context or {}
        started_at = time.perf_counter()
        limiter = seedance_limiter()
        limiter.acquire()
        task_id = ""
        try:
            if callable(should_stop):
                should_stop()
            submit_started = time.perf_counter()
            created = self._create(payload)
            task_id = str(created.get("id") or created.get("task_id") or "").strip()
            submit_ms = int((time.perf_counter() - submit_started) * 1000)
            if not task_id:
                raise ProviderError(
                    "Video generation returned no job id.",
                    retryable=True,
                    code="PROVIDER_ERROR",
                    provider="seedance",
                    category="provider_rejection",
                )
            result = {
                "id": task_id,
                "file_id": "",
                "uri": "",
                "inline": b"",
                "path": "",
                "raw": created,
                "model": self.model,
                "duration_requested": duration,
                "resolution": self.resolution,
                "aspect_ratio": ratio,
                "reference_count": max(0, len(content) - 1),
                "prompt_length": len(text),
                "store": False,
                "background": True,
                "stream": False,
                "delivery": "uri",
                "task": task or ("continue" if first else "generate"),
                "provider": "seedance",
                "mode": mode,
                "service_tier": payload.get("service_tier"),
                "priority": self.priority if version in {"2.0", "2.5"} else None,
                "submit_ms": submit_ms,
                "provider_wait_ms": 0,
                "elapsed_ms": submit_ms,
                "attempt_context": context,
            }
            if wait:
                polled = self.poll(
                    task_id,
                    timeout_seconds=seedance_operation_timeout(),
                    interval_seconds=self.poll_interval(),
                    should_stop=should_stop,
                )
                wait_ms = int((time.perf_counter() - started_at) * 1000) - submit_ms
                url = self._video_url(polled)
                last_url = ""
                content_obj = polled.get("content") if isinstance(polled.get("content"), dict) else {}
                if isinstance(content_obj, dict):
                    last_url = str(content_obj.get("last_frame_url") or "")
                timing = extract_task_timing(polled)
                result.update(
                    {
                        "uri": url,
                        "raw": polled,
                        "last_frame_url": last_url,
                        "provider_wait_ms": max(0, wait_ms),
                        "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
                        **timing,
                    }
                )
            return result
        except GenerationCancelled:
            self._try_cancel(task_id)
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
    ) -> dict[str, Any]:
        import httpx

        key = require_seedance_key()
        timeout = int(timeout_seconds or seedance_operation_timeout())
        base_interval = max(2, int(interval_seconds or self.poll_interval()))
        deadline = time.perf_counter() + timeout
        poll_started = time.perf_counter()
        consecutive_errors = 0
        poll_count = 0
        first_status = ""
        queued_ms = 0
        running_ms = 0
        phase_started = poll_started
        current_phase = ""
        # Never cancel on client timeout — resume the same task_id instead of resubmitting.
        while time.perf_counter() < deadline:
            if callable(should_stop):
                should_stop()
            try:
                response = httpx.get(
                    f"{self.base}/contents/generations/tasks/{task_id}",
                    headers=self._headers(key),
                    timeout=30,
                )
                status_code = response.status_code
                data = response.json() if response.content else {}
                if status_code >= 400:
                    raise self._http_error(status_code, data, "Video generation status could not be checked.")
                consecutive_errors = 0
                poll_count += 1
            except GenerationCancelled:
                self._try_cancel(task_id)
                raise
            except ProviderError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                logger.warning(
                    "SEEDANCE_POLL_ERROR count=%s/3 task_id=%s",
                    consecutive_errors,
                    task_id,
                )
                if consecutive_errors >= 3:
                    raise self._wrap_error(exc, "Video generation status could not be checked.") from exc
                time.sleep(base_interval)
                continue

            status = str(data.get("status") or data.get("task_status") or "").lower()
            if not first_status and status:
                first_status = status
            now = time.perf_counter()
            if status in {"queued", "pending"} and current_phase != "queued":
                if current_phase == "running":
                    running_ms += int((now - phase_started) * 1000)
                current_phase = "queued"
                phase_started = now
            elif status == "running" and current_phase != "running":
                if current_phase == "queued":
                    queued_ms += int((now - phase_started) * 1000)
                current_phase = "running"
                phase_started = now

            if status in {"succeeded", "success", "completed"}:
                if current_phase == "queued":
                    queued_ms += int((now - phase_started) * 1000)
                elif current_phase == "running":
                    running_ms += int((now - phase_started) * 1000)
                if not self._video_url(data):
                    raise ProviderError(
                        "Video generation returned no download URL.",
                        retryable=False,
                        code="INVALID_VIDEO",
                        provider="seedance",
                        category="provider_rejection",
                    )
                data["_poll_count"] = poll_count
                data["_first_status"] = first_status
                data["_queued_observed_ms"] = queued_ms
                data["_running_observed_ms"] = running_ms
                data["_local_poll_ms"] = int((now - poll_started) * 1000)
                logger.info(
                    "SEEDANCE_TASK_DONE task_id=%s model=%s api_wall_s=%s "
                    "first_status=%s queued_obs_ms=%s running_obs_ms=%s polls=%s",
                    task_id,
                    data.get("model") or self.model,
                    extract_task_timing(data).get("api_wall_seconds"),
                    first_status,
                    queued_ms,
                    running_ms,
                    poll_count,
                )
                return data
            if status in {"failed", "error", "cancelled", "canceled", "expired"}:
                detail = data.get("error") or data.get("message") or status
                if isinstance(detail, dict):
                    detail = detail.get("message") or detail.get("code") or status
                content = data.get("content")
                if (not detail or detail == status) and isinstance(content, dict):
                    detail = content.get("error") or content.get("message") or detail
                raise ProviderError(
                    f"Video generation did not succeed: {sanitize_provider_text(str(detail))}",
                    retryable=False,
                    code="CANCELLED" if "cancel" in status else "PROVIDER_ERROR",
                    provider="seedance",
                    category="provider_rejection",
                )
            # Bounded backoff: check sooner early, then settle near base_interval+2 (cap 12s).
            if poll_count < 4:
                sleep_for = min(base_interval, SEEDANCE_POLL_FAST_SECONDS)
            else:
                sleep_for = min(base_interval + 2, 12)
            time.sleep(sleep_for)
        raise ProviderError(
            f"Video generation timed out after {timeout}s for task {task_id}. "
            "The remote task was not cancelled; resume polling the same task id.",
            retryable=False,
            code="TIMEOUT",
            provider="seedance",
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
                provider="seedance",
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
                    provider="seedance",
                    category="download",
                )
            dest.write_bytes(response.content)
            return dest
        except ProviderError:
            raise
        except Exception as exc:
            logger.warning(
                "SEEDANCE_DOWNLOAD_FAILED %s",
                sanitize_provider_text(str(exc))[:300],
            )
            raise ProviderError(
                "The generated video could not be downloaded. The AI clip was not generated again.",
                retryable=True,
                code="DOWNLOAD_FAILED",
                provider="seedance",
                category="download",
            ) from exc

    def download_last_frame(self, url: str, dest: Path) -> Path | None:
        import httpx

        target = str(url or "").strip()
        if not target:
            return None
        try:
            response = httpx.get(target, timeout=60, follow_redirects=True)
            response.raise_for_status()
            if not response.content:
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.content)
            return dest
        except Exception:
            logger.warning("SEEDANCE_LAST_FRAME_DOWNLOAD_FAILED")
            return None

    def _create(self, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        key = require_seedance_key()
        try:
            response = httpx.post(
                f"{self.base}/contents/generations/tasks",
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
                    provider="seedance",
                    category="provider_rejection",
                )
            return data
        except ProviderError:
            raise
        except Exception as exc:
            raise self._wrap_error(exc, "Video generation could not be started.") from exc

    def _try_cancel(self, task_id: str) -> None:
        if not str(task_id or "").strip():
            return
        import httpx

        try:
            key = require_seedance_key()
            response = httpx.delete(
                f"{self.base}/contents/generations/tasks/{task_id}",
                headers=self._headers(key),
                timeout=30,
            )
            logger.info(
                "SEEDANCE_CANCEL_ATTEMPT task_id=%s http=%s",
                task_id,
                response.status_code,
            )
        except Exception:
            logger.info("SEEDANCE_CANCEL_SKIPPED task_id=%s", task_id)

    def _headers(self, key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _image_item(self, path: Path, *, role: str) -> dict[str, Any] | None:
        resolved = Path(path)
        if not resolved.exists():
            return None
        if resolved.stat().st_size > SEEDANCE_MAX_INLINE_BYTES:
            logger.warning("Skipping oversized Seedance image %s", resolved.name)
            return None
        return self._file_content(resolved, "image_url", role=role)

    def _file_content(self, path: Path, field: str, *, role: str = "") -> dict[str, Any]:
        mime, _ = mimetypes.guess_type(str(path))
        mime = (mime or "image/jpeg").lower()
        if mime == "image/jpg":
            mime = "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        data_url = f"data:{mime};base64,{encoded}"
        payload: dict[str, Any] = {"type": field, field: {"url": data_url}}
        if role:
            payload["role"] = role
        return payload

    def _video_url(self, task: dict[str, Any]) -> str:
        if not isinstance(task, dict):
            return ""
        content = task.get("content") or {}
        if isinstance(content, str) and content.startswith("http"):
            return content
        if isinstance(content, dict):
            url = (
                content.get("video_url")
                or (content.get("video") or {}).get("url")
                or content.get("url")
            )
            if url:
                return str(url)
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                url = item.get("video_url") or (item.get("video") or {}).get("url")
                if url:
                    return str(url)
        return str(task.get("video_url") or task.get("url") or task.get("uri") or "")

    def _http_error(self, status_code: int, data: Any, fallback: str) -> ProviderError:
        detail = ""
        request_id = ""
        if isinstance(data, dict):
            request_id = str(data.get("request_id") or data.get("id") or "")
            error = data.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("code") or "")
            elif error:
                detail = str(error)
            elif data.get("message"):
                detail = str(data.get("message"))
        message = sanitize_provider_text(detail or fallback)
        lowered = message.lower()
        logger.warning(
            "SEEDANCE_PROVIDER_ERROR status=%s message=%s request_id=%s",
            status_code,
            message[:300],
            request_id or "-",
        )
        if status_code in {401, 403}:
            return ProviderError(
                "The video service could not authorize this request.",
                retryable=False,
                code="AUTHENTICATION",
                status_code=status_code,
                provider="seedance",
                category="authentication",
                request_id=request_id,
            )
        if status_code == 429 or "rate limit" in lowered or "quota" in lowered:
            return ProviderError(
                "Video generation is temporarily rate limited. "
                "Please try again when the provider quota becomes available.",
                retryable=False,
                code="RATE_LIMITED",
                status_code=status_code or 429,
                provider="seedance",
                category="rate_limited",
                request_id=request_id,
            )
        if status_code == 404:
            if "not activated" in lowered or "activate the model" in lowered:
                return ProviderError(
                    "This Seedance model is not activated for the BytePlus Ark account. "
                    "Activate it in the Ark Console, or set SEEDANCE_MODEL to an activated model.",
                    retryable=False,
                    code="INVALID_CONFIGURATION",
                    status_code=404,
                    provider="seedance",
                    category="configuration",
                    request_id=request_id,
                )
            return ProviderError(
                "The video service model is not available.",
                retryable=False,
                code="INVALID_CONFIGURATION",
                status_code=404,
                provider="seedance",
                category="configuration",
                request_id=request_id,
            )
        if status_code in {400, 422}:
            return ProviderError(
                "The video provider rejected this request. Please try again.",
                retryable=False,
                code="INVALID_REQUEST",
                status_code=status_code,
                provider="seedance",
                category="provider_rejection",
                request_id=request_id,
            )
        if status_code in {408} or "timeout" in lowered or "timed out" in lowered:
            return ProviderError(
                "Video generation timed out. The worker was released. Please try again.",
                retryable=False,
                code="TIMEOUT",
                status_code=status_code,
                provider="seedance",
                category="timeout",
                request_id=request_id,
            )
        if status_code >= 500:
            return ProviderError(
                "We couldn't finish the video generation.",
                retryable=True,
                code="PROVIDER_ERROR",
                status_code=status_code,
                provider="seedance",
                category="provider_unavailable",
                request_id=request_id,
            )
        return ProviderError(
            "We couldn't finish the video generation.",
            retryable=False,
            code="PROVIDER_ERROR",
            status_code=status_code,
            provider="seedance",
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
        if "timed out" in lowered or "timeout" in lowered:
            return ProviderError(
                "Video generation timed out. The worker was released. Please try again.",
                retryable=False,
                code="TIMEOUT",
                provider="seedance",
                category="timeout",
            )
        return ProviderError(
            "We couldn't finish the video generation.",
            retryable=True,
            code="PROVIDER_ERROR",
            provider="seedance",
            category="network",
        )
