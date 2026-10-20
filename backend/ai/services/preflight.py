"""Validate a studio video before any external provider job is created."""

from __future__ import annotations

from ai.models import CharacterStatus, LanguageChoice, StyleChoice, VideoProject, VideoProjectStatus
from ai.providers.google.omni import require_omni_key
from ai.services.characters import resolve_voice, uses_master_reference
from ai.services.durations import (
    scene_count_for_duration,
    scene_duration_fits,
    supported_duration,
)
from ai.services.snapshots import generation_blocker, product_snapshot, snapshot_price_amount


class PreflightError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(errors[0] if errors else "This video is not ready to generate.")


def preflight_project(project: VideoProject) -> None:
    errors: list[str] = []
    product = getattr(project, "product", None)
    if product is None:
        errors.append("Choose a product before generating.")
    else:
        snapshot = project.product_snapshot or product_snapshot(product)
        blocker = generation_blocker(snapshot)
        if blocker:
            errors.append(blocker)
        if product.brand_id and project.owner_id and product.brand.owner_id != project.owner_id:
            errors.append("This product belongs to a different company.")

    try:
        duration = supported_duration(project.duration_seconds)
    except ValueError as exc:
        errors.append(str(exc))
        duration = 0

    brief = project.creative_brief or {}
    if brief.get("duration") not in (None, "", duration) and duration:
        try:
            brief_duration = supported_duration(brief.get("duration"))
        except ValueError as exc:
            errors.append(str(exc))
            brief_duration = 0
        if brief_duration and brief_duration != duration:
            errors.append(
                f"The brief says {brief_duration} seconds, but the project says {duration} seconds."
            )

    language = project.language or ""
    if language not in LanguageChoice.values:
        errors.append("Choose a supported language.")
    tone = project.speaking_style or ""
    if tone not in StyleChoice.values:
        errors.append("Choose a supported tone.")

    aspect = str(brief.get("aspect_ratio") or "9:16")
    if aspect != "9:16":
        errors.append("Studio videos are 9:16. Other aspect ratios are not supported.")

    if not project.selected_concept_id and not project.scenes.exists():
        errors.append("Choose a concept and review the storyboard before generating.")
    scenes = list(project.scenes.all())
    if project.selected_concept_id and not scenes:
        errors.append("The storyboard has no scenes.")
    if duration and scenes:
        preserve = bool(brief.get("bulk_preserve_timeline") or brief.get("from_project"))
        expected = scene_count_for_duration(duration)
        if not preserve and len(scenes) != expected:
            errors.append(
                f"A {duration}-second video needs {expected} scenes. This storyboard has {len(scenes)}."
            )
        total = 0.0
        for scene in scenes:
            total += float(scene.duration or 0)
            if not scene_duration_fits(scene.duration or 0):
                errors.append(
                    f"Scene {scene.order} is {scene.duration} seconds. Each scene must be between 3 and 10 seconds."
                )
            if not (scene.visual or scene.narration or scene.caption or scene.title):
                errors.append(f"Scene {scene.order} has no shot, voice-over, or caption.")
        if scenes and abs(total - duration) > 1.5:
            errors.append(
                f"Scene timings add up to {total:.1f} seconds, not the requested {duration} seconds."
            )

    generate_character = bool(brief.get("generate_character"))
    character_id = None if generate_character else brief.get("character_id")
    config = None
    try:
        config = project.character_config
    except Exception:
        config = None
    if not generate_character and config is not None and config.character_id:
        character_id = config.character_id
    style_key = str(brief.get("style") or brief.get("template_id") or "").strip().lower()
    faceless = style_key in {"faceless_explainer", "faceless"} or bool(brief.get("faceless"))
    selected = next(
        (item for item in (project.creative_directions or []) if item.get("id") == project.selected_concept_id),
        None,
    )
    if selected and str(selected.get("style") or "").strip().lower() in {"faceless_explainer", "faceless"}:
        faceless = True

    if not faceless and (brief.get("presenter_locked") is True or brief.get("lock_presenter") is True):
        if not character_id and not brief.get("generate_character"):
            errors.append(
                "Select a character or check Generate character before creating this video."
            )

    price = str(brief.get("offer_price") or brief.get("price") or (project.product_snapshot or {}).get("price") or "").strip()
    currency = str(brief.get("currency") or brief.get("price_currency") or (project.product_snapshot or {}).get("currency") or "").strip()
    if not currency:
        from ai.services.director import currency_from_price

        currency = currency_from_price(price)
    cta = str(
        brief.get("cta")
        or brief.get("call_to_action")
        or (selected or {}).get("cta")
        or ""
    ).strip()
    has_story = bool(scenes)
    if project.selected_concept_id and not has_story:
        if not price:
            errors.append("Set a valid product price before generating.")
        if not cta:
            errors.append("Set a CTA before generating.")
    if (
        snapshot_price_amount({"price": price}) > 0
        and not currency
        and price.replace(".", "", 1).replace(",", "", 1).isdigit()
    ):
        errors.append("Set a currency separate from the price (for example USD or MYR).")

    if character_id:
        from ai.models import Character

        character = Character.objects.filter(pk=character_id, owner=project.owner).first()
        if character is None or character.status != CharacterStatus.ACTIVE:
            errors.append("The selected character is no longer available.")
        elif product is not None and character.brand_id != product.brand_id:
            errors.append("Choose a character from this product's brand.")
        elif character is not None:
            if not faceless:
                from ai.services.master_character import MASTER_REQUIRED_ERROR, character_is_video_ready

                frozen_master = uses_master_reference(config)
                legacy_snapshot = (
                    config is not None
                    and not frozen_master
                    and bool(config.reference_snapshot)
                    and project.status != VideoProjectStatus.DRAFT
                )
                if not frozen_master and not legacy_snapshot and not character_is_video_ready(character):
                    errors.append(MASTER_REQUIRED_ERROR)
            voice_id = ""
            voice_language = language
            voice_gender = project.speaker_gender
            if config is not None:
                voice_id = config.voice_id or ""
                voice_language = config.language or language
                voice_gender = config.gender or voice_gender
            try:
                resolve_voice(voice_language, voice_gender, voice_id)
            except ValueError as exc:
                errors.append(str(exc))

    try:
        require_omni_key()
    except Exception as exc:
        errors.append(str(exc))

    if errors:
        raise PreflightError(errors)
