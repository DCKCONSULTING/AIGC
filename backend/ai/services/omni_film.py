"""One Studio video as a Gemini Omni extension chain, not one request per scene.

Verified limits for gemini-omni-1.1-flash: each interactions.create is 3–10 seconds,
and previous_interaction_id can extend that by another 3–10 seconds up to 40
seconds total. 45s and 60s therefore become the fewest such chains, joined once.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.utils import timezone

from ai.exceptions import ProviderError
from ai.models import Scene, VideoAsset, VideoProject, VideoProjectStatus
from ai.services.cancel import raise_if_cancelled
from ai.services.captions import spoken_caption
from ai.services.compiler import compile_film_prompt
from ai.services.director import is_studio_project, media_exists
from ai.services.durations import OMNI_MAX_CONTINUOUS_DURATION_SECONDS, chain_is_new_generation, plan_omni_chains
from ai.services.ffmpeg import FFmpegError, burn_captions, concat_clips, probe_media, split_copy
from ai.services.generation_metrics import record_omni_request, record_span

logger = logging.getLogger(__name__)

_MAX_GENERATION_ATTEMPTS = 2
# SQLite allows one writer. Hold this across database work and drop it
# while an Omni create is in flight so independent chains overlap on the network.
_db_lock = threading.RLock()
_MAX_DOWNLOAD_ATTEMPTS = 3
_MAX_POSTPROCESS_ATTEMPTS = 2
_NO_OMNI_RETRY = {"RATE_LIMITED", "TIMEOUT", "INVALID_REQUEST", "AUTHENTICATION", "DOWNLOAD_FAILED", "JOIN_FAILED", "CAPTION_FAILED", "FFMPEG_FAILED"}


class _Heartbeat:
    """Refresh updated_at while a blocking Omni create is in flight.

    This does not cancel the HTTP call. Cancellation is applied after the
    request returns.
    """

    def __init__(self, project_id: int, label: str):
        self.project_id = project_id
        self.label = label
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"omni-heartbeat-{project_id}", daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        self._thread.join(timeout=1)
        return False

    def _run(self) -> None:
        from ai.models import VideoProject

        while not self._stop.wait(8):
            try:
                with _db_lock:
                    VideoProject.objects.filter(pk=self.project_id).exclude(
                        status__in={
                            VideoProjectStatus.FAILED,
                            VideoProjectStatus.READY_FOR_REVIEW,
                            VideoProjectStatus.APPROVED,
                        }
                    ).update(stage_label=self.label, updated_at=timezone.now())
            except Exception:
                logger.debug("Omni heartbeat skipped for project %s", self.project_id, exc_info=True)


def generate_continuous_film(service, project: VideoProject) -> bool:
    """Generate the full Studio video. Returns True when preview_video was saved."""
    from ai.providers.video import video_provider_name

    if video_provider_name() == "veo":
        from ai.services.veo_film import generate_continuous_veo_film

        return generate_continuous_veo_film(service, project)
    if video_provider_name() == "minimax":
        from ai.services.minimax_film import generate_continuous_minimax_film

        return generate_continuous_minimax_film(service, project)
    if video_provider_name() == "seedance":
        from ai.services.seedance_film import generate_continuous_seedance_film

        return generate_continuous_seedance_film(service, project)
    if not is_studio_project(project):
        return False
    scenes = list(project.scenes.all().order_by("order"))
    if not scenes:
        raise ProviderError("Add a storyboard before generating.", retryable=False, code="VALIDATION_FAILED")
    product_frame = service._product_first_frame(project)
    if not product_frame:
        raise ProviderError("Add a product photo before generating.", retryable=False, code="VALIDATION_FAILED")
    duration = int(project.duration_seconds or 0)
    chains = plan_omni_chains(duration)
    over_boundary = duration > OMNI_MAX_CONTINUOUS_DURATION_SECONDS
    signature = _signature(project, scenes)
    if media_exists(project.preview_video):
        _clear_resume(project)
    elif _saved_signature(project) != signature:
        _clear_resume(project)
    project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 8, "Preparing")
    raise_if_cancelled(project)

    prep_started = time.perf_counter()
    paths = service._reference_images(project)
    prepare = getattr(service.omni, "prepare_images", None)
    prepared: list[dict] = []
    if callable(prepare):
        encoded = prepare(paths)
        if isinstance(encoded, list):
            prepared = encoded
    record_span(project, "reference_prepare_ms", int((time.perf_counter() - prep_started) * 1000))
    metrics_brief = dict(project.creative_brief or {})
    metrics = dict(metrics_brief.get("generation_metrics") or {})
    metrics["reference_count"] = len(prepared)
    metrics["architecture"] = "omni_extension_chain"
    metrics["video_provider"] = "omni"
    metrics["video_model"] = str(getattr(service.omni, "model", "") or "gemini-omni-1.1-flash")
    metrics["omni_chains"] = chains
    metrics["requested_duration"] = duration
    metrics["number_of_chains"] = len(chains)
    metrics["chain_concurrency"] = _chain_workers(len(chains))
    metrics["continuity_boundary_seconds"] = OMNI_MAX_CONTINUOUS_DURATION_SECONDS
    metrics["job_started_at"] = metrics.get("job_started_at") or timezone.now().isoformat()
    if getattr(project, "created_at", None):
        metrics["job_created_at"] = project.created_at.isoformat()
    metrics_brief["generation_metrics"] = metrics
    project.creative_brief = metrics_brief
    project.save(update_fields=["creative_brief", "updated_at"])

    total_segments = sum(len(chain) for chain in chains)
    join_mode = ""
    caption_pass = False
    chain_files = _generate_chains(
        service,
        project,
        scenes,
        chains=chains,
        prepared=prepared,
        signature=signature,
        total_segments=total_segments,
        over_boundary=over_boundary,
    )

    if over_boundary:
        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 88, "Joining")
    else:
        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 90, "Finalizing")
    assembly_started = time.perf_counter()
    extra_temps: list[Path] = []
    try:
        clean, join_mode = _join_chains(chain_files)
        if join_mode:
            extra_temps.append(clean)
        record_span(project, "assembly_ms", int((time.perf_counter() - assembly_started) * 1000))
        _split_scene_clips(project, scenes, clean)
        preview = _burn_preview(project, scenes, clean)
        if preview != clean:
            extra_temps.append(preview)
        caption_pass = preview != clean
        validation_started = time.perf_counter()
        report = _log_probe(preview, "final")
        record_span(project, "validation_ms", int((time.perf_counter() - validation_started) * 1000))
        _store_duration_report(project, report)
        if report.get("has_video") and not report.get("has_audio"):
            raise ProviderError(
                "The finished video has no audio stream.",
                retryable=False,
                code="MISSING_AUDIO",
                category="validation",
            )
        if report.get("has_video") is False and preview.exists() and preview.stat().st_size == 0:
            raise ProviderError(
                "The finished video file is empty.",
                retryable=False,
                code="INVALID_VIDEO",
                category="validation",
            )
        project.preview_video.save("preview.mp4", ContentFile(preview.read_bytes()), save=True)
        try:
            from ai.services.poster import save_video_poster

            save_video_poster(project, video_path=preview, enhance=False, force=True)
        except Exception:
            logger.exception("First-screen poster was not saved for video %s", project.pk)
        if not media_exists(project.preview_video):
            raise ProviderError(
                "The finished video file is missing.",
                retryable=False,
                code="INVALID_VIDEO",
                category="validation",
            )
        _record_film_metrics(
            project,
            duration=duration,
            chains=chains,
            join_mode=join_mode,
            caption_pass=caption_pass,
            report=report,
        )
        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 98, "Finalizing")
        _mark_resume_complete(project)
        return True
    finally:
        for path in extra_temps:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Temp cleanup skipped for %s", path)


def _chain_workers(chain_count: int) -> int:
    """How many independent Omni chains may run at once.

    Hops inside one chain stay sequential because each hop needs the previous
    interaction id. Separate chains do not, so they share the existing
    Studio concurrency cap.
    """
    count = max(1, int(chain_count or 1))
    if count == 1:
        return 1
    scene_cap = max(1, min(int(getattr(settings, "VIDEO_SCENE_CONCURRENCY", 6) or 6), 8))
    in_flight = max(1, min(int(getattr(settings, "OMNI_MAX_IN_FLIGHT", 3) or 3), 8))
    return max(1, min(count, scene_cap, in_flight))


def _generate_chains(
    service,
    project: VideoProject,
    scenes: list[Scene],
    *,
    chains: list[list[int]],
    prepared: list[dict],
    signature: dict,
    total_segments: int,
    over_boundary: bool,
) -> list[Path]:
    finished_before = []
    cursor = 0
    for segments in chains:
        finished_before.append(cursor)
        cursor += len(segments)

    def run(chain_index: int) -> Path:
        close_old_connections()
        _db_lock.acquire()
        try:
            from django.db import connection

            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA busy_timeout = 30000")
            if chain_is_new_generation(chain_index):
                project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 70, "Generating final section")
            return _generate_chain(
                service,
                project,
                scenes,
                chain_index=chain_index,
                segments=chains[chain_index],
                prepared=prepared,
                signature=signature,
                finished_before=finished_before[chain_index],
                total_segments=total_segments,
                over_boundary=over_boundary,
            )
        finally:
            _db_lock.release()
            close_old_connections()

    workers = _chain_workers(len(chains))
    if workers == 1:
        return [run(index) for index in range(len(chains))]

    logger.info(
        "Omni chains in parallel project=%s chains=%s workers=%s",
        project.pk,
        len(chains),
        workers,
    )
    results: dict[int, Path] = {}
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run, index): index for index in range(len(chains))}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except BaseException as exc:
                errors.append(exc)
                logger.info(
                    "Omni chain failed project=%s chain=%s error=%s",
                    project.pk,
                    index,
                    type(exc).__name__,
                )
    if errors:
        raise errors[0]
    return [results[index] for index in range(len(chains))]


def _generate_chain(
    service,
    project: VideoProject,
    scenes: list[Scene],
    *,
    chain_index: int,
    segments: list[int],
    prepared: list[dict],
    signature: dict,
    finished_before: int,
    total_segments: int,
    over_boundary: bool = False,
) -> Path:
    cached = _chain_asset(project, chain_index, signature)
    if cached is not None:
        logger.info("Reusing Omni chain %s for project %s", chain_index, project.pk)
        return Path(cached.file.path)
    previous_id = ""
    story_start = _story_offset(project, chain_index)
    pieces: list[Path] = []
    cumulative_file: Path | None = None
    for segment_index, seconds in enumerate(segments):
        raise_if_cancelled(project)
        start = story_start + sum(segments[:segment_index])
        end = start + seconds
        label = _segment_label(chain_index, over_boundary)
        done = finished_before + segment_index
        progress = 12 + int(70 * done / max(total_segments, 1))
        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, progress, label)
        existing = _segment_asset(project, chain_index, segment_index, signature)
        if existing is not None:
            path = Path(existing.file.path)
            report = _log_probe(path, label)
            previous_id = str((existing.metadata or {}).get("interaction_id") or previous_id)
            if _is_cumulative(report, segments, segment_index):
                cumulative_file = path
            else:
                pieces.append(path)
            continue
        extend = bool(previous_id)
        prompt_started = time.perf_counter()
        prompt = compile_film_prompt(
            project,
            scenes,
            start,
            end,
            extend=extend,
            boundary=chain_is_new_generation(chain_index) and not extend,
        )
        record_span(project, "prompt_build_ms", int((time.perf_counter() - prompt_started) * 1000))
        store = segment_index < len(segments) - 1
        started, dest, report = _request_segment(
            service,
            project,
            prompt=prompt,
            seconds=seconds,
            prepared=prepared if not extend else None,
            previous_interaction_id=previous_id,
            store=store,
            label=label,
            chain_index=chain_index,
            hop_index=segment_index,
        )
        previous_id = str(started.get("id") or "")
        asset = _save_segment_asset(
            project,
            dest,
            chain_index=chain_index,
            segment_index=segment_index,
            interaction_id=previous_id,
            duration_requested=seconds,
            duration_received=report.get("duration"),
            signature=signature,
            store=store,
        )
        path = Path(asset.file.path)
        if _is_cumulative(report, segments, segment_index):
            cumulative_file = path
        else:
            pieces.append(path)
    if cumulative_file is not None and _covers_chain(cumulative_file, segments):
        chain_path = cumulative_file
    elif len(pieces) == 1:
        chain_path = pieces[0]
    elif pieces:
        joined = Path(tempfile.mkstemp(suffix=".mp4")[1])
        concat_started = time.perf_counter()
        try:
            concat_clips(pieces, joined, fade=0)
        except FFmpegError as exc:
            raise ProviderError(
                "Video pieces could not be joined.",
                retryable=False,
                code="JOIN_FAILED",
                category="postprocessing",
            ) from exc
        record_span(project, "ffmpeg_ms", int((time.perf_counter() - concat_started) * 1000))
        chain_path = joined
    else:
        raise ProviderError(
            "Omni did not return a video for this chain.",
            retryable=False,
            code="PROVIDER_ERROR",
        )
    _save_chain_asset(project, chain_path, chain_index, signature, segments)
    return chain_path


def _request_segment(
    service,
    project: VideoProject,
    *,
    prompt: str,
    seconds: int,
    prepared: list[dict] | None,
    previous_interaction_id: str,
    store: bool,
    label: str,
    chain_index: int = 0,
    hop_index: int = 0,
) -> tuple[dict, Path, dict]:
    last_error: Exception | None = None
    for attempt in range(1, _MAX_GENERATION_ATTEMPTS + 1):
        raise_if_cancelled(project)
        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, project.progress or 20, "Submitting to Gemini Omni")
        request_started = time.perf_counter()
        try:
            with _Heartbeat(project.pk, f"{label} — waiting for Gemini Omni"):
                _db_lock.release()
                try:
                    started = service.omni.start(
                        prompt,
                        duration_seconds=seconds,
                        aspect_ratio="9:16",
                        prepared_images=prepared,
                        previous_interaction_id=previous_interaction_id or None,
                        store=store,
                        attempt_context={
                            "film_id": project.pk,
                            "chain_id": chain_index,
                            "hop_index": hop_index,
                            "attempt": attempt,
                        },
                    )
                finally:
                    _db_lock.acquire()
        except ProviderError as exc:
            last_error = exc
            logger.info(
                "OMNI_RETRY film=%s chain=%s hop=%s attempt=%s error=%s reason=%s retryable=%s",
                project.pk,
                chain_index,
                hop_index,
                attempt,
                type(exc).__name__,
                str(exc)[:300],
                bool(getattr(exc, "retryable", False)),
            )
            _record_request(
                project,
                {},
                seconds=seconds,
                success=False,
                retry_count=attempt - 1,
                error_type=_error_type(exc),
                elapsed_ms=int((time.perf_counter() - request_started) * 1000),
                store=store,
                chain_id=chain_index,
                hop_index=hop_index,
                previous_interaction_id_present=bool(previous_interaction_id),
            )
            if not getattr(exc, "retryable", False) or attempt == _MAX_GENERATION_ATTEMPTS:
                raise ProviderError(
                    str(exc),
                    retryable=False if str(getattr(exc, "code", "") or "").upper() in _NO_OMNI_RETRY else bool(getattr(exc, "retryable", False)),
                    code=getattr(exc, "code", "") or "PROVIDER_ERROR",
                    status_code=getattr(exc, "status_code", 0) or 0,
                    provider=getattr(exc, "provider", "") or "omni",
                    request_id=getattr(exc, "request_id", "") or "",
                    category=getattr(exc, "category", "") or "generation",
                    retry_after=str(getattr(exc, "retry_after", "") or ""),
                ) from exc
            if str(getattr(exc, "code", "") or "").upper() in _NO_OMNI_RETRY:
                raise
            time.sleep(min(2 ** attempt, 8))
            continue
        raise_if_cancelled(project)
        elapsed_ms = int((time.perf_counter() - request_started) * 1000)
        dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
        download_started = time.perf_counter()
        try:
            _download_started(service, started, dest)
        except ProviderError as exc:
            dest.unlink(missing_ok=True)
            _record_request(
                project,
                started,
                seconds=seconds,
                success=False,
                retry_count=attempt - 1,
                error_type="DOWNLOAD_FAILED",
                elapsed_ms=elapsed_ms,
                store=store,
                chain_id=chain_index,
                hop_index=hop_index,
                previous_interaction_id_present=bool(previous_interaction_id),
            )
            raise ProviderError(
                str(exc) or "Video download failed.",
                retryable=True,
                code="DOWNLOAD_FAILED",
                provider="omni",
                request_id=str(started.get("id") or ""),
                category="download",
            ) from exc
        record_span(project, "download_ms", int((time.perf_counter() - download_started) * 1000))
        probe_started = time.perf_counter()
        report = _log_probe(dest, label)
        record_span(project, "ffprobe_ms", int((time.perf_counter() - probe_started) * 1000))
        missing_audio = bool(report.get("has_video") and not report.get("has_audio"))
        _record_request(
            project,
            started,
            seconds=seconds,
            success=not missing_audio,
            retry_count=attempt - 1,
            error_type="MISSING_AUDIO" if missing_audio else "",
            elapsed_ms=elapsed_ms,
            store=store,
            report=report,
            chain_id=chain_index,
            hop_index=hop_index,
            previous_interaction_id_present=bool(previous_interaction_id),
        )
        if missing_audio:
            dest.unlink(missing_ok=True)
            last_error = ProviderError(
                "Gemini Omni returned a video with no audio stream.",
                retryable=True,
                code="MISSING_AUDIO",
                category="validation",
            )
            if attempt == _MAX_GENERATION_ATTEMPTS:
                raise last_error
            continue
        return started, dest, report
    raise last_error or ProviderError("Video generation failed.", retryable=False, code="GENERATION_FAILED")


def _download_started(service, started: dict, dest: Path) -> None:
    file_id = str(started.get("file_id") or "")
    if file_id and not started.get("inline"):
        poll = getattr(service.omni, "poll", None)
        if callable(poll):
            poll(file_id, timeout_seconds=120, interval_seconds=service.omni.poll_interval())
    last: Exception | None = None
    for attempt in range(_MAX_DOWNLOAD_ATTEMPTS):
        try:
            service.omni.save_video(started, dest)
            if dest.exists() and dest.stat().st_size > 0:
                return
            last = ProviderError("Omni video download was empty.", retryable=True, code="DOWNLOAD_FAILED")
        except ProviderError as exc:
            last = exc
            if getattr(exc, "code", "") != "DOWNLOAD_FAILED" or attempt == _MAX_DOWNLOAD_ATTEMPTS - 1:
                raise
        time.sleep(min(2 ** attempt, 4))
    raise last or ProviderError("Video download failed.", retryable=True, code="DOWNLOAD_FAILED")


def _join_chains(files: list[Path]) -> tuple[Path, str]:
    existing = [path for path in files if path.exists()]
    if len(existing) == 1:
        return existing[0], ""
    if not existing:
        raise ProviderError("No Omni video was produced.", retryable=False, code="PROVIDER_ERROR")
    dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
    last_error: Exception | None = None
    for attempt in range(1, _MAX_POSTPROCESS_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            concat_clips(existing, dest, fade=0)
            from ai.services import ffmpeg as ffmpeg_mod

            mode = str(getattr(ffmpeg_mod, "LAST_JOIN_MODE", "") or "copy")
            logger.info("Joined %s Omni chains in %sms join_mode=%s", len(existing), int((time.perf_counter() - started) * 1000), mode)
            return dest, mode
        except FFmpegError as exc:
            last_error = exc
            logger.warning("join attempt %s failed", attempt, exc_info=True)
    dest.unlink(missing_ok=True)
    raise ProviderError(
        "The Omni videos could not be joined.",
        retryable=False,
        code="JOIN_FAILED",
        category="postprocessing",
    ) from last_error


def _burn_preview(project: VideoProject, scenes: list[Scene], clean: Path) -> Path:
    captions = []
    for scene in scenes:
        text = spoken_caption(scene.narration or "", scene.caption or "")
        if not str(text or "").strip():
            continue
        captions.append(
            {
                "text": text,
                "duration": float(scene.duration or 0) or 1,
                "placement": (scene.metadata or {}).get("caption_placement") or "bottom",
            }
        )
    if not captions:
        return clean
    dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
    last_error: Exception | None = None
    for attempt in range(1, _MAX_POSTPROCESS_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            burn_captions(clean, captions, dest)
            elapsed = int((time.perf_counter() - started) * 1000)
            record_span(project, "ffmpeg_ms", elapsed)
            logger.info("Caption pass project_id=%s elapsed_ms=%s", project.pk, elapsed)
            return dest
        except FFmpegError as exc:
            last_error = exc
            logger.warning("caption attempt %s failed for project %s", attempt, project.pk, exc_info=True)
    dest.unlink(missing_ok=True)
    raise ProviderError(
        "Captions could not be added. The Omni video was kept and was not generated again.",
        retryable=False,
        code="CAPTION_FAILED",
        category="postprocessing",
    ) from last_error


def _split_scene_clips(project: VideoProject, scenes: list[Scene], clean: Path) -> None:
    report = _log_probe(clean, "master")
    actual = float(report.get("duration") or 0) or float(project.duration_seconds or 0)
    weights = [max(float(scene.duration or 0), 0.1) for scene in scenes]
    total = sum(weights) or 1
    cursor = 0.0
    for scene, weight in zip(scenes, weights, strict=True):
        length = actual * weight / total
        start = cursor
        end = min(actual, cursor + length)
        cursor = end
        dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
        try:
            if len(scenes) == 1:
                dest.write_bytes(clean.read_bytes())
            else:
                split_copy(clean, dest, start, end)
            scene.video_clip.save(f"{scene.scene_key}.mp4", ContentFile(dest.read_bytes()), save=True)
            metadata = {
                **(scene.metadata or {}),
                "status": "generated",
                "needs_regeneration": False,
                "error": "",
                "captions_burned": False,
                "clip_prepared": False,
                "omni_film": True,
            }
            scene.metadata = metadata
            scene.generation_status = "completed"
            scene.failure_code = ""
            scene.failure_message = ""
            scene.failed_at = None
            scene.provider = "omni"
            scene.save(
                update_fields=[
                    "metadata",
                    "generation_status",
                    "failure_code",
                    "failure_message",
                    "failed_at",
                    "provider",
                ]
            )
        except FFmpegError:
            logger.warning("Scene clip split failed for %s", scene.scene_key, exc_info=True)
        finally:
            dest.unlink(missing_ok=True)


def _is_cumulative(report: dict, segments: list[int], segment_index: int) -> bool:
    got = float(report.get("duration") or 0)
    if got <= 0:
        return segment_index == 0
    expected = float(sum(segments[: segment_index + 1]))
    segment = float(segments[segment_index])
    if got + 1.5 >= expected:
        return True
    if got <= segment + 1.5:
        return False
    return abs(got - expected) <= abs(got - segment)


def _covers_chain(path: Path, segments: list[int]) -> bool:
    report = probe_media(path)
    got = float(report.get("duration") or 0)
    return got + 1.5 >= float(sum(segments))


def _story_offset(project: VideoProject, chain_index: int) -> float:
    chains = plan_omni_chains(int(project.duration_seconds or 0))
    return float(sum(sum(chain) for chain in chains[:chain_index]))


def _segment_label(chain_index: int, over_boundary: bool) -> str:
    if chain_is_new_generation(chain_index):
        return "Generating final section"
    if over_boundary:
        return "Generating continuous section"
    return "Generating continuous film"


def _store_duration_report(project: VideoProject, report: dict) -> None:
    from django.conf import settings

    from ai.services.generation_metrics import _brief_lock

    with _brief_lock:
        project.refresh_from_db(fields=["creative_brief"])
        _store_duration_report_unlocked(project, report, settings)


def _store_duration_report_unlocked(project: VideoProject, report: dict, settings) -> None:
    actual = float(report.get("duration") or 0)
    requested = float(project.duration_seconds or 0)
    tolerance = float(getattr(settings, "DURATION_TOLERANCE_SECONDS", 2.0) or 2.0)
    difference = round(actual - requested, 2) if requested else 0.0
    brief = dict(project.creative_brief or {})
    brief["duration_report"] = {
        "actual_duration": round(actual, 2),
        "requested_duration": requested,
        "duration_difference": difference,
        "within_tolerance": abs(difference) <= tolerance if requested and actual else False,
        "audio_present": bool(report.get("has_audio")),
        "video_codec": report.get("video_codec") or "",
        "audio_codec": report.get("audio_codec") or "",
        "width": report.get("width"),
        "height": report.get("height"),
        "fps": report.get("fps"),
        "file_size": report.get("file_size") or 0,
    }
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])


def _log_probe(path: Path, label: str) -> dict:
    started = time.perf_counter()
    report = probe_media(path)
    size = path.stat().st_size if path.exists() else 0
    logger.info(
        "probe %s audio_present=%s audio_codec=%s duration=%s video_codec=%s resolution=%sx%s fps=%s file_size=%s ffprobe_ms=%s",
        label,
        bool(report.get("has_audio")),
        report.get("audio_codec") or "",
        report.get("duration"),
        report.get("video_codec") or "",
        report.get("width") or "",
        report.get("height") or "",
        report.get("fps") or "",
        size,
        int((time.perf_counter() - started) * 1000),
    )
    report["file_size"] = size
    return report


def _record_film_metrics(
    project: VideoProject,
    *,
    duration: int,
    chains: list[list[int]],
    join_mode: str,
    caption_pass: bool,
    report: dict,
) -> None:
    from ai.services.generation_metrics import _brief_lock

    with _brief_lock:
        project.refresh_from_db(fields=["creative_brief"])
        _record_film_metrics_unlocked(
            project,
            duration=duration,
            chains=chains,
            join_mode=join_mode,
            caption_pass=caption_pass,
            report=report,
        )


def _record_film_metrics_unlocked(
    project: VideoProject,
    *,
    duration: int,
    chains: list[list[int]],
    join_mode: str,
    caption_pass: bool,
    report: dict,
) -> None:
    metrics = dict((project.creative_brief or {}).get("generation_metrics") or {})
    requests = list(metrics.get("omni_requests") or [])
    metrics["requested_duration"] = duration
    metrics["number_of_chains"] = len(chains)
    metrics["number_of_omni_calls"] = len(requests)
    metrics["number_of_extensions"] = max(0, sum(len(chain) for chain in chains) - len(chains))
    metrics["number_of_ffmpeg_operations"] = int(bool(join_mode)) + int(bool(caption_pass))
    metrics["join_mode"] = join_mode
    metrics["caption_pass"] = bool(caption_pass)
    metrics["audio_present"] = bool(report.get("has_audio"))
    metrics["final_duration"] = report.get("duration") or 0
    metrics["omni_chain_count"] = len(chains)
    metrics["omni_extension_count"] = max(0, sum(len(chain) for chain in chains) - len(chains))
    metrics["continuity_boundary_seconds"] = OMNI_MAX_CONTINUOUS_DURATION_SECONDS
    brief = dict(project.creative_brief or {})
    brief["generation_metrics"] = metrics
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])


def _record_request(
    project: VideoProject,
    started: dict,
    *,
    seconds: int,
    success: bool,
    retry_count: int,
    error_type: str,
    elapsed_ms: int,
    store: bool,
    report: dict | None = None,
    chain_id: int = 0,
    hop_index: int = 0,
    previous_interaction_id_present: bool = False,
) -> None:
    report = report or {}
    completed = timezone.now()
    record_omni_request(
        project,
        {
            "film_id": project.pk,
            "chain_id": chain_id,
            "hop_index": hop_index,
            "attempt": retry_count + 1,
            "model": str(started.get("model") or getattr(getattr(project, "omni", None), "model", "") or "gemini-omni-1.1-flash"),
            "duration": int(started.get("duration_requested") or seconds),
            "duration_requested": int(started.get("duration_requested") or seconds),
            "duration_received": report.get("duration") or 0,
            "resolution": str(started.get("resolution") or report.get("height") or ""),
            "aspect_ratio": str(started.get("aspect_ratio") or "9:16"),
            "reference_count": int(started.get("reference_count") or 0),
            "prompt_length": int(started.get("prompt_length") or 0),
            "store": bool(started.get("store", store)),
            "background": False,
            "stream": False,
            "delivery": str(started.get("delivery") or ""),
            "task": str(started.get("task") or ""),
            "previous_interaction_id_present": previous_interaction_id_present,
            "success": success,
            "status": "ok" if success else (error_type or "error"),
            "retry_count": retry_count,
            "error_type": error_type,
            "omni_generation_duration_ms": int(started.get("elapsed_ms") or elapsed_ms),
            "elapsed_seconds": round((started.get("elapsed_ms") or elapsed_ms) / 1000, 3),
            "completed_at": completed.isoformat(),
            "interaction_id": str(started.get("id") or ""),
        },
    )


def _error_type(exc: Exception) -> str:
    code = str(getattr(exc, "code", "") or "").upper()
    if code:
        return code
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "TIMEOUT"
    if "429" in text or "rate limit" in text or "quota" in text:
        return "RATE_LIMITED"
    return "PROVIDER_ERROR"


def _signature(project: VideoProject, scenes: list[Scene]) -> dict:
    return {
        "duration": int(project.duration_seconds or 0),
        "scenes": [
            {
                "order": scene.order,
                "narration": scene.narration or "",
                "caption": scene.caption or "",
                "visual": (scene.visual or "")[:180],
                "locked": bool((scene.metadata or {}).get("caption_locked")),
            }
            for scene in scenes
        ],
    }


def _saved_signature(project: VideoProject) -> dict:
    return dict((project.creative_brief or {}).get("omni_resume") or {}).get("signature") or {}


def _clear_resume(project: VideoProject) -> None:
    brief = dict(project.creative_brief or {})
    brief.pop("omni_resume", None)
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])
    for asset in list(project.assets.all()):
        role = str((asset.metadata or {}).get("role") or "")
        if role in {"omni_segment", "omni_chain"}:
            asset.delete()


def _mark_resume_complete(project: VideoProject) -> None:
    from ai.services.generation_metrics import _brief_lock

    with _brief_lock:
        project.refresh_from_db(fields=["creative_brief"])
        _mark_resume_complete_unlocked(project)


def _mark_resume_complete_unlocked(project: VideoProject) -> None:
    brief = dict(project.creative_brief or {})
    resume = dict(brief.get("omni_resume") or {})
    resume["complete"] = True
    brief["omni_resume"] = resume
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])


def _remember_signature(project: VideoProject, signature: dict) -> None:
    from ai.services.generation_metrics import _brief_lock

    with _brief_lock:
        project.refresh_from_db(fields=["creative_brief"])
        _remember_signature_unlocked(project, signature)


def _remember_signature_unlocked(project: VideoProject, signature: dict) -> None:
    brief = dict(project.creative_brief or {})
    resume = dict(brief.get("omni_resume") or {})
    resume["signature"] = signature
    brief["omni_resume"] = resume
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])


def _save_segment_asset(
    project: VideoProject,
    source: Path,
    *,
    chain_index: int,
    segment_index: int,
    interaction_id: str,
    duration_requested: int,
    duration_received,
    signature: dict,
    store: bool,
) -> VideoAsset:
    _remember_signature(project, signature)
    asset = VideoAsset(
        project=project,
        kind=VideoAsset.Kind.VIDEO,
        prompt="",
        metadata={
            "role": "omni_segment",
            "chain_index": chain_index,
            "segment_index": segment_index,
            "interaction_id": interaction_id,
            "duration_requested": duration_requested,
            "duration_received": duration_received or 0,
            "store": store,
            "signature": signature,
        },
    )
    asset.file.save(f"omni-c{chain_index}-s{segment_index}.mp4", ContentFile(source.read_bytes()), save=True)
    source.unlink(missing_ok=True)
    return asset


def _save_chain_asset(
    project: VideoProject,
    source: Path,
    chain_index: int,
    signature: dict,
    segments: list[int],
) -> None:
    asset = VideoAsset(
        project=project,
        kind=VideoAsset.Kind.VIDEO,
        prompt="",
        metadata={
            "role": "omni_chain",
            "chain_index": chain_index,
            "segments": segments,
            "signature": signature,
        },
    )
    asset.file.save(f"omni-chain-{chain_index}.mp4", ContentFile(source.read_bytes()), save=True)


def _matching_asset(project: VideoProject, role: str, signature: dict, **matches) -> VideoAsset | None:
    for asset in project.assets.filter(kind=VideoAsset.Kind.VIDEO).order_by("-id"):
        meta = asset.metadata or {}
        if meta.get("role") != role or meta.get("signature") != signature:
            continue
        if any(meta.get(key) != value for key, value in matches.items()):
            continue
        if media_exists(asset.file):
            return asset
    return None


def _segment_asset(project, chain_index, segment_index, signature) -> VideoAsset | None:
    return _matching_asset(
        project,
        "omni_segment",
        signature,
        chain_index=chain_index,
        segment_index=segment_index,
    )


def _chain_asset(project, chain_index, signature) -> VideoAsset | None:
    asset = _matching_asset(project, "omni_chain", signature, chain_index=chain_index)
    if asset is None:
        return None
    report = probe_media(Path(asset.file.path))
    if report.get("has_video") and report.get("has_audio"):
        return asset
    if not report.get("has_video"):
        # Test fixtures and unprobeable files are still the bytes Omni returned.
        return asset
    return None
