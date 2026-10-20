"""Clone one studio project into several videos and enqueue them in parallel."""

from __future__ import annotations

import copy
import uuid

from ai.models import GenderChoice, VideoProject, VideoProjectStatus
from ai.providers.google.omni import require_omni_key
from ai.providers.intelligence import require_intelligence
from ai.services.characters import sync_project_character
from ai.services.director import DirectorService
from ai.services.durations import SUPPORTED_DURATIONS, supported_duration
from ai.services.preflight import preflight_project
from ai.services.snapshots import product_snapshot
from ai.services.style_recipes import MAX_BULK
from ai.tasks import enqueue_video_generation

MAX_STUDIO_BULK = MAX_BULK
DURATION_CYCLE = tuple(SUPPORTED_DURATIONS)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int_ids(values) -> list[int]:
    rows = values if isinstance(values, (list, tuple)) else [values]
    ids: list[int] = []
    seen: set[int] = set()
    for item in rows:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return ids


def _text_ids(values) -> list[str]:
    rows = values if isinstance(values, (list, tuple)) else str(values or "").split(",")
    ids: list[str] = []
    seen: set[str] = set()
    for item in rows:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return ids


def normalize_gender_mode(value: str) -> str:
    raw = str(value or "female").strip().lower().replace(" ", "_")
    if raw in {"male", "all_male", "mall"}:
        return GenderChoice.MALE
    if raw in {"mix", "mixed"}:
        return "mix"
    return GenderChoice.FEMALE


def character_slots(
    character_ids,
    generate_character: bool,
    *,
    ready_ids: list[int] | None = None,
) -> list[dict]:
    ids = _int_ids(character_ids)
    if ready_ids is not None:
        allowed = set(ready_ids)
        ids = [item for item in ids if item in allowed]
    slots = [{"character_id": item, "generate_character": False} for item in ids]
    if generate_character:
        slots.append({"character_id": None, "generate_character": True})
    if not slots:
        raise ValueError("Select a character or check Generate character.")
    return slots


def resolve_bulk_characters(character_ids, generate_character, *, ready_ids, source_generate=False) -> list[dict]:
    """Drop saved characters that have no approved master.

    A character checked on the brief as Generate character, or a selection that
    cannot be used on video, becomes a generated on-camera person.
    """
    requested = _int_ids(character_ids)
    ready = [item for item in requested if item in set(ready_ids or [])]
    generate = _as_bool(generate_character) or bool(source_generate) or (bool(requested) and not ready)
    return character_slots(ready, generate)


def _job_sequence(concepts: list[str], combos: list[dict], target: int) -> list[dict]:
    """Every selected story gets at least one video, then unused story/character combos."""
    if not combos:
        return []
    if target >= len(combos):
        return [dict(combos[index % len(combos)]) for index in range(target)]
    sequence: list[dict] = []
    seen: set[str] = set()
    for combo in combos:
        concept_id = combo["concept_id"]
        if concept_id in seen:
            continue
        sequence.append(dict(combo))
        seen.add(concept_id)
        if len(sequence) >= target:
            return sequence
    leftover = [dict(item) for item in combos if item not in sequence]
    index = 0
    while len(sequence) < target:
        source = leftover or combos
        sequence.append(dict(source[index % len(source)]))
        index += 1
    return sequence


def expand_studio_bulk_jobs(
    *,
    concept_ids,
    character_ids=None,
    generate_character=False,
    gender_mode="female",
    duration_mode="fixed",
    duration_seconds=45,
    count=None,
) -> list[dict]:
    concepts = _text_ids(concept_ids)
    if not concepts:
        raise ValueError("Select at least one concept.")
    slots = character_slots(character_ids, _as_bool(generate_character), ready_ids=None)
    combos = [
        {**slot, "concept_id": concept_id}
        for concept_id in concepts
        for slot in slots
    ]
    try:
        requested = int(count) if count not in (None, "") else len(combos)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose how many videos to generate.") from exc
    if requested < 1:
        raise ValueError("Generate at least one video.")
    target = max(requested, len(concepts))
    if target > MAX_STUDIO_BULK:
        raise ValueError(f"Create up to {MAX_STUDIO_BULK} videos at a time.")

    mode = str(duration_mode or "fixed").strip().lower()
    mix_duration = mode == "mix"
    duration = 0 if mix_duration else supported_duration(duration_seconds)
    gender = normalize_gender_mode(gender_mode)
    genders = [GenderChoice.FEMALE, GenderChoice.MALE] if gender == "mix" else [gender]
    durations = list(DURATION_CYCLE) if mix_duration else [duration]

    jobs = []
    for index, combo in enumerate(_job_sequence(concepts, combos, target)):
        combo["index"] = index
        combo["gender"] = genders[index % len(genders)]
        combo["duration"] = durations[index % len(durations)]
        jobs.append(combo)
    return jobs


def _clone_source(source: VideoProject, job: dict, batch_id: str) -> VideoProject:
    brief = copy.deepcopy(source.creative_brief or {})
    brief.pop("cancel_requested", None)
    brief.pop("cancelled_at", None)
    brief.pop("generation_metrics", None)
    brief["duration"] = job["duration"]
    brief["generate_character"] = bool(job.get("generate_character"))
    brief["bulk_batch_id"] = batch_id
    brief["bulk_source_project_id"] = source.pk
    brief["bulk_job_index"] = job["index"]
    if job.get("seedance_model"):
        brief["seedance_model"] = job["seedance_model"]
        brief["video_model"] = job["seedance_model"]
    elif job.get("video_model"):
        brief["seedance_model"] = job["video_model"]
        brief["video_model"] = job["video_model"]
    if job.get("generate_character"):
        brief.pop("character_id", None)
        presenter = dict(brief.get("presenter") or {})
        presenter.pop("character_id", None)
        presenter["mode"] = "generated"
        look = str(presenter.get("look") or "")
        if "reference identity" in look.lower() or "preserve exact face" in look.lower():
            presenter["look"] = ""
        brief["presenter"] = presenter
    elif job.get("character_id"):
        brief["character_id"] = job["character_id"]
        brief["generate_character"] = False
    return VideoProject.objects.create(
        owner=source.owner,
        product=source.product,
        product_snapshot=product_snapshot(source.product, source.product_snapshot),
        language=source.language,
        speaking_style=source.speaking_style,
        speaker_gender=job["gender"],
        duration_seconds=job["duration"],
        reference_url=source.reference_url,
        merchant_instructions=source.merchant_instructions,
        product_analysis=copy.deepcopy(source.product_analysis or {}),
        reference_analysis=copy.deepcopy(source.reference_analysis or {}),
        creative_brief=brief,
        creative_directions=copy.deepcopy(source.creative_directions or []),
        status=VideoProjectStatus.DRAFT,
        stage_label="Preparing bulk video",
        progress=2,
    )


def _bind_character(project: VideoProject, job: dict) -> None:
    if job.get("generate_character") or not job.get("character_id"):
        return
    from ai.models import Character

    character = Character.objects.filter(pk=job["character_id"], owner=project.owner).first()
    gender = (character.gender if character else "") or job["gender"]
    project.speaker_gender = gender
    project.save(update_fields=["speaker_gender", "updated_at"])
    sync_project_character(
        project,
        job["character_id"],
        language=project.language,
        tone=project.speaking_style,
        gender=gender,
    )


def bulk_generate_from_studio(source: VideoProject, payload: dict) -> list[VideoProject]:
    require_intelligence()
    require_omni_key()
    if not (source.creative_directions or []):
        raise ValueError("Create concepts before generating videos.")
    raw_character_ids = payload.get("character_ids") or payload.get("characters")
    from ai.models import Character, CharacterStatus
    from ai.services.master_character import character_is_video_ready

    ready_ids = []
    for character_id in _int_ids(raw_character_ids):
        character = Character.objects.filter(
            pk=character_id,
            owner=source.owner,
            status=CharacterStatus.ACTIVE,
        ).first()
        if character and character_is_video_ready(character):
            ready_ids.append(character.pk)
    source_generate = bool((source.creative_brief or {}).get("generate_character"))
    generate_character = (
        _as_bool(payload.get("generate_character"))
        or source_generate
        or (bool(_int_ids(raw_character_ids)) and not ready_ids)
    )
    seedance_model = str(
        payload.get("seedance_model") or payload.get("video_model") or payload.get("model") or ""
    ).strip()
    if seedance_model:
        from ai.providers.seedance import resolve_seedance_model

        seedance_model = resolve_seedance_model(seedance_model)
    jobs = expand_studio_bulk_jobs(
        concept_ids=payload.get("concept_ids") or payload.get("concepts"),
        character_ids=ready_ids,
        generate_character=generate_character,
        gender_mode=payload.get("gender_mode") or payload.get("gender") or source.speaker_gender,
        duration_mode=payload.get("duration_mode"),
        duration_seconds=payload.get("duration_seconds") or payload.get("duration") or source.duration_seconds,
        count=payload.get("count") or payload.get("video_count"),
    )
    if seedance_model:
        for job in jobs:
            job["seedance_model"] = seedance_model
            job["video_model"] = seedance_model
    available = {str(item.get("id") or "") for item in (source.creative_directions or [])}
    missing = [job["concept_id"] for job in jobs if job["concept_id"] not in available]
    if missing:
        raise ValueError("Choose concepts from this project's story list.")

    director = DirectorService()
    batch_id = uuid.uuid4().hex[:12]
    created: list[VideoProject] = []
    failures: list[str] = []
    queued_ids: list[int] = []
    for job in jobs:
        project = _clone_source(source, job, batch_id)
        try:
            _bind_character(project, job)
            project.refresh_from_db()
            director.select_concept(project, job["concept_id"])
            project.refresh_from_db()
            project.product_snapshot = product_snapshot(project.product, project.product_snapshot)
            from ai.services.characters import refresh_unfrozen_character_snapshot

            refresh_unfrozen_character_snapshot(project)
            project.refresh_from_db()
            preflight_project(project)
            from django.utils import timezone as dj_tz

            brief = dict(project.creative_brief or {})
            brief["queued_at"] = dj_tz.now().isoformat()
            metrics = dict(brief.get("generation_metrics") or {})
            metrics["queued_at"] = brief["queued_at"]
            if job.get("seedance_model"):
                brief["seedance_model"] = job["seedance_model"]
                brief["video_model"] = job["seedance_model"]
                metrics["video_model"] = job["seedance_model"]
            brief["generation_metrics"] = metrics
            project.creative_brief = brief
            project.status = VideoProjectStatus.QUEUED
            project.stage_label = "Preparing director plan"
            project.progress = 4
            project.error_message = ""
            project.save(
                update_fields=["creative_brief", "status", "stage_label", "progress", "error_message", "updated_at"]
            )
            queued_ids.append(project.pk)
            created.append(project)
        except Exception as exc:
            message = str(exc).split("\n")[0][:500] or "This bulk video could not start."
            if getattr(project, "pk", None):
                project.mark_failed(message)
                project.refresh_from_db()
                created.append(project)
            failures.append(message)
    for project_id in queued_ids:
        enqueue_video_generation(project_id)
    if not created:
        raise ValueError(failures[0] if failures else "Unable to start bulk generation.")
    return created
