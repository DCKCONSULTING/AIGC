from __future__ import annotations

import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)


def generate_video_project(project_id: int) -> None:
    from ai.services.video import VideoGenerationService

    VideoGenerationService().run(project_id)


def apply_video_correction(project_id: int, parsed: dict) -> None:
    from ai.models import VideoProject
    from ai.services.video import VideoGenerationService

    project = VideoProject.objects.get(pk=project_id)
    VideoGenerationService().apply_correction(project, parsed)


def enqueue_video_generation(project_id: int) -> None:
    _enqueue(generate_video_project, project_id)


def enqueue_video_correction(project_id: int, parsed: dict) -> None:
    _enqueue(apply_video_correction, project_id, parsed)


def regenerate_video_scenes(project_id: int, scene_ids: list[int]) -> None:
    from ai.services.video import VideoGenerationService

    VideoGenerationService().regenerate_scenes(project_id, scene_ids)


def enqueue_scene_regeneration(project_id: int, scene_ids: list[int]) -> None:
    _enqueue(regenerate_video_scenes, project_id, scene_ids)


def generate_bulk_item(item_id: int) -> None:
    from ai.services.bulk_studio import BulkVideoGenerationService

    BulkVideoGenerationService().run_item(item_id)


def enqueue_bulk_item(item_id: int) -> None:
    _enqueue(generate_bulk_item, item_id)


def generate_video_poster(project_id: int, enhance: bool = False) -> None:
    from ai.models import VideoProject
    from ai.services.poster import save_video_poster

    project = VideoProject.objects.filter(pk=project_id).first()
    if project:
        save_video_poster(project, enhance=enhance, force=False)


def enqueue_video_poster(project_id: int, enhance: bool = False) -> None:
    _enqueue(generate_video_poster, project_id, enhance)


def enqueue_missing_video_posters(limit: int = 12) -> None:
    from ai.models import VideoProject

    from django.db.models import Q

    rows = (
        VideoProject.objects.filter(poster="")
        .filter(Q(preview_video__gt="") | Q(final_video__gt="") | Q(export_file__gt=""))
        .order_by("-updated_at")
        .values_list("id", flat=True)[:limit]
    )
    for project_id in rows:
        enqueue_video_poster(project_id, False)


def _enqueue(func, *args) -> None:
    if getattr(settings, "AI_SYNC_TASKS", False):
        func(*args)
        return
    try:
        from django_q.tasks import async_task

        async_task(f"{func.__module__}.{func.__name__}", *args)
        return
    except Exception:
        logger.exception("django-q enqueue failed; running AI job in a background thread")
    thread = threading.Thread(target=_safe_run, args=(func, args), daemon=True)
    thread.start()


def _safe_run(func, args) -> None:
    try:
        func(*args)
    except Exception:
        logger.exception("Background AI job failed")
