"""Studio film via Seedance 2.5: prefer one long clip; multi-clip with first-frame continuity."""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from ai.exceptions import ProviderError
from ai.models import VideoProject, VideoProjectStatus
from ai.providers.seedance import (
    SeedanceProvider,
    plan_seedance_generation,
    resolve_seedance_model,
)
from ai.services.cancel import raise_if_cancelled
from ai.services.compiler import compile_film_prompt
from ai.services.director import is_studio_project, media_exists
from ai.services.ffmpeg import FFmpegError, concat_clips, probe_media, run_ffmpeg, trim_copy
from ai.services.generation_metrics import record_omni_request, record_span
from ai.services.omni_film import _Heartbeat, _burn_preview, _log_probe, _split_scene_clips, _store_duration_report
from ai.services.presenter import presenter_image_paths
from ai.services.snapshots import snapshot_paths

logger = logging.getLogger(__name__)


def generate_continuous_seedance_film(service, project: VideoProject) -> bool:
    if not is_studio_project(project):
        return False
    scenes = list(project.scenes.all().order_by("order"))
    if not scenes:
        raise ProviderError("Add a storyboard before generating.", retryable=False, code="VALIDATION_FAILED")
    product_frame = service._product_first_frame(project)
    if not product_frame:
        raise ProviderError("Add a product photo before generating.", retryable=False, code="VALIDATION_FAILED")
    duration = int(project.duration_seconds or 0)
    brief_early = dict(project.creative_brief or {})
    requested_model = (
        brief_early.get("seedance_model")
        or brief_early.get("video_model")
        or (brief_early.get("generation_metrics") or {}).get("video_model")
    )
    # Per-job model selection must survive concurrent 2.5 + Fast workloads.
    try:
        model_id = resolve_seedance_model(requested_model) if requested_model else None
    except ProviderError:
        model_id = None
    if model_id:
        provider = SeedanceProvider(model=model_id)
    elif getattr(service.omni, "family", lambda: "")() == "seedance":
        provider = service.omni
    else:
        provider = SeedanceProvider()
    plan = plan_seedance_generation(duration, model=provider.model)
    project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 8, "Preparing references")
    raise_if_cancelled(project)

    prep_started = time.perf_counter()
    paths = service._reference_images(project)
    character_paths = presenter_image_paths(project)
    product_paths = [str(item) for item in snapshot_paths(project.product_snapshot or {}) if Path(item).exists()]
    if product_frame:
        product_paths = [product_frame, *[p for p in product_paths if p != product_frame]]
    prepared = provider.prepare_images(
        paths,
        character_paths=character_paths,
        product_paths=product_paths,
        style_paths=[p for p in paths if p not in set(character_paths) | set(product_paths)],
    )
    record_span(project, "reference_prepare_ms", int((time.perf_counter() - prep_started) * 1000))
    started_at = timezone.now()
    brief = dict(project.creative_brief or {})
    brief["seedance_model"] = provider.model
    brief["video_model"] = provider.model
    metrics = dict(brief.get("generation_metrics") or {})
    metrics.update(
        {
            "architecture": "seedance_fewest_clips",
            "video_provider": "seedance",
            "video_model": provider.model,
            "seedance_model": provider.model,
            "seedance_api_version": provider.api_version(),
            "seedance_resolution": provider.resolution,
            "seedance_priority": getattr(provider, "priority", None),
            "seedance_service_tier": (
                "default" if provider.api_version() == "2.5" else None
            ),
            "seedance_generate_audio": True,
            "requested_duration": duration,
            "seedance_clip_count": plan["clip_count"],
            "seedance_clip_durations": plan["clip_durations"],
            "seedance_generated_duration": plan["generated_duration"],
            "seedance_max_clip_seconds": plan["max_clip_seconds"],
            "reference_count": len(prepared),
            "generation_started_at": started_at.isoformat(),
            "job_started_at": metrics.get("job_started_at") or started_at.isoformat(),
            "continuity_note": (
                "Clip 1 uses reference_image R2V (ratio 9:16). Later clips use last-frame "
                "continuity as first_frame I2V (ratio adaptive per Seedance 2.x contract). "
                "first_frame and reference_image are never mixed in one request."
            ),
        }
    )
    brief["generation_metrics"] = metrics
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])
    logger.info(
        "video_provider=seedance video_model=%s requested_duration=%s clips=%s refs=%s",
        provider.model,
        duration,
        plan["clip_count"],
        len(prepared),
    )

    clip_durations = list(plan["clip_durations"])
    hops = len(clip_durations)
    extra_temps: list[Path] = []
    clip_files: list[Path] = []
    previous_last_frame: str | None = None
    cursor = 0.0
    generation_started = time.perf_counter()
    total_submit_ms = 0
    total_wait_ms = 0
    total_download_ms = 0
    total_api_wall_seconds = 0
    total_queued_obs_ms = 0
    total_running_obs_ms = 0
    total_local_poll_ms = 0
    # Studio films require native audio by default. Tests may call start(generate_audio=False).
    require_audio = True
    try:
        for hop, clip_seconds in enumerate(clip_durations):
            raise_if_cancelled(project)
            start = cursor
            end = cursor + float(clip_seconds)
            cursor = end
            label = f"Generating clip {hop + 1}/{hops} ({clip_seconds}s)"
            progress = 12 + int(70 * hop / max(hops, 1))
            project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, progress, label)
            prompt = compile_film_prompt(
                project,
                scenes,
                start,
                end,
                extend=hop > 0,
                boundary=False,
                provider="seedance",
            )
            dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
            extra_temps.append(dest)
            request_started = time.perf_counter()
            # Hop 0: omni reference-to-video (product/character as reference_image, 9:16).
            # Later hops: first_frame I2V continuity only (ratio forced adaptive by provider).
            continuity_frame = previous_last_frame if hop > 0 else None
            use_refs = prepared if hop == 0 else None
            with _Heartbeat(project.pk, f"{label} — waiting for Seedance"):
                started = provider.start(
                    prompt,
                    prepared_images=use_refs,
                    first_frame_path=continuity_frame,
                    duration_seconds=clip_seconds,
                    aspect_ratio="9:16",
                    generate_audio=require_audio,
                    return_last_frame=hop < hops - 1,
                    wait=True,
                    attempt_context={
                        "film_id": project.pk,
                        "chain_id": 0,
                        "hop_index": hop,
                        "attempt": 1,
                    },
                    should_stop=lambda: raise_if_cancelled(project),
                )
            total_submit_ms += int(started.get("submit_ms") or 0)
            total_wait_ms += int(started.get("provider_wait_ms") or 0)
            if started.get("api_wall_seconds") is not None:
                total_api_wall_seconds += int(started.get("api_wall_seconds") or 0)
            total_queued_obs_ms += int(started.get("queued_observed_ms") or 0)
            total_running_obs_ms += int(started.get("running_observed_ms") or 0)
            total_local_poll_ms += int(started.get("local_poll_ms") or 0)
            download_started = time.perf_counter()
            try:
                provider.save_video(started, dest)
            except ProviderError as exc:
                record_omni_request(
                    project,
                    {
                        "film_id": project.pk,
                        "chain_id": 0,
                        "hop_index": hop,
                        "attempt": 1,
                        "model": provider.model,
                        "duration": started.get("duration_requested") or clip_seconds,
                        "store": False,
                        "task": started.get("task") or "",
                        "previous_interaction_id_present": bool(continuity_frame),
                        "success": False,
                        "status": "DOWNLOAD_FAILED",
                        "error_type": "DOWNLOAD_FAILED",
                        "elapsed_seconds": round(time.perf_counter() - request_started, 3),
                    },
                )
                raise ProviderError(
                    str(exc) or "The generated video could not be downloaded.",
                    retryable=False,
                    code="DOWNLOAD_FAILED",
                    provider="seedance",
                    category="download",
                ) from exc
            download_ms = int((time.perf_counter() - download_started) * 1000)
            total_download_ms += download_ms
            record_span(project, "download_ms", download_ms)
            report = _log_probe(dest, label)
            record_omni_request(
                project,
                {
                    "film_id": project.pk,
                    "chain_id": 0,
                    "hop_index": hop,
                    "attempt": 1,
                    "model": provider.model,
                    "duration": started.get("duration_requested") or clip_seconds,
                    "store": False,
                    "task": started.get("task") or ("generate" if hop == 0 else "continue"),
                    "previous_interaction_id_present": bool(continuity_frame),
                    "success": bool(report.get("has_video")),
                    "status": "ok" if report.get("has_video") else "INVALID_VIDEO",
                    "error_type": "" if report.get("has_video") else "INVALID_VIDEO",
                    "audio_present": bool(report.get("has_audio")),
                    "elapsed_seconds": round(time.perf_counter() - request_started, 3),
                    "http_status": 0,
                    "seedance_mode": started.get("mode") or "",
                    "aspect_ratio": started.get("aspect_ratio") or "",
                    "submit_ms": started.get("submit_ms") or 0,
                    "provider_wait_ms": started.get("provider_wait_ms") or 0,
                    "api_wall_seconds": started.get("api_wall_seconds"),
                    "queued_observed_ms": started.get("queued_observed_ms"),
                    "running_observed_ms": started.get("running_observed_ms"),
                    "first_status": started.get("first_status") or "",
                    "download_ms": download_ms,
                },
            )
            if not report.get("has_video"):
                raise ProviderError(
                    "The finished video file is empty.",
                    retryable=False,
                    code="INVALID_VIDEO",
                    provider="seedance",
                    category="validation",
                )
            if require_audio and report.get("has_video") and not report.get("has_audio"):
                raise ProviderError(
                    "The finished video has no audio stream.",
                    retryable=False,
                    code="MISSING_AUDIO",
                    provider="seedance",
                    category="validation",
                )
            clip_files.append(dest)
            if hop < hops - 1:
                previous_last_frame = _next_first_frame(provider, started, dest, extra_temps)

        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 86, "Joining clips")
        post_started = time.perf_counter()
        if len(clip_files) == 1:
            combined = clip_files[0]
            join_mode = ""
        else:
            combined = Path(tempfile.mkstemp(suffix=".mp4")[1])
            extra_temps.append(combined)
            try:
                concat_clips(clip_files, combined, fade=0)
                join_mode = "concat"
            except FFmpegError as exc:
                raise ProviderError(
                    "The Seedance videos could not be joined.",
                    retryable=False,
                    code="JOIN_FAILED",
                    provider="seedance",
                    category="postprocessing",
                ) from exc

        clean = combined
        trim_to = int(plan["trim_to"] or 0) or duration
        if trim_to and float(probe_media(combined).get("duration") or 0) > trim_to + 0.15:
            trimmed = Path(tempfile.mkstemp(suffix=".mp4")[1])
            extra_temps.append(trimmed)
            try:
                trim_copy(combined, trimmed, trim_to)
            except FFmpegError as exc:
                raise ProviderError(
                    "The video could not be trimmed to the requested length.",
                    retryable=False,
                    code="FFMPEG_FAILED",
                    provider="seedance",
                    category="postprocessing",
                ) from exc
            clean = trimmed

        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 90, "Finalizing video")
        _split_scene_clips(project, scenes, clean)
        preview = _burn_preview(project, scenes, clean)
        if preview != clean:
            extra_temps.append(preview)
        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 94, "Validating video")
        report = _log_probe(preview, "final")
        _store_duration_report(project, report)
        if require_audio and report.get("has_video") and not report.get("has_audio"):
            raise ProviderError(
                "The finished video has no audio stream.",
                retryable=False,
                code="MISSING_AUDIO",
                category="validation",
            )
        if not preview.exists() or preview.stat().st_size == 0:
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
        record_span(project, "postprocess_duration_ms", int((time.perf_counter() - post_started) * 1000))
        record_span(project, "seedance_submit_ms", total_submit_ms)
        record_span(project, "seedance_provider_wait_ms", total_wait_ms)
        record_span(project, "seedance_download_ms", total_download_ms)
        record_span(project, "seedance_api_wall_seconds", total_api_wall_seconds)
        metrics = dict((project.creative_brief or {}).get("generation_metrics") or {})
        metrics.update(
            {
                "generation_completed_at": timezone.now().isoformat(),
                "generation_duration_seconds": round(time.perf_counter() - generation_started, 3),
                "seedance_trimmed_duration": report.get("duration") or trim_to,
                "final_duration_seconds": report.get("duration") or 0,
                "audio_present": bool(report.get("has_audio")),
                "resolution": f"{report.get('width') or ''}x{report.get('height') or ''}",
                "fps": report.get("fps") or 0,
                "join_mode": join_mode,
                "seedance_submit_ms": total_submit_ms,
                "seedance_provider_wait_ms": total_wait_ms,
                "seedance_download_ms": total_download_ms,
                # API created_at→updated_at wall; includes queue + render. Not pure render.
                "seedance_api_wall_seconds": total_api_wall_seconds,
                "seedance_queued_observed_ms": total_queued_obs_ms,
                "seedance_running_observed_ms": total_running_obs_ms,
                "seedance_local_poll_ms": total_local_poll_ms,
                "seedance_polling_overhead_ms": max(0, total_wait_ms - total_api_wall_seconds * 1000)
                if total_api_wall_seconds
                else None,
            }
        )
        brief = dict(project.creative_brief or {})
        brief["generation_metrics"] = metrics
        project.creative_brief = brief
        project.save(update_fields=["creative_brief", "updated_at"])
        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 98, "Finalizing video")
        return True
    finally:
        for path in extra_temps:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Seedance temp cleanup skipped for %s", path)


def _next_first_frame(provider, started: dict, clip_path: Path, extra_temps: list[Path]) -> str | None:
    last_url = str(started.get("last_frame_url") or "").strip()
    if last_url:
        dest = Path(tempfile.mkstemp(suffix=".jpg")[1])
        saved = provider.download_last_frame(last_url, dest)
        if saved and saved.exists() and saved.stat().st_size >= 32:
            extra_temps.append(saved)
            return str(saved)
        dest.unlink(missing_ok=True)
    frame = _extract_last_frame(clip_path)
    if frame:
        extra_temps.append(frame)
        return str(frame)
    logger.warning("Seedance continuity frame unavailable; next clip may restart visually")
    return None


def _extract_last_frame(video_path: Path) -> Path | None:
    try:
        report = probe_media(video_path)
        duration = float(report.get("duration") or 0)
        if duration <= 0:
            return None
        stamp = max(0.0, duration - 0.12)
        dest = Path(tempfile.mkstemp(suffix=".jpg")[1])
        run_ffmpeg(
            [
                "-ss",
                f"{stamp:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(dest),
            ]
        )
        if dest.exists() and dest.stat().st_size >= 32:
            return dest
        dest.unlink(missing_ok=True)
    except Exception:
        logger.warning("Seedance last-frame extract failed for %s", video_path, exc_info=True)
    return None
