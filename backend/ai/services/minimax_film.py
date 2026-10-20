"""Studio film via MiniMax H3: multi-clip generation with optional first-frame continuity."""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from ai.exceptions import ProviderError
from ai.models import VideoProject, VideoProjectStatus
from ai.providers.minimax import MiniMaxProvider, plan_minimax_generation
from ai.services.cancel import raise_if_cancelled
from ai.services.compiler import compile_film_prompt
from ai.services.director import is_studio_project, media_exists
from ai.services.ffmpeg import FFmpegError, concat_clips, probe_media, run_ffmpeg, trim_copy
from ai.services.generation_metrics import record_omni_request, record_span
from ai.services.omni_film import _Heartbeat, _burn_preview, _log_probe, _split_scene_clips, _store_duration_report
from ai.services.presenter import presenter_image_paths
from ai.services.snapshots import snapshot_paths

logger = logging.getLogger(__name__)


def generate_continuous_minimax_film(service, project: VideoProject) -> bool:
    if not is_studio_project(project):
        return False
    scenes = list(project.scenes.all().order_by("order"))
    if not scenes:
        raise ProviderError("Add a storyboard before generating.", retryable=False, code="VALIDATION_FAILED")
    product_frame = service._product_first_frame(project)
    if not product_frame:
        raise ProviderError("Add a product photo before generating.", retryable=False, code="VALIDATION_FAILED")
    duration = int(project.duration_seconds or 0)
    provider = service.omni if getattr(service.omni, "family", lambda: "")() == "minimax" else MiniMaxProvider()
    plan = plan_minimax_generation(duration, model=provider.model)
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
    metrics = dict(brief.get("generation_metrics") or {})
    metrics.update(
        {
            "architecture": "minimax_multi_clip",
            "video_provider": "minimax",
            "video_model": provider.model,
            "requested_duration": duration,
            "minimax_clip_count": plan["clip_count"],
            "minimax_clip_durations": plan["clip_durations"],
            "minimax_generated_duration": plan["generated_duration"],
            "reference_count": len(prepared),
            "generation_started_at": started_at.isoformat(),
            "job_started_at": metrics.get("job_started_at") or started_at.isoformat(),
            "continuity_note": (
                "Later clips use the previous clip's last frame as first_frame when extraction succeeds. "
                "Visual continuity is best-effort and not guaranteed by shared prompts alone."
            ),
        }
    )
    brief["generation_metrics"] = metrics
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])
    logger.info(
        "video_provider=minimax video_model=%s requested_duration=%s clips=%s refs=%s",
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
                provider="minimax",
            )
            dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
            extra_temps.append(dest)
            request_started = time.perf_counter()
            first_frame = previous_last_frame
            use_refs = prepared if hop == 0 and not first_frame else None
            if hop == 0 and not use_refs and product_frame:
                first_frame = product_frame
            with _Heartbeat(project.pk, f"{label} — waiting for MiniMax"):
                started = provider.start(
                    prompt,
                    prepared_images=use_refs,
                    first_frame_path=first_frame,
                    duration_seconds=clip_seconds,
                    aspect_ratio="9:16",
                    generate_audio=True,
                    attempt_context={
                        "film_id": project.pk,
                        "chain_id": 0,
                        "hop_index": hop,
                        "attempt": 1,
                    },
                    should_stop=lambda: raise_if_cancelled(project),
                )
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
                        "previous_interaction_id_present": False,
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
                    provider="minimax",
                    category="download",
                ) from exc
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
                    "previous_interaction_id_present": bool(first_frame),
                    "success": bool(report.get("has_video")),
                    "status": "ok" if report.get("has_video") else "INVALID_VIDEO",
                    "error_type": "" if report.get("has_video") else "INVALID_VIDEO",
                    "audio_present": bool(report.get("has_audio")),
                    "elapsed_seconds": round(time.perf_counter() - request_started, 3),
                    "http_status": 0,
                    "minimax_mode": started.get("mode") or "",
                },
            )
            if not report.get("has_video"):
                raise ProviderError(
                    "The finished video file is empty.",
                    retryable=False,
                    code="INVALID_VIDEO",
                    provider="minimax",
                    category="validation",
                )
            if report.get("has_video") and not report.get("has_audio"):
                raise ProviderError(
                    "The finished video has no audio stream.",
                    retryable=False,
                    code="MISSING_AUDIO",
                    provider="minimax",
                    category="validation",
                )
            clip_files.append(dest)
            if hop < hops - 1:
                frame_path = _extract_last_frame(dest)
                if frame_path:
                    extra_temps.append(frame_path)
                    previous_last_frame = str(frame_path)
                else:
                    previous_last_frame = None
                    logger.warning(
                        "MiniMax last-frame extract failed after hop=%s; next clip will not use first_frame continuity",
                        hop,
                    )

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
                    "The MiniMax videos could not be joined.",
                    retryable=False,
                    code="JOIN_FAILED",
                    provider="minimax",
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
                    provider="minimax",
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
        if report.get("has_video") and not report.get("has_audio"):
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
        metrics = dict((project.creative_brief or {}).get("generation_metrics") or {})
        metrics.update(
            {
                "generation_completed_at": timezone.now().isoformat(),
                "generation_duration_seconds": round(time.perf_counter() - generation_started, 3),
                "minimax_trimmed_duration": report.get("duration") or trim_to,
                "final_duration_seconds": report.get("duration") or 0,
                "audio_present": bool(report.get("has_audio")),
                "resolution": f"{report.get('width') or ''}x{report.get('height') or ''}",
                "fps": report.get("fps") or 0,
                "join_mode": join_mode,
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
                logger.debug("MiniMax temp cleanup skipped for %s", path)


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
        logger.warning("MiniMax last-frame extract failed for %s", video_path, exc_info=True)
    return None
