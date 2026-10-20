"""Stop in-flight Studio / Bulk video generation."""

from __future__ import annotations

import logging

from django.utils import timezone

from ai.models import (
    BulkGeneration,
    BulkGenerationStatus,
    BulkItemStatus,
    VideoProject,
    VideoProjectStatus,
)

logger = logging.getLogger(__name__)

CANCEL_MESSAGE = "Stopped by you."
CANCEL_STAGE = "Stopped"

ACTIVE_GENERATION = {
    VideoProjectStatus.QUEUED,
    VideoProjectStatus.ANALYZING,
    VideoProjectStatus.BRIEF_READY,
    VideoProjectStatus.SCRIPT_READY,
    VideoProjectStatus.PLANNING,
    VideoProjectStatus.GENERATING,
    VideoProjectStatus.GENERATING_ASSETS,
    VideoProjectStatus.GENERATING_VIDEO,
    VideoProjectStatus.GENERATING_VOICE,
    VideoProjectStatus.PROCESSING,
    VideoProjectStatus.ASSEMBLING,
    VideoProjectStatus.QA,
    VideoProjectStatus.QA_RUNNING,
    VideoProjectStatus.CORRECTING,
}


class GenerationCancelled(Exception):
    """Raised inside a worker when the merchant stops generation."""


def cancel_requested(project: VideoProject | None) -> bool:
    if project is None:
        return False
    project.refresh_from_db(fields=["status", "error_message", "creative_brief", "stage_label"])
    # A new generate sets QUEUED. A leftover stop flag from the previous run
    # must not cancel that new job or leave Studio spinning.
    if project.status == VideoProjectStatus.QUEUED:
        return False
    brief = project.creative_brief or {}
    if brief.get("cancel_requested"):
        return True
    if project.status == VideoProjectStatus.FAILED and (
        project.error_message == CANCEL_MESSAGE or project.stage_label == CANCEL_STAGE
    ):
        return True
    return False


def clear_generation_cancel(project: VideoProject) -> VideoProject:
    """Drop a previous Stop so the next generate can actually start."""
    brief = dict(project.creative_brief or {})
    if not brief.get("cancel_requested") and not brief.get("cancelled_at"):
        return project
    brief.pop("cancel_requested", None)
    brief.pop("cancelled_at", None)
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])
    return project


def raise_if_cancelled(project: VideoProject) -> None:
    if cancel_requested(project):
        raise GenerationCancelled(CANCEL_MESSAGE)


def _mark_project_stopped(project: VideoProject) -> VideoProject:
    brief = dict(project.creative_brief or {})
    brief["cancel_requested"] = True
    brief["cancelled_at"] = timezone.now().isoformat()
    project.creative_brief = brief
    project.status = VideoProjectStatus.FAILED
    project.error_message = CANCEL_MESSAGE
    project.stage_label = CANCEL_STAGE
    project.save(
        update_fields=["creative_brief", "status", "error_message", "stage_label", "updated_at"]
    )
    for scene in project.scenes.all():
        meta = dict(scene.metadata or {})
        if meta.get("status") in {"generating", "regenerating", "queued"} or scene.generation_status in {
            "running",
            "queued",
        }:
            meta["status"] = "failed"
            meta["error"] = CANCEL_MESSAGE
            meta["needs_regeneration"] = False
            scene.metadata = meta
            scene.generation_status = "failed"
            scene.failure_code = "CANCELLED"
            scene.failure_message = CANCEL_MESSAGE
            scene.save(
                update_fields=[
                    "metadata",
                    "generation_status",
                    "failure_code",
                    "failure_message",
                ]
            )
    return project


def cancel_video_project(project: VideoProject, *, cancel_batch: bool = True) -> list[VideoProject]:
    """Stop one video, and optionally every sibling from the same Studio multi-story batch."""
    targets = [project]
    if cancel_batch:
        brief = project.creative_brief or {}
        batch_id = str(brief.get("bulk_batch_id") or "").strip()
        source_id = brief.get("bulk_source_project_id")
        if batch_id:
            siblings = (
                VideoProject.objects.filter(owner=project.owner, status__in=ACTIVE_GENERATION)
                .exclude(pk=project.pk)
                .filter(creative_brief__bulk_batch_id=batch_id)
            )
            targets.extend(list(siblings))
        elif source_id:
            try:
                source_pk = int(source_id)
            except (TypeError, ValueError):
                source_pk = 0
            if source_pk:
                siblings = (
                    VideoProject.objects.filter(owner=project.owner, status__in=ACTIVE_GENERATION)
                    .exclude(pk=project.pk)
                    .filter(creative_brief__bulk_source_project_id=source_pk)
                )
                targets.extend(list(siblings))

    stopped: list[VideoProject] = []
    seen: set[int] = set()
    for item in targets:
        if item.pk in seen:
            continue
        seen.add(item.pk)
        if item.status in ACTIVE_GENERATION or item.pk == project.pk:
            stopped.append(_mark_project_stopped(item))
            logger.info("Cancelled video generation project_id=%s", item.pk)
    if not stopped:
        stopped.append(_mark_project_stopped(project))
    _drop_queued_tasks([item.pk for item in stopped])
    return stopped


def cancel_bulk_generation(bulk: BulkGeneration) -> BulkGeneration:
    """Stop a Bulk Studio batch: queued + generating items and their video projects."""
    bulk.status = BulkGenerationStatus.CANCELLED
    bulk.completed_at = timezone.now()
    bulk.error_message = CANCEL_MESSAGE
    bulk.save(update_fields=["status", "completed_at", "error_message", "updated_at"])

    stopped_projects: list[VideoProject] = []
    for item in bulk.items.select_related("video_project"):
        if item.status in {
            BulkItemStatus.DRAFT,
            BulkItemStatus.PLANNED,
            BulkItemStatus.QUEUED,
            BulkItemStatus.GENERATING,
        }:
            item.status = BulkItemStatus.CANCELLED
            item.error_message = CANCEL_MESSAGE
            item.completed_at = timezone.now()
            item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        project = item.video_project
        if project and project.status in ACTIVE_GENERATION:
            stopped_projects.append(_mark_project_stopped(project))
    _drop_queued_tasks([project.pk for project in stopped_projects])
    logger.info("Cancelled bulk generation bulk_id=%s", bulk.pk)
    return bulk


def _drop_queued_tasks(project_ids: list[int]) -> None:
    """Best-effort: remove django-q jobs that have not started yet."""
    if not project_ids:
        return
    try:
        from django_q.models import OrmQ
    except Exception:
        return
    try:
        for row in OrmQ.objects.all():
            payload = row.payload() if callable(getattr(row, "payload", None)) else getattr(row, "task", None)
            args = ()
            func = ""
            if isinstance(payload, dict):
                func = str(payload.get("func") or "")
                args = payload.get("args") or ()
            if not args:
                continue
            if args[0] in project_ids and (
                "generate_video_project" in func
                or "generate_bulk_item" in func
                or "regenerate_video_scenes" in func
                or "apply_video_correction" in func
            ):
                row.delete()
    except Exception:
        logger.exception("Unable to drop queued generation tasks")
