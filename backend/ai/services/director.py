from __future__ import annotations

import logging
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from ai.models import Scene, VideoProject, VideoProjectStatus
from ai.providers.intelligence import IntelligenceClient
from ai.services.captions import spoken_caption, wrap_caption
from ai.services.presenter import (
    normalize_presenter_payload,
    presenter_identity_text,
    presenter_should_appear,
)
from ai.services.durations import scene_count_for_duration, supported_duration
from ai.services.script import LANGUAGE_GUIDE, STYLE_GUIDE, nativize_spoken_copy, speech_lock, spoken_copy_instruction
from ai.services.templates import suggest_templates

logger = logging.getLogger(__name__)

OBJECTIVES = ("buy", "enquire", "follow", "visit")
MUST_REMAIN_OPTIONS = (
    "product_appearance",
    "logo",
    "packaging",
    "presenter",
    "product_name",
    "price",
    "brand_colors",
    "other",
)
PLATFORMS = ("tiktok", "instagram", "facebook", "")
SCENE_STATUSES = (
    "draft",
    "ready",
    "generating",
    "generated",
    "qa_warning",
    "qa_failed",
    "approved",
    "regenerating",
    "failed",
)

CONCEPTS_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "style": {"type": "string"},
                    "strategy": {"type": "string"},
                    "audience_angle": {"type": "string"},
                    "hook": {"type": "string"},
                    "narrative": {"type": "string"},
                    "cta": {"type": "string"},
                    "estimated_duration": {"type": "integer"},
                    "why_it_works": {"type": "string"},
                    "template_id": {"type": "string"},
                    "scenes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "scene_key": {"type": "string"},
                                "order": {"type": "integer"},
                                "title": {"type": "string"},
                                "start_time": {"type": "number"},
                                "end_time": {"type": "number"},
                                "duration": {"type": "number"},
                                "shot_description": {"type": "string"},
                                "presenter_action": {"type": "string"},
                                "camera_framing": {"type": "string"},
                                "camera_movement": {"type": "string"},
                                "lighting": {"type": "string"},
                                "pace": {"type": "string"},
                                "transition": {"type": "string"},
                                "voice_over": {"type": "string"},
                                "on_screen_caption": {"type": "string"},
                                "benefit": {"type": "string"},
                                "approved_claim": {"type": "string"},
                                "location": {"type": "string"},
                                "background": {"type": "string"},
                                "cta": {"type": "boolean"},
                                "scene_role": {"type": "string"},
                            },
                            "required": [
                                "shot_description",
                                "voice_over",
                                "on_screen_caption",
                                "duration",
                            ],
                        },
                    },
                },
                "required": ["title", "style", "hook", "narrative", "cta", "scenes"],
            },
        }
    },
    "required": ["concepts"],
}


COPY_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "cta": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene_key": {"type": "string"},
                    "voice_over": {"type": "string"},
                    "on_screen_caption": {"type": "string"},
                },
            },
        },
        "language_notes": {"type": "string"},
    },
}

SCENE_ROLES = (
    "hook",
    "product_in_use",
    "product_detail",
    "presenter",
    "lifestyle",
    "hero_cta",
)


def is_studio_project(project: VideoProject | None) -> bool:
    if not project:
        return False
    brief = project.creative_brief or {}
    return bool(project.selected_concept_id or brief.get("schema_version") == 2)


MAX_CONCEPTS = 10
DEFAULT_SCENE_TRANSITION = "match cut — continue the same shot"

_HIDE_PRICE_RE = re.compile(
    r"(?:no|hide|remove|removing|without|jangan|buang|tiada|tanpa)\s+"
    r"(?:the\s+)?(?:price|harga|rm|cost)"
    r"|(?:price|harga)\s*(?:/|and|&)\s*(?:url|website|link)",
    re.I,
)
_HIDE_URL_RE = re.compile(
    r"(?:no|hide|remove|removing|without|jangan|buang|tiada|tanpa)\s+"
    r"(?:the\s+)?(?:url|website|link|domain|pautan|laman|web)"
    r"|(?:price|harga)\s*(?:/|and|&)\s*(?:url|website|link)"
    r"|(?:url|website|link)\s*(?:/|and|&)\s*(?:price|harga)",
    re.I,
)


def concept_count(value, default: int = 3) -> int:
    try:
        count = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, MAX_CONCEPTS))


def _character_id(data: dict, existing: dict):
    if "character_id" in data:
        raw = data.get("character_id")
        if raw in (None, "", "none", "null"):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    raw = existing.get("character_id")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def normalize_brief(raw: dict | None, project: VideoProject | None = None) -> dict:
    data = dict(raw or {})
    snapshot = (project.product_snapshot if project else None) or {}
    objective = str(data.get("objective") or "").strip().lower()
    if objective not in OBJECTIVES:
        objective = ""
    duration = supported_duration(
        data.get("duration") or data.get("duration_seconds") or (project.duration_seconds if project else 45) or 45
    )
    must_remain = [
        item
        for item in _as_list(data.get("must_remain_exact"))
        if item in MUST_REMAIN_OPTIONS
    ]
    original_price = str(data.get("original_price") or "").strip()
    offer_price = str(data.get("offer_price") or "").strip()
    offer_text = str(data.get("offer_text") or data.get("offer") or "").strip()
    snapshot_price = str(snapshot.get("price") or "").strip()
    snapshot_offer = str(snapshot.get("offer") or "").strip()
    if not original_price:
        original_price = snapshot_price
    if not offer_text:
        offer_text = snapshot_offer
    platform = str(data.get("platform") or "").strip().lower()
    if platform not in PLATFORMS:
        platform = ""
    existing = (project.creative_brief if project else None) or {}
    generate_character = _as_bool(
        data["generate_character"] if "generate_character" in data else existing.get("generate_character")
    )
    seedance_model = str(
        data.get("seedance_model")
        or data.get("video_model")
        or existing.get("seedance_model")
        or existing.get("video_model")
        or ""
    ).strip()
    if seedance_model:
        try:
            from ai.providers.seedance import resolve_seedance_model

            seedance_model = resolve_seedance_model(seedance_model)
        except Exception:
            # Keep the prior brief value if an incoming alias is invalid.
            seedance_model = str(existing.get("seedance_model") or existing.get("video_model") or "").strip()
    return {
        **{key: value for key, value in existing.items() if key not in {
            "objective", "customer", "main_benefit", "offer", "price", "original_price",
            "offer_price", "offer_text", "must_remain_exact", "must_not_show",
            "language", "market", "platform", "duration", "legacy_instructions",
            "schema_version", "presenter", "location", "style_key", "character_id", "generate_character",
            "seedance_model", "video_model",
        }},
        "schema_version": 2,
        "objective": objective,
        "customer": str(data.get("customer") or "").strip(),
        "main_benefit": str(data.get("main_benefit") or "").strip(),
        "original_price": original_price,
        "offer_price": offer_price,
        "offer_text": offer_text,
        "offer": offer_text or snapshot_offer,
        "price": offer_price or original_price or snapshot_price,
        "must_remain_exact": must_remain,
        "must_not_show": str(data.get("must_not_show") or "").strip(),
        "language": str(data.get("language") or (project.language if project else "") or ""),
        "market": str(data.get("market") or "").strip(),
        "platform": platform,
        "duration": duration,
        "legacy_instructions": str(data.get("legacy_instructions") or "").strip(),
        "location": str(data.get("location") or data.get("background") or existing.get("location") or "").strip(),
        "presenter": normalize_presenter_payload(
            data.get("presenter") if isinstance(data.get("presenter"), dict) else existing.get("presenter"),
            gender=getattr(project, "speaker_gender", "") if project else "",
        ),
        "style_key": str(data.get("style_key") or existing.get("style_key") or "").strip(),
        "character_id": None if generate_character else _character_id(data, existing),
        "generate_character": generate_character,
        "approved_claims": snapshot.get("approved_claims") or existing.get("approved_claims") or [],
        "brand_rules": data.get("brand_rules") or existing.get("brand_rules") or {},
        "product_truth": {
            "name": snapshot.get("name") or "",
            "price": snapshot_price,
            "offer": snapshot_offer,
            "approved_claims": snapshot.get("approved_claims") or [],
            "prohibited_claims": snapshot.get("prohibited_claims") or [],
        },
        **(
            {"seedance_model": seedance_model, "video_model": seedance_model}
            if seedance_model
            else {}
        ),
    }


def brief_from_legacy(project: VideoProject) -> dict:
    existing = project.creative_brief or {}
    if existing.get("schema_version") == 2 or existing.get("objective") or existing.get("customer"):
        return normalize_brief(existing, project)
    return normalize_brief(
        {
            **existing,
            "customer": existing.get("audience") or "",
            "main_benefit": existing.get("promise") or "",
            "legacy_instructions": project.merchant_instructions or "",
            "duration": project.duration_seconds,
            "language": project.language,
        },
        project,
    )


def extra_instruction_text(brief: dict | None, project=None) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for value in (
        str((brief or {}).get("legacy_instructions") or "").strip(),
        str(getattr(project, "merchant_instructions", "") or "").strip() if project is not None else "",
    ):
        if value and value not in seen:
            seen.add(value)
            parts.append(value)
    return "\n".join(parts)


def extra_instruction_requirement(brief: dict | None, project=None) -> str:
    extra = extra_instruction_text(brief, project)
    if not extra:
        return ""
    return (
        "REQUIRED extra instruction from the merchant. This field is optional, "
        "but when present it MUST shape the story, hook, scenes, voice-over, locale, and CTA. "
        "If the instruction names Cantonese, Mandarin, Hokkien, or another locale, speak that language. "
        "Do not ignore or contradict it:\n"
        f"{extra}"
    )


def _suppression_blob(brief: dict | None) -> str:
    data = brief or {}
    return " ".join(
        part
        for part in [
            extra_instruction_text(data),
            str(data.get("must_not_show") or ""),
        ]
        if part
    )


def suppress_price(brief: dict | None) -> bool:
    data = brief or {}
    if data.get("show_price") is False:
        return True
    return bool(_HIDE_PRICE_RE.search(_suppression_blob(data)))


def suppress_website(brief: dict | None) -> bool:
    data = brief or {}
    if data.get("show_website") is False:
        return True
    return bool(_HIDE_URL_RE.search(_suppression_blob(data)))


def strip_suppressed_content(text: str, brief: dict | None, snapshot: dict | None = None) -> str:
    """Drop price/URL tokens the merchant asked not to show."""
    value = str(text or "")
    if not value:
        return ""
    data = brief or {}
    snap = snapshot or {}
    if suppress_price(data):
        for raw in (
            selling_price_text(data, snap),
            original_price_text(data, snap),
            data.get("offer_price"),
            data.get("price"),
            data.get("original_price"),
            snap.get("price"),
        ):
            token = str(raw or "").strip()
            if token:
                value = re.sub(re.escape(token), " ", value, flags=re.I)
        value = re.sub(r"\bRM\s*[\d][\d,.]+\b", " ", value, flags=re.I)
        value = re.sub(r"\b(?:USD|MYR|SGD)\s*[\d][\d,.]+\b", " ", value, flags=re.I)
    if suppress_website(data):
        from urllib.parse import urlparse

        value = re.sub(r"https?://\S+", " ", value, flags=re.I)
        for raw in (data.get("website"), snap.get("website"), snap.get("product_link")):
            host = urlparse(str(raw or "")).netloc or str(raw or "").strip()
            host = host.replace("www.", "")
            if host:
                value = re.sub(re.escape(host), " ", value, flags=re.I)
    return re.sub(r"[\s·,;:/]+", " ", value).strip(" ·,-")


def compose_merchant_instructions(brief: dict) -> str:
    lines = []
    if brief.get("objective"):
        lines.append(f"Viewer action: {brief['objective']}.")
    if brief.get("customer"):
        lines.append(f"Customer: {brief['customer']}")
    if brief.get("main_benefit"):
        lines.append(f"Main benefit: {brief['main_benefit']}")
    if brief.get("offer_text") or brief.get("offer_price") or brief.get("original_price"):
        offer = " ".join(
            part
            for part in [
                f"Original price {brief['original_price']}" if brief.get("original_price") else "",
                f"Offer price {brief['offer_price']}" if brief.get("offer_price") else "",
                brief.get("offer_text") or "",
            ]
            if part
        )
        lines.append(f"Approved offer: {offer}")
    if brief.get("must_remain_exact"):
        lines.append("Must remain exact: " + ", ".join(brief["must_remain_exact"]))
    if brief.get("must_not_show"):
        lines.append(f"Must not show: {brief['must_not_show']}")
    extra = extra_instruction_requirement(brief)
    if extra:
        lines.append(extra)
    if brief.get("location"):
        lines.append(f"Location / background: {brief['location']}")
    presenter = brief.get("presenter") or {}
    if isinstance(presenter, dict) and (presenter.get("ethnicity") or presenter.get("ethnicity_label") or presenter.get("look")):
        label = presenter.get("ethnicity_label") or presenter.get("ethnicity") or ""
        look = presenter.get("look") or ""
        lines.append(f"Presenter: {label} {presenter.get('gender') or ''} {look}".strip())
    return "\n".join(lines)


def _safe_float(value, default: float = 0.0) -> float:
    if value in (None, ""):
        return float(default)
    if isinstance(value, bool) or isinstance(value, (list, dict, tuple, set)):
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number != number:
        return float(default)
    return number


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(_safe_float(value, default))
    except (TypeError, ValueError):
        return int(default)


def is_video_fallback(meta: dict | None) -> bool:
    data = meta or {}
    return bool(data.get("video_fallback") or data.get("seedance_fallback"))


def scene_generation_id(meta: dict | None) -> str:
    data = meta or {}
    return str(
        data.get("omni_interaction_id")
        or data.get("generation_id")
        or data.get("seedance_task_id")
        or ""
    )


def media_exists(field) -> bool:
    try:
        if not field or not getattr(field, "name", ""):
            return False
        storage = getattr(field, "storage", None)
        if storage:
            return bool(storage.exists(field.name))
        return Path(field.path).exists()
    except Exception:
        return False


def _file_url(field) -> str:
    try:
        if not field or not media_exists(field):
            return ""
        return field.url
    except Exception:
        return ""


def _discard_scene_outputs(scene: Scene) -> None:
    changed = False
    for attr in ("image", "video_clip", "audio"):
        field = getattr(scene, attr, None)
        if not field:
            continue
        try:
            field.delete(save=False)
        except Exception:
            pass
        setattr(scene, attr, "")
        changed = True
    if changed and scene.pk:
        scene.save(update_fields=["image", "video_clip", "audio"])


def record_event(project: VideoProject, event_type: str, payload: dict | None = None) -> None:
    events = list(project.director_events or [])
    events.append(
        {
            "type": event_type,
            "at": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }
    )
    project.director_events = events[-200:]
    project.save(update_fields=["director_events", "updated_at"])
    logger.info("Director event %s for project %s", event_type, project.pk)


class DirectorService:
    def __init__(self, gemini: IntelligenceClient | None = None):
        self.gemini = gemini or IntelligenceClient()

    def review_copy(self, project: VideoProject) -> None:
        """Rewrite VO/captions/CTA into natural commercial language for the selected locale."""
        language = project.language or "conversational_bm"
        guide = LANGUAGE_GUIDE.get(language, LANGUAGE_GUIDE["conversational_bm"])
        malay = language in {"conversational_bm", "formal_bm", "bm_english"}
        copy_rule = spoken_copy_instruction(language)
        scenes = list(project.scenes.all())
        if not scenes:
            return
        brief = brief_from_legacy(project)
        snapshot = project.product_snapshot or {}
        payload = [
            {
                "scene_key": scene.scene_key,
                "title": scene.title,
                "voice_over": scene.narration,
                "on_screen_caption": scene.caption,
                "script_locked": bool((scene.metadata or {}).get("script_locked")),
                "caption_locked": bool((scene.metadata or {}).get("caption_locked")),
            }
            for scene in scenes
        ]
        try:
            raw = self.gemini.generate_json(
                (
                    f"{self._context(project, brief)}\n"
                    f"Rewrite the voice-over and captions for this language: {guide} "
                    f"{speech_lock(language)} "
                    f"{copy_rule} "
                    f"{'Natural Malaysian commercial Malay, not a literal translation.' if malay else ''} "
                    "Keep approved prices, product name, and claims exactly when they are allowed. "
                    "Each on-screen caption MUST be the exact spoken voice-over for that scene, word for word. "
                    "Do not paraphrase, shorten, or invent a different caption. "
                    "Do not invent a website, discount, urgency, or offer. "
                    f"{'Do not mention price, URL, or website in speech or captions.' if suppress_price(brief) or suppress_website(brief) else 'The final CTA must name the product and ask for a real purchase action. Include the approved price in speech only when the brief allows it.'}\n"
                    f"Current scenes: {payload}\n"
                    f"Current CTA: {(project.script or {}).get('cta') or ''}"
                ),
                schema=COPY_REVIEW_SCHEMA,
                system=(
                    "You are a commercial copywriter for the selected speaking language. "
                    "Write natural spoken copy, not a literal translation. Return JSON only."
                ),
                operation="copy_review",
                project=project,
            )
        except Exception:
            logger.exception("Copy review failed for project %s", project.pk)
            self._lock_presenter_continuity(project)
            self._ensure_commercial_cta(project)
            return
        reviewed = {item.get("scene_key"): item for item in (raw.get("scenes") or []) if item.get("scene_key")}
        for scene in scenes:
            item = reviewed.get(scene.scene_key) or {}
            meta = dict(scene.metadata or {})
            if item.get("voice_over") and not meta.get("script_locked"):
                scene.narration = str(item["voice_over"]).strip()
                meta["voice_over"] = scene.narration
            if item.get("on_screen_caption") and not meta.get("caption_locked"):
                scene.caption = spoken_caption(scene.narration, item["on_screen_caption"])
                meta["on_screen_caption"] = scene.caption
            scene.metadata = meta
            scene.save()
        if raw.get("cta"):
            script = dict(project.script or {})
            script["cta"] = self._protect_text(
                raw["cta"],
                str(brief.get("offer_price") or brief.get("price") or snapshot.get("price") or ""),
                str(brief.get("offer_text") or brief.get("offer") or snapshot.get("offer") or ""),
                str(brief.get("original_price") or snapshot.get("price") or ""),
            )
            project.script = script
            project.save(update_fields=["script", "updated_at"])
        self._lock_presenter_continuity(project)
        self._ensure_commercial_cta(project)
        self._align_captions_to_speech(project)
        self._refresh_script_from_scenes(project)
        record_event(project, "copy_reviewed", {"notes": raw.get("language_notes") or ""})

    def _lock_presenter_continuity(self, project: VideoProject) -> None:
        scenes = list(project.scenes.all())
        identity = presenter_identity_text(project)
        if not presenter_should_appear(project, scenes) and not identity:
            return
        lock_all = bool(identity)
        for scene in scenes:
            meta = dict(scene.metadata or {})
            if lock_all or meta.get("presenter_action"):
                meta["presenter_locked"] = True
                if identity:
                    meta["presenter_identity"] = identity
                scene.metadata = meta
                Scene.objects.filter(pk=scene.pk).update(metadata=meta)

    def _ensure_commercial_cta(self, project: VideoProject) -> None:
        last = project.scenes.order_by("order").last()
        if not last:
            return
        meta = dict(last.metadata or {})
        if meta.get("caption_locked"):
            return
        if last.narration:
            last.caption = spoken_caption(last.narration, last.caption)
            meta["on_screen_caption"] = last.caption
            meta["cta"] = True
            last.metadata = meta
            last.save()
            return
        if _cta_is_complete(f"{last.caption} {last.narration}", project):
            return
        last.caption = wrap_caption(commercial_cta(project.creative_brief or {}, project.product_snapshot or {}, project.language))
        meta["on_screen_caption"] = last.caption
        meta["cta"] = True
        last.metadata = meta
        last.save()

    def _align_captions_to_speech(self, project: VideoProject) -> None:
        """Make every caption the exact spoken sentence. Do not paraphrase.

        Locked Caption keeps a merchant-edited line, but never leaves a scene blank:
        empty locked captions still fill from the spoken voice-over.
        """
        brief = project.creative_brief or {}
        snapshot = project.product_snapshot or {}
        for scene in project.scenes.all():
            meta = dict(scene.metadata or {})
            spoken = strip_suppressed_content(scene.narration or "", brief, snapshot)
            spoken = nativize_spoken_copy(project.language, spoken)
            if spoken and spoken != (scene.narration or "") and not meta.get("script_locked"):
                scene.narration = spoken
                meta["voice_over"] = spoken
            existing = strip_suppressed_content((scene.caption or "").replace("\n", " "), brief, snapshot)
            if meta.get("caption_locked") and existing:
                spoken_exact = " ".join(existing.split())
                aligned = wrap_caption(spoken_exact)
                if not meta.get("script_locked"):
                    scene.narration = spoken_exact
                    meta["voice_over"] = spoken_exact
            else:
                aligned = spoken_caption(scene.narration, scene.caption)
                aligned = wrap_caption(
                    strip_suppressed_content(aligned.replace("\n", " "), brief, snapshot) or aligned
                )
            scene.caption = aligned
            meta["on_screen_caption"] = aligned
            scene.metadata = meta
            scene.save()

    def save_brief(self, project: VideoProject, raw: dict) -> dict:
        brief = normalize_brief(raw, project)
        presenter = brief.get("presenter") or {}
        if isinstance(presenter, dict) and (
            presenter.get("ethnicity") or presenter.get("ethnicity_label") or presenter.get("look") or presenter.get("mode") == "upload"
        ):
            remain = list(brief.get("must_remain_exact") or [])
            if "presenter" not in remain:
                remain.append("presenter")
            brief["must_remain_exact"] = remain
        project.creative_brief = brief
        project.duration_seconds = brief["duration"]
        composed = compose_merchant_instructions(brief)
        if composed:
            project.merchant_instructions = composed
        project.save(update_fields=["creative_brief", "duration_seconds", "merchant_instructions", "updated_at"])
        record_event(project, "brief_saved", {"objective": brief.get("objective")})
        return brief

    def generate_concepts(self, project: VideoProject, count: int | None = None) -> list[dict]:
        brief = brief_from_legacy(project)
        project.creative_brief = brief
        category = ""
        try:
            category = project.product.brand.category.name
        except Exception:
            category = ""
        requested = concept_count(count if count is not None else brief.get("concept_count"))
        templates = suggest_templates(
            brief,
            category=category,
            platform=brief.get("platform") or "",
            count=requested,
        )
        duration = supported_duration(brief.get("duration") or project.duration_seconds or 45)
        scene_count = scene_count_for_duration(duration)
        prompt = (
            f"{self._context(project, brief)}\n"
            f"Create {requested} meaningfully different {duration}-second 9:16 video concepts. "
            f"Do not write {requested} versions of the same idea. "
            f"Use these template starting points if they fit, or choose better styles for the product: "
            f"{[item['id'] for item in templates]}. "
            "Each concept needs title, style, strategy, audience_angle, hook, narrative, CTA, "
            "why_it_works, estimated_duration, and a complete scene timeline. "
            f"estimated_duration must be exactly {duration}. "
            f"Use exactly {scene_count} scenes. Scene timestamps must add up to {duration} seconds. "
            "Each scene must be between 3 and 10 seconds. "
            "Give scenes meaningful variation — do not repeat the same static product shot. "
            "Cover distinct roles where they fit the length: "
            "hook, product, and a final hero plus commercially complete CTA. "
            "Add product detail, presenter, or lifestyle scenes only when the scene budget allows. "
            "If a presenter appears in more than one scene, keep the same person, face, clothing, and hair. "
            f"Presenter identity to keep consistent: {presenter_identity_text(project) or 'the same on-camera presenter throughout'}. "
            "The final CTA must name the product and ask for a real purchase action. "
            f"{'Do not mention or show price, URL, or website.' if suppress_price(brief) or suppress_website(brief) else 'Include the approved price in spoken CTA only when the brief allows a price on screen.'} "
            f"Approved original price: {'hidden' if suppress_price(brief) else (brief.get('original_price') or 'none')}. "
            f"Approved offer price: {'hidden' if suppress_price(brief) else (brief.get('offer_price') or brief.get('price') or 'none')}. "
            f"Approved offer text: {'hidden' if suppress_price(brief) else (brief.get('offer_text') or brief.get('offer') or 'none')}. "
            "If an original price or offer price was supplied and is not hidden, voice-over must use those exact amounts when a price is spoken. "
            "Do not prefix RM onto a price that already has USD, $, EUR, or another currency. "
            "Never invent a website, discount, urgency, or offer. Never show a URL or domain. "
            "Each on-screen caption must be the exact spoken voice-over, word for word. Do not paraphrase or shorten. "
            "Use only approved product facts, prices, and claims. Never invent a price or discount. "
            "If no price or offer was supplied, or the brief asks to remove price, do not add one. "
            f"{extra_instruction_requirement(brief, project)} "
            f"{speech_lock(project.language)} "
            f"{spoken_copy_instruction(project.language)} "
            "Voice-over and captions must be natural spoken commercial language for the selected language — "
            "not a literal or awkward translation. "
            "Return structured JSON only."
        )
        try:
            raw = self.gemini.generate_json(
                prompt,
                schema=CONCEPTS_SCHEMA,
                system=(
                    "You are an advertising creative director. "
                    "Never invent product facts, prices, or claims. Return JSON only."
                ),
                operation="concepts",
                project=project,
            )
            concepts = self._normalize_concepts(
                raw.get("concepts") or [], project, brief, templates, duration, count=requested
            )
        except Exception:
            logger.exception("Concept generation failed for project %s; using director templates", project.pk)
            concepts = self._normalize_concepts([], project, brief, templates, duration, count=requested)
        if len(concepts) < min(3, requested):
            raise ValueError(
                f"The AI did not return {min(3, requested)} usable concept{'s' if min(3, requested) != 1 else ''}. Please try again."
            )
        project.creative_directions = concepts[:requested]
        project.selected_concept_id = ""
        project.save(update_fields=["creative_brief", "creative_directions", "selected_concept_id", "updated_at"])
        record_event(project, "concepts_generated", {"count": len(project.creative_directions)})
        return project.creative_directions

    def select_concept(self, project: VideoProject, concept_id: str, scene_mix: list | None = None) -> dict:
        concepts = list(project.creative_directions or [])
        selected = next((item for item in concepts if item.get("id") == concept_id), None)
        if not selected:
            raise ValueError("Choose one of the generated concepts.")
        scenes = selected.get("scenes") or []
        if scene_mix:
            scenes = self._mix_scenes(concepts, scene_mix)
        if not scenes:
            raise ValueError("This concept has no scenes to use.")
        self._apply_timeline(project, scenes, selected)
        project.selected_concept_id = selected["id"]
        fields = ["selected_concept_id", "script", "shot_plan", "updated_at"]
        if project.status in {
            VideoProjectStatus.EXPORTED,
            VideoProjectStatus.APPROVED,
            VideoProjectStatus.FAILED,
            VideoProjectStatus.READY,
            VideoProjectStatus.READY_FOR_REVIEW,
        }:
            project.status = VideoProjectStatus.DRAFT
            project.stage_label = "Storyboard ready"
            project.progress = 0
            project.error_message = ""
            project.qa_status = ""
            project.qa_results = {}
            project.approved_at = None
            fields.extend(
                ["status", "stage_label", "progress", "error_message", "qa_status", "qa_results", "approved_at"]
            )
        project.save(update_fields=fields)
        record_event(project, "concept_selected", {"concept_id": selected["id"], "mixed": bool(scene_mix)})
        return selected

    def adapt_duration(self, project: VideoProject, duration: int) -> list[dict]:
        duration = supported_duration(duration)
        brief = brief_from_legacy(project)
        brief["duration"] = duration
        project.creative_brief = brief
        project.duration_seconds = duration
        project.save(update_fields=["creative_brief", "duration_seconds", "updated_at"])
        if not project.selected_concept_id and not project.scenes.exists():
            return []
        current = [self.scene_to_timeline(scene) for scene in project.scenes.all()]
        prompt = (
            f"{self._context(project, brief)}\n"
            f"Rebuild this scene timeline for exactly {duration} seconds. "
            "Do not simply truncate a longer video. Redesign scene count, order, and timing. "
            "Preserve locked fields and approved product facts. "
            f"Current timeline: {current}\n"
            "Return one concept with the adapted scenes."
        )
        raw = self.gemini.generate_json(
            prompt,
            schema=CONCEPTS_SCHEMA,
            system="You adapt video timelines. Never invent prices or claims. Return JSON only.",
            operation="adapt_duration",
            project=project,
        )
        concepts = self._normalize_concepts(raw.get("concepts") or [], project, brief, [], duration)
        if not concepts or not concepts[0].get("scenes"):
            raise ValueError("Could not rebuild the timeline for that duration. Please try again.")
        adapted = concepts[0]["scenes"]
        selected = next(
            (item for item in (project.creative_directions or []) if item.get("id") == project.selected_concept_id),
            {"id": project.selected_concept_id or "adapted", "title": "Adapted timeline"},
        )
        self._apply_timeline(project, adapted, selected)
        record_event(project, "duration_adapted", {"duration": duration})
        return adapted

    def update_scene(self, scene: Scene, data: dict, *, unlock: dict | None = None) -> Scene:
        meta = dict(scene.metadata or {})
        locks = {
            "product": bool(meta.get("product_locked")),
            "presenter": bool(meta.get("presenter_locked")),
            "location": bool(meta.get("location_locked")),
            "script": bool(meta.get("script_locked")),
            "caption": bool(meta.get("caption_locked")),
        }
        for key, value in (unlock or {}).items():
            field = f"{key}_locked" if not str(key).endswith("_locked") else str(key)
            if field in {
                "product_locked",
                "presenter_locked",
                "location_locked",
                "script_locked",
                "caption_locked",
                "scene_locked",
            }:
                meta[field] = bool(value)
                locks[field.replace("_locked", "")] = bool(value)

        if meta.get("approved") and not data.get("confirm_approved_edit"):
            raise ValueError("This scene is approved. Confirm before changing it.")

        if "order" in data:
            scene.order = int(data["order"] or scene.order)
        if "title" in data:
            scene.title = str(data.get("title") or scene.title)
        if "duration" in data:
            scene.duration = max(1.0, float(data.get("duration") or scene.duration or 5))
        if "shot_description" in data or "visual" in data:
            scene.visual = str(data.get("shot_description") or data.get("visual") or scene.visual)
            meta["shot_description"] = scene.visual
        if ("voice_over" in data or "narration" in data) and not locks["script"]:
            scene.narration = str(data.get("voice_over") or data.get("narration") or "")
            meta["voice_over"] = scene.narration
        if ("on_screen_caption" in data or "caption" in data) and not locks["caption"]:
            scene.caption = str(data.get("on_screen_caption") or data.get("caption") or "")
            meta["on_screen_caption"] = scene.caption

        director_fields = (
            "start_time",
            "end_time",
            "presenter_action",
            "camera_framing",
            "camera_movement",
            "lighting",
            "pace",
            "transition",
            "benefit",
            "approved_claim",
            "location",
            "background",
            "sound_direction",
            "composition",
            "depth_of_field",
            "lens",
        )
        for field in director_fields:
            if field not in data:
                continue
            if field in {"location", "background"} and locks["location"]:
                continue
            if field == "presenter_action" and locks["presenter"]:
                continue
            meta[field] = data[field]

        for lock_name in ("product", "presenter", "location", "script", "caption", "scene"):
            key = f"{lock_name}_locked"
            if key in data:
                meta[key] = bool(data[key])

        if "start_time" in data or "end_time" in data or "duration" in data:
            start = float(meta.get("start_time") or 0)
            end = float(meta.get("end_time") or (start + scene.duration))
            if "end_time" in data:
                end = float(data["end_time"] or end)
            if "start_time" in data:
                start = float(data["start_time"] or start)
            if end <= start:
                end = start + max(scene.duration, 1)
            scene.duration = max(1.0, end - start)
            meta["start_time"] = start
            meta["end_time"] = end

        if meta.get("approved") and data.get("confirm_approved_edit"):
            meta["approved"] = False
            meta["approved_at"] = ""
            meta["status"] = "ready"

        # Editing clears the last provider result. A leftover qa_failed flag
        # is not a new Omni rejection.
        if meta.get("status") in {"qa_failed", "failed", "qa_warning"}:
            meta["status"] = "ready"
            meta["needs_regeneration"] = bool(scene.video_clip)
        meta["error"] = ""
        meta["pipeline_error"] = {}
        scene.metadata = meta
        scene.generation_status = "queued"
        scene.failure_code = ""
        scene.failure_message = ""
        scene.provider = ""
        scene.provider_request_id = ""
        scene.failed_at = None
        scene.save()
        record_event(scene.project, "scene_edited", {"scene_key": scene.scene_key})
        self._refresh_script_from_scenes(scene.project)
        return scene

    def reorder_scenes(self, project: VideoProject, scene_keys: list[str]) -> None:
        scenes = {scene.scene_key: scene for scene in project.scenes.all()}
        cursor = 0.0
        for index, key in enumerate(scene_keys, start=1):
            scene = scenes.get(key)
            if not scene:
                continue
            scene.order = index
            meta = dict(scene.metadata or {})
            meta["start_time"] = cursor
            meta["end_time"] = cursor + float(scene.duration or 5)
            cursor = meta["end_time"]
            scene.metadata = meta
            scene.save(update_fields=["order", "metadata"])
        extras = [scene for key, scene in scenes.items() if key not in scene_keys]
        for scene in extras:
            scene.delete()
        self._refresh_script_from_scenes(project)
        record_event(project, "scenes_reordered", {"scene_keys": scene_keys})

    def duplicate_scene(self, scene: Scene) -> Scene:
        project = scene.project
        new_key = f"{scene.scene_key}-copy-{uuid.uuid4().hex[:6]}"
        clone = Scene.objects.create(
            project=project,
            scene_key=new_key,
            order=scene.order + 1,
            title=f"{scene.title} copy" if scene.title else "Copied scene",
            visual=scene.visual,
            narration=scene.narration,
            caption=scene.caption,
            duration=scene.duration,
            metadata={
                **(scene.metadata or {}),
                "status": "draft",
                "approved": False,
                "approved_at": "",
                "generation_id": "",
                "omni_interaction_id": "",
                "seedance_task_id": "",
                "needs_regeneration": False,
            },
        )
        for later in project.scenes.filter(order__gte=clone.order).exclude(pk=clone.pk):
            later.order += 1
            later.save(update_fields=["order"])
        self._retime(project)
        record_event(project, "scene_copied", {"from": scene.scene_key, "to": clone.scene_key})
        return clone

    def delete_scene(self, scene: Scene) -> None:
        project = scene.project
        if project.scenes.count() <= 1:
            raise ValueError("Keep at least one scene.")
        key = scene.scene_key
        scene.delete()
        self._retime(project)
        record_event(project, "scene_deleted", {"scene_key": key})

    def copy_scene_from_concept(self, project: VideoProject, concept_id: str, scene_key: str, *, replace_key: str = "") -> Scene:
        concept = next((item for item in (project.creative_directions or []) if item.get("id") == concept_id), None)
        if not concept:
            raise ValueError("That concept is no longer available.")
        source = next((item for item in (concept.get("scenes") or []) if item.get("scene_key") == scene_key), None)
        if not source:
            raise ValueError("That scene is not in the selected concept.")
        if replace_key:
            existing = project.scenes.filter(scene_key=replace_key).first()
            if not existing:
                raise ValueError("The scene to replace was not found.")
            self._write_timeline_scene(existing, source, existing.order, existing.metadata or {})
            existing.save()
            self._refresh_script_from_scenes(project)
            return existing
        order = project.scenes.count() + 1
        created = Scene.objects.create(
            project=project,
            scene_key=f"{source.get('scene_key') or 'scene'}-{uuid.uuid4().hex[:6]}",
            order=order,
        )
        self._write_timeline_scene(created, source, order, {})
        created.save()
        self._retime(project)
        record_event(project, "scene_copied", {"concept_id": concept_id, "scene_key": scene_key})
        return created

    def approve_scenes(self, project: VideoProject, scene_ids: list[int] | None = None, *, all_scenes: bool = False) -> list[Scene]:
        queryset = project.scenes.all()
        if not all_scenes and scene_ids:
            queryset = queryset.filter(pk__in=scene_ids)
        updated = []
        now = datetime.now(timezone.utc).isoformat()
        for scene in queryset:
            meta = dict(scene.metadata or {})
            meta["approved"] = True
            meta["approved_at"] = now
            meta["status"] = "approved"
            scene.metadata = meta
            scene.save(update_fields=["metadata"])
            updated.append(scene)
        record_event(project, "scenes_approved", {"count": len(updated), "all": all_scenes})
        return updated

    def scene_to_timeline(self, scene: Scene) -> dict:
        meta = scene.metadata or {}
        start = float(meta.get("start_time") or 0)
        duration = float(scene.duration or 5)
        return {
            "id": scene.id,
            "scene_key": scene.scene_key,
            "order": scene.order,
            "title": scene.title,
            "start_time": start,
            "end_time": float(meta.get("end_time") or start + duration),
            "duration": duration,
            "shot_description": meta.get("shot_description") or scene.visual,
            "presenter_action": meta.get("presenter_action") or "",
            "camera_framing": meta.get("camera_framing") or meta.get("camera") or "",
            "camera_movement": meta.get("camera_movement") or "",
            "lighting": meta.get("lighting") or "",
            "pace": meta.get("pace") or "",
            "transition": meta.get("transition") or "",
            "voice_over": scene.narration or meta.get("voice_over") or "",
            "on_screen_caption": scene.caption or meta.get("on_screen_caption") or "",
            "benefit": meta.get("benefit") or "",
            "approved_claim": meta.get("approved_claim") or "",
            "location": meta.get("location") or "",
            "background": meta.get("background") or "",
            "sound_direction": meta.get("sound_direction") or "",
            "composition": meta.get("composition") or "",
            "depth_of_field": meta.get("depth_of_field") or "",
            "lens": meta.get("lens") or "",
            "product_locked": bool(meta.get("product_locked")),
            "presenter_locked": bool(meta.get("presenter_locked")),
            "location_locked": bool(meta.get("location_locked")),
            "script_locked": bool(meta.get("script_locked")),
            "caption_locked": bool(meta.get("caption_locked")),
            "scene_locked": bool(meta.get("scene_locked")),
            "status": meta.get("status") or infer_scene_status(scene),
            "generation_id": scene_generation_id(meta),
            "qa_status": meta.get("qa_status") or "",
            "qa_results": meta.get("qa_results") or [],
            "approved": bool(meta.get("approved")),
            "error": meta.get("error") or "",
            "visual": scene.visual,
            "narration": scene.narration,
            "caption": scene.caption,
            "image_url": _file_url(scene.image),
            "video_url": _file_url(scene.video_clip),
            "audio_url": _file_url(scene.audio),
        }

    def _apply_timeline(self, project: VideoProject, scenes: list[dict], concept: dict) -> None:
        duration = supported_duration(project.duration_seconds or 45)
        brief = project.creative_brief or {}
        if not (brief.get("bulk_preserve_timeline") or brief.get("from_project")):
            scenes = _retarget_timeline(scenes, duration)
        keep = []
        cursor = 0.0
        shots = []
        script_scenes = []
        for index, item in enumerate(scenes, start=1):
            if not isinstance(item, dict):
                continue
            key = str(item.get("scene_key") or f"scene-{index}")[:64]
            existing = Scene.objects.filter(project=project, scene_key=key).first()
            if existing:
                _discard_scene_outputs(existing)
            start = _safe_float(item.get("start_time"), cursor)
            duration = max(
                1.0,
                _safe_float(item.get("duration"), _safe_float(item.get("end_time"), start) - start or 5),
            )
            end = _safe_float(item.get("end_time"), start + duration)
            if end <= start:
                end = start + duration
            scene, _ = Scene.objects.update_or_create(
                project=project,
                scene_key=key,
                defaults={
                    "order": _safe_int(item.get("order"), index),
                    "title": str(item.get("title") or f"Scene {index}")[:200],
                    "visual": str(item.get("shot_description") or item.get("visual") or ""),
                    "narration": str(item.get("voice_over") or item.get("narration") or ""),
                    "caption": str(item.get("on_screen_caption") or item.get("caption") or ""),
                    "duration": duration,
                },
            )
            self._write_timeline_scene(scene, item, index, {})
            scene.metadata = {
                **(scene.metadata or {}),
                "start_time": start,
                "end_time": end,
                "status": "ready",
                "error": "",
                "pipeline_error": {},
            }
            scene.generation_status = "queued"
            scene.failure_code = ""
            scene.failure_message = ""
            scene.provider = ""
            scene.provider_request_id = ""
            scene.failed_at = None
            scene.retry_count = 0
            scene.save()
            keep.append(scene.pk)
            cursor = end
            shots.append(
                {
                    "scene_key": key,
                    "camera": item.get("camera_framing") or item.get("camera") or "",
                    "image_prompt": item.get("shot_description") or scene.visual,
                    "video_prompt": item.get("shot_description") or scene.visual,
                    "on_screen_text": scene.caption,
                }
            )
            script_scenes.append(
                {
                    "scene": index,
                    "scene_key": key,
                    "order": scene.order,
                    "title": scene.title,
                    "visual": scene.visual,
                    "narration": scene.narration,
                    "caption": scene.caption,
                    "duration": scene.duration,
                    "product_facts": [item.get("benefit") or item.get("approved_claim") or ""],
                    "cta": bool(item.get("cta")),
                }
            )
        for extra in project.scenes.exclude(pk__in=keep):
            _discard_scene_outputs(extra)
            extra.delete()
        self._lock_presenter_continuity(project)
        self._stamp_continuity(project, concept)
        self._ensure_commercial_cta(project)
        last = project.scenes.order_by("order").last()
        if last:
            if script_scenes:
                script_scenes[-1]["caption"] = last.caption
                script_scenes[-1]["narration"] = last.narration
            if shots:
                shots[-1]["on_screen_text"] = last.caption
        project.script = {
            "duration_seconds": project.duration_seconds,
            "language": project.language,
            "style": project.speaking_style,
            "hook": concept.get("hook") or "",
            "title": concept.get("title") or "",
            "full_script": " ".join(scene.narration for scene in project.scenes.all()),
            "scenes": script_scenes,
            "cta": concept.get("cta") or "",
            "claims": (project.product_snapshot or {}).get("approved_claims") or [],
            "unsupported_claims": [],
        }
        project.shot_plan = {"shots": shots}
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
                {"scene_key": scene.scene_key, "text": scene.caption, "duration": scene.duration}
                for scene in project.scenes.all()
            ]
        }
        project.save(update_fields=["script", "shot_plan", "narration", "captions", "updated_at"])

    def _stamp_continuity(self, project: VideoProject, concept: dict | None = None) -> None:
        """Lock shared visual continuity once from the approved storyboard."""
        concept = concept or {}
        brief = dict(project.creative_brief or {})
        scenes = list(project.scenes.all().order_by("order"))
        locations = []
        lighting = []
        cameras = []
        for scene in scenes:
            meta = scene.metadata or {}
            place = scene_place(meta)
            if place:
                locations.append(place)
            if meta.get("lighting"):
                lighting.append(str(meta.get("lighting")))
            if meta.get("camera_framing") or meta.get("camera"):
                cameras.append(str(meta.get("camera_framing") or meta.get("camera")))
        identity = presenter_identity_text(project)
        continuity = {
            "location": locations[0] if locations else str(brief.get("location") or concept.get("location") or ""),
            "lighting": lighting[0] if lighting else str(brief.get("lighting") or ""),
            "wardrobe": str(brief.get("wardrobe") or concept.get("wardrobe") or identity or ""),
            "camera_style": cameras[0] if cameras else "",
            "visual_style": str(concept.get("style") or brief.get("style") or ""),
            "product_position": "consistent product placement across every scene",
            "presenter_appearance": identity or "the same approved presenter throughout",
        }
        brief["continuity_state"] = continuity
        style = str(concept.get("style") or brief.get("style") or "").strip().lower()
        if style:
            brief["style"] = style
        brief.setdefault("presenter_locked", True)
        if style in {"faceless_explainer", "faceless"}:
            brief["faceless"] = True
            brief["presenter_locked"] = False
        project.creative_brief = brief
        project.save(update_fields=["creative_brief", "updated_at"])

        # Same location, wardrobe, and lighting stay in the prompt.
        # A scene waits for the previous clip only when the storyboard asks for that frame.
        for index, scene in enumerate(scenes):
            meta = dict(scene.metadata or {})
            if "previous_frame_required" in meta and "requires_previous_scene_continuity" not in meta:
                meta["requires_previous_scene_continuity"] = bool(meta.get("previous_frame_required"))
            elif "requires_previous_scene_continuity" not in meta:
                meta["requires_previous_scene_continuity"] = False
            same_place = index == 0 or not explicit_location_change(
                meta,
                scenes[index - 1].metadata or {},
                continuity.get("location") or "",
            )
            if brief.get("presenter_locked") and not brief.get("faceless"):
                meta["presenter_locked"] = True
            if same_place:
                meta.setdefault("location_locked", True)
                meta.setdefault("product_locked", True)
            if not meta.get("location") and not meta.get("background") and continuity.get("location"):
                meta["location"] = continuity["location"]
            if not meta.get("lighting") and continuity.get("lighting"):
                meta["lighting"] = continuity["lighting"]
            if not meta.get("camera_framing") and continuity.get("camera_style"):
                meta["camera_framing"] = continuity["camera_style"]
            scene.metadata = meta
            scene.save(update_fields=["metadata"])

    def _write_timeline_scene(self, scene: Scene, item: dict, order: int, metadata: dict) -> None:

        preserved_locks = {
            key: metadata.get(key)
            for key in (
                "product_locked",
                "presenter_locked",
                "location_locked",
                "script_locked",
                "caption_locked",
                "scene_locked",
                "requires_previous_scene_continuity",
                "approved",
                "approved_at",
            )
            if key in metadata
        }
        scene.order = _safe_int(item.get("order"), order)
        scene.title = str(item.get("title") or scene.title or f"Scene {order}")[:200]
        if not metadata.get("script_locked"):
            scene.narration = str(item.get("voice_over") or item.get("narration") or scene.narration or "")
        if not metadata.get("caption_locked"):
            scene.caption = str(item.get("on_screen_caption") or item.get("caption") or scene.caption or "")
        if not metadata.get("product_locked"):
            scene.visual = str(item.get("shot_description") or item.get("visual") or scene.visual or "")
        scene.duration = max(1.0, _safe_float(item.get("duration"), scene.duration or 5))
        meta = {
            **metadata,
            "shot_description": scene.visual,
            "presenter_action": item.get("presenter_action") or metadata.get("presenter_action") or "",
            "camera_framing": item.get("camera_framing") or metadata.get("camera_framing") or "",
            "camera_movement": item.get("camera_movement") or metadata.get("camera_movement") or "",
            "lighting": item.get("lighting") or metadata.get("lighting") or "",
            "pace": item.get("pace") or metadata.get("pace") or "",
            "transition": item.get("transition") or metadata.get("transition") or DEFAULT_SCENE_TRANSITION,
            "voice_over": scene.narration,
            "on_screen_caption": scene.caption,
            "benefit": item.get("benefit") or metadata.get("benefit") or "",
            "approved_claim": item.get("approved_claim") or metadata.get("approved_claim") or "",
            "location": item.get("location") or metadata.get("location") or "",
            "background": item.get("background") or metadata.get("background") or "",
            "sound_direction": item.get("sound_direction") or metadata.get("sound_direction") or "",
            "image_prompt": item.get("shot_description") or scene.visual,
            "video_prompt": item.get("shot_description") or scene.visual,
            "camera": item.get("camera_framing") or metadata.get("camera") or "",
            "scene_role": item.get("scene_role") or metadata.get("scene_role") or "",
            "product_locked": True if "product_locked" not in preserved_locks else preserved_locks["product_locked"],
            "status": metadata.get("status") or "ready",
        }
        if not metadata.get("caption_locked") and (scene.narration or scene.caption):
            scene.caption = spoken_caption(scene.narration, scene.caption)
            meta["on_screen_caption"] = scene.caption
        meta.update(preserved_locks)
        scene.metadata = meta

    def _mix_scenes(self, concepts: list[dict], scene_mix: list) -> list[dict]:
        by_concept = {item.get("id"): item for item in concepts}
        mixed = []
        if not isinstance(scene_mix, list):
            return mixed
        for index, item in enumerate(scene_mix, start=1):
            if not isinstance(item, dict):
                continue
            concept = by_concept.get(item.get("concept_id"))
            if not concept:
                continue
            source = next(
                (scene for scene in (concept.get("scenes") or []) if scene.get("scene_key") == item.get("scene_key")),
                None,
            )
            if not source:
                continue
            copied = deepcopy(source)
            copied["order"] = index
            copied["scene_key"] = copied.get("scene_key") or f"scene-{index}"
            if any(existing.get("scene_key") == copied["scene_key"] for existing in mixed):
                copied["scene_key"] = f"{copied['scene_key']}-{index}"
            mixed.append(copied)
        cursor = 0.0
        for scene in mixed:
            duration = max(1.0, _safe_float(scene.get("duration"), 5))
            scene["start_time"] = cursor
            scene["end_time"] = cursor + duration
            cursor += duration
        return mixed

    def _normalize_concepts(
        self,
        concepts: list,
        project: VideoProject,
        brief: dict,
        templates: list[dict],
        duration: int,
        count: int = 3,
    ) -> list[dict]:
        requested = concept_count(count)
        snapshot = project.product_snapshot or {}
        approved_price = str(brief.get("offer_price") or brief.get("price") or snapshot.get("price") or "").strip()
        approved_offer = str(brief.get("offer_text") or brief.get("offer") or snapshot.get("offer") or "").strip()
        original_price = str(brief.get("original_price") or snapshot.get("price") or "").strip()
        cleaned = []
        seen_styles = set()
        seen_ids = set()
        for index, raw in enumerate(concepts, start=1):
            template = templates[index - 1] if index <= len(templates) else {}
            scenes = self._normalize_concept_scenes(
                raw.get("scenes") or [],
                duration,
                approved_price,
                approved_offer,
                original_price,
                snapshot,
            )
            if not scenes:
                continue
            style = str(raw.get("style") or template.get("style") or f"style-{index}").strip()
            if style.lower() in seen_styles:
                style = f"{style} {index}"
            seen_styles.add(style.lower())
            concept_id = str(raw.get("id") or template.get("id") or f"concept-{index}")
            if concept_id in seen_ids:
                concept_id = f"{concept_id}-{index}"
            seen_ids.add(concept_id)
            cleaned.append(
                {
                    "id": concept_id,
                    "title": raw.get("title") or template.get("title") or f"Concept {index}",
                    "style": style,
                    "strategy": raw.get("strategy") or template.get("strategy") or "",
                    "audience_angle": raw.get("audience_angle") or brief.get("customer") or "",
                    "hook": raw.get("hook") or "",
                    "narrative": raw.get("narrative") or "",
                    "cta": self._protect_text(raw.get("cta") or "", approved_price, approved_offer, original_price),
                    "estimated_duration": duration,
                    "why_it_works": raw.get("why_it_works") or template.get("why") or "",
                    "template_id": raw.get("template_id") or template.get("id") or "",
                    "scenes": scenes,
                }
            )
            if len(cleaned) >= requested:
                break
        pad_index = 0
        while len(cleaned) < requested and templates:
            extra = templates[pad_index % len(templates)]
            pad_index += 1
            concept_id = extra["id"]
            if concept_id in seen_ids:
                concept_id = f"{extra['id']}-{len(cleaned) + 1}"
            if concept_id in seen_ids:
                continue
            seen_ids.add(concept_id)
            style = str(extra.get("style") or extra["id"])
            if style.lower() in seen_styles:
                style = f"{style} {len(cleaned) + 1}"
            seen_styles.add(style.lower())
            cleaned.append(
                {
                    "id": concept_id,
                    "title": extra["title"] if extra["id"] == concept_id else f"{extra['title']} {len(cleaned) + 1}",
                    "style": style,
                    "strategy": extra["strategy"],
                    "audience_angle": brief.get("customer") or "",
                    "hook": brief.get("main_benefit") or extra["strategy"],
                    "narrative": extra["strategy"],
                    "cta": _cta_for(brief),
                    "estimated_duration": duration,
                    "why_it_works": extra["why"],
                    "template_id": extra["id"],
                    "scenes": self._fallback_scenes(brief, extra, duration, snapshot),
                }
            )
        return cleaned[:requested]

    def _normalize_concept_scenes(
        self,
        scenes: list,
        duration: int,
        approved_price: str,
        approved_offer: str,
        original_price: str,
        snapshot: dict,
    ) -> list[dict]:
        cleaned = []
        cursor = 0.0
        for index, item in enumerate(scenes, start=1):
            scene_duration = max(1.0, float(item.get("duration") or 5))
            start = float(item.get("start_time") if item.get("start_time") is not None else cursor)
            end = float(item.get("end_time") or (start + scene_duration))
            if end <= start:
                end = start + scene_duration
            scene_duration = end - start
            caption = wrap_caption(
                self._protect_text(
                    item.get("on_screen_caption") or item.get("caption") or "",
                    approved_price,
                    approved_offer,
                    original_price,
                )
            )
            voice = self._protect_text(
                item.get("voice_over") or item.get("narration") or "",
                approved_price,
                approved_offer,
                original_price,
            )
            role = str(item.get("scene_role") or "").strip()
            if role not in SCENE_ROLES:
                role = SCENE_ROLES[min(index - 1, len(SCENE_ROLES) - 1)]
            cleaned.append(
                {
                    "scene_key": item.get("scene_key") or f"scene-{index}",
                    "order": item.get("order") or index,
                    "title": item.get("title") or f"Scene {index}",
                    "start_time": start,
                    "end_time": end,
                    "duration": scene_duration,
                    "shot_description": item.get("shot_description") or item.get("visual") or "",
                    "presenter_action": item.get("presenter_action") or "",
                    "camera_framing": item.get("camera_framing") or "",
                    "camera_movement": item.get("camera_movement") or "",
                    "lighting": item.get("lighting") or "",
                    "pace": item.get("pace") or "",
                    "transition": item.get("transition") or DEFAULT_SCENE_TRANSITION,
                    "voice_over": voice,
                    "on_screen_caption": spoken_caption(voice, caption),
                    "benefit": item.get("benefit") or "",
                    "approved_claim": item.get("approved_claim") or "",
                    "location": item.get("location") or "",
                    "background": item.get("background") or "",
                    "cta": bool(item.get("cta")),
                    "scene_role": role,
                }
            )
            cursor = end
        if not cleaned:
            return []
        cleaned = _retarget_timeline(cleaned, duration)
        last = cleaned[-1]
        last["cta"] = True
        last["scene_role"] = last.get("scene_role") or "hero_cta"
        last["on_screen_caption"] = spoken_caption(
            last.get("voice_over") or "",
            last.get("on_screen_caption")
            or commercial_cta(
                {
                    "offer_price": approved_price,
                    "offer_text": approved_offer,
                    "original_price": original_price,
                    "price": approved_price,
                },
                snapshot,
                "",
            ),
        )
        total = sum(item["duration"] for item in cleaned)
        if total > 0 and abs(total - duration) > 1.5:
            scale = duration / total
            cursor = 0.0
            for item in cleaned:
                item["duration"] = max(1.0, round(item["duration"] * scale, 2))
                item["start_time"] = cursor
                item["end_time"] = cursor + item["duration"]
                cursor = item["end_time"]
        return cleaned

    def _fallback_scenes(self, brief: dict, template: dict, duration: int, snapshot: dict) -> list[dict]:
        chunks = scene_count_for_duration(duration)
        each = round(duration / chunks, 2)
        benefit = brief.get("main_benefit") or snapshot.get("name") or "the product"
        blocked = f"{brief.get('must_not_show') or ''} {brief.get('legacy_instructions') or ''}".lower()
        skip_presenter = any(
            token in blocked
            for token in ("presenter", "hands", "no talent", "product photos only", "supplied product photos")
        )
        titles = ["Hook", "Product in use", "Product detail", "Presenter", "Lifestyle", "Hero + CTA", "Offer", "Close"]
        roles = list(SCENE_ROLES)
        if skip_presenter:
            titles = ["Hook", "Product detail", "Shade close-up", "Texture", "Hero", "Offer", "Close", "CTA"]
            roles = [role for role in SCENE_ROLES if role != "presenter"] or roles
        scenes = []
        cursor = 0.0
        for index in range(chunks):
            title = titles[index] if index < len(titles) else f"Scene {index + 1}"
            voice = benefit if index else (brief.get("customer") or benefit)
            caption = spoken_caption(
                voice,
                benefit if index < chunks - 1 else commercial_cta(brief, snapshot, ""),
            )
            role = roles[index] if index < len(roles) else "hero_cta"
            scenes.append(
                {
                    "scene_key": f"scene-{index + 1}",
                    "order": index + 1,
                    "title": title,
                    "start_time": cursor,
                    "end_time": cursor + each,
                    "duration": each,
                    "shot_description": (
                        f"{template['title']}: {title.lower()} for {snapshot.get('name') or 'the product'}. "
                        + (
                            "Use only the supplied product photos. Simple pan, crop, or zoom. "
                            "Do not add a presenter, hands, packaging, or a new product view."
                            if skip_presenter
                            else ""
                        )
                    ).strip(),
                    "presenter_action": (
                        ""
                        if skip_presenter
                        else ("Present the product naturally to camera." if index else "Open with a clear hook.")
                    ),
                    "camera_framing": "medium close-up" if role != "product_detail" else "tight product detail",
                    "camera_movement": "slow push-in",
                    "lighting": "natural daylight",
                    "pace": "steady",
                    "transition": DEFAULT_SCENE_TRANSITION,
                    "voice_over": voice,
                    "on_screen_caption": caption,
                    "benefit": benefit,
                    "approved_claim": "",
                    "location": "",
                    "background": "",
                    "cta": index == chunks - 1,
                    "scene_role": role,
                }
            )
            cursor += each
        return scenes

    def _protect_text(self, text: str, approved_price: str, approved_offer: str, original_price: str) -> str:
        value = str(text or "")
        if not value:
            return value
        # Never let the model keep an invented RM amount that is not approved.
        import re

        amounts = re.findall(r"(?:RM\s*)?\d+(?:\.\d{1,2})?", value, flags=re.I)
        allowed = {
            _digits(approved_price),
            _digits(approved_offer),
            _digits(original_price),
        }
        allowed.discard("")
        for amount in amounts:
            if _digits(amount) and _digits(amount) not in allowed:
                if approved_price:
                    value = value.replace(amount, approved_price)
                elif original_price:
                    value = value.replace(amount, original_price)
        return value

    def _refresh_script_from_scenes(self, project: VideoProject) -> None:
        self._align_captions_to_speech(project)
        scenes = list(project.scenes.all())
        script = dict(project.script or {})
        script["scenes"] = [
            {
                "scene": scene.order,
                "scene_key": scene.scene_key,
                "order": scene.order,
                "title": scene.title,
                "visual": scene.visual,
                "narration": scene.narration,
                "caption": scene.caption,
                "duration": scene.duration,
            }
            for scene in scenes
        ]
        script["full_script"] = " ".join(scene.narration for scene in scenes)
        script["duration_seconds"] = project.duration_seconds
        project.script = script
        project.shot_plan = {
            "shots": [
                {
                    "scene_key": scene.scene_key,
                    "camera": (scene.metadata or {}).get("camera_framing") or (scene.metadata or {}).get("camera") or "",
                    "image_prompt": (scene.metadata or {}).get("image_prompt") or scene.visual,
                    "video_prompt": (scene.metadata or {}).get("video_prompt") or scene.visual,
                    "on_screen_text": scene.caption,
                }
                for scene in scenes
            ]
        }
        project.narration = {
            "language": project.language,
            "style": project.speaking_style,
            "lines": [{"scene_key": scene.scene_key, "text": scene.narration} for scene in scenes],
        }
        project.captions = {
            "lines": [
                {"scene_key": scene.scene_key, "text": scene.caption, "duration": scene.duration}
                for scene in scenes
            ]
        }
        project.save(update_fields=["script", "shot_plan", "narration", "captions", "updated_at"])

    def _retime(self, project: VideoProject) -> None:
        cursor = 0.0
        for index, scene in enumerate(project.scenes.all(), start=1):
            scene.order = index
            meta = dict(scene.metadata or {})
            meta["start_time"] = cursor
            meta["end_time"] = cursor + float(scene.duration or 5)
            cursor = meta["end_time"]
            scene.metadata = meta
            scene.save(update_fields=["order", "metadata"])
        self._refresh_script_from_scenes(project)

    def _context(self, project: VideoProject, brief: dict) -> str:
        language = LANGUAGE_GUIDE.get(project.language, LANGUAGE_GUIDE["conversational_bm"])
        style = STYLE_GUIDE.get(project.speaking_style, STYLE_GUIDE["warm"])
        identity = presenter_identity_text(project)
        return (
            f"Language: {language}\n"
            f"{speech_lock(project.language)}\n"
            f"Style: {style}\n"
            f"Speaker gender: {getattr(project, 'speaker_gender', 'female')}\n"
            f"Presenter: {identity or 'not specified'}\n"
            f"Location / background: {(brief.get('location') or 'not specified')}\n"
            f"Duration: {brief.get('duration') or project.duration_seconds} seconds\n"
            f"Product snapshot:\n{project.product_snapshot}\n"
            f"Product analysis:\n{project.product_analysis or 'None'}\n"
            f"Creative brief:\n{brief}\n"
            f"{extra_instruction_requirement(brief, project)}\n"
            f"Merchant instructions:\n{getattr(project, 'merchant_instructions', None) or 'None'}\n"
            f"Selected concept: {project.selected_concept_id or 'None'}\n"
        )


def _retarget_timeline(scenes: list[dict], duration: int) -> list[dict]:
    """Fit a concept timeline to the requested length and scene budget."""
    count = scene_count_for_duration(duration)
    rows = [dict(item) for item in scenes]
    if len(rows) > count:
        rows = rows[: count - 1] + [rows[-1]] if count > 1 else rows[:1]
    while len(rows) < count:
        seed = rows[-1] if rows else {}
        index = len(rows) + 1
        rows.append(
            {
                "scene_key": f"scene-{index}",
                "order": index,
                "title": seed.get("title") or f"Scene {index}",
                "shot_description": seed.get("shot_description") or seed.get("visual") or "",
                "presenter_action": seed.get("presenter_action") or "",
                "camera_framing": seed.get("camera_framing") or "",
                "camera_movement": seed.get("camera_movement") or "",
                "lighting": seed.get("lighting") or "",
                "pace": seed.get("pace") or "",
                "transition": seed.get("transition") or DEFAULT_SCENE_TRANSITION,
                "voice_over": seed.get("voice_over") or "",
                "on_screen_caption": seed.get("on_screen_caption") or "",
                "benefit": seed.get("benefit") or "",
                "approved_claim": seed.get("approved_claim") or "",
                "location": seed.get("location") or "",
                "background": seed.get("background") or "",
                "cta": index == count,
                "scene_role": "hero_cta" if index == count else seed.get("scene_role") or "",
            }
        )
    each = round(duration / count, 2)
    cursor = 0.0
    fitted = []
    for index, item in enumerate(rows, start=1):
        scene_duration = round(duration - cursor, 2) if index == count else each
        item = dict(item)
        item["order"] = index
        item["scene_key"] = f"scene-{index}"
        item["duration"] = scene_duration
        item["start_time"] = cursor
        item["end_time"] = round(cursor + scene_duration, 2)
        item["cta"] = index == count
        fitted.append(item)
        cursor = item["end_time"]
    return fitted


def scene_place(meta: dict | None, default: str = "") -> str:
    data = meta or {}
    return str(data.get("location") or data.get("background") or default or "").strip().lower()


def explicit_location_change(meta: dict | None, prev_meta: dict | None, default: str = "") -> bool:
    current = scene_place(meta, default)
    previous = scene_place(prev_meta, default)
    if current and previous and current != previous:
        return True
    transition = str((meta or {}).get("transition") or "").lower()
    return any(
        token in transition
        for token in ("new location", "different location", "change location", "cut to another", "move to")
    )


def continuity_dependents(project: VideoProject, origin: Scene) -> list[Scene]:
    """Scenes after origin that were generated from its last frame."""
    scenes = list(project.scenes.all().order_by("order"))
    started = False
    dependents: list[Scene] = []
    for scene in scenes:
        if scene.pk == origin.pk:
            started = True
            continue
        if not started:
            continue
        if not (scene.metadata or {}).get("requires_previous_scene_continuity"):
            break
        dependents.append(scene)
    return dependents


def mark_continuity_stale(scenes: list[Scene]) -> list[Scene]:
    marked: list[Scene] = []
    for scene in scenes:
        if (scene.metadata or {}).get("scene_locked"):
            break
        meta = dict(scene.metadata or {})
        meta["needs_regeneration"] = True
        meta["continuity_invalid"] = True
        if meta.get("status") not in {"generating", "regenerating"}:
            meta["status"] = "ready"
        scene.metadata = meta
        scene.save(update_fields=["metadata"])
        marked.append(scene)
    return marked


def infer_scene_status(scene: Scene) -> str:
    meta = scene.metadata or {}
    if meta.get("approved"):
        return "approved"
    column = getattr(scene, "generation_status", "") or ""
    if column == "failed":
        return "failed"
    if column == "running":
        return "generating"
    if column == "completed":
        return "generated"
    # A queued scene with no provider failure is waiting to generate.
    # qa_failed left behind after the provider fields were cleared is not a rejection.
    if column in {"", "queued"} and meta.get("status") in {"qa_failed", "failed"}:
        if not getattr(scene, "failure_code", ""):
            return "ready" if scene.video_clip else "draft"
    if meta.get("status") in SCENE_STATUSES:
        return meta["status"]
    if meta.get("needs_regeneration"):
        return "ready"
    if scene.video_clip and (meta.get("qa_status") == "failed"):
        return "qa_failed"
    if scene.video_clip and (meta.get("qa_status") == "warning"):
        return "qa_warning"
    if scene.video_clip:
        return "generated"
    return "draft"


def _as_list(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch == ".")


def _amount_key(value: str) -> str:
    digits = _digits(value)
    if "." in digits:
        digits = digits.rstrip("0").rstrip(".")
    return digits


def _cta_for(brief: dict) -> str:
    return commercial_cta(brief, {}, "")


_PRICE_CURRENCY_RE = re.compile(
    r"^(RM|MYR|USD|SGD|EUR|GBP|AUD|IDR|THB|PHP|CNY|HKD)",
    re.I,
)


def format_approved_price(value: str) -> str:
    """Keep typed currencies. Only add RM to a bare number."""
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    if compact[:1] in {"$", "€", "£"} or _PRICE_CURRENCY_RE.match(compact):
        return text
    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", compact):
        return f"RM{compact}"
    return text


def currency_from_price(value: str) -> str:
    compact = re.sub(r"\s+", "", str(value or "")).upper()
    if not compact:
        return ""
    if compact.startswith(("RM", "MYR")):
        return "MYR"
    if compact.startswith("USD") or compact.startswith("$"):
        return "USD"
    if compact.startswith(("SGD", "S$")):
        return "SGD"
    if compact.startswith(("EUR", "€")):
        return "EUR"
    if compact.startswith(("GBP", "£")):
        return "GBP"
    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", compact):
        return "MYR"
    return ""


def selling_price_text(brief: dict, snapshot: dict | None = None) -> str:
    data = brief or {}
    snap = snapshot or {}
    return format_approved_price(
        data.get("offer_price") or data.get("price") or data.get("original_price") or snap.get("price") or ""
    )


def original_price_text(brief: dict, snapshot: dict | None = None) -> str:
    data = brief or {}
    snap = snapshot or {}
    typed = str(data.get("original_price") or "").strip()
    if typed:
        return format_approved_price(typed)
    return format_approved_price(snap.get("price") or "")


def price_overlay(brief: dict, snapshot: dict | None = None) -> str:
    """On-screen price line from the brief: original, offer, and offer text."""
    data = brief or {}
    snap = snapshot or {}
    original = format_approved_price(data.get("original_price") or "")
    offer = format_approved_price(data.get("offer_price") or "")
    selling = offer or format_approved_price(data.get("price") or "") or original or format_approved_price(
        snap.get("price") or ""
    )
    offer_text = str(data.get("offer_text") or data.get("offer") or snap.get("offer") or "").strip()
    parts = []
    if original and selling and _amount_key(original) != _amount_key(selling):
        parts.append(original)
        parts.append(selling)
    elif selling:
        parts.append(selling)
    if offer_text and offer_text.lower() not in " ".join(parts).lower():
        parts.append(offer_text)
    return " · ".join(parts)


def _price_in_text(text: str, *values: str) -> bool:
    blob = re.sub(r"[\s,]", "", re_norm(text))
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        token = re.sub(r"[\s,]", "", re_norm(raw))
        digits = _digits(raw)
        if token and token in blob:
            return True
        if digits and digits.replace(".", "") and digits.replace(".", "") in blob.replace(".", ""):
            return True
    return False


def commercial_cta(brief: dict, snapshot: dict, language: str = "") -> str:
    name = str(snapshot.get("name") or brief.get("product_name") or "").strip()
    price = "" if suppress_price(brief) else price_overlay(brief, snapshot)
    malay = language in {"conversational_bm", "formal_bm", "bm_english", ""}
    chinese = language in {"chinese", "mandarin_my"}
    cantonese = language == "cantonese"
    hokkien = language == "hokkien"
    if malay:
        actions = {
            "buy": "Dapatkan hari ini",
            "enquire": "Tanya kami",
            "follow": "Follow kami",
            "visit": "Lawati kami",
        }
    elif chinese:
        actions = {
            "buy": "立即选购",
            "enquire": "立刻咨询",
            "follow": "点击关注",
            "visit": "欢迎光临",
        }
    elif cantonese:
        actions = {
            "buy": "即刻買",
            "enquire": "即刻查詢",
            "follow": "記得follow",
            "visit": "歡迎嚟睇",
        }
    elif hokkien:
        actions = {
            "buy": "緊來買喔",
            "enquire": "來問看覓",
            "follow": "記得跟",
            "visit": "歡迎來看喔",
        }
    else:
        actions = {
            "buy": "Shop now",
            "enquire": "Message us",
            "follow": "Follow for more",
            "visit": "Visit us",
        }
    action = actions.get(brief.get("objective") or "buy", actions["buy"])
    parts = [part for part in [name, price, action] if part]
    return " · ".join(parts) or action


def _cta_is_complete(text: str, project: VideoProject) -> bool:
    snapshot = project.product_snapshot or {}
    brief = project.creative_brief or {}
    blob = re_norm(text)
    name = re_norm(snapshot.get("name") or "")
    actions = ("dapatkan", "shop", "beli", "tanya", "message", "follow", "lawati", "visit", "buy")
    has_action = any(word in blob for word in actions)
    prices = [
        brief.get("offer_price") or "",
        brief.get("original_price") or "",
        brief.get("price") or "",
        snapshot.get("price") or "",
        selling_price_text(brief, snapshot),
        format_approved_price(brief.get("offer_price") or ""),
        format_approved_price(brief.get("original_price") or ""),
    ]
    has_approved_price = any(str(value or "").strip() for value in prices)
    has_price = suppress_price(brief) or (not has_approved_price) or _price_in_text(text, *prices)
    mangled = "rmusd" in re.sub(r"[\s,]", "", blob) or "rm$" in re.sub(r"[\s,]", "", blob)
    has_name = bool(name) and name in blob
    return has_action and has_price and not mangled and (has_name or not name)


def re_norm(value) -> str:
    import re

    return re.sub(r"\s+", " ", str(value or "")).strip().lower()
