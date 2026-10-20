"""Studio film as one Veo 3.1 chain: 8s create then +7s extensions, then trim."""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from ai.exceptions import ProviderError
from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.providers.google.veo import (
    VEO_EXTENSION_SECONDS,
    VEO_INITIAL_SECONDS,
    VeoProvider,
    plan_veo_generation,
)
from ai.services.cancel import raise_if_cancelled
from ai.services.compiler import compile_film_prompt
from ai.services.director import is_studio_project, media_exists
from ai.services.ffmpeg import FFmpegError, probe_media, trim_copy
from ai.services.generation_metrics import record_omni_request, record_span
from ai.services.omni_film import _Heartbeat, _burn_preview, _log_probe, _split_scene_clips, _store_duration_report
from ai.services.presenter import presenter_image_paths
from ai.services.snapshots import snapshot_paths

logger = logging.getLogger(__name__)


def generate_continuous_veo_film(service, project: VideoProject) -> bool:
    if not is_studio_project(project):
        return False
    scenes = list(project.scenes.all().order_by("order"))
    if not scenes:
        raise ProviderError("Add a storyboard before generating.", retryable=False, code="VALIDATION_FAILED")
    product_frame = service._product_first_frame(project)
    if not product_frame:
        raise ProviderError("Add a product photo before generating.", retryable=False, code="VALIDATION_FAILED")
    duration = int(project.duration_seconds or 0)
    plan = plan_veo_generation(duration)
    provider = service.omni if getattr(service.omni, "family", lambda: "")() == "veo" else VeoProvider()
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
            "architecture": "veo_extension_chain",
            "video_provider": "veo",
            "video_model": provider.model,
            "requested_duration": duration,
            "veo_initial_duration": plan["initial_duration"],
            "veo_extension_count": plan["extension_count"],
            "veo_generated_duration": plan["generated_duration"],
            "reference_count": len(prepared),
            "generation_started_at": started_at.isoformat(),
            "job_started_at": metrics.get("job_started_at") or started_at.isoformat(),
        }
    )
    brief["generation_metrics"] = metrics
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])
    logger.info(
        "video_provider=veo video_model=%s requested_duration=%s extensions=%s refs=%s",
        provider.model,
        duration,
        plan["extension_count"],
        len(prepared),
    )

    hops = 1 + int(plan["extension_count"])
    extra_temps: list[Path] = []
    current: Path | None = None
    previous_uri = ""
    previous_video = None
    generation_started = time.perf_counter()
    try:
        for hop in range(hops):
            raise_if_cancelled(project)
            if hop == 0:
                start, end = 0.0, float(VEO_INITIAL_SECONDS)
                label = f"Generating {VEO_INITIAL_SECONDS}s"
                progress = 12
            else:
                reached = VEO_INITIAL_SECONDS + hop * VEO_EXTENSION_SECONDS
                start = float(VEO_INITIAL_SECONDS + (hop - 1) * VEO_EXTENSION_SECONDS)
                end = float(reached)
                label = f"Extending to {reached}s"
                progress = 12 + int(70 * hop / max(hops, 1))
            project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, progress, label)
            prompt = compile_film_prompt(
                project,
                scenes,
                start,
                end,
                extend=hop > 0,
                boundary=False,
                provider="veo",
            )
            dest = Path(tempfile.mkstemp(suffix=".mp4")[1])
            extra_temps.append(dest)
            request_started = time.perf_counter()
            with _Heartbeat(project.pk, f"{label} — waiting for Veo"):
                started = provider.start(
                    prompt,
                    prepared_images=prepared if hop == 0 else None,
                    video_path=str(current) if current is not None else None,
                    previous_video=previous_video,
                    previous_video_uri=previous_uri or None,
                    duration_seconds=VEO_INITIAL_SECONDS if hop == 0 else 0,
                    aspect_ratio="9:16",
                    generate_audio=True,
                    attempt_context={"film_id": project.pk, "chain_id": 0, "hop_index": hop, "attempt": 1},
                    should_stop=lambda: raise_if_cancelled(project),
                )
            previous_video = started.get("generated_video") or previous_video
            previous_uri = str(started.get("uri") or previous_uri or "")
            saved = started.get("path")
            if saved:
                extra_temps.append(Path(saved))
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
                        "duration": started.get("duration_requested") or 0,
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
                    provider="veo",
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
                    "duration": started.get("duration_requested") or (VEO_INITIAL_SECONDS if hop == 0 else VEO_EXTENSION_SECONDS),
                    "store": False,
                    "task": started.get("task") or ("generate" if hop == 0 else "extend"),
                    "previous_interaction_id_present": False,
                    "success": bool(report.get("has_video")),
                    "status": "ok" if report.get("has_video") else "INVALID_VIDEO",
                    "error_type": "" if report.get("has_video") else "INVALID_VIDEO",
                    "audio_present": bool(report.get("has_audio")),
                    "elapsed_seconds": round(time.perf_counter() - request_started, 3),
                    "http_status": 0,
                },
            )
            if not report.get("has_video"):
                raise ProviderError(
                    "The finished video file is empty.",
                    retryable=False,
                    code="INVALID_VIDEO",
                    provider="veo",
                    category="validation",
                )
            if report.get("has_video") and not report.get("has_audio"):
                raise ProviderError(
                    "The finished video has no audio stream.",
                    retryable=False,
                    code="MISSING_AUDIO",
                    provider="veo",
                    category="validation",
                )
            current = dest
        assert current is not None
        project.mark_progress(VideoProjectStatus.GENERATING_VIDEO, 88, "Finalizing video")
        post_started = time.perf_counter()
        clean = current
        trim_to = int(plan["trim_to"] or 0) or duration
        if trim_to and float(probe_media(current).get("duration") or 0) > trim_to + 0.15:
            trimmed = Path(tempfile.mkstemp(suffix=".mp4")[1])
            extra_temps.append(trimmed)
            try:
                trim_copy(current, trimmed, trim_to)
            except FFmpegError as exc:
                raise ProviderError(
                    "The video could not be trimmed to the requested length.",
                    retryable=False,
                    code="FFMPEG_FAILED",
                    provider="veo",
                    category="postprocessing",
                ) from exc
            clean = trimmed
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
                "veo_trimmed_duration": report.get("duration") or trim_to,
                "final_duration_seconds": report.get("duration") or 0,
                "audio_present": bool(report.get("has_audio")),
                "resolution": f"{report.get('width') or ''}x{report.get('height') or ''}",
                "fps": report.get("fps") or 0,
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
                logger.debug("Veo temp cleanup skipped for %s", path)
