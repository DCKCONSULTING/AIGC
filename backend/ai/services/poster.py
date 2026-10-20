"""Capture a first-screen poster after a video is assembled."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile

from ai.exceptions import GoogleProviderError
from ai.models import VideoProject
from ai.services.director import media_exists
from ai.services.ffmpeg import FFmpegError, extract_first_frame

logger = logging.getLogger(__name__)

POSTER_PROMPT = (
    "Create a 9:16 first-screen poster that matches this exact opening video frame. "
    "Keep the person, product, clothing, lighting, and background unchanged. "
    "Do not add text, logos, or extra objects."
)


def project_video_path(project: VideoProject) -> Path | None:
    for field in (project.export_file, project.final_video, project.preview_video):
        if field and media_exists(field):
            try:
                return Path(field.path)
            except Exception:
                continue
    return None


def save_video_poster(
    project: VideoProject,
    *,
    video_path: Path | None = None,
    enhance: bool = True,
    force: bool = False,
) -> bool:
    if project.poster and media_exists(project.poster) and not force:
        return True
    source = Path(video_path) if video_path else project_video_path(project)
    if source is None or not source.exists():
        return False
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        dest = Path(tmp.name)
    try:
        extract_first_frame(source, dest)
        payload = dest.read_bytes()
        if enhance:
            payload = _gemini_poster(dest) or payload
        project.poster.save("poster.jpg", ContentFile(payload), save=True)
        return True
    except FFmpegError:
        logger.warning("First-screen capture failed for video %s", project.pk)
        return False
    except Exception:
        logger.exception("First-screen poster failed for video %s", project.pk)
        return False
    finally:
        dest.unlink(missing_ok=True)


def _gemini_poster(frame_path: Path) -> bytes | None:
    try:
        from ai.providers.google.nano_banana import NanoBananaProvider

        return NanoBananaProvider().generate_image(
            POSTER_PROMPT,
            reference_images=[frame_path],
            aspect_ratio="9:16",
        )
    except (GoogleProviderError, Exception):
        logger.warning("Gemini first-screen poster fell back to the extracted frame")
        return None


def backfill_video_posters(*, enhance: bool = False, limit: int | None = None) -> int:
    from django.db.models import Q

    rows = VideoProject.objects.filter(poster="").filter(
        Q(preview_video__gt="") | Q(final_video__gt="") | Q(export_file__gt="")
    )
    if limit:
        rows = rows[:limit]
    saved = 0
    for project in rows.iterator():
        if save_video_poster(project, enhance=enhance, force=False):
            saved += 1
    return saved
