"""Structured timing for Studio / Omni video generation."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

from django.utils import timezone

_brief_lock = threading.Lock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def ensure_metrics(project) -> dict:
    brief = dict(project.creative_brief or {})
    metrics = dict(brief.get("generation_metrics") or {})
    if "scenes" not in metrics or not isinstance(metrics.get("scenes"), list):
        metrics["scenes"] = []
    if "started_at" not in metrics:
        metrics["started_at"] = timezone.now().isoformat()
    brief["generation_metrics"] = metrics
    project.creative_brief = brief
    return metrics


def persist_metrics(project, metrics: dict) -> None:
    brief = dict(project.creative_brief or {})
    brief["generation_metrics"] = metrics
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])


@contextmanager
def timed_phase(project, phase_key: str) -> Iterator[dict]:
    metrics = ensure_metrics(project)
    started = _now_ms()
    metrics[f"{phase_key}_started_ms"] = started
    metrics[f"{phase_key}_started_at"] = timezone.now().isoformat()
    persist_metrics(project, metrics)
    try:
        yield metrics
    finally:
        ended = _now_ms()
        metrics = ensure_metrics(project)
        metrics[f"{phase_key}_ms"] = max(0, ended - started)
        metrics[f"{phase_key}_ended_ms"] = ended
        metrics[f"{phase_key}_finished_at"] = timezone.now().isoformat()
        persist_metrics(project, metrics)


def mark_total(project) -> dict:
    metrics = ensure_metrics(project)
    started = int(metrics.get("project_creation_started_ms") or metrics.get("script_generation_started_ms") or _now_ms())
    if "project_creation_started_ms" not in metrics:
        metrics["project_creation_started_ms"] = started
    metrics["total_generation_ms"] = max(0, _now_ms() - started)
    metrics["total_generation_seconds"] = round(metrics["total_generation_ms"] / 1000, 3)
    metrics["completed_at"] = timezone.now().isoformat()
    metrics["generation_finished_at"] = metrics["completed_at"]
    if metrics.get("started_at"):
        metrics["generation_started_at"] = metrics["started_at"]
    persist_metrics(project, metrics)
    return metrics


def _safe_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def record_scene_timing(
    project,
    *,
    scene_id: int,
    scene_key: str,
    status: str,
    provider: str = "omni",
    model: str = "",
    started_at: float | None = None,
    completed_at: float | None = None,
    duration_ms: int | None = None,
) -> None:
    metrics = ensure_metrics(project)
    rows = list(metrics.get("scenes") or [])
    started = started_at or time.time()
    completed = completed_at or time.time()
    elapsed = duration_ms if duration_ms is not None else int(max(0, (completed - started) * 1000))
    row = {
        "scene_id": int(scene_id),
        "scene_key": _safe_text(scene_key),
        "started_at": timezone.datetime.fromtimestamp(started, tz=timezone.get_current_timezone()).isoformat(),
        "completed_at": timezone.datetime.fromtimestamp(completed, tz=timezone.get_current_timezone()).isoformat(),
        "duration_ms": elapsed,
        "status": _safe_text(status),
        "provider": _safe_text(provider),
        "model": _safe_text(model),
    }
    rows = [item for item in rows if item.get("scene_id") != scene_id]
    rows.append(row)
    metrics["scenes"] = rows
    scene_total = sum(int(item.get("duration_ms") or 0) for item in rows)
    metrics["scene_generation_total_ms"] = scene_total
    persist_metrics(project, metrics)


def record_omni_request(project, row: dict) -> None:
    """Append one Omni create to the job timeline. Values are scalars only."""
    with _brief_lock:
        project.refresh_from_db(fields=["creative_brief"])
        _record_omni_request_unlocked(project, row)


def _record_omni_request_unlocked(project, row: dict) -> None:
    metrics = ensure_metrics(project)
    rows = list(metrics.get("omni_requests") or [])
    clean = {}
    for key, value in row.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
    rows.append(clean)
    metrics["omni_requests"] = rows
    metrics["omni_request_count"] = len(rows)
    durations = [int(item.get("omni_generation_duration_ms") or 0) for item in rows]
    metrics["omni_generation_duration_ms"] = sum(durations)
    persist_metrics(project, metrics)


def record_span(project, key: str, elapsed_ms: int) -> None:
    with _brief_lock:
        project.refresh_from_db(fields=["creative_brief"])
        metrics = ensure_metrics(project)
        metrics[key] = max(0, int(elapsed_ms))
        persist_metrics(project, metrics)


def set_parallel_window(project, *, wall_ms: int, concurrency: int, scene_count: int) -> None:
    metrics = ensure_metrics(project)
    metrics["scene_generation_parallel_ms"] = max(0, int(wall_ms))
    metrics["scene_concurrency"] = int(concurrency)
    metrics["scene_count"] = int(scene_count)
    persist_metrics(project, metrics)
