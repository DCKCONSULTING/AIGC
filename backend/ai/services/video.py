from __future__ import annotations

import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections

from ai.exceptions import GoogleProviderError, MissingAPIKeyError, ProviderError
from ai.models import (
    Scene,
    VideoAsset,
    VideoProject,
    VideoProjectStatus,
)
from ai.providers.google.client import speech_configured
from ai.providers.google.nano_banana import NanoBananaProvider
from ai.providers.google.omni import GeminiOmniProvider
from ai.providers.google.speech import SpeechProvider
from ai.providers.video import get_video_generation_provider

from .amendments import AmendmentService
from .cancel import GenerationCancelled, raise_if_cancelled
from .compiler import compile_scene_prompt
from .director import (
    DirectorService,
    continuity_dependents,
    is_studio_project,
    is_video_fallback,
    mark_continuity_stale,
    media_exists,
)
from .ffmpeg import (
    FFmpegError,
    assemble_project,
    clip_is_assembly_ready,
    image_to_clip,
    inspect_audio,
    prepare_scene_clip,
    probe_duration,
    probe_media,
)
from .intelligence import KalodataService
from .omni_film import generate_continuous_film
from .product import ProductAnalysisService
from .presenter import (
    presenter_identity_text,
    presenter_image_paths,
    presenter_should_appear,
    stamp_presenter_reference,
)
from .qa import QAService
from .reference import ReferenceAnalysisService
from .script import ScriptService
from .snapshots import product_snapshot, snapshot_paths
from .usage import record_usage

logger = logging.getLogger(__name__)


def _omni_wait_seconds() -> int:
    try:
        value = int(getattr(settings, "OMNI_REQUEST_TIMEOUT_SECONDS", 300) or 300)
    except (TypeError, ValueError):
        value = 300
    return max(60, min(value, 600))


def visible_generation_error(exc: BaseException) -> str:
    code = str(getattr(exc, "code", "") or "").upper()
    if code == "RATE_LIMITED":
        return str(exc)
    if code == "TIMEOUT":
        return "Video generation timed out. The worker was released. Please try again."
    if code == "DOWNLOAD_FAILED":
        return "The generated video could not be downloaded. The AI clip was not generated again."
    if code in {"JOIN_FAILED", "CAPTION_FAILED", "FFMPEG_FAILED", "POSTPROCESSING_FAILED"}:
        return str(exc) or "Video post-processing failed. The AI clip was not generated again."
    if code == "INVALID_REQUEST":
        return (
            "Video regeneration is currently unavailable. "
            "The video provider rejected the status request. "
            "Try again after the provider issue is resolved."
        )
    return str(exc)


def _stamp_job_failure(project: VideoProject, exc: BaseException) -> None:
    from ai.providers.video import video_model_name, video_provider_name

    code = str(getattr(exc, "code", "") or "").upper()
    brief = dict(project.creative_brief or {})
    metrics = dict(brief.get("generation_metrics") or {})
    brief["provider_error"] = {
        "provider": str(
            getattr(exc, "provider", "") or metrics.get("video_provider") or video_provider_name()
        ),
        "model": str(metrics.get("video_model") or video_model_name()),
        "status_code": int(getattr(exc, "status_code", 0) or 0),
        "retry_after": str(getattr(exc, "retry_after", "") or ""),
        "message": visible_generation_error(exc),
        "timestamp": timezone_now(),
        "error_type": code or type(exc).__name__,
    }
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])
    if code == "RATE_LIMITED":
        project.stage_label = "Rate limited"
        project.save(update_fields=["stage_label", "updated_at"])


def timezone_now() -> str:
    from django.utils import timezone

    return timezone.now().isoformat()


class VideoGenerationService:
    def __init__(
        self,
        product_service: ProductAnalysisService | None = None,
        reference_service: ReferenceAnalysisService | None = None,
        script_service: ScriptService | None = None,
        images: NanoBananaProvider | None = None,
        omni: GeminiOmniProvider | None = None,
        seedance: GeminiOmniProvider | None = None,
        speech: SpeechProvider | None = None,
        qa: QAService | None = None,
    ):
        self.product_service = product_service or ProductAnalysisService()
        self.reference_service = reference_service or ReferenceAnalysisService()
        self.script_service = script_service or ScriptService()
        self.images = images or NanoBananaProvider()
        self.omni = omni or seedance or get_video_generation_provider()
        self.kalodata = KalodataService()
        self.speech = speech or SpeechProvider()
        self.qa = qa or QAService()

    def _active_video_provider(self) -> str:
        family = str(getattr(self.omni, "family", lambda: "")() or "").strip().lower()
        if family in {"veo", "minimax", "seedance", "omni"}:
            return family
        from ai.providers.video import video_provider_name

        try:
            return video_provider_name()
        except Exception:
            return "omni"

    def run(self, project_id: int) -> VideoProject:
        project = VideoProject.objects.select_related("product").get(pk=project_id)
        try:
            from ai.services.generation_metrics import ensure_metrics, mark_total, persist_metrics, timed_phase
            from ai.services.preflight import PreflightError, preflight_project
            from django.utils import timezone as dj_tz

            # Record queue wait when the worker picks up a previously queued job.
            brief = dict(project.creative_brief or {})
            metrics = ensure_metrics(project)
            metrics["job_claimed_at"] = dj_tz.now().isoformat()
            queued_at = brief.get("queued_at") or metrics.get("queued_at")
            if queued_at:
                try:
                    from datetime import datetime

                    started = datetime.fromisoformat(str(queued_at).replace("Z", "+00:00"))
                    metrics["queue_wait_ms"] = max(
                        0, int((dj_tz.now() - started).total_seconds() * 1000)
                    )
                except Exception:
                    pass
            persist_metrics(project, metrics)

            raise_if_cancelled(project)
            with timed_phase(project, "project_creation"):
                self._refresh_snapshot(project)
                raise_if_cancelled(project)
                if is_studio_project(project):
                    try:
                        from ai.services.characters import refresh_unfrozen_character_snapshot

                        refresh_unfrozen_character_snapshot(project)
                        project.refresh_from_db()
                        preflight_project(project)
                    except PreflightError as exc:
                        project.mark_failed(str(exc))
                        raise
            raise_if_cancelled(project)
            with timed_phase(project, "script_generation"):
                self._analyze(project)
                raise_if_cancelled(project)
                self._plan(project)
            raise_if_cancelled(project)
            with timed_phase(project, "storyboard_generation"):
                if not (project.selected_concept_id and project.scenes.exists()):
                    self._sync_scenes(project)
                raise_if_cancelled(project)
                if self.omni.family() != "1.x" and not is_studio_project(project):
                    self._create_images(project)
            raise_if_cancelled(project)
            filmed = False
            with timed_phase(project, "scene_generation"):
                if is_studio_project(project):
                    filmed = generate_continuous_film(self, project)
                else:
                    self._create_videos(project)
            raise_if_cancelled(project)
            self._create_voice(project)
            raise_if_cancelled(project)
            with timed_phase(project, "assembly"):
                if not (filmed and media_exists(project.preview_video)):
                    self._assemble(project)
            if not is_studio_project(project):
                raise_if_cancelled(project)
                if project.preview_video:
                    project.mark_progress(VideoProjectStatus.QA_RUNNING, 92, "Video ready")
                try:
                    with timed_phase(project, "qa"):
                        self._quality(project)
                        self._recommend(project)
                except Exception:
                    logger.exception("QA after assemble skipped for project %s", project.pk)
            mark_total(project)
            raise_if_cancelled(project)
            if is_studio_project(project) and not media_exists(project.preview_video):
                raise ProviderError(
                    "The finished video file is missing.",
                    retryable=False,
                    code="INVALID_VIDEO",
                    category="validation",
                )
            project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Ready")
            return project
        except GenerationCancelled:
            project.refresh_from_db()
            if project.status == VideoProjectStatus.QUEUED:
                project.mark_failed("Generation did not start. Please try again.")
            logger.info("Video generation stopped by user project_id=%s", project_id)
            return project
        except MissingAPIKeyError as exc:
            if project.preview_video and not is_studio_project(project):
                logger.exception("Generation key error after preview for project %s", project.pk)
                project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Video ready")
                return project
            project.mark_failed(visible_generation_error(exc))
            raise
        except (GoogleProviderError, ProviderError, FFmpegError) as exc:
            if project.preview_video and not is_studio_project(project):
                logger.exception("Generation error after preview for project %s", project.pk)
                project.error_message = visible_generation_error(exc)
                project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Video ready")
                project.refresh_from_db()
                return project
            _stamp_job_failure(project, exc)
            project.mark_failed(visible_generation_error(exc))
            raise
        except ImportError:
            logger.exception("Video generation failed for project %s", project_id)
            project.mark_failed("Video generation is restarting on the server. Please try again in a moment.")
            raise
        except Exception:
            logger.exception("Video generation failed for project %s", project_id)
            if project.preview_video and not is_studio_project(project):
                project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Video ready")
                return project
            project.mark_failed("Video generation failed. Please try again.")
            raise

    def apply_correction(self, project: VideoProject, parsed: dict) -> VideoProject:
        regenerate = set(parsed.get("regenerate") or [])
        scene_key = parsed.get("scene_key") or ""
        instruction = (parsed.get("instruction") or "").strip()
        try:
            self._refresh_snapshot(project)
            if instruction and instruction not in (project.merchant_instructions or ""):
                project.merchant_instructions = "\n".join(
                    part for part in [project.merchant_instructions, instruction] if part
                )
            if regenerate & {"product_snapshot", "brief", "script", "shot_plan"}:
                if "brief" in regenerate or "product_snapshot" in regenerate:
                    project.creative_brief = self.script_service.build_brief(project)
                    from ai.services.durations import supported_duration

                    duration = supported_duration(
                        (project.creative_brief or {}).get("duration") or self.script_service._duration(project)
                    )
                    project.duration_seconds = duration
                if "script" in regenerate or "brief" in regenerate:
                    project.script = self.script_service.generate_script(project)
                if "shot_plan" in regenerate or "script" in regenerate:
                    project.shot_plan = self.script_service.plan_shots(project)
                project.save()
                self._sync_scenes(project)

            scenes = list(project.scenes.all())
            if scene_key:
                scenes = [scene for scene in scenes if scene.scene_key == scene_key]
            elif "scene" in regenerate:
                scenes = list(project.scenes.all())
            else:
                scenes = []

            if scenes or regenerate & {"scene", "video"}:
                if self.omni.family() != "1.x" and not is_studio_project(project):
                    self._create_images(project, scenes=scenes or None, force=True)
                studio_full = is_studio_project(project) and not scene_key and "scene" not in regenerate
                if studio_full:
                    generate_continuous_film(self, project)
                else:
                    self._create_videos(project, scenes=scenes or None, force=True)
            if regenerate & {"narration", "captions", "script", "change_narration", "scene"}:
                self._create_voice(project)
            if regenerate & {"video", "scene", "narration", "captions", "script"}:
                self._assemble(project)
            if not is_studio_project(project):
                if project.preview_video:
                    project.mark_progress(VideoProjectStatus.QA_RUNNING, 92, "Video ready")
                try:
                    self._quality(project)
                    self._recommend(project)
                except Exception:
                    logger.exception("QA after correction skipped for project %s", project.pk)
            project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Ready for review")
            return project
        except Exception as exc:
            logger.exception("Correction failed for project %s", project.pk)
            if project.preview_video:
                project.error_message = (
                    visible_generation_error(exc)
                    if isinstance(exc, (MissingAPIKeyError, ProviderError, GoogleProviderError))
                    else project.error_message
                )
                project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Video ready")
                return project
            project.mark_failed(
                visible_generation_error(exc)
                if isinstance(exc, (MissingAPIKeyError, ProviderError, GoogleProviderError))
                else "Correction failed."
            )
            raise

    def _analyze(self, project: VideoProject) -> None:
        project.mark_progress(VideoProjectStatus.ANALYZING, 8, "Reviewing product")
        if not project.product_analysis:
            try:
                analysis = self.product_service.analyze(
                    project.product,
                    overrides=project.product_snapshot,
                    instructions=project.merchant_instructions,
                    language=project.language,
                )
            except Exception:
                logger.exception("Product analysis skipped for project %s", project.pk)
                analysis = {"name": project.product_snapshot.get("name") or project.product.name, "facts": []}
            project.product_analysis = analysis
            project.save(update_fields=["product_analysis", "updated_at"])
        if not project.kalodata_insights:
            category = ""
            try:
                category = project.product.brand.category.name
            except Exception:
                category = ""
            project.kalodata_insights = self.kalodata.insights(
                category=category,
                product_name=project.product_snapshot.get("name") or project.product.name,
            )
            project.save(update_fields=["kalodata_insights", "updated_at"])
        if (project.reference_video or project.reference_url) and not project.reference_analysis:
            project.mark_progress(VideoProjectStatus.ANALYZING, 16, "Studying reference video")
            try:
                project.reference_analysis = self.reference_service.analyze(
                    project.reference_video.path if project.reference_video else None,
                    reference_url=project.reference_url or "",
                    product_snapshot=project.product_snapshot,
                )
            except Exception:
                logger.exception("Reference analysis skipped for project %s", project.pk)
                project.reference_analysis = {}
            project.save(update_fields=["reference_analysis", "updated_at"])

    def regenerate_scenes(self, project_id: int, scene_ids: list[int]) -> VideoProject:
        project = VideoProject.objects.select_related("product").get(pk=project_id)
        requested = list(project.scenes.filter(pk__in=scene_ids).order_by("order"))
        extra_ids: list[int] = []
        for scene in requested:
            extra_ids.extend(item.pk for item in mark_continuity_stale(continuity_dependents(project, scene)))
        scene_ids = list(dict.fromkeys([*scene_ids, *extra_ids]))
        scenes = list(project.scenes.filter(pk__in=scene_ids).order_by("order"))
        if not scenes:
            project.mark_failed("No scenes were selected to regenerate.")
            return project
        try:
            logger.info(
                "Regenerating scenes %s for project %s",
                [scene.scene_key for scene in scenes],
                project.pk,
            )
            self._refresh_snapshot(project)
            locked = [scene for scene in scenes if (scene.metadata or {}).get("scene_locked")]
            if locked and len(locked) == len(scenes):
                project.mark_failed("All selected scenes are locked.")
                return project
            to_render = [
                scene
                for scene in scenes
                if (scene.metadata or {}).get("needs_regeneration")
                and not (scene.metadata or {}).get("scene_locked")
            ]
            reassemble_only = not to_render and any(
                (scene.metadata or {}).get("needs_reassemble") for scene in scenes
            )
            if not to_render and not reassemble_only:
                to_render = [scene for scene in scenes if not (scene.metadata or {}).get("scene_locked")]
                if not to_render:
                    project.mark_failed("All selected scenes are locked.")
                    return project
            if to_render:
                if self.omni.family() != "1.x" and not is_studio_project(project):
                    self._create_images(project, scenes=to_render, force=True)
                self._create_videos(project, scenes=to_render, force=True)
            elif reassemble_only:
                logger.info("Reassembling project %s without video regeneration", project.pk)
            self._create_voice(project)
            self._assemble(project)
            if not is_studio_project(project):
                if project.preview_video:
                    project.mark_progress(VideoProjectStatus.QA_RUNNING, 92, "Video ready")
                try:
                    self._quality(project)
                    self._recommend(project)
                except Exception:
                    logger.exception("QA after scene regeneration skipped for project %s", project.pk)
            project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Ready for review")
            return project
        except Exception as exc:
            logger.exception("Scene regeneration failed for project %s", project.pk)
            for scene in scenes:
                meta = dict(scene.metadata or {})
                if meta.get("status") in {"generating", "regenerating"}:
                    meta["status"] = "failed"
                    meta["error"] = str(exc) if isinstance(exc, (MissingAPIKeyError, ProviderError, GoogleProviderError)) else "Scene generation failed."
                    scene.metadata = meta
                    scene.save(update_fields=["metadata"])
            if project.preview_video:
                project.mark_progress(VideoProjectStatus.READY_FOR_REVIEW, 100, "Video ready")
                return project
            project.mark_failed(
                visible_generation_error(exc)
                if isinstance(exc, (MissingAPIKeyError, ProviderError, GoogleProviderError))
                else "Scene regeneration failed."
            )
            raise

    def _plan(self, project: VideoProject) -> None:
        director_planned = bool(project.selected_concept_id and project.scenes.exists())
        if director_planned:
            project.mark_progress(VideoProjectStatus.PLANNING, 36, "Using your storyboard")
            logger.info("Using director timeline for project %s", project.pk)
            if not project.script:
                DirectorService()._refresh_script_from_scenes(project)
            if is_studio_project(project):
                DirectorService()._align_captions_to_speech(project)
            else:
                try:
                    DirectorService().review_copy(project)
                except Exception:
                    logger.exception("Copy review skipped for project %s", project.pk)
            missing_prompts = not all(
                (scene.metadata or {}).get("video_prompt") or scene.visual
                for scene in project.scenes.all()
            )
            if missing_prompts and not project.shot_plan:
                project.shot_plan = self.script_service.plan_shots(project)
                project.save(update_fields=["shot_plan", "updated_at"])
                self._merge_shot_metadata(project)
            return
        project.mark_progress(VideoProjectStatus.BRIEF_READY, 24, "Writing creative brief")
        if not project.creative_brief:
            project.creative_brief = self.script_service.build_brief(project)
            project.creative_directions = (project.creative_brief or {}).get("directions") or []
            project.save(update_fields=["creative_brief", "creative_directions", "updated_at"])
        project.mark_progress(VideoProjectStatus.SCRIPT_READY, 36, "Writing script")
        if not project.script:
            project.script = self.script_service.generate_script(project)
            project.save(update_fields=["script", "updated_at"])
        project.mark_progress(VideoProjectStatus.PLANNING, 42, "Planning the shots")
        if not project.shot_plan:
            project.shot_plan = self.script_service.plan_shots(project)
            project.save(update_fields=["shot_plan", "updated_at"])

    def _merge_shot_metadata(self, project: VideoProject) -> None:
        shots = {
            item.get("scene_key"): item
            for item in (project.shot_plan or {}).get("shots") or []
        }
        for scene in project.scenes.all():
            extra = shots.get(scene.scene_key) or {}
            if not extra:
                continue
            meta = dict(scene.metadata or {})
            if extra.get("image_prompt"):
                meta["image_prompt"] = extra["image_prompt"]
            if extra.get("video_prompt"):
                meta["video_prompt"] = extra["video_prompt"]
            if extra.get("camera") and not meta.get("camera_framing"):
                meta["camera_framing"] = extra["camera"]
            scene.metadata = meta
            scene.save(update_fields=["metadata"])

    def _sync_scenes(self, project: VideoProject) -> None:
        script_scenes = (project.script or {}).get("scenes") or []
        shots = {
            item.get("scene_key"): item
            for item in (project.shot_plan or {}).get("shots") or []
        }
        keep = []
        for index, item in enumerate(script_scenes, start=1):
            key = item.get("scene_key") or f"scene-{index}"
            existing = Scene.objects.filter(project=project, scene_key=key).first()
            metadata = {**((existing.metadata if existing else None) or {})}
            metadata.update(shots.get(key) or {})
            metadata["product_facts"] = item.get("product_facts") or []
            metadata["scene"] = item.get("scene") or index
            scene, _ = Scene.objects.update_or_create(
                project=project,
                scene_key=key,
                defaults={
                    "order": item.get("order") or item.get("scene") or index,
                    "title": item.get("title") or f"Scene {index}",
                    "visual": item.get("visual") or "",
                    "narration": item.get("narration") or "",
                    "caption": item.get("caption") or "",
                    "duration": float(item.get("duration") or 5),
                    "metadata": metadata,
                },
            )
            keep.append(scene.pk)
        project.scenes.exclude(pk__in=keep).delete()
        project.narration = {
            "language": project.language,
            "style": project.speaking_style,
            "lines": [
                {"scene_key": scene.scene_key, "text": scene.narration}
                for scene in project.scenes.all()
            ],
        }
        project.captions = {
            "lines": [
                {
                    "scene_key": scene.scene_key,
                    "text": scene.caption,
                    "duration": scene.duration,
                }
                for scene in project.scenes.all()
            ]
        }
        project.save(update_fields=["narration", "captions", "updated_at"])

    def _create_images(
        self,
        project: VideoProject,
        scenes: list[Scene] | None = None,
        *,
        force: bool = False,
    ) -> None:
        project.mark_progress(VideoProjectStatus.GENERATING_ASSETS, 48, "Creating images")
        references = self._reference_images(project)
        for scene in scenes or project.scenes.all():
            if not force and scene.image:
                continue
            prompt = (scene.metadata or {}).get("image_prompt") or scene.visual
            try:
                image_bytes = self.images.generate_image(
                    (
                        f"Vertical 9:16 product scene. Product: {project.product_snapshot.get('name')}. "
                        f"{prompt}"
                    ),
                    reference_images=references,
                    aspect_ratio="9:16",
                )
                filename = f"{scene.scene_key}.png"
                scene.image.save(filename, ContentFile(image_bytes), save=True)
                VideoAsset.objects.create(
                    project=project,
                    scene=scene,
                    kind=VideoAsset.Kind.IMAGE,
                    file=scene.image,
                    prompt=prompt,
                )
            except (GoogleProviderError, ProviderError, MissingAPIKeyError):
                logger.warning("Still image skipped for %s", scene.scene_key)
        self._create_thumbnail(project, references)

    def _create_thumbnail(self, project: VideoProject, references: list[str]) -> None:
        if project.assets.filter(kind=VideoAsset.Kind.THUMBNAIL).exists():
            return
        first = project.scenes.order_by("order").first()
        if not first or not first.image:
            return
        try:
            thumb = self.images.generate_image(
                f"Thumbnail for {project.product_snapshot.get('name')}. Keep the product unchanged.",
                reference_images=references or [first.image.path],
                aspect_ratio="9:16",
            )
            asset = VideoAsset(project=project, kind=VideoAsset.Kind.THUMBNAIL, prompt="thumbnail")
            asset.file.save("thumbnail.png", ContentFile(thumb), save=True)
        except GoogleProviderError:
            logger.warning("Thumbnail generation failed for project %s", project.pk)

    def _create_videos(
        self,
        project: VideoProject,
        scenes: list[Scene] | None = None,
        *,
        force: bool = False,
    ) -> None:
        """Scene regeneration and non-Studio clips only.

        A full Studio generate uses generate_continuous_film. Do not call this
        to turn a storyboard into N independent Omni requests.
        """
        from ai.services.generation_metrics import record_scene_timing, set_parallel_window

        studio = is_studio_project(project)
        if studio:
            DirectorService()._align_captions_to_speech(project)
        work = list(scenes or project.scenes.all().order_by("order"))
        if studio:
            for scene in work:
                scene.refresh_from_db()
        total = max(len(work), 1)
        generate_audio = True if studio else not speech_configured()
        self._ensure_presenter_identity(project)
        product_frame = self._product_first_frame(project)
        if not product_frame:
            raise ProviderError("Add a product photo before generating.", retryable=False)
        jobs = []
        for index, scene in enumerate(work, start=1):
            metadata = scene.metadata or {}
            if metadata.get("scene_locked") and not force:
                continue
            if metadata.get("approved") and not metadata.get("needs_regeneration") and not force:
                continue
            if (
                not force
                and media_exists(scene.video_clip)
                and not metadata.get("needs_regeneration")
                and not is_video_fallback(metadata)
                and metadata.get("status") not in {"failed", "qa_failed"}
            ):
                continue
            metadata = {**metadata, "status": "generating", "error": ""}
            scene.metadata = metadata
            scene.generation_status = "running"
            scene.save(update_fields=["metadata", "generation_status"])
            jobs.append(
                {
                    "scene": scene,
                    "index": index,
                    "prompt": self._omni_prompt(project, scene),
                    "duration": self.omni.clamp_duration(int(scene.duration or 5)),
                    "attempt": 0,
                    "task_id": "",
                    "file_id": "",
                    "uri": "",
                    "inline": b"",
                    "download_attempts": 0,
                    "started_at": 0.0,
                    "wall_started": 0.0,
                    "error": None,
                    "image_paths": [],
                }
            )
        if not jobs:
            return
        project.mark_progress(
            VideoProjectStatus.GENERATING_VIDEO,
            64,
            f"Creating {len(jobs)} scene{'s' if len(jobs) != 1 else ''} together",
        )
        one_shot = self.omni.family() == "1.x"
        # Style is copied from the stored analysis. Do not resend the reference file on every scene.
        ref_video = None
        if (
            not one_shot
            and project.reference_video
            and not project.reference_analysis
            and not is_studio_project(project)
        ):
            ref_video = project.reference_video.path
        studio_failures: list[Exception] = []
        concurrency = max(1, min(int(getattr(settings, "VIDEO_SCENE_CONCURRENCY", 6) or 6), 8))
        all_scenes = list(project.scenes.all().order_by("order"))
        scene_by_id = {scene.pk: scene for scene in all_scenes}
        done_ids = {
            scene.pk
            for scene in all_scenes
            if media_exists(scene.video_clip)
            and scene.pk not in {job["scene"].pk for job in jobs}
        }
        last_frame_paths: dict[int, str] = {}

        def needs_continuity(scene: Scene) -> bool:
            return bool((scene.metadata or {}).get("requires_previous_scene_continuity"))

        def previous_scene(scene: Scene) -> Scene | None:
            earlier = [item for item in all_scenes if item.order < scene.order]
            return earlier[-1] if earlier else None

        def refs_for(scene: Scene) -> list[str]:
            previous = previous_scene(scene) if needs_continuity(scene) else None
            previous_frame = ""
            if previous is not None:
                previous_frame = last_frame_paths.get(previous.pk) or ""
                if not previous_frame and media_exists(previous.video_clip):
                    previous_frame = self._extract_final_frame(previous) or ""
                    if previous_frame:
                        last_frame_paths[previous.pk] = previous_frame
            return self._reference_images(
                project,
                previous_frame=previous_frame if needs_continuity(scene) else None,
            )

        def begin(job: dict) -> dict:
            """Start one Omni job. Network-bound; safe under ThreadPoolExecutor."""
            close_old_connections()
            scene = job["scene"]
            job["attempt"] += 1
            job["error"] = None
            job["wall_started"] = time.time()
            try:
                character_id = project.character_config.character_id
            except Exception:
                character_id = ""
            logger.info(
                "MISA VIDEO GENERATION video_id=%s scene_id=%s character_id=%s duration=%s language=%s "
                "aspect_ratio=9:16 provider=%s attempt=%s concurrency=%s continuity=%s",
                project.pk,
                scene.pk,
                character_id or "",
                job["duration"],
                project.language,
                getattr(self.omni, "family", lambda: "omni")(),
                job["attempt"],
                concurrency,
                needs_continuity(scene),
            )
            image_paths = job.get("image_paths") or None
            try:
                task = self.omni.start(
                    job["prompt"],
                    image_path=product_frame,
                    image_paths=None if one_shot else image_paths,
                    video_path=None if one_shot else ref_video,
                    duration_seconds=job["duration"],
                    aspect_ratio="9:16",
                    generate_audio=generate_audio,
                )
            except (ProviderError, MissingAPIKeyError) as exc:
                job["error"] = exc
                job["task_id"] = ""
                return job
            finally:
                close_old_connections()
            job["task_id"] = str(task.get("id") or "")
            job["file_id"] = str(task.get("file_id") or "")
            job["uri"] = str(task.get("uri") or "")
            job["inline"] = task.get("inline") or b""
            job["started_at"] = time.time()
            return job

        def stamp_begin_result(job: dict) -> None:
            scene = job["scene"]
            last_error = job.get("error")
            if last_error:
                self._stamp_pipeline_error(
                    scene,
                    stage="gemini_omni",
                    provider=getattr(last_error, "provider", "") or "omni",
                    error_type=getattr(last_error, "category", "") or "provider_error",
                    retry_count=job["attempt"],
                    detail=str(last_error),
                    code=getattr(last_error, "code", "") or "",
                    status_code=getattr(last_error, "status_code", 0) or 0,
                    request_id=getattr(last_error, "request_id", "") or "",
                    retryable=bool(getattr(last_error, "retryable", False)),
                )
                return
            if job.get("task_id"):
                project.provider_request_id = job["task_id"]
                project.save(update_fields=["provider_request_id", "updated_at"])
                self._remember_omni_file(scene, job)

        remaining = list(jobs)
        pending_batch: list[dict] = []
        wall_started = time.time()

        def predecessor_ready(job: dict, active_ids: set[int]) -> bool:
            if time.time() < float(job.get("retry_after") or 0):
                return False
            scene = job["scene"]
            if not needs_continuity(scene):
                return True
            previous = previous_scene(scene)
            if previous is None or previous.pk in done_ids:
                return True
            return previous.pk not in active_ids

        def launch_ready() -> None:
            nonlocal remaining, pending_batch
            active_ids = {job["scene"].pk for job in remaining} | {job["scene"].pk for job in pending_batch}
            ready_jobs: list[dict] = []
            blocked: list[dict] = []
            for job in remaining:
                if predecessor_ready(job, active_ids):
                    ready_jobs.append(job)
                else:
                    blocked.append(job)
            slots = max(0, concurrency - len(pending_batch))
            take = ready_jobs[:slots]
            remaining = ready_jobs[slots:] + blocked
            if not take:
                return
            for job in take:
                job["image_paths"] = refs_for(job["scene"])
            workers = min(concurrency, len(take))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(begin, job): job for job in take}
                for future in as_completed(futures):
                    raise_if_cancelled(project)
                    job = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        job["error"] = ProviderError(str(exc), retryable=True)
                    stamp_begin_result(job)
            pending_batch.extend(take)

        while remaining or pending_batch:
            raise_if_cancelled(project)
            launch_ready()
            if not pending_batch:
                if remaining:
                    time.sleep(0.05)
                    continue
                break
            still = []
            for job in list(pending_batch):
                scene = job["scene"]
                last_error = job.get("error")
                if not job.get("task_id"):
                    if last_error and (
                        isinstance(last_error, MissingAPIKeyError)
                        or not getattr(last_error, "retryable", False)
                        or job["attempt"] >= 3
                    ):
                        self._finish_failed_scene(
                            project,
                            scene,
                            last_error,
                            studio,
                            "",
                            job["prompt"],
                        )
                        record_scene_timing(
                            project,
                            scene_id=scene.pk,
                            scene_key=scene.scene_key,
                            status="failed",
                            provider="omni",
                            model=(getattr(self.omni, "model", "") if isinstance(getattr(self.omni, "model", None), str) else ""),
                            started_at=job.get("wall_started") or time.time(),
                            completed_at=time.time(),
                        )
                        done_ids.add(scene.pk)
                        studio_failures.append(last_error)
                        continue
                    delay = min(2 ** max(job["attempt"] - 1, 0), 8)
                    job["retry_after"] = time.time() + delay
                    job["task_id"] = ""
                    record_scene_timing(
                        project,
                        scene_id=scene.pk,
                        scene_key=scene.scene_key,
                        status="retrying",
                        provider="omni",
                        model=(getattr(self.omni, "model", "") if isinstance(getattr(self.omni, "model", None), str) else ""),
                        started_at=job.get("wall_started") or time.time(),
                        completed_at=time.time(),
                    )
                    remaining.append(job)
                    continue
                try:
                    if job.get("inline"):
                        state = "completed"
                        finished = {"output_video": {"data": job["inline"]}}
                    elif job.get("file_id"):
                        checker = getattr(self.omni, "check", None)
                        if callable(checker) and hasattr(checker, "__code__"):
                            state, record = checker(job["file_id"])
                        else:
                            record = self.omni.poll(job["file_id"])
                            state = "completed"
                        finished = {"uri": job.get("uri") or "", "file": record}
                    else:
                        checker = getattr(self.omni, "check", None)
                        if callable(checker) and hasattr(checker, "__code__"):
                            raise ProviderError(
                                "Omni did not return a video file. The response had no output_video URI or inline data.",
                                retryable=False,
                                code="MISSING_VIDEO_OUTPUT",
                                provider="omni",
                                request_id=str(job.get("task_id") or ""),
                                category="provider_rejection",
                            )
                        finished = self.omni.poll(job["task_id"])
                        state = "completed"
                except (ProviderError, MissingAPIKeyError) as exc:
                    interaction_id = str(job.get("task_id") or "")
                    self._stamp_pipeline_error(
                        scene,
                        stage="gemini_omni",
                        provider=getattr(exc, "provider", "") or "omni",
                        error_type=getattr(exc, "category", "") or "provider_error",
                        task_id=interaction_id,
                        retry_count=job["attempt"],
                        detail=str(exc),
                        code=getattr(exc, "code", "") or "",
                        status_code=getattr(exc, "status_code", 0) or 0,
                        request_id=getattr(exc, "request_id", "") or interaction_id,
                        retryable=bool(getattr(exc, "retryable", False)),
                    )
                    job["error"] = exc
                    if interaction_id:
                        timed_out = time.time() - job["started_at"] > _omni_wait_seconds()
                        if not getattr(exc, "retryable", False) or timed_out:
                            self._finish_failed_scene(
                                project,
                                scene,
                                exc,
                                studio,
                                interaction_id,
                                job["prompt"],
                            )
                            record_scene_timing(
                                project,
                                scene_id=scene.pk,
                                scene_key=scene.scene_key,
                                status="failed",
                                provider="omni",
                                model=(getattr(self.omni, "model", "") if isinstance(getattr(self.omni, "model", None), str) else ""),
                                started_at=job.get("wall_started") or time.time(),
                                completed_at=time.time(),
                            )
                            done_ids.add(scene.pk)
                            studio_failures.append(exc)
                            continue
                        still.append(job)
                        continue
                    still.append(job)
                    continue
                except Exception:
                    if time.time() - job["started_at"] > _omni_wait_seconds() and job.get("task_id"):
                        timeout = ProviderError("Video generation timed out.", retryable=True)
                        job["error"] = timeout
                        self._finish_failed_scene(
                            project,
                            scene,
                            timeout,
                            studio,
                            str(job.get("task_id") or ""),
                            job["prompt"],
                        )
                        record_scene_timing(
                            project,
                            scene_id=scene.pk,
                            scene_key=scene.scene_key,
                            status="failed",
                            provider="omni",
                            model=(getattr(self.omni, "model", "") if isinstance(getattr(self.omni, "model", None), str) else ""),
                            started_at=job.get("wall_started") or time.time(),
                            completed_at=time.time(),
                        )
                        done_ids.add(scene.pk)
                        studio_failures.append(timeout)
                        continue
                    if time.time() - job["started_at"] > _omni_wait_seconds():
                        job["error"] = ProviderError("Video generation timed out.", retryable=True)
                        job["task_id"] = ""
                    still.append(job)
                    continue
                if state != "completed":
                    if time.time() - job["started_at"] > _omni_wait_seconds() and job.get("task_id"):
                        timeout = ProviderError("Video generation timed out.", retryable=True)
                        job["error"] = timeout
                        self._finish_failed_scene(
                            project,
                            scene,
                            timeout,
                            studio,
                            str(job.get("task_id") or ""),
                            job["prompt"],
                        )
                        record_scene_timing(
                            project,
                            scene_id=scene.pk,
                            scene_key=scene.scene_key,
                            status="failed",
                            provider="omni",
                            model=(getattr(self.omni, "model", "") if isinstance(getattr(self.omni, "model", None), str) else ""),
                            started_at=job.get("wall_started") or time.time(),
                            completed_at=time.time(),
                        )
                        done_ids.add(scene.pk)
                        studio_failures.append(timeout)
                        continue
                    if time.time() - job["started_at"] > _omni_wait_seconds():
                        job["error"] = ProviderError("Video generation timed out.", retryable=True)
                        job["task_id"] = ""
                    still.append(job)
                    continue
                dest: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                        dest = Path(tmp.name)
                    self.omni.save_video(finished, dest)
                    audio_report = probe_media(dest)
                    logger.info(
                        "scene probe scene_id=%s audio_present=%s audio_codec=%s duration=%s video_codec=%s resolution=%sx%s fps=%s file_size=%s",
                        scene.pk,
                        bool(audio_report.get("has_audio")),
                        audio_report.get("audio_codec") or "",
                        audio_report.get("duration"),
                        audio_report.get("video_codec") or "",
                        audio_report.get("width") or "",
                        audio_report.get("height") or "",
                        audio_report.get("fps") or "",
                        dest.stat().st_size if dest.exists() else 0,
                    )
                    if studio and audio_report.get("has_video") and not audio_report.get("has_audio"):
                        raise ProviderError(
                            "Video generation returned no audio stream.",
                            retryable=True,
                            code="VALIDATION_FAILED",
                            category="validation",
                        )
                    payload = dest.read_bytes()
                    prepared = False
                    scene.video_clip.save(
                        f"{scene.scene_key}.mp4",
                        ContentFile(payload),
                        save=True,
                    )
                    task_id = job.get("task_id") or ""
                    metadata = {
                        **(scene.metadata or {}),
                        "omni_interaction_id": task_id,
                        "omni_file_id": job.get("file_id") or (scene.metadata or {}).get("omni_file_id") or "",
                        "generation_id": task_id,
                        "video_fallback": False,
                        "seedance_fallback": False,
                        "needs_regeneration": False,
                        "needs_reassemble": False,
                        "status": "generated",
                        "error": "",
                        "audio": audio_report,
                        "pipeline_error": {},
                        # Only true when FFmpeg actually burned the spoken line onto this clip.
                        "captions_burned": bool(prepared and (scene.caption or "").strip()),
                        "clip_prepared": prepared,
                    }
                    scene.metadata = metadata
                    scene.generation_status = "completed"
                    scene.failure_code = ""
                    scene.failure_message = ""
                    scene.failed_at = None
                    scene.provider = "omni"
                    scene.provider_request_id = task_id
                    scene.save(
                        update_fields=[
                            "metadata",
                            "generation_status",
                            "failure_code",
                            "failure_message",
                            "failed_at",
                            "provider",
                            "provider_request_id",
                        ]
                    )
                    later_needs_frame = any(
                        (item.metadata or {}).get("requires_previous_scene_continuity")
                        for item in all_scenes
                        if item.order > scene.order
                    )
                    if later_needs_frame:
                        frame = self._extract_final_frame(scene)
                        if frame:
                            last_frame_paths[scene.pk] = frame
                    done_ids.add(scene.pk)
                    record_scene_timing(
                        project,
                        scene_id=scene.pk,
                        scene_key=scene.scene_key,
                        status="completed",
                        provider=self._active_video_provider(),
                        model=(getattr(self.omni, "model", "") if isinstance(getattr(self.omni, "model", None), str) else ""),
                        started_at=job.get("wall_started") or time.time(),
                        completed_at=time.time(),
                    )
                    logger.info("Clip created scene_id=%s", scene.pk)
                    logger.info(
                        "Scene completed scene_id=%s interaction_id=%s file_id=%s",
                        scene.pk,
                        task_id,
                        job.get("file_id") or "",
                    )
                    logger.info(
                        "Scene %s generated via video_provider=%s %s",
                        scene.scene_key,
                        self._active_video_provider(),
                        task_id,
                    )
                    record_usage(
                        project=project,
                        provider=self._active_video_provider(),
                        operation="video_scene",
                        request_id=task_id,
                        status="succeeded",
                    )
                    VideoAsset.objects.create(
                        project=project,
                        scene=scene,
                        kind=VideoAsset.Kind.VIDEO,
                        file=scene.video_clip,
                        prompt=job["prompt"],
                        metadata={"fallback": False},
                    )
                except (ProviderError, MissingAPIKeyError) as exc:
                    self._stamp_pipeline_error(
                        scene,
                        stage="gemini_omni",
                        provider=getattr(exc, "provider", "") or "omni",
                        error_type="audio_silent"
                        if "silent" in str(exc).lower() or "audible" in str(exc).lower()
                        else (getattr(exc, "category", "") or "provider_error"),
                        task_id=str(job.get("task_id") or ""),
                        retry_count=job["attempt"],
                        detail=str(exc),
                        code=getattr(exc, "code", "") or "",
                        status_code=getattr(exc, "status_code", 0) or 0,
                        request_id=getattr(exc, "request_id", "") or str(job.get("task_id") or ""),
                        retryable=bool(getattr(exc, "retryable", False)),
                    )
                    job["error"] = exc
                    if getattr(exc, "code", "") == "DOWNLOAD_FAILED" and job.get("task_id"):
                        job["download_attempts"] = int(job.get("download_attempts") or 0) + 1
                        if job["download_attempts"] >= 3:
                            self._finish_failed_scene(
                                project,
                                scene,
                                exc,
                                studio,
                                str(job.get("task_id") or ""),
                                job["prompt"],
                            )
                            record_scene_timing(
                                project,
                                scene_id=scene.pk,
                                scene_key=scene.scene_key,
                                status="failed",
                                provider="omni",
                                model=(getattr(self.omni, "model", "") if isinstance(getattr(self.omni, "model", None), str) else ""),
                                started_at=job.get("wall_started") or time.time(),
                                completed_at=time.time(),
                            )
                            done_ids.add(scene.pk)
                            studio_failures.append(exc)
                            continue
                        still.append(job)
                        continue
                    job["task_id"] = ""
                    still.append(job)
                finally:
                    if dest:
                        dest.unlink(missing_ok=True)
            pending_batch = still
            if pending_batch:
                ready_count = len(jobs) - len(remaining) - len(pending_batch)
                project.mark_progress(
                    VideoProjectStatus.GENERATING_VIDEO,
                    min(64 + int(12 * max(ready_count, 1) / total), 76),
                    f"Creating scenes ({max(ready_count, 0)} of {len(jobs)} ready)",
                )
                interval_fn = getattr(self.omni, "poll_interval", None)
                interval = (
                    interval_fn()
                    if callable(interval_fn) and hasattr(interval_fn, "__code__")
                    else 2
                )
                time.sleep(interval)

        set_parallel_window(
            project,
            wall_ms=int((time.time() - wall_started) * 1000),
            concurrency=concurrency,
            scene_count=len(jobs),
        )

        if studio_failures:
            first = studio_failures[0]
            raise ProviderError(
                str(first),
                retryable=any(getattr(item, "retryable", True) for item in studio_failures),
                code=getattr(first, "code", "") or "",
                status_code=getattr(first, "status_code", 0) or 0,
                provider=getattr(first, "provider", "") or "",
                request_id=getattr(first, "request_id", "") or "",
                category=getattr(first, "category", "") or "",
            ) from first


    def _finish_failed_scene(
        self,
        project: VideoProject,
        scene: Scene,
        last_error: Exception,
        studio: bool,
        last_task_id: str,
        prompt: str,
    ) -> None:
        record_usage(
            project=project,
            provider=self._active_video_provider(),
            operation="video_scene",
            status="failed",
            metadata={"scene_key": scene.scene_key, "error": str(last_error)},
        )
        logger.warning(
            "Video generation failed for project %s scene %s: %s",
            project.pk,
            scene.scene_key,
            last_error,
        )
        silent_error = "audible" in str(last_error).lower() or "silent" in str(last_error).lower()
        first_frame = self._product_first_frame(project)
        dest: Path | None = None
        if not studio and first_frame and not silent_error:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                dest = Path(tmp.name)
            image_to_clip(Path(first_frame), dest, scene.duration or 5)
            payload, prepared = self._prepare_generated_clip(scene, dest)
            scene.video_clip.save(
                f"{scene.scene_key}.mp4",
                ContentFile(payload),
                save=True,
            )
            metadata = {
                **(scene.metadata or {}),
                "video_fallback": True,
                "seedance_fallback": True,
                "needs_regeneration": False,
                "status": "qa_failed",
                "error": str(last_error),
                "audio": inspect_audio(dest),
                "captions_burned": bool((scene.caption or "").strip()),
                "clip_prepared": prepared,
                "pipeline_error": {
                    "stage": "gemini_omni",
                    "scene": scene.scene_key,
                    "provider": "gemini_omni",
                    "error_type": "fallback_still",
                    "task_id": last_task_id,
                    "retry_count": 3,
                    "detail": str(last_error),
                },
            }
            scene.metadata = metadata
            scene.save(update_fields=["metadata"])
            logger.warning("Video fallback still used for %s", scene.scene_key)
            dest.unlink(missing_ok=True)
            VideoAsset.objects.create(
                project=project,
                scene=scene,
                kind=VideoAsset.Kind.VIDEO,
                file=scene.video_clip,
                prompt=prompt,
                metadata={"fallback": True},
            )
            mark_continuity_stale(continuity_dependents(project, scene))
            return
        if scene.video_clip:
            scene.video_clip.delete(save=False)
            scene.video_clip = ""
        metadata = {
            **(scene.metadata or {}),
            "video_fallback": False,
            "seedance_fallback": False,
            "status": "failed",
            "error": scene.failure_message or str(last_error),
        }
        scene.metadata = metadata
        scene.generation_status = "failed"
        if not scene.failure_code:
            scene.failure_code = getattr(last_error, "code", "") or "PROVIDER_REJECTION"
            scene.failure_message = str(last_error)[:500]
            scene.provider = getattr(last_error, "provider", "") or "omni"
            scene.provider_request_id = getattr(last_error, "request_id", "") or last_task_id
        scene.save(
            update_fields=[
                "video_clip",
                "metadata",
                "generation_status",
                "failure_code",
                "failure_message",
                "provider",
                "provider_request_id",
            ]
        )
        mark_continuity_stale(continuity_dependents(project, scene))
        if studio:
            logger.error("Scene %s failed audio/video generation: %s", scene.scene_key, last_error)

    def _block_continuity_scene(self, scene: Scene) -> None:
        meta = dict(scene.metadata or {})
        meta["needs_regeneration"] = True
        meta["continuity_invalid"] = True
        meta["status"] = "ready"
        meta["error"] = "Waiting for the previous scene before this shot can continue."
        scene.metadata = meta
        scene.save(update_fields=["metadata"])

    def _ensure_presenter_identity(self, project: VideoProject) -> None:
        from ai.services.characters import materialize_character_references, uses_master_reference

        materialize_character_references(project)
        try:
            if uses_master_reference(project.character_config):
                existing = presenter_image_paths(project)
                if existing:
                    stamp_presenter_reference(project, existing[0])
                return
        except Exception:
            pass
        if not is_studio_project(project):
            return
        if not presenter_should_appear(project):
            return
        existing = presenter_image_paths(project)
        if existing:
            stamp_presenter_reference(project, existing[0])
            return
        identity = presenter_identity_text(project) or (
            f"{getattr(project, 'speaker_gender', 'female') or 'female'} presenter"
        )
        prompt = (
            "Photorealistic vertical portrait of the same on-camera product presenter who will appear "
            f"in a 9:16 commercial. {identity}. Neutral everyday clothing, natural skin, looking at camera, "
            "head-and-shoulders, soft daylight, no product, no text, no logo, no watermark."
        )
        try:
            image_bytes = self.images.generate_image(prompt, aspect_ratio="3:4")
        except Exception:
            logger.warning("Presenter identity still skipped for project %s", project.pk)
            stamp_presenter_reference(project)
            return
        asset = VideoAsset(
            project=project,
            kind=VideoAsset.Kind.IMAGE,
            prompt="presenter-identity",
            metadata={"presenter_identity": True, "presenter_reference": True, "angle": "front"},
        )
        asset.file.save("presenter-identity.png", ContentFile(image_bytes), save=True)
        stamp_presenter_reference(project, asset.file.path)

    def _prepare_generated_clip(self, scene: Scene, source: Path) -> tuple[bytes, bool]:
        """Burn this scene's caption while the clip is still being generated."""
        from ai.services.captions import spoken_caption

        caption = spoken_caption(scene.narration or "", scene.caption or "").strip()
        if caption and caption != (scene.caption or "").strip():
            scene.caption = caption
            meta = dict(scene.metadata or {})
            meta["on_screen_caption"] = caption
            scene.metadata = meta
            scene.save(update_fields=["caption", "metadata"])
        if not caption and clip_is_assembly_ready(source):
            return source.read_bytes(), True
        ready: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                ready = Path(tmp.name)
            prepare_scene_clip(
                source,
                ready,
                caption=caption,
                duration=probe_duration(source) or scene.duration,
                placement=(scene.metadata or {}).get("caption_placement") or "bottom",
            )
            return ready.read_bytes(), bool(caption)
        except FFmpegError:
            logger.warning("Caption burn failed for scene %s; assembly will retry the story caption", scene.pk)
            return source.read_bytes(), False
        finally:
            if ready:
                ready.unlink(missing_ok=True)

    def _create_voice(self, project: VideoProject) -> None:
        if is_studio_project(project):
            if project.narration_audio:
                project.narration_audio.delete(save=False)
                project.narration_audio = None
                project.save(update_fields=["narration_audio", "updated_at"])
            return
        project.mark_progress(VideoProjectStatus.GENERATING_VOICE, 78, "Recording voice")
        lines = [scene.narration.strip() for scene in project.scenes.all() if scene.narration.strip()]
        text = " ".join(lines)
        if not text:
            return
        if not speech_configured():
            logger.warning(
                "Skipping narration for project %s; Google Speech is not configured",
                project.pk,
            )
            return
        audio = self.speech.synthesize(
            text,
            language=project.language,
            gender=getattr(project, "speaker_gender", "female") or "female",
        )
        project.narration_audio.save("narration.mp3", ContentFile(audio), save=True)
        VideoAsset.objects.create(
            project=project,
            kind=VideoAsset.Kind.AUDIO,
            file=project.narration_audio,
            prompt="narration",
        )

    def _assemble(self, project: VideoProject) -> None:
        studio = is_studio_project(project)
        clips = []
        captions = []
        prepared = []
        for scene in project.scenes.all():
            if studio and is_video_fallback(scene.metadata):
                continue
            if not media_exists(scene.video_clip):
                if scene.video_clip:
                    logger.warning(
                        "Skipping missing clip for project %s scene %s (%s)",
                        project.pk,
                        scene.scene_key,
                        scene.video_clip.name,
                    )
                    scene.video_clip = ""
                    scene.save(update_fields=["video_clip"])
                continue
            clips.append(Path(scene.video_clip.path))
            from ai.services.captions import spoken_caption

            caption_text = spoken_caption(scene.narration or "", scene.caption or "")
            captions.append(
                {
                    "text": caption_text,
                    "duration": scene.duration,
                    "placement": (scene.metadata or {}).get("caption_placement") or "bottom",
                }
            )
            # clip_prepared means the caption was burned during generation. Do not trust
            # captions_burned alone — older jobs set it whenever caption text existed.
            prepared.append(bool((scene.metadata or {}).get("clip_prepared")))
        if not clips:
            raise FFmpegError("No scene clips are ready to assemble.")
        captions_already_burned = bool(prepared) and all(prepared)
        project.mark_progress(VideoProjectStatus.ASSEMBLING, 88, "Joining scenes")
        dest: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                dest = Path(tmp.name)
            audio = None
            if not studio and project.narration_audio:
                audio = Path(project.narration_audio.path)
            assemble_project(
                clips,
                audio,
                captions,
                dest,
                mix_external_audio=bool(audio),
                captions_already_burned=captions_already_burned,
            )
            project.preview_video.save("preview.mp4", ContentFile(dest.read_bytes()), save=True)
            try:
                from ai.services.poster import save_video_poster

                save_video_poster(project, video_path=dest, enhance=False, force=True)
            except Exception:
                logger.exception("First-screen poster was not saved for video %s", project.pk)
            assembled = inspect_audio(dest)
            try:
                from ai.services.ffmpeg import probe_duration

                actual = float(probe_duration(dest) or 0)
            except Exception:
                actual = 0.0
            requested = float(project.duration_seconds or 0)
            tolerance = float(getattr(settings, "DURATION_TOLERANCE_SECONDS", 2.0) or 2.0)
            difference = round(actual - requested, 2) if requested else 0.0
            brief = dict(project.creative_brief or {})
            brief["duration_report"] = {
                "actual_duration": round(actual, 2),
                "requested_duration": requested,
                "duration_difference": difference,
                "within_tolerance": abs(difference) <= tolerance if requested else True,
            }
            project.creative_brief = brief
            update_fields = ["creative_brief", "updated_at"]
            if studio and not assembled.get("audible"):
                project.error_message = assembled.get("reason") or "Assembled video has no audible audio."
                update_fields.append("error_message")
            elif requested and abs(difference) > tolerance:
                project.error_message = (
                    f"Assembled duration is {actual:.1f}s vs requested {requested:.0f}s "
                    f"(difference {difference:+.1f}s)."
                )
                update_fields.append("error_message")
            project.save(update_fields=update_fields)
        except FFmpegError:
            first = project.scenes.filter(video_clip__isnull=False).first()
            if first:
                self._stamp_pipeline_error(
                    first,
                    stage="assembly",
                    provider="ffmpeg",
                    error_type="assembly_failed",
                    detail="Video processing failed during assembly.",
                )
            raise
        finally:
            if dest:
                dest.unlink(missing_ok=True)

    def _quality(self, project: VideoProject) -> None:
        project.mark_progress(VideoProjectStatus.QA_RUNNING, 94, "Checking quality")
        self.qa.run(project)

    def _omni_prompt(self, project: VideoProject, scene: Scene) -> str:
        return compile_scene_prompt(scene, project, provider="gemini_omni")

    def _recommend(self, project: VideoProject) -> None:
        try:
            AmendmentService().recommend(project)
        except Exception:
            logger.exception("Amendment recommendations skipped for project %s", project.pk)

    def _refresh_snapshot(self, project: VideoProject) -> None:
        project.product_snapshot = product_snapshot(project.product, project.product_snapshot)
        project.save(update_fields=["product_snapshot", "updated_at"])

    def _product_first_frame(self, project: VideoProject) -> str | None:
        for item in snapshot_paths(project.product_snapshot or {}):
            path = Path(item)
            if path.exists():
                return str(path)
        try:
            for image in project.product.images.all():
                if image.image and Path(image.image.path).exists():
                    return image.image.path
        except Exception:
            pass
        return None

    def _extract_final_frame(self, scene: Scene) -> str | None:
        """Return a JPEG path for the last frame of a completed scene clip."""
        if not media_exists(scene.video_clip):
            return None
        try:
            from ai.services.ffmpeg import probe_duration, sample_frames

            video_path = Path(scene.video_clip.path)
            if video_path.stat().st_size < 1024:
                return None
            duration = probe_duration(video_path) or float(scene.duration or 0) or 1.0
            if duration <= 0:
                return None
            stamp = max(0.0, duration - 0.12)
            dest_dir = Path(tempfile.mkdtemp(prefix=f"scene-{scene.pk}-frame-"))
            frames = sample_frames(video_path, dest_dir, timestamps=[stamp])
            if frames:
                return str(frames[0][1])
        except Exception:
            logger.warning("Final frame extract failed for scene %s", scene.pk, exc_info=True)
        return None

    def _reference_images(
        self,
        project: VideoProject,
        *,
        previous_frame: str | None = None,
    ) -> list[str]:
        """Product + approved Master Character (or legacy presenter) refs.

        Previous-scene final frames are included only when the caller passes
        previous_frame for a scene that requires continuity.
        """
        product_paths: list[str] = []
        for item in snapshot_paths(project.product_snapshot or {}):
            path = Path(item)
            if path.exists():
                product_paths.append(str(path))
        try:
            for image in project.product.images.all():
                if image.image and Path(image.image.path).exists():
                    product_paths.append(image.image.path)
        except Exception:
            pass
        generate_character = bool((project.creative_brief or {}).get("generate_character"))
        presenter_paths = [] if generate_character else presenter_image_paths(project)
        try:
            from ai.services.characters import master_reference_path, uses_master_reference

            config = None if generate_character else project.character_config
        except Exception:
            config = None
        if config is not None and uses_master_reference(config):
            master = master_reference_path(config)
            unique: list[str] = []
            seen: set[str] = set()
            master_path = str(master) if master else ""
            continuity = [previous_frame] if previous_frame and Path(previous_frame).exists() else []
            ordered = [*product_paths[:1], *([master_path] if master_path else []), *continuity]
            for path in ordered:
                key = str(path)
                if not key or key in seen:
                    continue
                seen.add(key)
                unique.append(key)
            return unique[:4]
        style_paths: list[str] = []
        for asset in project.assets.filter(kind=VideoAsset.Kind.IMAGE).order_by("id"):
            meta = asset.metadata or {}
            if meta.get("qa_frame"):
                continue
            if meta.get("presenter_reference") or meta.get("presenter_identity") or meta.get("presenter_photo"):
                continue
            if not (meta.get("style_reference") or asset.prompt == "style-reference"):
                continue
            if asset.file and Path(asset.file.path).exists():
                style_paths.append(asset.file.path)
        unique: list[str] = []
        seen: set[str] = set()
        continuity = [previous_frame] if previous_frame and Path(previous_frame).exists() else []
        ordered = [
            *product_paths[:1],
            *presenter_paths[:2],
            *continuity,
            *product_paths[1:],
            *style_paths,
        ]
        for path in ordered:
            if path in seen:
                continue
            seen.add(path)
            unique.append(path)
        return unique[:4]

    def _remember_omni_file(self, scene: Scene, job: dict) -> None:
        meta = dict(scene.metadata or {})
        if job.get("task_id"):
            meta["omni_interaction_id"] = job["task_id"]
        if job.get("file_id"):
            meta["omni_file_id"] = job["file_id"]
        scene.metadata = meta
        scene.provider = "omni"
        scene.provider_request_id = str(job.get("task_id") or "")
        scene.save(update_fields=["metadata", "provider", "provider_request_id"])

    def _stamp_pipeline_error(
        self,
        scene: Scene,
        *,
        stage: str,
        provider: str,
        error_type: str,
        task_id: str = "",
        retry_count: int = 0,
        detail: str = "",
        code: str = "",
        status_code: int = 0,
        request_id: str = "",
        retryable: bool = False,
    ) -> None:
        from django.utils import timezone

        from ai.providers.google.omni import sanitize_provider_text

        message = sanitize_provider_text(detail)[:500]
        provider_name = "omni" if "omni" in (provider or "") else (provider or "omni")
        request = (request_id or task_id or "")[:255]
        meta = dict(scene.metadata or {})
        pipeline_error = {
            "stage": stage,
            "scene": scene.scene_key,
            "provider": provider_name,
            "error_type": error_type,
            "task_id": request,
            "retry_count": retry_count,
            "detail": message,
            "code": code,
            "status": status_code,
            "retryable": retryable,
        }
        if meta.get("omni_file_id"):
            pipeline_error["omni_file_id"] = meta["omni_file_id"]
        meta["pipeline_error"] = pipeline_error
        meta["error"] = message
        meta["status"] = "failed"
        scene.metadata = meta
        scene.generation_status = "failed"
        scene.failure_code = (code or "PROVIDER_REJECTION")[:64]
        scene.failure_message = message
        scene.provider = provider_name[:40]
        scene.provider_request_id = request
        scene.failed_at = timezone.now()
        scene.retry_count = retry_count
        scene.save(
            update_fields=[
                "metadata",
                "generation_status",
                "failure_code",
                "failure_message",
                "provider",
                "provider_request_id",
                "failed_at",
                "retry_count",
            ]
        )
        logger.warning(
            "MISA VIDEO GENERATION video_id=%s scene_id=%s provider=%s attempt=%s "
            "provider_response status=%s code=%s message=%s request_id=%s",
            scene.project_id,
            scene.pk,
            provider_name,
            retry_count,
            status_code or "",
            scene.failure_code,
            message,
            request,
        )
