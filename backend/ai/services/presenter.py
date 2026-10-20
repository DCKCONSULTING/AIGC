from __future__ import annotations

from pathlib import Path

from django.core.exceptions import ObjectDoesNotExist

from ai.models import Scene, VideoAsset, VideoProject

PRESENTER_ETHNICITY_PRESETS = (
    ("european", "European"),
    ("chinese", "Chinese"),
    ("malaysian_chinese", "Malaysian Chinese"),
    ("malay", "Malay"),
    ("indian", "Indian"),
    ("african", "African"),
    ("middle_eastern", "Middle Eastern"),
    ("japanese", "Japanese"),
    ("korean", "Korean"),
    ("southeast_asian", "Southeast Asian"),
    ("latino", "Latino / Hispanic"),
    ("mixed", "Mixed heritage"),
)

PRESENTER_ANGLES = ("front", "left", "right", "up", "down")

PRESENTER_ASSET_MARKERS = frozenset(
    {"presenter_reference", "presenter_identity", "presenter_photo"}
)


def preset_label(value: str) -> str:
    lookup = {item[0]: item[1] for item in PRESENTER_ETHNICITY_PRESETS}
    return lookup.get(value, value.replace("_", " ").strip())


def presenter_from_brief(project: VideoProject | None) -> dict:
    if not project:
        return {}
    brief = project.creative_brief or {}
    raw = brief.get("presenter") or {}
    if not isinstance(raw, dict):
        raw = {}
    ethnicity = str(raw.get("ethnicity") or "").strip()
    custom = str(raw.get("ethnicity_custom") or raw.get("custom") or "").strip()
    if ethnicity in {"custom", "other"}:
        ethnicity = custom or ethnicity
    label = str(raw.get("ethnicity_label") or "").strip()
    if not label:
        label = custom if custom and ethnicity in {custom, "custom", "other"} else preset_label(ethnicity)
    gender = str(raw.get("gender") or getattr(project, "speaker_gender", "") or "female").strip()
    look = str(raw.get("look") or "").strip()
    mode = str(raw.get("mode") or "").strip() or ("upload" if presenter_image_paths(project) else "generated")
    if not ethnicity and not custom and not look and mode != "upload":
        return {
            "ethnicity": "",
            "ethnicity_label": "",
            "ethnicity_custom": "",
            "gender": gender,
            "look": look,
            "mode": mode,
        }
    return {
        "ethnicity": ethnicity,
        "ethnicity_label": label,
        "ethnicity_custom": custom,
        "gender": gender,
        "look": look,
        "mode": mode,
    }


def _character_identity_text(project: VideoProject | None, *, include_labels: bool = True) -> str:
    if not project or not getattr(project, "pk", None):
        return ""
    try:
        config = project.character_config
    except ObjectDoesNotExist:
        return ""
    identity = config.identity_snapshot or {}
    appearance = str(config.appearance_snapshot or identity.get("appearance") or "").strip()
    name = str(identity.get("name") or identity.get("character_name") or "").strip()
    wardrobe = str(identity.get("wardrobe") or "").strip()
    master = bool(identity.get("master_reference_image") or identity.get("master_reference_version"))
    parts = []
    if master:
        parts.append("The master character reference is the identity source of truth.")
        if include_labels and name:
            parts.append(f"Character identifier: {name} (id {identity.get('id') or config.character_id}). The name is not the face.")
        if appearance:
            parts.append(appearance)
        if wardrobe:
            parts.append(f"Wardrobe: {wardrobe}")
        parts.append("Preserve the same person shown in the master reference. Do not generate a different face.")
        return ". ".join(parts)
    if not name and not appearance:
        return ""
    if include_labels and name:
        parts.append(f"Character {name} (id {identity.get('id') or config.character_id})")
    if appearance:
        parts.append(appearance)
    if wardrobe:
        parts.append(f"Wardrobe: {wardrobe}")
    parts.append("Keep this exact person. Do not generate a different face.")
    return ". ".join(parts)


def presenter_identity_text(project: VideoProject | None, *, include_labels: bool = True) -> str:
    character_text = _character_identity_text(project, include_labels=include_labels)
    data = presenter_from_brief(project)
    if not data:
        return character_text
    if not (data.get("ethnicity") or data.get("ethnicity_label") or data.get("look") or data.get("mode") == "upload"):
        return character_text
    parts = []
    label = data.get("ethnicity_label") or data.get("ethnicity") or ""
    gender = data.get("gender") or getattr(project, "speaker_gender", "") or "female"
    if label:
        parts.append(f"{label} {gender} presenter")
    elif data.get("look"):
        parts.append(f"{gender} presenter")
    if data.get("look"):
        parts.append(data["look"])
    if data.get("mode") == "upload":
        parts.append("Use the supplied presenter photographs as the only identity reference.")
    base = ". ".join(part.strip(" .") for part in parts if part).strip()
    if character_text and base:
        return f"{character_text}. {base}"
    return character_text or base


def presenter_should_appear(project: VideoProject | None, scenes: list[Scene] | None = None) -> bool:
    if not project:
        return False
    brief = project.creative_brief or {}
    blocked = f"{brief.get('must_not_show') or ''} {brief.get('legacy_instructions') or ''}".lower()
    if any(
        token in blocked
        for token in ("no presenter", "no talent", "product photos only", "supplied product photos")
    ):
        return False
    if presenter_identity_text(project) or presenter_image_paths(project):
        return True
    if brief.get("generate_character"):
        return True
    work = scenes if scenes is not None else list(project.scenes.all())
    return any((scene.metadata or {}).get("presenter_action") for scene in work)


def presenter_image_paths(project: VideoProject | None) -> list[str]:
    if not project:
        return []
    paths: list[str] = []
    seen: set[str] = set()
    ordered = []
    for asset in project.assets.filter(kind=VideoAsset.Kind.IMAGE).order_by("id"):
        meta = asset.metadata or {}
        prompt = (asset.prompt or "").strip()
        if not (
            any(meta.get(flag) for flag in PRESENTER_ASSET_MARKERS)
            or prompt in {"presenter-reference", "presenter-identity"}
        ):
            continue
        if not asset.file:
            continue
        path = Path(asset.file.path)
        if not path.exists():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        ordered.append((str(meta.get("angle") or ""), str(path)))
    preferred = {angle: index for index, angle in enumerate(PRESENTER_ANGLES)}
    ordered.sort(key=lambda item: preferred.get(item[0], 99))
    for _, path in ordered:
        paths.append(path)
    return paths


def stamp_presenter_reference(project: VideoProject, path: str | None = None) -> None:
    refs = [path] if path else presenter_image_paths(project)
    if not refs:
        return
    primary = refs[0]
    identity = presenter_identity_text(project)
    for scene in project.scenes.all():
        meta = dict(scene.metadata or {})
        meta["presenter_reference"] = primary
        meta["presenter_locked"] = True
        if identity:
            meta["presenter_identity"] = identity
        scene.metadata = meta
        Scene.objects.filter(pk=scene.pk).update(metadata=meta)


def normalize_presenter_payload(raw: dict | None, *, gender: str = "") -> dict:
    data = dict(raw or {})
    ethnicity = str(data.get("ethnicity") or "").strip()
    custom = str(data.get("ethnicity_custom") or data.get("custom") or "").strip()
    if ethnicity in {"custom", "other"} and custom:
        ethnicity_key = "custom"
        label = custom
    elif custom and ethnicity not in {item[0] for item in PRESENTER_ETHNICITY_PRESETS}:
        ethnicity_key = "custom"
        label = custom
        ethnicity = custom
    else:
        ethnicity_key = ethnicity
        label = str(data.get("ethnicity_label") or "").strip() or preset_label(ethnicity)
    look = str(data.get("look") or "").strip()
    mode = str(data.get("mode") or "").strip()
    return {
        "ethnicity": ethnicity if ethnicity_key != "custom" else custom or ethnicity,
        "ethnicity_key": ethnicity_key,
        "ethnicity_label": label,
        "ethnicity_custom": custom,
        "gender": str(data.get("gender") or gender or "").strip(),
        "look": look,
        "mode": mode,
    }
