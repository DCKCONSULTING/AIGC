from __future__ import annotations

import re
from django.core.files.base import ContentFile
from django.utils.text import slugify

from ai.models import StyleRecipe, VideoAsset, VideoProject, VideoProjectStatus
from ai.services.director import DirectorService, commercial_cta, normalize_brief, record_event
from ai.services.presenter import (
    presenter_from_brief,
    presenter_identity_text,
    presenter_image_paths,
    stamp_presenter_reference,
)
from ai.services.snapshots import product_snapshot
from ai.tasks import enqueue_video_generation


MAX_BULK = 10


def recipe_from_project(project: VideoProject) -> dict:
    brief = project.creative_brief or {}
    presenter = presenter_from_brief(project)
    scenes = []
    locations = []
    lighting = []
    for scene in project.scenes.all():
        meta = scene.metadata or {}
        location = meta.get("location") or meta.get("background") or brief.get("location") or ""
        light = meta.get("lighting") or ""
        if location:
            locations.append(str(location))
        if light:
            lighting.append(str(light))
        scenes.append(
            {
                "order": scene.order,
                "title": scene.title,
                "scene_role": meta.get("scene_role") or "",
                "duration": scene.duration,
                "camera_framing": meta.get("camera_framing") or meta.get("camera") or "",
                "camera_movement": meta.get("camera_movement") or "",
                "lighting": light,
                "location": location,
                "background": meta.get("background") or "",
                "pace": meta.get("pace") or "",
                "transition": meta.get("transition") or "",
                "presenter_action": meta.get("presenter_action") or "",
                "shot_shape": meta.get("shot_description") or scene.visual or "",
            }
        )
    concept = next(
        (
            item
            for item in (project.creative_directions or [])
            if item.get("id") == project.selected_concept_id
        ),
        {},
    )
    return {
        "language": project.language,
        "speaking_style": project.speaking_style,
        "speaker_gender": project.speaker_gender,
        "duration_seconds": project.duration_seconds,
        "presenter": presenter,
        "location": brief.get("location") or (locations[0] if locations else ""),
        "lighting": lighting[0] if lighting else "",
        "template_id": concept.get("template_id") or "",
        "style_title": concept.get("title") or concept.get("style") or "",
        "must_remain_exact": brief.get("must_remain_exact") or ["product_appearance", "product_name", "price", "presenter"],
        "objective": brief.get("objective") or "",
        "platform": brief.get("platform") or "",
        "scene_blueprint": scenes,
    }


def save_recipe(
    *,
    owner,
    project: VideoProject,
    name: str,
    key: str = "",
) -> StyleRecipe:
    label = (name or "").strip() or (project.product.name if project.product_id else "Studio style")
    slug = slugify(key or label)[:64] or f"style-{project.pk}"
    recipe = recipe_from_project(project)
    obj, _created = StyleRecipe.objects.update_or_create(
        owner=owner,
        key=slug,
        defaults={
            "name": label[:120],
            "source_project": project,
            "recipe": recipe,
        },
    )
    _copy_presenter_files(project, obj)
    brief = dict(project.creative_brief or {})
    brief["style_key"] = obj.key
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])
    record_event(project, "style_saved", {"key": obj.key, "name": obj.name})
    return obj


def apply_recipe_to_project(
    project: VideoProject,
    recipe: StyleRecipe | dict,
    *,
    overrides: dict | None = None,
) -> VideoProject:
    payload = dict(recipe.recipe if isinstance(recipe, StyleRecipe) else recipe or {})
    changes = dict(overrides or {})
    previous_character = (project.creative_brief or {}).get("character_id")
    if changes.get("language"):
        payload["language"] = changes["language"]
    if changes.get("speaking_style") or changes.get("style"):
        payload["speaking_style"] = changes.get("speaking_style") or changes.get("style")
    if changes.get("speaker_gender") or changes.get("gender"):
        payload["speaker_gender"] = changes.get("speaker_gender") or changes.get("gender")
    if changes.get("location") or changes.get("background"):
        payload["location"] = changes.get("location") or changes.get("background")
    if changes.get("presenter"):
        payload["presenter"] = {**(payload.get("presenter") or {}), **dict(changes["presenter"])}
    else:
        presenter = dict(payload.get("presenter") or {})
        if changes.get("ethnicity") or changes.get("presenter_ethnicity"):
            value = str(changes.get("ethnicity") or changes.get("presenter_ethnicity") or "").strip()
            presenter["ethnicity"] = value
            presenter["ethnicity_label"] = value.replace("_", " ")
        if changes.get("ethnicity_custom"):
            presenter["ethnicity_custom"] = changes["ethnicity_custom"]
            presenter["ethnicity"] = changes["ethnicity_custom"]
            presenter["ethnicity_label"] = changes["ethnicity_custom"]
        if changes.get("look"):
            presenter["look"] = changes["look"]
        payload["presenter"] = presenter

    if payload.get("language"):
        project.language = payload["language"]
    if payload.get("speaking_style"):
        project.speaking_style = payload["speaking_style"]
    if payload.get("speaker_gender"):
        project.speaker_gender = payload["speaker_gender"]
    if payload.get("duration_seconds"):
        project.duration_seconds = int(payload["duration_seconds"])

    brief = normalize_brief(
        {
            **(project.creative_brief or {}),
            "objective": payload.get("objective") or (project.creative_brief or {}).get("objective") or "buy",
            "duration": payload.get("duration_seconds") or project.duration_seconds,
            "must_remain_exact": payload.get("must_remain_exact")
            or ["product_appearance", "product_name", "price", "presenter"],
            "platform": payload.get("platform") or "",
            "location": payload.get("location") or "",
            "presenter": payload.get("presenter") or {},
            "style_key": getattr(recipe, "key", "") if isinstance(recipe, StyleRecipe) else changes.get("style_key") or "",
        },
        project,
    )
    brief["location"] = payload.get("location") or brief.get("location") or ""
    brief["presenter"] = payload.get("presenter") or {}
    if isinstance(recipe, StyleRecipe):
        brief["style_key"] = recipe.key
    project.creative_brief = brief
    project.save(
        update_fields=[
            "language",
            "speaking_style",
            "speaker_gender",
            "duration_seconds",
            "creative_brief",
            "updated_at",
        ]
    )
    if isinstance(recipe, StyleRecipe):
        _attach_recipe_presenter(recipe, project)
    _apply_blueprint(project, payload)
    character_id = changes.get("character_id") or previous_character or (project.creative_brief or {}).get("character_id")
    if character_id:
        from ai.services.characters import sync_project_character

        sync_project_character(
            project,
            character_id,
            language=project.language,
            tone=project.speaking_style,
            gender=project.speaker_gender,
            voice_id=str((overrides or {}).get("voice_id") or ""),
        )
    return project


def bulk_create_from_recipe(
    *,
    owner,
    recipe: StyleRecipe,
    products,
    overrides: dict | None = None,
) -> list[VideoProject]:
    source = getattr(recipe, "source_project", None)
    if source is None or str(getattr(source, "qa_status", "") or "").lower() not in {"passed", "pass"}:
        raise ValueError(
            "Bulk generation requires a master video that has passed QA. "
            "Generate and approve one video first, then save its Style Key."
        )
    created: list[VideoProject] = []
    for product in list(products)[:MAX_BULK]:
        project = VideoProject.objects.create(
            owner=owner,
            product=product,
            product_snapshot=product_snapshot(product),
            language=recipe.recipe.get("language") or "conversational_bm",
            speaking_style=recipe.recipe.get("speaking_style") or "warm",
            speaker_gender=recipe.recipe.get("speaker_gender") or "female",
            duration_seconds=int(recipe.recipe.get("duration_seconds") or 45),
            status=VideoProjectStatus.QUEUED,
            stage_label="Queued",
            progress=2,
        )
        apply_recipe_to_project(project, recipe, overrides=overrides)
        project.status = VideoProjectStatus.QUEUED
        project.stage_label = "Queued"
        project.progress = 2
        project.save(update_fields=["status", "stage_label", "progress", "updated_at"])
        enqueue_video_generation(project.pk)
        created.append(project)
    return created


def _apply_blueprint(project: VideoProject, payload: dict) -> None:
    blueprint = list(payload.get("scene_blueprint") or [])
    if not blueprint:
        return
    snapshot = project.product_snapshot or {}
    brief = project.creative_brief or {}
    name = snapshot.get("name") or getattr(project.product, "name", "the product")
    benefit = brief.get("main_benefit") or name
    location = payload.get("location") or brief.get("location") or ""
    scenes = []
    cursor = 0.0
    for index, item in enumerate(blueprint, start=1):
        duration = float(item.get("duration") or 5)
        shot = re.sub(
            r"\bfor\s+.+?\.?\s*$",
            f"for {name}.",
            str(item.get("shot_shape") or item.get("shot_description") or ""),
            count=1,
            flags=re.I,
        ) or f"{item.get('title') or f'Scene {index}'} for {name}."
        if location:
            shot = f"{shot} Background: {location}."
        caption = commercial_cta(brief, snapshot, project.language) if index == len(blueprint) else benefit
        scenes.append(
            {
                "scene_key": item.get("scene_key") or f"scene-{index}",
                "order": item.get("order") or index,
                "title": item.get("title") or f"Scene {index}",
                "start_time": cursor,
                "end_time": cursor + duration,
                "duration": duration,
                "shot_description": shot,
                "presenter_action": item.get("presenter_action") or "Present the product naturally to camera.",
                "camera_framing": item.get("camera_framing") or "medium close-up",
                "camera_movement": item.get("camera_movement") or "slow push-in",
                "lighting": item.get("lighting") or payload.get("lighting") or "natural daylight",
                "pace": item.get("pace") or "steady",
                "transition": item.get("transition") or "cut",
                "voice_over": benefit,
                "on_screen_caption": caption,
                "benefit": benefit,
                "location": location or item.get("location") or "",
                "background": location or item.get("background") or "",
                "cta": index == len(blueprint),
                "scene_role": item.get("scene_role") or "",
            }
        )
        cursor += duration
    concept = {
        "id": f"style-{payload.get('template_id') or 'recipe'}",
        "title": payload.get("style_title") or "Saved style",
        "style": project.speaking_style,
        "strategy": "Reuse the approved visual style with this product.",
        "hook": benefit,
        "narrative": benefit,
        "cta": commercial_cta(brief, snapshot, project.language),
        "template_id": payload.get("template_id") or "",
        "scenes": scenes,
    }
    director = DirectorService()
    director._apply_timeline(project, scenes, concept)
    project.selected_concept_id = concept["id"]
    project.creative_directions = [concept]
    project.save(update_fields=["selected_concept_id", "creative_directions", "script", "shot_plan", "updated_at"])
    stamp_presenter_reference(project)


def _copy_presenter_files(project: VideoProject, recipe: StyleRecipe) -> None:
    paths = presenter_image_paths(project)
    presenter = dict(recipe.recipe.get("presenter") or {})
    presenter["has_photos"] = bool(paths)
    recipe.recipe = {**recipe.recipe, "presenter": presenter}
    recipe.save(update_fields=["recipe", "updated_at"])


def _attach_recipe_presenter(recipe: StyleRecipe, project: VideoProject) -> None:
    source = recipe.source_project
    if not source or source.pk == project.pk:
        return
    for asset in source.assets.filter(kind=VideoAsset.Kind.IMAGE).order_by("id"):
        meta = dict(asset.metadata or {})
        if not (meta.get("presenter_reference") or meta.get("presenter_identity") or meta.get("presenter_photo")):
            continue
        if not asset.file:
            continue
        clone = VideoAsset(
            project=project,
            kind=VideoAsset.Kind.IMAGE,
            prompt=asset.prompt or "presenter-reference",
            metadata={**meta, "presenter_reference": True, "from_style_key": recipe.key},
        )
        asset.file.open("rb")
        try:
            clone.file.save(asset.file.name.split("/")[-1], ContentFile(asset.file.read()), save=True)
        finally:
            asset.file.close()
    stamp_presenter_reference(project)
