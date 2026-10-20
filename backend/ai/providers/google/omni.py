from __future__ import annotations

import base64
import logging
import mimetypes
import re
import threading
import time
from pathlib import Path
from typing import Any

from django.conf import settings

from ai.exceptions import GoogleProviderError, MissingAPIKeyError, ProviderError

from .client import get_genai_client, require_gemini_api_key

logger = logging.getLogger(__name__)

MAX_INLINE_BYTES = 4 * 1024 * 1024
MAX_REFERENCE_IMAGES = 4
DEFAULT_POLL_SECONDS = 5

_limiter: threading.BoundedSemaphore | None = None
_limiter_size = 0
_limiter_guard = threading.Lock()


def omni_request_timeout() -> int:
    try:
        value = int(getattr(settings, "OMNI_REQUEST_TIMEOUT_SECONDS", 300) or 300)
    except (TypeError, ValueError):
        value = 300
    return max(60, min(value, 600))


# google-genai 2.21.0 maps HttpRetryOptions.attempts onto RetryConfig.max_retries.
# The retry loop then performs max_retries + 1 HTTP sends. attempts=0 is one send.
# The library default is max_retries = 3, so four sends, and a Retry-After header
# is slept in full with no cap. That is what let one create() outlive 300 seconds.
OMNI_SDK_HTTP_ATTEMPTS = 1
OMNI_WATCHDOG_GRACE_SECONDS = 5


def _force_single_http_attempt(client: Any) -> None:
    """One HTTP send per Omni create.

    The parent client rewrites HttpRetryOptions.attempts 0 to 1. The
    interactions SDK then uses that number as max_retries, and the retry loop
    performs max_retries + 1 sends. Forcing max_retries to 0 is one send.
    """
    try:
        config = client.interactions.sdk_configuration.retry_config
    except Exception:
        return
    config.max_retries = 0
    config.retry_connection_errors = False


def _abort_omni_client(client: Any) -> None:
    """Close the HTTP client so a stuck interactions.create stops blocking."""
    api = getattr(client, "_api_client", None)
    for obj in (api, client):
        if obj is None:
            continue
        for name in ("_httpx_client", "_async_httpx_client"):
            http = getattr(obj, name, None)
            close = getattr(http, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception:
                logger.debug("Closing Omni HTTP client failed", exc_info=True)
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("Closing Omni client failed", exc_info=True)


def _attempt_fields(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context or {}
    return {
        "film": context.get("film_id", ""),
        "chain": context.get("chain_id", ""),
        "hop": context.get("hop_index", ""),
        "attempt": context.get("attempt", 1),
    }


def omni_limiter() -> threading.BoundedSemaphore:
    """Process-wide cap on blocking Omni creates. Shared by Studio, regen, and bulk."""
    global _limiter, _limiter_size
    try:
        size = int(getattr(settings, "OMNI_MAX_IN_FLIGHT", 3) or 3)
    except (TypeError, ValueError):
        size = 3
    size = max(1, min(size, 8))
    with _limiter_guard:
        if _limiter is None or _limiter_size != size:
            _limiter = threading.BoundedSemaphore(size)
            _limiter_size = size
        return _limiter


def file_resource_id(uri: str) -> str:
    """Return files/{id} from an Omni download URI, or an empty string."""
    match = re.search(r"/files/([^/:?#]+)", str(uri or ""))
    if not match:
        return ""
    return f"files/{match.group(1)}"


def public_resource_uri(uri: str) -> str:
    return str(uri or "").split("?", 1)[0]


def _file_state(record: Any) -> str:
    raw = getattr(record, "state", None)
    if raw is None and isinstance(record, dict):
        raw = record.get("state") or ""
    token = str(raw or "").split(".")[-1].strip().upper()
    if token in {"", "NONE", "STATE_UNSPECIFIED", "UNSPECIFIED"}:
        return "STATE_UNSPECIFIED"
    return token


def require_omni_key() -> str:
    try:
        return require_gemini_api_key()
    except MissingAPIKeyError as exc:
        raise MissingAPIKeyError(
            "Gemini Omni is not configured. Add GEMINI_API_KEY to backend/.env."
        ) from exc


class GeminiOmniProvider:
    """Gemini Omni Flash video generation via the Interactions API."""

    def __init__(self):
        self.model = getattr(settings, "GEMINI_OMNI_MODEL", "") or "gemini-omni-1.1-flash"
        self.resolution = getattr(settings, "GEMINI_OMNI_RESOLUTION", "") or "720p"

    def family(self) -> str:
        return "omni"

    def clamp_duration(self, duration_seconds: int) -> int:
        return min(max(int(duration_seconds or 4), 3), 10)

    def _log_attempt_end(self, fields: dict[str, Any], started: float, timeout: int, *, success: bool, exc: BaseException | None) -> None:
        elapsed = time.perf_counter() - started
        message = sanitize_provider_text(str(exc)) if exc else ""
        logger.info(
            "OMNI_ATTEMPT_END film=%s chain=%s hop=%s attempt=%s ended_at=%s elapsed=%.1f "
            "timeout_seconds=%s success=%s exception_type=%s exception_message=%s retryable=%s",
            fields["film"],
            fields["chain"],
            fields["hop"],
            fields["attempt"],
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            elapsed,
            timeout,
            str(success).lower(),
            type(exc).__name__ if exc else "",
            message[:300],
            str(bool(getattr(exc, "retryable", False))).lower(),
        )

    def prepare_images(self, paths: list[str | Path] | None) -> list[dict[str, Any]]:
        """Encode reference images once so a job can reuse the same payload."""
        parts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path in paths or []:
            part = self._media_part(path, "image", seen)
            if not part:
                continue
            parts.append(part)
            if len(parts) >= MAX_REFERENCE_IMAGES:
                break
        return parts

    def start(
        self,
        prompt: str,
        *,
        image_path: str | Path | None = None,
        image_paths: list[str | Path] | None = None,
        video_path: str | Path | None = None,
        duration_seconds: int = 8,
        aspect_ratio: str = "9:16",
        generate_audio: bool = True,
        prepared_images: list[dict[str, Any]] | None = None,
        previous_interaction_id: str | None = None,
        store: bool = False,
        task: str | None = None,
        attempt_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Omni always produces native audio with the video. There is no voice_id argument.
        # A Character voice id is only a preferred-voice line in the text prompt.
        # There is no numeric face seed. The same Character reference images in
        # image_paths are the identity input for every scene in the project.
        del generate_audio
        require_omni_key()
        duration = self.clamp_duration(duration_seconds)
        ratio = aspect_ratio if aspect_ratio in {"9:16", "16:9"} else "9:16"
        resolution = self.resolution if self.resolution in {"360p", "720p", "1080p", "4k"} else "720p"
        # 720p is Omni's default. 1080p and 4k are provider-side upscales.
        # MISA does not request that extra work; one local scale can be added later
        # only if a deliverable actually requires it.
        if resolution in {"1080p", "4k"}:
            resolution = "720p"
        inputs: list[dict[str, Any]] = []
        image_count = 0
        seen: set[str] = set()
        extending = bool(str(previous_interaction_id or "").strip())
        # An extension continues the stored interaction. Resending the reference
        # set on every hop repeats work Omni already has.
        if extending:
            prepared_images = []
            image_path = None
            image_paths = None
            video_path = None
        if prepared_images is not None:
            for part in prepared_images:
                if not isinstance(part, dict) or part.get("type") != "image":
                    continue
                inputs.append(part)
                image_count += 1
                if image_count >= MAX_REFERENCE_IMAGES:
                    break
        else:
            for path in [image_path, *(image_paths or [])]:
                part = self._media_part(path, "image", seen)
                if not part:
                    continue
                inputs.append(part)
                image_count += 1
                if image_count >= MAX_REFERENCE_IMAGES:
                    break
        video_part = self._media_part(video_path, "video", seen)
        if video_part:
            inputs.append(video_part)
        inputs.append({"type": "text", "text": prompt})
        chosen = task or ("extend" if extending else self._task(image_count=image_count, has_video=bool(video_part)))
        # URI delivery is rejected unless the interaction is stored. The chain
        # still decides which hop is extended; this only satisfies the request.
        persisted = True
        del store
        timeout = omni_request_timeout()
        fields = _attempt_fields(attempt_context)
        logger.info(
            "OMNI_ATTEMPT_START film=%s chain=%s hop=%s attempt=%s started_at=%s "
            "timeout_seconds=%s sdk_http_attempts=%s task=%s store=%s previous_interaction=%s "
            "references=%s model=%s duration=%ss",
            fields["film"],
            fields["chain"],
            fields["hop"],
            fields["attempt"],
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            timeout,
            OMNI_SDK_HTTP_ATTEMPTS,
            chosen,
            persisted,
            extending,
            image_count,
            self.model,
            duration,
        )
        started = time.perf_counter()
        interaction = None
        try:
            from google.genai import types

            client = get_genai_client(
                http_options=types.HttpOptions(
                    timeout=int(timeout * 1000),
                    retry_options=types.HttpRetryOptions(attempts=0),
                )
            )
            _force_single_http_attempt(client)
            # Video interactions reject a later status GET with
            # "Multiple authentication credentials received", including a
            # one-key request. The create call itself has to return the file.
            create_kwargs: dict[str, Any] = {
                "model": self.model,
                "input": inputs,
                "background": False,
                "store": persisted,
                "stream": False,
                "generation_config": {"video_config": {"task": chosen}},
                "response_format": {
                    "type": "video",
                    "delivery": "uri",
                    "aspect_ratio": ratio,
                    "duration": f"{duration}s",
                    "resolution": resolution,
                },
                "timeout": timeout,
            }
            if extending:
                create_kwargs["previous_interaction_id"] = str(previous_interaction_id).strip()
                # task=extend treats the previous model video as input and
                # rejects it: "Only user input is allowed when video task is set."
                # The continuation prompt is enough. Docs set task only as a fallback.
                create_kwargs.pop("generation_config", None)
            holder: dict[str, Any] = {}

            def _send() -> None:
                try:
                    holder["interaction"] = client.interactions.create(**create_kwargs)
                except Exception as exc:
                    holder["error"] = exc

            limiter = omni_limiter()
            limiter.acquire()
            try:
                worker = threading.Thread(target=_send, name="omni-create", daemon=True)
                worker.start()
                worker.join(timeout + OMNI_WATCHDOG_GRACE_SECONDS)
                if worker.is_alive():
                    _abort_omni_client(client)
                    worker.join(2)
                    raise GoogleProviderError(
                        f"Gemini Omni attempt exceeded {timeout} seconds and was stopped.",
                        retryable=False,
                        code="TIMEOUT",
                        category="timeout",
                    )
            finally:
                limiter.release()
            if holder.get("error") is not None:
                raise holder["error"]
            interaction = holder.get("interaction")
        except GoogleProviderError as exc:
            self._log_attempt_end(fields, started, timeout, success=False, exc=exc)
            raise
        except Exception as exc:
            wrapped = self._wrap_error(exc, "Video generation could not be started.", request_id="")
            self._log_attempt_end(fields, started, timeout, success=False, exc=wrapped)
            raise wrapped from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self._log_attempt_end(fields, started, timeout, success=True, exc=None)
        interaction_id = str(getattr(interaction, "id", "") or "")
        if not interaction_id:
            raise GoogleProviderError("Video generation returned no job id.", retryable=True)
        video = getattr(interaction, "output_video", None)
        uri = self._video_uri(video)
        data = self._video_bytes(video)
        file_id = file_resource_id(uri) if uri else ""
        logger.info("Omni interaction created interaction_id=%s", interaction_id)
        if uri and data:
            logger.info(
                "output_video.uri=%s file_id=%s inline_data=present; using uri",
                public_resource_uri(uri),
                file_id,
            )
            data = b""
        elif uri:
            logger.info("output_video.uri=%s file_id=%s", public_resource_uri(uri), file_id)
        elif data:
            logger.info("output_video.data present bytes=%s", len(data))
        else:
            logger.info("output_video.uri= output_video.data=absent interaction_id=%s", interaction_id)
        if uri and not file_id:
            raise GoogleProviderError(
                "Omni returned a video URI that did not contain a Files resource id.",
                retryable=False,
                code="MISSING_VIDEO_OUTPUT",
                provider="omni",
                request_id=interaction_id,
                category="provider_rejection",
            )
        if not uri and not data:
            raise GoogleProviderError(
                "Omni did not return a video file. The response had no output_video URI or inline data.",
                retryable=False,
                code="MISSING_VIDEO_OUTPUT",
                provider="omni",
                request_id=interaction_id,
                category="provider_rejection",
            )
        logger.info(
            "Omni request finished interaction_id=%s elapsed_ms=%s delivery=%s",
            interaction_id,
            elapsed_ms,
            "uri" if uri else "inline",
        )
        return {
            "id": interaction_id,
            "file_id": file_id,
            "uri": uri,
            "inline": data,
            "raw": interaction,
            "model": self.model,
            "store": persisted,
            "background": False,
            "stream": False,
            "delivery": "uri" if uri else "inline",
            "duration_requested": duration,
            "resolution": resolution,
            "aspect_ratio": ratio,
            "reference_count": image_count,
            "prompt_length": len(prompt or ""),
            "task": chosen,
            "elapsed_ms": elapsed_ms,
        }

    def poll_interval(self) -> int:
        value = getattr(settings, "GEMINI_OMNI_POLL_SECONDS", DEFAULT_POLL_SECONDS)
        try:
            return max(1, min(int(value or DEFAULT_POLL_SECONDS), 8))
        except (TypeError, ValueError):
            return DEFAULT_POLL_SECONDS

    def check(self, file_id: str) -> tuple[str, Any]:
        """One Files API lookup. Returns completed or running. Failed files raise.

        This does not call interactions.get. The interaction id is kept for
        traceability and is not the video status resource.
        """
        require_omni_key()
        name = str(file_id or "").strip()
        if name and not name.startswith("files/"):
            name = f"files/{name}"
        if not name:
            raise GoogleProviderError(
                "Omni did not return a video file id to check.",
                retryable=False,
                code="MISSING_VIDEO_OUTPUT",
                provider="omni",
                category="provider_rejection",
            )
        try:
            client = get_genai_client()
            record = client.files.get(name=name)
        except Exception as exc:
            raise self._wrap_error(exc, "Video file status could not be checked.", request_id="") from exc
        state = _file_state(record)
        logger.info("Files status=%s file_id=%s", state, name)
        if state == "ACTIVE":
            return "completed", record
        if state == "FAILED":
            detail = ""
            error = getattr(record, "error", None)
            if error:
                detail = sanitize_provider_text(str(getattr(error, "message", None) or error))
            raise GoogleProviderError(
                detail or "The video provider reported that the file failed.",
                retryable=False,
                code="PROVIDER_REJECTION",
                provider="omni",
                request_id="",
                category="provider_rejection",
            )
        return "running", record

    def poll(self, task_id: str, *, timeout_seconds: int = 600, interval_seconds: int | None = None) -> Any:
        waited = 0
        consecutive_errors = 0
        interval = interval_seconds if interval_seconds is not None else self.poll_interval()
        while waited < timeout_seconds:
            try:
                state, interaction = self.check(task_id)
                consecutive_errors = 0
            except GoogleProviderError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                logger.warning("Gemini Omni poll error %s/3: %s", consecutive_errors, exc)
                if consecutive_errors >= 3:
                    raise self._wrap_error(
                        exc,
                        "Video generation status could not be checked.",
                    ) from exc
                time.sleep(interval)
                waited += interval
                continue
            if state == "completed":
                return interaction
            time.sleep(interval)
            waited += interval
        raise GoogleProviderError("Video generation timed out.", retryable=True)

    def save_video(self, task: Any, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        video = getattr(task, "output_video", None)
        if video is None and isinstance(task, dict):
            video = task.get("output_video") or task
        uri = self._video_uri(video) or self._video_uri(task)
        data = self._video_bytes(video) if video is not None else b""
        if not data:
            data = self._video_bytes(self._video_from_steps(task))
        # URI delivery is the Omni video path. Inline bytes are only used when
        # the POST body has no file URI.
        if uri:
            self._download_uri(uri, dest)
            logger.info("Omni video downloaded file_id=%s", file_resource_id(uri))
            return dest
        if data:
            dest.write_bytes(data)
            logger.info("Omni video downloaded inline bytes=%s", len(data))
            return dest
        raise GoogleProviderError(
            "Video generation returned no video.",
            retryable=False,
            code="MISSING_VIDEO_OUTPUT",
            provider="omni",
            category="provider_rejection",
        )

    def _download_uri(self, uri: str, dest: Path) -> None:
        try:
            client = get_genai_client()
            client.files.download(file=uri, destination=str(dest))
        except Exception as exc:
            if isinstance(exc, (GoogleProviderError, MissingAPIKeyError, ProviderError)):
                raise
            raise GoogleProviderError(
                sanitize_provider_text(str(exc) or "Omni video download failed."),
                retryable=True,
                code="DOWNLOAD_FAILED",
                provider="omni",
                request_id="",
                category="network",
            ) from exc
        if not dest.exists() or dest.stat().st_size == 0:
            raise GoogleProviderError(
                "Omni video download failed.",
                retryable=True,
                code="DOWNLOAD_FAILED",
                provider="omni",
                request_id="",
                category="network",
            )

    def _task(self, *, image_count: int, has_video: bool) -> str:
        if image_count > 1 or (image_count and has_video):
            return "reference_to_video"
        if image_count == 1:
            return "image_to_video"
        return "text_to_video"

    def _media_part(self, path: str | Path | None, kind: str, seen: set[str]) -> dict[str, Any] | None:
        if not path:
            return None
        resolved = Path(path)
        if not resolved.exists():
            return None
        key = str(resolved.resolve())
        if key in seen:
            return None
        size = resolved.stat().st_size
        if size > MAX_INLINE_BYTES:
            logger.warning("Skipping oversized Gemini Omni %s %s", kind, resolved)
            return None
        seen.add(key)
        mime, _ = mimetypes.guess_type(str(resolved))
        if kind == "image":
            mime = mime or "image/jpeg"
        else:
            mime = mime or "video/mp4"
        encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
        return {"type": kind, "data": encoded, "mime_type": mime}

    def _video_bytes(self, video: Any) -> bytes:
        if video is None:
            return b""
        if isinstance(video, (bytes, bytearray)):
            return bytes(video)
        data = video.get("data") if isinstance(video, dict) else getattr(video, "data", None)
        if not data:
            return b""
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        try:
            return base64.b64decode(str(data), validate=False)
        except Exception:
            return b""

    def _video_uri(self, video: Any) -> str:
        if video is None:
            return ""
        if isinstance(video, dict):
            return str(video.get("uri") or video.get("url") or "")
        return str(getattr(video, "uri", None) or getattr(video, "url", None) or "")

    def _video_from_steps(self, interaction: Any) -> Any:
        steps = interaction.get("steps") if isinstance(interaction, dict) else getattr(interaction, "steps", None)
        for step in steps or []:
            contents = step.get("content") if isinstance(step, dict) else getattr(step, "content", None)
            for item in contents or []:
                kind = item.get("type") if isinstance(item, dict) else getattr(item, "type", "")
                if str(kind) == "video":
                    return item
        return None

    def _failure_message(self, interaction: Any, status: str) -> str:
        errors = getattr(interaction, "errors", None) or []
        details = []
        for item in errors:
            message = getattr(item, "message", None) or str(item)
            if message:
                details.append(sanitize_provider_text(str(message)))
        detail = " ".join(details).strip()
        if status == "budget_exceeded":
            return "The video provider quota was exceeded."
        if detail:
            return detail
        return "Video generation failed."

    def _wrap_error(self, exc: Exception, fallback: str, request_id: str = "") -> ProviderError:
        if isinstance(exc, (GoogleProviderError, MissingAPIKeyError, ProviderError)):
            return exc
        status = _google_status(exc)
        raw_message, code = _provider_message_and_code(exc)
        message = sanitize_provider_text(raw_message or fallback)
        category, retryable = _classify_provider_failure(status, code, message)
        retry_after = _retry_after_text(raw_message or message)
        if code == "RATE_LIMITED" or category == "rate_limited":
            wait = f" The provider asked to wait {retry_after}." if retry_after else ""
            message = (
                "Video generation is temporarily rate limited. "
                "Please try again when the provider quota becomes available."
                + wait
            )
            code = "RATE_LIMITED"
            retryable = False
        if not message:
            message = fallback
        logger.warning(
            "MISA VIDEO GENERATION provider=omni provider_response status=%s code=%s message=%s request_id=%s",
            status or 0,
            code,
            message,
            request_id,
        )
        return GoogleProviderError(
            message,
            retryable=retryable,
            code=code,
            status_code=status,
            provider="omni",
            request_id=request_id,
            category=category,
            retry_after=retry_after if code == "RATE_LIMITED" else "",
        )


def sanitize_provider_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"AIza[0-9A-Za-z_\-]{8,}", "[redacted]", value)
    value = re.sub(r"sk-[A-Za-z0-9]{8,}", "[redacted]", value)
    value = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", value, flags=re.I)
    value = re.sub(
        r"(api[_-]?key|access[_-]?token|token|secret|password)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        value,
        flags=re.I,
    )
    return value.strip()[:500]


def _provider_message_and_code(exc: Exception) -> tuple[str, str]:
    message = str(getattr(exc, "message", "") or "").strip()
    code = str(getattr(exc, "status", "") or "").strip()
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        error = details.get("error") if isinstance(details.get("error"), dict) else details
        message = message or str(error.get("message") or "")
        code = code or str(error.get("code") or error.get("status") or "")
    text = str(exc)
    embedded = re.search(r"'message': '([^']+)'", message or text)
    if embedded:
        message = embedded.group(1)
    elif not message and text and "object at 0x" not in text:
        message = text.strip()
    if not code:
        match = re.search(r"'code': '([^']+)'", text)
        if match:
            code = match.group(1)
    status = _google_status(exc)
    normalized = code.upper().replace("-", "_") if code else ""
    if status in {401, 403} or normalized in {"UNAUTHENTICATED", "AUTHENTICATION", "PERMISSION_DENIED"}:
        normalized = "AUTHENTICATION"
    elif normalized in {"INVALID_REQUEST", "INVALID_ARGUMENT"}:
        normalized = "INVALID_REQUEST"
    elif not normalized and status == 400:
        lowered = message.lower()
        if "duration" in lowered:
            normalized = "INVALID_DURATION"
        elif any(token in lowered for token in ("image", "media", "reference", "mime")):
            normalized = "INVALID_MEDIA"
        elif "prompt" in lowered:
            normalized = "INVALID_PROMPT"
        else:
            normalized = "INVALID_REQUEST"
    elif status in {401, 403}:
        normalized = "AUTHENTICATION"
    elif status == 429 or "quota" in message.lower() or "rate limit" in message.lower():
        normalized = "RATE_LIMITED"
    elif status >= 500:
        normalized = "PROVIDER_UNAVAILABLE"
    elif "timed out" in message.lower() or "timeout" in message.lower():
        normalized = "TIMEOUT"
    return message, normalized


def _classify_provider_failure(status: int, code: str, message: str) -> tuple[str, bool]:
    normalized = (code or "").upper()
    lowered = message.lower()
    if normalized in {"AUTHENTICATION"} or status in {401, 403}:
        return "authentication", False
    if normalized == "INVALID_REQUEST":
        return "invalid_request", False
    if normalized in {"QUOTA", "RATE_LIMITED"} or status == 429 or "quota" in lowered or "rate limit" in lowered:
        return "rate_limited", False
    if normalized == "INVALID_DURATION" or "duration" in lowered:
        return "configuration", False
    if normalized == "INVALID_MEDIA":
        return "invalid_media", False
    if normalized == "INVALID_PROMPT" or "prompt" in lowered:
        return "invalid_prompt", False
    if normalized in {"INVALID_REQUEST", "UNSUPPORTED_FORMAT", "MISSING_CONFIGURATION"} or status in {400, 404}:
        return "configuration", False
    if normalized == "TIMEOUT" or "timed out" in lowered or "timeout" in lowered:
        return "timeout", False
    if status >= 500 or normalized == "PROVIDER_UNAVAILABLE":
        return "provider_unavailable", True
    if status == 0:
        return "network", True
    return "provider_rejection", False


def _google_status(exc: Exception) -> int:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and value >= 400:
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", 0)
        if isinstance(value, int) and value >= 400:
            return value
    text = str(exc)
    for code in (401, 403, 404, 429, 400):
        if str(code) in text:
            return code
    return 0


def _retry_after_text(message: str) -> str:
    match = re.search(r"retry in ([0-9]+h)?([0-9]+m)?([0-9]+s)?", str(message or ""), flags=re.I)
    if not match:
        return ""
    return "".join(part for part in match.groups() if part)
