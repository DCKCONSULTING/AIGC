"""Orchestrate many Studio videos without replacing VideoGenerationService."""

from __future__ import annotations

import copy
import logging
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from ai.exceptions import MissingAPIKeyError, ProviderError
from ai.models import (
    BulkGeneration,
    BulkGenerationItem,
    BulkGenerationMode,
    BulkGenerationStatus,
    BulkItemStatus,
    Character,
    CharacterStatus,
    LanguageChoice,
    StyleChoice,
    VideoProject,
    VideoProjectStatus,
)
from ai.providers.google.omni import require_omni_key
from ai.providers.intelligence import IntelligenceClient, require_intelligence
from ai.services.characters import CharacterError, sync_project_character
from ai.services.director import DirectorService, _retarget_timeline, commercial_cta, normalize_brief
from ai.services.durations import scene_count_for_duration, supported_duration
from ai.services.preflight import PreflightError, preflight_project
from ai.services.reference import ReferenceAnalysisService
from ai.services.snapshots import generation_blocker, product_snapshot
from ai.services.script import LANGUAGE_GUIDE, speech_lock
from ai.services.style_recipes import MAX_BULK
from brands.models import Product

logger = logging.getLogger(__name__)

MAX_BULK_VIDEOS = MAX_BULK
REFERENCE_MODES = {
    BulkGenerationMode.REFERENCE_LOCATION,
    BulkGenerationMode.REFERENCE_CHARACTER,
}
SAME_FLOW_MODES = {BulkGenerationMode.EXISTING_VIDEO}
PLAN_EDIT_STATUSES = {BulkGenerationStatus.DRAFT, BulkGenerationStatus.PLAN_READY}
BUSY_STATUSES = {BulkGenerationStatus.QUEUED, BulkGenerationStatus.GENERATING}
# Mode / pipeline labels that must never become spoken dialogue or visual copy.
WORKFLOW_LABEL_TOKENS = (
    "bulk existing video",
    "existing_video",
    "existing video",
    "master_spec",
    "master spec",
    "reference_location",
    "reference_character",
    "bulk_generation",
    "bulk generation",
    "bulk mode",
    "from_project",
    "generation_plan",
)
ACTIVE_PROJECT_STATUSES = {
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
VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".m4v", ".avi")

MODE_CONSTRAINTS = {
    BulkGenerationMode.CHARACTER: {
        "locked": {
            "character": True,
            "product": True,
            "brand": True,
            "voice": True,
            "price": True,
            "cta": True,
        },
        "variables": {
            "story": True,
            "location": True,
            "action": True,
            "camera": True,
            "hook": True,
            "environment": True,
        },
    },
    BulkGenerationMode.PRODUCT: {
        "locked": {
            "product": True,
            "product_appearance": True,
            "price": True,
            "cta": True,
            "brand": True,
            "offer": True,
        },
        "variables": {
            "story": True,
            "hook": True,
            "location": True,
            "action": True,
            "camera": True,
            "environment": True,
        },
    },
    BulkGenerationMode.EXISTING_VIDEO: {
        "locked": {
            "story": True,
            "scenes": True,
            "script": True,
            "dialogue": True,
            "timing": True,
            "cta": True,
            "product": True,
            "duration": True,
        },
        "variables": {
            "location": True,
            "character": False,
            "product": False,
            "story": False,
        },
    },
    BulkGenerationMode.REFERENCE_LOCATION: {
        "locked": {
            "story": True,
            "scenes": True,
            "character": True,
            "dialogue": True,
            "timing": True,
            "camera": True,
            "product": True,
            "cta": True,
        },
        "variables": {"location": True, "environment": True},
    },
    BulkGenerationMode.REFERENCE_CHARACTER: {
        "locked": {
            "story": True,
            "scenes": True,
            "dialogue": True,
            "timing": True,
            "camera": True,
            "location": True,
            "product": True,
            "cta": True,
        },
        "variables": {"character": True},
    },
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "variations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sequence": {"type": "integer"},
                    "title": {"type": "string"},
                    "location": {"type": "string"},
                    "hook": {"type": "string"},
                    "story": {"type": "string"},
                    "action": {"type": "string"},
                    "camera": {"type": "string"},
                    "environment": {"type": "string"},
                    "locked_elements": {"type": "array", "items": {"type": "string"}},
                    "variable_elements": {"type": "array", "items": {"type": "string"}},
                    "scenes": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["title"],
            },
        }
    },
    "required": ["variations"],
}

MASTER_SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "story": {"type": "string"},
        "cta": {"type": "string"},
        "location": {"type": "string"},
        "hook": {"type": "string"},
        "camera_intent": {"type": "string"},
        "character_notes": {"type": "string"},
        "scenes": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["story", "scenes"],
}

LOCATION_SEEDS = (
    "modern bathroom",
    "sunlit bedroom",
    "bright kitchen",
    "home garden",
    "neighbourhood cafe",
    "small office desk",
    "clean studio set",
    "quiet beach path",
    "city apartment balcony",
    "local convenience store",
)

STORY_SEEDS = (
    "Morning routine",
    "Getting ready",
    "Product demonstration",
    "Outdoor lifestyle",
    "UGC testimonial",
    "Problem and solution",
    "Close-up proof",
    "Everyday lifestyle",
    "Before and after",
    "Offer and CTA",
)


def bulk_concurrency() -> int:
    return max(1, min(int(getattr(settings, "BULK_VIDEO_CONCURRENCY", 3) or 3), 8))


def default_constraints(mode: str) -> dict:
    return copy.deepcopy(MODE_CONSTRAINTS.get(mode) or MODE_CONSTRAINTS[BulkGenerationMode.PRODUCT])


def contains_workflow_label(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in WORKFLOW_LABEL_TOKENS)


def scrub_workflow_text(text: str, *, fallback: str = "") -> str:
    """Drop internal workflow labels from creative fields; keep real marketing copy."""
    import re

    value = str(text or "").strip()
    if not value:
        return str(fallback or "").strip()
    if contains_workflow_label(value):
        cleaned = value
        for token in WORKFLOW_LABEL_TOKENS:
            cleaned = re.sub(re.escape(token), " ", cleaned, flags=re.I)
        cleaned = " ".join(cleaned.split()).strip(" ·-–,")
        if cleaned and not contains_workflow_label(cleaned):
            return cleaned
        return str(fallback or "").strip()
    return value


def creative_title_for_bulk(product_name: str, count: int) -> str:
    name = scrub_workflow_text(product_name, fallback="Product") or "Product"
    return f"{name} · {max(1, int(count))} videos"[:160]


def _scale_scene_timings(scenes: list[dict], duration: int) -> list[dict]:
    """Keep scene count and creative copy; stretch/compress timings to the target length."""
    rows = [dict(item) for item in scenes if isinstance(item, dict)]
    if not rows:
        return []
    target = max(1, int(duration))
    total = sum(max(0.1, float(item.get("duration") or 0)) for item in rows) or float(len(rows))
    scale = target / total
    cursor = 0.0
    fitted: list[dict] = []
    for index, item in enumerate(rows, start=1):
        scene = dict(item)
        if index == len(rows):
            scene_duration = round(max(1.0, target - cursor), 2)
        else:
            scene_duration = round(max(1.0, float(item.get("duration") or (target / len(rows))) * scale), 2)
        scene["order"] = index
        scene["scene_key"] = str(item.get("scene_key") or f"scene-{index}")[:64]
        scene["duration"] = scene_duration
        scene["start_time"] = cursor
        scene["end_time"] = round(cursor + scene_duration, 2)
        fitted.append(scene)
        cursor = scene["end_time"]
    return fitted


def master_spec_from_project(project: VideoProject, *, locks=None, variables=None) -> dict:
    """Copy the Studio storyboard so bulk children reuse the same creative flow."""
    director = DirectorService()
    scenes = [director.scene_to_timeline(scene) for scene in project.scenes.all().order_by("order")]
    brief = project.creative_brief or {}
    script = project.script or {}
    first = scenes[0] if scenes else {}
    location = str(brief.get("location") or first.get("location") or first.get("background") or "")
    return {
        "from_project": True,
        "source_video_id": project.pk,
        "duration": project.duration_seconds,
        "language": project.language,
        "scene_count": len(scenes),
        "scenes": scenes,
        "story": str(script.get("narrative") or brief.get("main_benefit") or project.merchant_instructions or ""),
        "cta": str(script.get("cta") or brief.get("cta") or ""),
        "location": location,
        "hook": str(script.get("hook") or brief.get("hook") or first.get("title") or ""),
        "camera_intent": str((brief.get("continuity_state") or {}).get("camera_style") or first.get("camera_framing") or ""),
        "character_notes": str(brief.get("continuity_state", {}).get("presenter_appearance") or ""),
        "locked": dict(locks or {}),
        "variables": dict(variables or {}),
        "analysis": {
            "from_project": True,
            "duration": project.duration_seconds,
            "scene_count": len(scenes),
            "location": location,
            "cta": str(script.get("cta") or brief.get("cta") or ""),
            "visual_style": str((brief.get("continuity_state") or {}).get("visual_style") or brief.get("style") or ""),
            "presenter": str(brief.get("continuity_state", {}).get("presenter_appearance") or ""),
            "pacing": str(first.get("pace") or ""),
            "flow": [
                {
                    "order": item.get("order"),
                    "title": item.get("title") or f"Scene {item.get('order')}",
                    "purpose": item.get("scene_role") or item.get("title") or "",
                    "duration": item.get("duration"),
                    "script": item.get("voice_over") or item.get("narration") or "",
                }
                for item in scenes
            ],
        },
    }


def _int_ids(values) -> list[int]:
    rows = values if isinstance(values, (list, tuple)) else str(values or "").split(",")
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


def _bool_map(raw, allowed: dict) -> dict:
    data = raw if isinstance(raw, dict) else {}
    out = {}
    for key, default in allowed.items():
        if key in data:
            value = data[key]
            if isinstance(value, bool):
                out[key] = value
            else:
                out[key] = str(value or "").strip().lower() in {"1", "true", "yes", "on"}
        else:
            out[key] = default
    return out


def _validate_reference_upload(upload) -> None:
    if upload is None:
        raise ValueError("Upload a reference video.")
    name = (getattr(upload, "name", "") or "").lower()
    content = (getattr(upload, "content_type", "") or "").lower()
    if content.startswith("video/") or name.endswith(VIDEO_EXTENSIONS):
        return
    raise ValueError("Upload an MP4, MOV, or WebM reference video.")


def _source_library_video(owner, payload) -> tuple[VideoProject, object] | None:
    raw = payload.get("source_video_id") or payload.get("source_video")
    if not raw:
        return None
    try:
        pk = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a valid source video.") from exc
    project = VideoProject.objects.filter(pk=pk, owner=owner).first()
    if not project:
        raise ValueError("That source video was not found.")
    for field in (project.export_file, project.final_video, project.preview_video):
        if field and getattr(field, "name", ""):
            return project, field
    raise ValueError("That video is not ready to use as a reference yet.")


def _attach_library_reference(bulk: BulkGeneration, field) -> None:
    filename = os.path.basename(getattr(field, "name", "") or "") or f"source-{bulk.pk}.mp4"
    field.open("rb")
    try:
        bulk.reference_video.save(filename, ContentFile(field.read()), save=True)
    finally:
        field.close()


def _character_from_project(project: VideoProject):
    try:
        config = project.character_config
    except Exception:
        config = None
    if config is not None and config.character_id:
        return config.character
    brief = project.creative_brief or {}
    raw = brief.get("character_id") or (brief.get("presenter") or {}).get("character_id")
    if not raw:
        return None
    return Character.objects.filter(pk=raw).first()


def _instruction_from_payload(payload: dict | None) -> str:
    if not payload:
        return ""
    return str(payload.get("instruction") or payload.get("instructions") or "").strip()


def instruction_requirement(bulk: BulkGeneration) -> str:
    extra = str(getattr(bulk, "instruction", "") or "").strip()
    if not extra:
        return ""
    return (
        "SOURCE OF TRUTH instruction from the merchant. This field is optional, "
        "but when present every story, hook, scene, voice-over, and CTA MUST follow it. "
        "Do not ignore, weaken, or invent a conflicting story:\n"
        f"{extra}"
    )


class BulkVideoGenerationService:
    def __init__(self, intelligence: IntelligenceClient | None = None):
        self.intelligence = intelligence or IntelligenceClient()
        self.reference = ReferenceAnalysisService(self.intelligence)
        self.director = DirectorService(self.intelligence)

    def _set_instruction(self, bulk: BulkGeneration, payload: dict | None) -> None:
        if not payload or ("instruction" not in payload and "instructions" not in payload):
            return
        next_value = _instruction_from_payload(payload)
        if next_value == (bulk.instruction or ""):
            return
        bulk.instruction = next_value
        bulk.save(update_fields=["instruction", "updated_at"])

    def create(self, owner, payload: dict, files=None) -> BulkGeneration:
        mode = str(payload.get("mode") or "").strip()
        if mode not in BulkGenerationMode.values:
            raise ValueError("Choose a Bulk Studio mode.")
        product = payload.get("product")
        if not isinstance(product, Product):
            raise ValueError("Select a product.")
        if product.brand.owner_id != owner.id:
            raise ValueError("This product belongs to a different company.")
        snapshot = product_snapshot(product)
        blocker = generation_blocker(snapshot)
        if blocker:
            raise ValueError(blocker)

        character = payload.get("character")
        character_ids = _int_ids(payload.get("character_ids"))
        if mode == BulkGenerationMode.CHARACTER:
            character = self._owned_character(owner, getattr(character, "pk", payload.get("character_id")), product)
        elif character or payload.get("character_id"):
            character = self._owned_character(
                owner, getattr(character, "pk", None) or payload.get("character_id"), product
            )
        else:
            character = None

        if mode == BulkGenerationMode.REFERENCE_CHARACTER:
            character_ids = [
                self._owned_character(owner, item, product).pk for item in character_ids
            ]
            if not character_ids:
                raise ValueError("Select the characters that should appear in these videos.")

        try:
            count = int(payload.get("requested_count") or payload.get("count") or len(character_ids) or 10)
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose how many videos to generate.") from exc
        if mode == BulkGenerationMode.REFERENCE_CHARACTER:
            count = len(character_ids)
        if count < 1:
            raise ValueError("Generate at least one video.")
        if count > MAX_BULK_VIDEOS:
            raise ValueError(f"Create up to {MAX_BULK_VIDEOS} videos at a time.")

        language = str(payload.get("language") or LanguageChoice.CONVERSATIONAL_BM)
        if language not in LanguageChoice.values:
            raise ValueError("Choose a supported language.")
        style = str(payload.get("speaking_style") or StyleChoice.WARM)
        if style not in StyleChoice.values:
            raise ValueError("Choose a supported tone.")
        duration = supported_duration(payload.get("duration_seconds") or payload.get("duration") or 45)
        constraints = default_constraints(mode)
        locks = _bool_map(payload.get("locks"), constraints["locked"])
        variables = _bool_map(payload.get("variables"), constraints["variables"])
        title = scrub_workflow_text(str(payload.get("title") or "").strip(), fallback="")[:160]
        if not title:
            title = creative_title_for_bulk(getattr(product, "name", "") or "Product", count)

        upload = None
        if files:
            upload = files.get("reference_video") or files.get("video")
        source = _source_library_video(owner, payload)
        reference_url = str(payload.get("reference_url") or "").strip()
        if mode == BulkGenerationMode.EXISTING_VIDEO and not source:
            raise ValueError("Select an existing Studio video.")
        if mode in REFERENCE_MODES:
            if upload:
                _validate_reference_upload(upload)
            elif not source:
                raise ValueError("Upload a reference video.")
        if source and character is None:
            inherited = _character_from_project(source[0])
            if inherited and inherited.owner_id == owner.id and inherited.brand_id == product.brand_id:
                character = inherited
        # Same-flow locks duration: always inherit the source film length.
        if mode == BulkGenerationMode.EXISTING_VIDEO and source and source[0].duration_seconds:
            duration = supported_duration(source[0].duration_seconds)

        bulk = BulkGeneration(
            owner=owner,
            product=product,
            character=character,
            mode=mode,
            title=title,
            language=language,
            speaking_style=style,
            duration_seconds=duration,
            requested_count=count,
            character_ids=character_ids,
            locks=locks,
            variables=variables,
            instruction=_instruction_from_payload(payload),
            reference_url=reference_url,
            status=BulkGenerationStatus.DRAFT,
        )
        bulk.save()
        if upload:
            bulk.reference_video.save(upload.name, upload, save=True)
        elif source:
            _attach_library_reference(bulk, source[1])
        if source:
            source_project = source[0]
            if source_project.scenes.exists():
                spec = master_spec_from_project(source_project, locks=locks, variables=variables)
            else:
                spec = dict(bulk.master_spec or {})
                spec["source_video_id"] = source_project.pk
            spec["generate_character"] = bool(
                (source_project.creative_brief or {}).get("generate_character")
            ) or not bulk.character_id
            bulk.master_spec = spec
            bulk.save(update_fields=["master_spec", "updated_at"])
        return bulk

    def analyze_reference(self, bulk: BulkGeneration, payload: dict | None = None) -> BulkGeneration:
        self._set_instruction(bulk, payload)
        if bulk.mode == BulkGenerationMode.EXISTING_VIDEO or (
            (bulk.master_spec or {}).get("from_project") and (bulk.master_spec or {}).get("scenes")
        ):
            if not (payload or {}).get("force"):
                return bulk
        if bulk.mode not in REFERENCE_MODES:
            raise ValueError("Reference analysis is only used for the reference-video modes.")
        if not bulk.reference_video:
            raise ValueError("Upload a reference video first.")
        require_intelligence()
        bulk.status = BulkGenerationStatus.ANALYZING
        bulk.error_message = ""
        bulk.save(update_fields=["status", "error_message", "updated_at"])
        snapshot = product_snapshot(bulk.product)
        try:
            analysis = self.reference.analyze(
                bulk.reference_video.path,
                product_snapshot=snapshot,
            )
            spec = self._build_master_spec(bulk, analysis, snapshot)
        except (MissingAPIKeyError, ProviderError, ValueError):
            bulk.status = BulkGenerationStatus.DRAFT
            bulk.save(update_fields=["status", "updated_at"])
            raise
        except Exception:
            logger.exception("Reference analysis failed for bulk %s", bulk.pk)
            spec = self._fallback_master_spec(bulk, snapshot, {})
        bulk.master_spec = spec
        bulk.status = BulkGenerationStatus.DRAFT
        bulk.save(update_fields=["master_spec", "status", "updated_at"])
        return bulk

    def generate_plan(self, bulk: BulkGeneration, *, replace: bool = True, payload: dict | None = None) -> BulkGeneration:
        self._set_instruction(bulk, payload)
        if bulk.status in BUSY_STATUSES:
            raise ValueError("This batch is already generating.")
        if bulk.mode in REFERENCE_MODES and not (bulk.master_spec or {}).get("scenes"):
            if not bulk.reference_video:
                raise ValueError("Upload and analyze a reference video first.")
            self.analyze_reference(bulk)
            bulk.refresh_from_db()
        snapshot = product_snapshot(bulk.product)
        if bulk.mode == BulkGenerationMode.EXISTING_VIDEO or (bulk.master_spec or {}).get("from_project"):
            variations = self._clone_flow_plan(bulk, snapshot)
            if len(variations) != bulk.requested_count:
                raise ValueError(f"The plan must contain exactly {bulk.requested_count} videos.")
            self._store_plan(bulk, variations, replace=replace)
            return bulk
        require_intelligence()
        try:
            raw = self.intelligence.generate_json(
                self._plan_prompt(bulk, snapshot),
                schema=PLAN_SCHEMA,
                system=(
                    "You plan controlled advertising variations. "
                    "Never change locked facts, prices, claims, or product identity. "
                    "If a merchant instruction is present, it is the source of truth for every story. "
                    "Return JSON only."
                ),
                operation="bulk_plan",
                owner=bulk.owner,
            )
            variations = self._normalize_plan(bulk, raw.get("variations") or [], snapshot)
        except (MissingAPIKeyError, ProviderError):
            raise
        except Exception:
            logger.exception("Bulk plan generation failed for %s; using fallback", bulk.pk)
            variations = self._fallback_plan(bulk, snapshot)
        if len(variations) != bulk.requested_count:
            raise ValueError(f"The plan must contain exactly {bulk.requested_count} videos.")
        self._store_plan(bulk, variations, replace=replace)
        return bulk

    def regenerate_plan_item(self, bulk: BulkGeneration, sequence: int) -> BulkGeneration:
        if bulk.status not in PLAN_EDIT_STATUSES:
            raise ValueError("The plan can only be edited before videos start.")
        plan = list(bulk.generation_plan or [])
        current = next((item for item in plan if int(item.get("sequence") or 0) == int(sequence)), None)
        if current is None:
            raise ValueError("That plan item does not exist.")
        snapshot = product_snapshot(bulk.product)
        try:
            raw = self.intelligence.generate_json(
                self._plan_prompt(bulk, snapshot, sequence=sequence, existing=current),
                schema=PLAN_SCHEMA,
                system="Replace one variation only. Keep locked facts unchanged. Return JSON only.",
                operation="bulk_plan_item",
                owner=bulk.owner,
            )
            replacements = self._normalize_plan(bulk, raw.get("variations") or [], snapshot)
        except Exception:
            replacements = self._fallback_plan(bulk, snapshot)
        replacement = replacements[0] if replacements else current
        replacement["sequence"] = int(sequence)
        next_plan = [replacement if int(item.get("sequence") or 0) == int(sequence) else item for item in plan]
        self._store_plan(bulk, next_plan, replace=True)
        return bulk

    def update_plan(self, bulk: BulkGeneration, payload: dict) -> BulkGeneration:
        self._set_instruction(bulk, payload)
        if bulk.status not in PLAN_EDIT_STATUSES:
            raise ValueError("The plan can only be edited before videos start.")
        if payload.get("regenerate_sequence") not in (None, ""):
            return self.regenerate_plan_item(bulk, int(payload["regenerate_sequence"]))
        snapshot = product_snapshot(bulk.product)
        plan = list(bulk.generation_plan or [])
        if payload.get("variations") is not None:
            plan = self._normalize_plan(bulk, payload.get("variations") or [], snapshot)
        if payload.get("remove"):
            remove = {int(item) for item in payload["remove"]}
            plan = [item for item in plan if int(item.get("sequence") or 0) not in remove]
        if payload.get("reorder"):
            order = [int(item) for item in payload["reorder"]]
            by_seq = {int(item.get("sequence") or 0): item for item in plan}
            plan = [by_seq[item] for item in order if item in by_seq]
        if not plan:
            raise ValueError("Keep at least one video in the plan.")
        if len(plan) > MAX_BULK_VIDEOS:
            raise ValueError(f"Create up to {MAX_BULK_VIDEOS} videos at a time.")
        for index, item in enumerate(plan, start=1):
            item["sequence"] = index
        bulk.requested_count = len(plan)
        self._store_plan(bulk, plan, replace=True)
        return bulk

    def start_generation(self, bulk: BulkGeneration, payload: dict | None = None) -> BulkGeneration:
        self._set_instruction(bulk, payload)
        if bulk.status in BUSY_STATUSES:
            raise ValueError("This batch is already generating.")
        if bulk.status == BulkGenerationStatus.CANCELLED:
            raise ValueError("This batch was cancelled.")
        if not bulk.items.exists():
            if bulk.generation_plan:
                self._store_plan(bulk, list(bulk.generation_plan), replace=True)
            else:
                raise ValueError("Generate and approve a variation plan first.")
        require_intelligence()
        require_omni_key()
        bulk.status = BulkGenerationStatus.QUEUED
        bulk.error_message = ""
        bulk.started_at = timezone.now()
        bulk.completed_at = None
        bulk.save(update_fields=["status", "error_message", "started_at", "completed_at", "updated_at"])
        for item in bulk.items.order_by("sequence"):
            if item.status == BulkItemStatus.CANCELLED:
                continue
            if item.video_project_id and item.status in {BulkItemStatus.COMPLETED, BulkItemStatus.GENERATING}:
                continue
            try:
                self._prepare_item_project(item)
                item.status = BulkItemStatus.QUEUED
                item.error_message = ""
                item.completed_at = None
                item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
            except Exception as exc:
                item.status = BulkItemStatus.FAILED
                item.error_message = str(exc).split("\n")[0][:500]
                item.completed_at = timezone.now()
                item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        self.advance(bulk.pk)
        bulk.refresh_from_db()
        return bulk

    def retry_failed(self, bulk: BulkGeneration) -> BulkGeneration:
        failed = list(bulk.items.filter(status=BulkItemStatus.FAILED))
        if not failed:
            raise ValueError("There are no failed videos to retry.")
        if bulk.status == BulkGenerationStatus.CANCELLED:
            raise ValueError("This batch was cancelled.")
        require_omni_key()
        bulk.status = BulkGenerationStatus.GENERATING
        bulk.error_message = ""
        bulk.completed_at = None
        bulk.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        for item in failed:
            try:
                self._prepare_item_project(item, force=True)
                item.status = BulkItemStatus.QUEUED
                item.error_message = ""
                item.completed_at = None
                item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
            except Exception as exc:
                item.status = BulkItemStatus.FAILED
                item.error_message = str(exc).split("\n")[0][:500]
                item.completed_at = timezone.now()
                item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        self.advance(bulk.pk)
        bulk.refresh_from_db()
        return bulk

    def cancel(self, bulk: BulkGeneration) -> BulkGeneration:
        from ai.services.cancel import cancel_bulk_generation

        return cancel_bulk_generation(bulk)

    def advance(self, bulk_id: int) -> BulkGeneration:
        with transaction.atomic():
            bulk = BulkGeneration.objects.select_for_update().get(pk=bulk_id)
            if bulk.status == BulkGenerationStatus.CANCELLED:
                return bulk
            for item in bulk.items.select_related("video_project"):
                self._sync_item_from_project(item)
            # Only items already claimed for generation consume a concurrency slot.
            # Do not treat parked project.status=queued as running — that blocked the rest of the batch.
            running = [
                item
                for item in bulk.items.all()
                if item.status == BulkItemStatus.GENERATING
            ]
            queued = [item for item in bulk.items.order_by("sequence") if item.status == BulkItemStatus.QUEUED]
            slots = max(0, bulk_concurrency() - len(running))
            started = []
            for item in queued[:slots]:
                item.status = BulkItemStatus.GENERATING
                item.save(update_fields=["status", "updated_at"])
                started.append(item.pk)
            remaining_queued = max(0, len(queued) - len(started))
            if running or started or remaining_queued:
                bulk.status = BulkGenerationStatus.GENERATING
                bulk.save(update_fields=["status", "updated_at"])
            else:
                self._finish_batch(bulk)
        from ai.tasks import enqueue_bulk_item

        for item_id in started:
            enqueue_bulk_item(item_id)
        return BulkGeneration.objects.get(pk=bulk_id)

    def run_item(self, item_id: int) -> BulkGenerationItem:
        from ai.services.cancel import CANCEL_MESSAGE, GenerationCancelled, cancel_requested

        item = BulkGenerationItem.objects.select_related("bulk", "video_project").get(pk=item_id)
        bulk = item.bulk
        if bulk.status == BulkGenerationStatus.CANCELLED or item.status == BulkItemStatus.CANCELLED:
            item.status = BulkItemStatus.CANCELLED
            item.error_message = item.error_message or CANCEL_MESSAGE
            item.completed_at = item.completed_at or timezone.now()
            item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
            return item
        from ai.services.video import VideoGenerationService

        project = item.video_project
        if project is None:
            item.status = BulkItemStatus.FAILED
            item.error_message = "This variation has no video project."
            item.save(update_fields=["status", "error_message", "updated_at"])
            self.advance(bulk.pk)
            return item
        if cancel_requested(project):
            item.status = BulkItemStatus.CANCELLED
            item.error_message = CANCEL_MESSAGE
            item.completed_at = timezone.now()
            item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
            self.advance(bulk.pk)
            return item
        try:
            VideoGenerationService().run(project.pk)
        except GenerationCancelled:
            item.status = BulkItemStatus.CANCELLED
            item.error_message = CANCEL_MESSAGE
            item.completed_at = timezone.now()
            item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        except Exception as exc:
            project.refresh_from_db()
            if cancel_requested(project) or bulk.status == BulkGenerationStatus.CANCELLED:
                item.status = BulkItemStatus.CANCELLED
                item.error_message = CANCEL_MESSAGE
                item.completed_at = timezone.now()
                item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
            else:
                logger.exception("Bulk item %s failed", item.pk)
                item.status = BulkItemStatus.FAILED
                item.error_message = (getattr(project, "error_message", "") or str(exc))[:500]
                item.completed_at = timezone.now()
                item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        else:
            self._sync_item_from_project(item)
        self.advance(bulk.pk)
        item.refresh_from_db()
        return item

    def refresh(self, bulk: BulkGeneration) -> BulkGeneration:
        for item in bulk.items.select_related("video_project"):
            self._sync_item_from_project(item)
        if bulk.status in BUSY_STATUSES:
            self.advance(bulk.pk)
            bulk.refresh_from_db()
        return bulk

    def _owned_character(self, owner, character_id, product: Product) -> Character:
        try:
            pk = int(character_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Select a character.") from exc
        character = Character.objects.filter(pk=pk, owner=owner, status=CharacterStatus.ACTIVE).first()
        if character is None:
            raise ValueError("Choose an active character from your library.")
        if character.brand_id != product.brand_id:
            raise ValueError("Choose a character from this product's brand.")
        return character

    def _store_plan(self, bulk: BulkGeneration, variations: list[dict], *, replace: bool) -> None:
        bulk.generation_plan = variations
        bulk.requested_count = len(variations)
        bulk.status = BulkGenerationStatus.PLAN_READY
        bulk.error_message = ""
        bulk.save(update_fields=["generation_plan", "requested_count", "status", "error_message", "updated_at"])
        keep: list[int] = []
        if replace:
            for item in list(bulk.items.all()):
                if item.video_project_id:
                    keep.append(item.pk)
                else:
                    item.delete()
        existing = {item.sequence: item for item in bulk.items.all()}
        for variation in variations:
            sequence = int(variation["sequence"])
            item = existing.get(sequence)
            if item is None:
                item = BulkGenerationItem(bulk=bulk, sequence=sequence)
            item.title = str(variation.get("title") or f"Video {sequence:02d}")[:200]
            item.variation_config = {
                key: variation.get(key)
                for key in (
                    "title",
                    "location",
                    "hook",
                    "story",
                    "action",
                    "camera",
                    "environment",
                    "character_id",
                    "locked_elements",
                    "variable_elements",
                    "scenes",
                )
                if variation.get(key) not in (None, "", [])
            }
            if item.status in {BulkItemStatus.DRAFT, BulkItemStatus.PLANNED} or not item.video_project_id:
                item.status = BulkItemStatus.PLANNED
                item.error_message = ""
            item.save()
            keep.append(item.pk)
        bulk.items.exclude(pk__in=keep).filter(video_project__isnull=True).delete()

    def _prepare_item_project(self, item: BulkGenerationItem, *, force: bool = False) -> VideoProject:
        bulk = item.bulk
        variation = item.variation_config or {}
        project = item.video_project
        if project is None or force and project.status == VideoProjectStatus.FAILED:
            project = VideoProject.objects.create(
                owner=bulk.owner,
                product=bulk.product,
                product_snapshot=product_snapshot(bulk.product),
                language=bulk.language,
                speaking_style=bulk.speaking_style,
                speaker_gender=self._speaker_gender(bulk, variation),
                duration_seconds=bulk.duration_seconds,
                reference_analysis=copy.deepcopy((bulk.master_spec or {}).get("analysis") or {}),
                status=VideoProjectStatus.DRAFT,
                stage_label="Preparing bulk video",
                progress=2,
            )
            item.video_project = project
            item.save(update_fields=["video_project", "updated_at"])
        else:
            project.product_snapshot = product_snapshot(bulk.product, project.product_snapshot)
            project.language = bulk.language
            project.speaking_style = bulk.speaking_style
            project.duration_seconds = bulk.duration_seconds
            project.save()

        instruction = str(getattr(bulk, "instruction", "") or "").strip()
        brief = normalize_brief(
            {
                "schema_version": 2,
                "objective": "buy",
                "duration": bulk.duration_seconds,
                "language": bulk.language,
                "location": variation.get("location") or (bulk.master_spec or {}).get("location") or "",
                "main_benefit": scrub_workflow_text(
                    str(variation.get("hook") or variation.get("story") or ""),
                    fallback=scrub_workflow_text(item.title, fallback=""),
                ),
                "legacy_instructions": instruction,
                "character_id": self._item_character_id(bulk, variation),
                "generate_character": self._item_generate_character(bulk, variation),
                "must_remain_exact": self._must_remain(bulk),
                "cta": (bulk.master_spec or {}).get("cta") or "",
                "bulk": True,
                "bulk_generation_id": bulk.pk,
                "bulk_item_id": item.pk,
                "bulk_mode": bulk.mode,
                "bulk_source_project_id": (bulk.master_spec or {}).get("source_video_id"),
                "from_project": bool((bulk.master_spec or {}).get("from_project")),
                "bulk_preserve_timeline": bool(
                    (bulk.master_spec or {}).get("from_project") or bulk.mode == BulkGenerationMode.EXISTING_VIDEO
                ),
                "bulk_locks": bulk.locks,
                "bulk_variables": bulk.variables,
            },
            project,
        )
        if not brief.get("cta"):
            brief["cta"] = commercial_cta(brief, project.product_snapshot or {}, bulk.language)
        brief["from_project"] = bool((bulk.master_spec or {}).get("from_project"))
        brief["bulk_preserve_timeline"] = bool(
            (bulk.master_spec or {}).get("from_project") or bulk.mode == BulkGenerationMode.EXISTING_VIDEO
        )
        brief["bulk_source_project_id"] = (bulk.master_spec or {}).get("source_video_id")
        brief["bulk"] = True
        brief["bulk_generation_id"] = bulk.pk
        brief["bulk_item_id"] = item.pk
        brief["bulk_mode"] = bulk.mode
        project.creative_brief = brief
        required = instruction_requirement(bulk)
        story = str(variation.get("story") or item.title or "").strip()
        project.merchant_instructions = "\n".join(part for part in [required, story] if part)
        project.save(update_fields=["creative_brief", "merchant_instructions", "updated_at"])

        character_id = brief.get("character_id")
        if character_id:
            try:
                sync_project_character(
                    project,
                    character_id,
                    language=bulk.language,
                    tone=bulk.speaking_style,
                    gender=project.speaker_gender,
                )
            except CharacterError as exc:
                raise ValueError(str(exc)) from exc

        scenes = self._scenes_for_item(bulk, variation)
        concept = {
            "id": f"bulk-{bulk.pk}-{item.sequence}",
            "title": item.title or variation.get("title") or f"Video {item.sequence:02d}",
            "style": variation.get("hook") or bulk.mode,
            "cta": brief.get("cta") or "",
            "scenes": scenes,
        }
        project.creative_directions = [concept]
        project.save(update_fields=["creative_directions", "updated_at"])
        self.director._apply_timeline(project, scenes, concept)
        project.selected_concept_id = concept["id"]
        project.status = VideoProjectStatus.DRAFT
        project.stage_label = "Bulk storyboard ready"
        project.progress = 0
        project.error_message = ""
        project.save(
            update_fields=[
                "selected_concept_id",
                "status",
                "stage_label",
                "progress",
                "error_message",
                "updated_at",
            ]
        )
        try:
            preflight_project(project)
        except PreflightError:
            raise
        return project

    def _scenes_for_item(self, bulk: BulkGeneration, variation: dict) -> list[dict]:
        if variation.get("scenes"):
            scenes = self._normalize_scenes(copy.deepcopy(variation["scenes"]), bulk)
        elif (bulk.master_spec or {}).get("scenes"):
            scenes = self._normalize_scenes(copy.deepcopy(bulk.master_spec["scenes"]), bulk)
        else:
            scenes = []
        if not scenes:
            scenes = self._fallback_scenes(bulk, variation)
        location = scrub_workflow_text(
            str(variation.get("location") or (bulk.master_spec or {}).get("location") or ""),
            fallback="",
        ).strip()
        action = scrub_workflow_text(str(variation.get("action") or ""), fallback="").strip()
        camera = scrub_workflow_text(str(variation.get("camera") or ""), fallback="").strip()
        for index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                continue
            if location and (bulk.variables or {}).get("location"):
                scene["location"] = location
                scene["background"] = location
            if action and index == 1:
                scene["presenter_action"] = action
            if camera:
                scene["camera_framing"] = camera or scene.get("camera_framing") or ""
            if location:
                visual = scrub_workflow_text(
                    str(scene.get("shot_description") or scene.get("visual") or ""),
                    fallback="",
                ).strip()
                if location.lower() not in visual.lower():
                    scene["shot_description"] = f"{visual} Location: {location}.".strip()
            scene["voice_over"] = scrub_workflow_text(str(scene.get("voice_over") or ""), fallback="")
            scene["shot_description"] = scrub_workflow_text(
                str(scene.get("shot_description") or ""),
                fallback="",
            )
        return scenes

    def _item_character_id(self, bulk: BulkGeneration, variation: dict):
        if bulk.mode == BulkGenerationMode.REFERENCE_CHARACTER:
            return variation.get("character_id")
        if bulk.character_id:
            return bulk.character_id
        if variation.get("character_id"):
            return variation.get("character_id")
        source_id = (bulk.master_spec or {}).get("source_video_id")
        if source_id:
            source = VideoProject.objects.filter(pk=source_id, owner=bulk.owner).first()
            inherited = _character_from_project(source) if source else None
            if inherited:
                return inherited.pk
        return None

    def _item_generate_character(self, bulk: BulkGeneration, variation: dict) -> bool:
        if self._item_character_id(bulk, variation):
            return False
        if bulk.mode in {BulkGenerationMode.CHARACTER, BulkGenerationMode.REFERENCE_CHARACTER}:
            return False
        return True

    def _speaker_gender(self, bulk: BulkGeneration, variation: dict) -> str:
        character_id = self._item_character_id(bulk, variation)
        if character_id:
            character = Character.objects.filter(pk=character_id).first()
            if character and character.gender:
                return character.gender
        if bulk.character and bulk.character.gender:
            return bulk.character.gender
        return "female"

    def _must_remain(self, bulk: BulkGeneration) -> list[str]:
        mapping = {
            "product": "product_appearance",
            "product_appearance": "product_appearance",
            "character": "presenter",
            "price": "price",
            "brand": "brand_colors",
            "cta": "product_name",
        }
        remain = []
        for key, enabled in (bulk.locks or {}).items():
            if enabled and mapping.get(key):
                remain.append(mapping[key])
        if "product_appearance" not in remain:
            remain.append("product_appearance")
        if "price" not in remain:
            remain.append("price")
        return remain

    def _sync_item_from_project(self, item: BulkGenerationItem) -> None:
        project = item.video_project
        if project is None:
            return
        project.refresh_from_db()
        if item.status == BulkItemStatus.CANCELLED:
            return
        if project.status == VideoProjectStatus.FAILED:
            item.status = BulkItemStatus.FAILED
            item.error_message = (project.error_message or "Generation failed.")[:500]
            item.completed_at = item.completed_at or timezone.now()
        elif project.status == VideoProjectStatus.QUEUED and item.status in {
            BulkItemStatus.QUEUED,
            BulkItemStatus.DRAFT,
            BulkItemStatus.PLANNED,
        }:
            # Keep waiting items queued until advance claims a concurrency slot.
            pass
        elif project.status in ACTIVE_PROJECT_STATUSES:
            item.status = BulkItemStatus.GENERATING
        elif project.status in {
            VideoProjectStatus.READY_FOR_REVIEW,
            VideoProjectStatus.READY,
            VideoProjectStatus.APPROVED,
            VideoProjectStatus.EXPORTED,
        }:
            item.status = BulkItemStatus.COMPLETED
            item.error_message = ""
            item.completed_at = item.completed_at or timezone.now()
        item.save(update_fields=["status", "error_message", "completed_at", "updated_at"])

    def _finish_batch(self, bulk: BulkGeneration) -> None:
        items = list(bulk.items.exclude(status=BulkItemStatus.CANCELLED))
        failed = sum(1 for item in items if item.status == BulkItemStatus.FAILED)
        completed = sum(1 for item in items if item.status == BulkItemStatus.COMPLETED)
        if not items:
            bulk.status = BulkGenerationStatus.FAILED
            bulk.error_message = "No videos were generated."
        elif failed and completed:
            bulk.status = BulkGenerationStatus.COMPLETED_WITH_ERRORS
        elif failed and not completed:
            bulk.status = BulkGenerationStatus.FAILED
            bulk.error_message = bulk.error_message or "Every video in this batch failed."
        else:
            bulk.status = BulkGenerationStatus.COMPLETED
            bulk.error_message = ""
        bulk.completed_at = timezone.now()
        bulk.save(update_fields=["status", "error_message", "completed_at", "updated_at"])

    def _build_master_spec(self, bulk: BulkGeneration, analysis: dict, snapshot: dict) -> dict:
        try:
            raw = self.intelligence.generate_json(
                (
                    f"Turn this reference analysis into a reusable {bulk.duration_seconds}-second 9:16 commercial blueprint "
                    f"for {snapshot.get('name')}. Use only these product facts: {snapshot}. "
                    f"Analysis: {analysis}. "
                    f"Use exactly {scene_count_for_duration(bulk.duration_seconds)} scenes. "
                    "Keep dialogue, timing, camera intent, and CTA commercially complete. "
                    "Do not invent prices or claims. "
                    f"{instruction_requirement(bulk)}"
                ),
                schema=MASTER_SPEC_SCHEMA,
                system=(
                    "Extract a reusable creative specification. "
                    "If a merchant instruction is present, it is the source of truth for the story. "
                    "Return JSON only."
                ),
                operation="bulk_master_spec",
                owner=bulk.owner,
            )
        except Exception:
            logger.exception("Master spec generation failed for bulk %s", bulk.pk)
            raw = {}
        spec = self._fallback_master_spec(bulk, snapshot, analysis)
        instruction = str(getattr(bulk, "instruction", "") or "").strip()
        if instruction:
            spec["story"] = instruction
        elif raw.get("story"):
            spec["story"] = str(raw["story"])
        if raw.get("cta"):
            spec["cta"] = str(raw["cta"])
        if raw.get("location"):
            spec["location"] = str(raw["location"])
        if raw.get("hook"):
            spec["hook"] = str(raw["hook"])
        if raw.get("camera_intent"):
            spec["camera_intent"] = str(raw["camera_intent"])
        if raw.get("scenes"):
            spec["scenes"] = self._normalize_scenes(raw["scenes"], bulk)
        spec["analysis"] = analysis
        return self._keep_source_meta(bulk, spec)

    def _fallback_master_spec(self, bulk: BulkGeneration, snapshot: dict, analysis: dict) -> dict:
        cta = commercial_cta({"offer_price": snapshot.get("price"), "price": snapshot.get("price")}, snapshot, bulk.language)
        instruction = str(getattr(bulk, "instruction", "") or "").strip()
        return self._keep_source_meta(
            bulk,
            {
                "story": instruction
                or analysis.get("storytelling_structure")
                or analysis.get("storytelling_pattern")
                or "Product demonstration with a clear offer.",
                "hook": analysis.get("hook") or f"See {snapshot.get('name')}",
                "cta": cta,
                "location": "everyday home setting",
                "camera_intent": analysis.get("camera_style") or "handheld vertical",
                "character_notes": "",
                "analysis": analysis,
                "scenes": self._fallback_scenes(bulk, {"location": "everyday home setting", "title": snapshot.get("name")}),
            },
        )

    def _keep_source_meta(self, bulk: BulkGeneration, spec: dict) -> dict:
        previous = bulk.master_spec or {}
        for key in ("source_video_id", "generate_character"):
            if key in spec:
                continue
            if previous.get(key) not in (None, ""):
                spec[key] = previous[key]
        return spec

    def _plan_prompt(self, bulk: BulkGeneration, snapshot: dict, sequence: int | None = None, existing: dict | None = None) -> str:
        count = 1 if sequence else bulk.requested_count
        target = f"Replace variation {sequence} only." if sequence else f"Create exactly {count} distinct variations."
        characters = ""
        if bulk.mode == BulkGenerationMode.REFERENCE_CHARACTER:
            names = list(
                Character.objects.filter(pk__in=bulk.character_ids, owner=bulk.owner).values_list("id", "name")
            )
            characters = f"Assign each variation to one of these characters in order: {names}."
        return (
            f"{target} Mode: {bulk.mode}. "
            f"LOCKED: {bulk.locks}. VARIABLE: {bulk.variables}. "
            f"Product facts (do not change): {snapshot}. "
            f"Language: {bulk.language}. {LANGUAGE_GUIDE.get(bulk.language, '')} {speech_lock(bulk.language)} "
            f"Voice-over must be written and spoken in that locked language. "
            f"Duration: {bulk.duration_seconds}s. "
            f"Master specification: {bulk.master_spec or {}}. "
            f"{characters} "
            f"Existing item to replace: {existing or {}}. "
            f"{instruction_requirement(bulk)} "
            "Each variation needs title plus only the VARIABLE fields. "
            f"Use exactly {scene_count_for_duration(bulk.duration_seconds)} scenes when story or location changes. "
            "Never change price, product name, claims, or CTA wording that includes the offer. "
            "If a merchant instruction is present, treat it as the source of truth for every story."
        )

    def _normalize_plan(self, bulk: BulkGeneration, raw: list, snapshot: dict) -> list[dict]:
        rows = [item for item in raw if isinstance(item, dict)]
        if bulk.mode == BulkGenerationMode.REFERENCE_CHARACTER:
            assigned = []
            for index, character_id in enumerate(bulk.character_ids):
                source = rows[index] if index < len(rows) else {}
                assigned.append({**source, "character_id": character_id})
            rows = assigned
        if not rows:
            rows = self._fallback_plan(bulk, snapshot)
        if len(rows) < bulk.requested_count and bulk.mode != BulkGenerationMode.REFERENCE_CHARACTER:
            fallback = self._fallback_plan(bulk, snapshot)
            rows = (rows + fallback)[: bulk.requested_count]
        rows = rows[: bulk.requested_count]
        normalized = []
        for index, item in enumerate(rows, start=1):
            title = str(item.get("title") or STORY_SEEDS[(index - 1) % len(STORY_SEEDS)])[:200]
            location = str(item.get("location") or LOCATION_SEEDS[(index - 1) % len(LOCATION_SEEDS)])[:160]
            instruction = str(getattr(bulk, "instruction", "") or "").strip()
            variation = {
                "sequence": index,
                "title": title,
                "location": location if (bulk.variables or {}).get("location") else (bulk.master_spec or {}).get("location") or location,
                "hook": str(item.get("hook") or title)[:240],
                "story": str(item.get("story") or instruction or title)[:500],
                "action": str(item.get("action") or "")[:240],
                "camera": str(item.get("camera") or "")[:160],
                "environment": str(item.get("environment") or location)[:160],
                "locked_elements": [key for key, value in (bulk.locks or {}).items() if value],
                "variable_elements": [key for key, value in (bulk.variables or {}).items() if value],
            }
            if item.get("character_id"):
                variation["character_id"] = int(item["character_id"])
            if item.get("scenes"):
                variation["scenes"] = self._normalize_scenes(item["scenes"], bulk)
            normalized.append(variation)
        return normalized

    def _clone_flow_plan(self, bulk: BulkGeneration, snapshot: dict) -> list[dict]:
        spec = bulk.master_spec or {}
        scenes = self._normalize_scenes(copy.deepcopy(spec.get("scenes") or []), bulk)
        if not scenes:
            scenes = self._fallback_scenes(
                bulk,
                {
                    "location": str(spec.get("location") or ""),
                    "hook": str(spec.get("hook") or ""),
                    "story": str(spec.get("story") or ""),
                },
            )
        vary_location = bool((bulk.variables or {}).get("location"))
        vary_character = bool((bulk.variables or {}).get("character"))
        product_name = scrub_workflow_text(snapshot.get("name") or "", fallback="Video")
        hook = scrub_workflow_text(str(spec.get("hook") or ""), fallback=product_name)
        story = scrub_workflow_text(str(spec.get("story") or ""), fallback="")
        rows = []
        for index in range(bulk.requested_count):
            location = (
                LOCATION_SEEDS[index % len(LOCATION_SEEDS)]
                if vary_location
                else str(spec.get("location") or "")
            )
            item_scenes = copy.deepcopy(scenes)
            if vary_location and location:
                for scene in item_scenes:
                    if not isinstance(scene, dict):
                        continue
                    scene["location"] = location
                    scene["background"] = location
            variation = {
                "sequence": index + 1,
                "title": f"{hook} {index + 1:02d}"[:200],
                "location": location,
                "hook": hook,
                "story": story,
                "action": "",
                "camera": str(spec.get("camera_intent") or ""),
                "environment": location,
                "locked_elements": [key for key, value in (bulk.locks or {}).items() if value],
                "variable_elements": [key for key, value in (bulk.variables or {}).items() if value],
                "scenes": item_scenes,
            }
            if vary_character and index < len(bulk.character_ids):
                variation["character_id"] = bulk.character_ids[index]
            rows.append(variation)
        return rows

    def _fallback_plan(self, bulk: BulkGeneration, snapshot: dict) -> list[dict]:
        rows = []
        for index in range(bulk.requested_count):
            location = LOCATION_SEEDS[index % len(LOCATION_SEEDS)]
            title = STORY_SEEDS[index % len(STORY_SEEDS)]
            instruction = str(getattr(bulk, "instruction", "") or "").strip()
            variation = {
                "sequence": index + 1,
                "title": title,
                "location": location,
                "hook": f"{title} with {snapshot.get('name')}",
                "story": instruction or f"{title} in {location}.",
                "action": "Show the product naturally",
                "camera": "vertical handheld",
                "environment": location,
                "locked_elements": [key for key, value in (bulk.locks or {}).items() if value],
                "variable_elements": [key for key, value in (bulk.variables or {}).items() if value],
            }
            if bulk.mode == BulkGenerationMode.REFERENCE_CHARACTER and index < len(bulk.character_ids):
                variation["character_id"] = bulk.character_ids[index]
                variation["location"] = (bulk.master_spec or {}).get("location") or location
            rows.append(variation)
        return rows

    def _normalize_scenes(self, raw, bulk: BulkGeneration) -> list[dict]:
        """Normalize scene dicts; retarget timing when duration differs. Never discard good VO."""
        expected = scene_count_for_duration(bulk.duration_seconds)
        snapshot = product_snapshot(bulk.product)
        product_name = scrub_workflow_text(snapshot.get("name") or "", fallback="the product") or "the product"
        scenes = []
        for index, item in enumerate(raw or [], start=1):
            if not isinstance(item, dict):
                continue
            visual = scrub_workflow_text(
                str(item.get("shot_description") or item.get("visual") or ""),
                fallback="",
            )
            voice = scrub_workflow_text(
                str(item.get("voice_over") or item.get("narration") or item.get("script") or ""),
                fallback="",
            )
            caption = scrub_workflow_text(
                str(item.get("on_screen_caption") or item.get("caption") or ""),
                fallback="",
            )
            scenes.append(
                {
                    "scene_key": str(item.get("scene_key") or f"scene-{index}")[:64],
                    "order": index,
                    "title": scrub_workflow_text(
                        str(item.get("title") or f"Scene {index}"),
                        fallback=f"Scene {index}",
                    )[:200],
                    "duration": item.get("duration") or max(3, bulk.duration_seconds / expected),
                    "shot_description": visual,
                    "voice_over": voice,
                    "on_screen_caption": caption,
                    "location": str(item.get("location") or ""),
                    "camera_framing": str(item.get("camera_framing") or item.get("camera") or ""),
                    "presenter_action": str(item.get("presenter_action") or ""),
                    "background": str(item.get("background") or ""),
                }
            )
        if not scenes:
            return []
        # Same-flow / from-project: keep creative scene count and scale timings.
        # Other modes: fit the canonical scene budget for the duration.
        preserve_count = bulk.mode == BulkGenerationMode.EXISTING_VIDEO or bool(
            (bulk.master_spec or {}).get("from_project")
        )
        target = int(bulk.duration_seconds)
        if preserve_count:
            adapted = _scale_scene_timings(scenes, target)
        else:
            adapted = _retarget_timeline(scenes, target)
        repaired = []
        for index, item in enumerate(adapted, start=1):
            voice = scrub_workflow_text(str(item.get("voice_over") or ""), fallback="")
            visual = scrub_workflow_text(str(item.get("shot_description") or ""), fallback="")
            if not voice or contains_workflow_label(voice):
                voice = self._dialogue_for_scene(bulk, item, snapshot, index=index, total=len(adapted))
            if not visual or contains_workflow_label(visual):
                location = str(item.get("location") or (bulk.master_spec or {}).get("location") or "everyday setting")
                visual = (
                    f"{item.get('title') or f'Scene {index}'} featuring {product_name} in {location}. "
                    f"Keep {product_name} identical to the product photo."
                )
            repaired.append(
                {
                    **item,
                    "scene_key": str(item.get("scene_key") or f"scene-{index}")[:64],
                    "order": index,
                    "shot_description": visual,
                    "voice_over": voice,
                    "on_screen_caption": scrub_workflow_text(
                        str(item.get("on_screen_caption") or ""),
                        fallback=product_name if index < len(adapted) else "",
                    ),
                }
            )
        return repaired

    def _dialogue_for_scene(
        self,
        bulk: BulkGeneration,
        scene: dict,
        snapshot: dict,
        *,
        index: int,
        total: int,
    ) -> str:
        """Derive spoken lines from brief/product facts — never from workflow titles."""
        name = scrub_workflow_text(snapshot.get("name") or "", fallback="the product") or "the product"
        price = snapshot.get("price") or ""
        instruction = scrub_workflow_text(str(getattr(bulk, "instruction", "") or ""), fallback="")
        hook = scrub_workflow_text(
            str((bulk.master_spec or {}).get("hook") or scene.get("hook") or ""),
            fallback="",
        )
        story = scrub_workflow_text(
            str((bulk.master_spec or {}).get("story") or scene.get("story") or ""),
            fallback="",
        )
        benefit = hook or story or instruction or name
        last = index >= total
        if last:
            return commercial_cta(
                {"offer_price": price, "price": price, "cta": (bulk.master_spec or {}).get("cta")},
                snapshot,
                bulk.language,
            )
        if index == 1 and hook:
            return hook
        if benefit and benefit.lower() != name.lower():
            return benefit if len(benefit.split()) <= 28 else f"{name}. {benefit.split('.')[0]}."
        return f"{name}."

    def _fallback_scenes(self, bulk: BulkGeneration, variation: dict) -> list[dict]:
        expected = scene_count_for_duration(bulk.duration_seconds)
        duration = max(3.0, float(bulk.duration_seconds) / expected)
        snapshot = product_snapshot(bulk.product)
        name = scrub_workflow_text(snapshot.get("name") or "", fallback="the product") or "the product"
        price = snapshot.get("price") or ""
        location = scrub_workflow_text(
            str(variation.get("location") or (bulk.master_spec or {}).get("location") or ""),
            fallback="everyday setting",
        ) or "everyday setting"
        hook = scrub_workflow_text(
            str(variation.get("hook") or (bulk.master_spec or {}).get("hook") or ""),
            fallback="",
        )
        story = scrub_workflow_text(
            str(variation.get("story") or getattr(bulk, "instruction", "") or ""),
            fallback="",
        )
        cta = commercial_cta({"offer_price": price, "price": price}, snapshot, bulk.language)
        roles = ["Hook", "Product", "Lifestyle", "Proof", "Detail", "Offer", "CTA", "Close"]
        scenes = []
        for index in range(expected):
            last = index == expected - 1
            role = roles[index] if index < len(roles) else f"Scene {index + 1}"
            voice = self._dialogue_for_scene(
                bulk,
                {"hook": hook, "story": story},
                snapshot,
                index=index + 1,
                total=expected,
            )
            if last:
                voice = cta
            scenes.append(
                {
                    "scene_key": f"scene-{index + 1}",
                    "order": index + 1,
                    "title": role,
                    "duration": duration,
                    "shot_description": (
                        f"{role} featuring {name} in {location}. "
                        f"Keep {name} identical to the product photo."
                    ),
                    "voice_over": voice,
                    "on_screen_caption": cta if last else name,
                    "location": location,
                    "camera_framing": "medium vertical",
                    "presenter_action": scrub_workflow_text(str(variation.get("action") or ""), fallback=""),
                }
            )
        return scenes
