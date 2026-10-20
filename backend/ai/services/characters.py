"""Reusable characters. Identity is shared; each video keeps its own snapshot.

Voice selection is a preference, not proof of the soundtrack.

``default_voice_provider``, ``default_voice_id``, and ``default_voice_name`` (and the
same fields on ``VideoCharacterConfig``) record the requested Google TTS catalog voice.
That id is copied into the Omni scene prompt as a preferred speaking voice.

Gemini Omni generates the scene and its spoken audio together. ``GeminiOmniProvider.start``
does not accept a voice id, and this pipeline does not run Google TTS as a second stage
or replace Omni's audio in FFmpeg. ``voice_id`` must not be treated as evidence that the
final MP4 was synthesized by that exact Google voice.

Regeneration reads ``VideoCharacterConfig`` (appearance, reference storage names, language,
tone, gender, and the preferred voice). It does not re-read the live Character defaults.
Scene ``metadata["character_id"]`` stores the primary character so a later per-scene cast
can be added. Generation still uses one primary character per video.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

from accounts.authentication import acting_brand_id
from ai.models import (
    Character,
    CharacterMasterReference,
    CharacterReferenceImage,
    CharacterStatus,
    CharacterView,
    GenderChoice,
    LanguageChoice,
    MasterReferenceStatus,
    Scene,
    StyleChoice,
    VideoAsset,
    VideoCharacterConfig,
    VideoProject,
    VideoProjectStatus,
)
from ai.providers.google.speech import GENDER_VOICE, LANGUAGE_VOICE, voice_for
from ai.services.presenter import PRESENTER_ANGLES, stamp_presenter_reference
from ai.services.script import LANGUAGE_CODES, speech_lock

MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
ANGLE_ORDER = {angle: index for index, angle in enumerate((*PRESENTER_ANGLES, "other"))}
VOICE_ROLE = "preference"


class CharacterError(ValueError):
    pass


def voice_catalog() -> list[dict]:
    """Real Google TTS voice ids already used by the speech provider. Studio audio stays on Omni."""
    languages_for_code: dict[str, list[str]] = {}
    for language, spec in LANGUAGE_VOICE.items():
        languages_for_code.setdefault(spec["language_code"], []).append(language)
    rows = []
    seen: set[tuple[str, str, str]] = set()
    for gender, mapping in GENDER_VOICE.items():
        for code, name in mapping.items():
            for language in languages_for_code.get(code, []):
                key = (language, gender, name)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "provider": "google_tts",
                        "voice_id": name,
                        "voice_name": name,
                        "gender": gender,
                        "language": language,
                        "language_code": code,
                    }
                )
    return rows


def resolve_voice(language: str, gender: str, voice_id: str = "") -> dict:
    language = language if language in LanguageChoice.values else LanguageChoice.CONVERSATIONAL_BM
    gender = gender if gender in GenderChoice.values else GenderChoice.FEMALE
    expected = voice_for(language, gender)
    chosen = (voice_id or "").strip()
    if not chosen:
        return {
            "voice_provider": "google_tts",
            "voice_id": expected["name"],
            "voice_name": expected["name"],
        }
    match = next(
        (
            row
            for row in voice_catalog()
            if row["voice_id"] == chosen and row["language"] == language and row["gender"] == gender
        ),
        None,
    )
    if not match:
        match = next(
            (row for row in voice_catalog() if row["voice_id"] == chosen and row["language"] == language),
            None,
        )
    if not match or match["language_code"] != expected["language_code"]:
        raise CharacterError("Choose a voice that matches this language.")
    return {
        "voice_provider": "google_tts",
        "voice_id": match["voice_id"],
        "voice_name": match["voice_name"],
    }


def visible_characters(user, request=None, *, include_archived: bool = False):
    queryset = Character.objects.filter(owner=user).select_related("brand", "current_master").prefetch_related(
        "references",
        "master_versions",
    )
    del request
    if not include_archived:
        queryset = queryset.filter(status=CharacterStatus.ACTIVE)
    return queryset.annotate(video_count=Count("video_configs", distinct=True))


def get_owned_character(user, pk, *, include_archived: bool = True) -> Character:
    character = Character.objects.filter(pk=pk, owner=user).select_related("brand", "current_master").prefetch_related(
        "references",
        "master_versions",
    ).first()
    if not character:
        raise Character.DoesNotExist()
    if not include_archived and character.status != CharacterStatus.ACTIVE:
        raise Character.DoesNotExist()
    return character


def _choice_values(choices) -> set[str]:
    if hasattr(choices, "values"):
        return set(choices.values)
    return {item[0] if isinstance(item, tuple) else item for item in choices}


def _require_choice(value: str, choices, label: str) -> str:
    text = str(value or "").strip()
    if text not in _choice_values(choices):
        raise CharacterError(f"Choose a supported {label}.")
    return text


def _image_bytes(upload) -> tuple[str, bytes]:
    name = (getattr(upload, "name", "") or "reference.jpg").strip() or "reference.jpg"
    if hasattr(upload, "seek"):
        upload.seek(0)
    data = upload.read()
    if hasattr(upload, "seek"):
        upload.seek(0)
    return name, data


def validate_image_upload(upload) -> bytes:
    name, data = _image_bytes(upload)
    lowered = name.lower()
    content = (getattr(upload, "content_type", "") or "").lower()
    allowed_types = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    if not (content in allowed_types or lowered.endswith(IMAGE_SUFFIXES)):
        raise CharacterError("Upload a PNG, JPG, or WebP image.")
    if not data:
        raise CharacterError("That image file was empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise CharacterError("Each reference image must be 8 MB or smaller.")
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise CharacterError("That image file could not be read.") from exc
    return data


def front_source_path(character: Character) -> Path | None:
    """The original front photo only. Never pick a side or random angle."""
    if character.source_front_image:
        try:
            path = Path(character.source_front_image.path)
            if path.is_file():
                return path
        except (ValueError, OSError):
            pass
    front = character.references.filter(view_type=CharacterView.FRONT).order_by("sort_order", "id").first()
    if front and front.image:
        try:
            path = Path(front.image.path)
            if path.is_file():
                return path
        except (ValueError, OSError):
            pass
    return None


def persist_front_source(character: Character, source: Path | None = None) -> None:
    """Copy the front photo onto source_front_image without touching the master."""
    path = source or front_source_path(character)
    if path is None or not path.is_file():
        return
    current = ""
    if character.source_front_image:
        try:
            current = str(Path(character.source_front_image.path).resolve())
        except (ValueError, OSError):
            current = ""
    if current and current == str(path.resolve()):
        return
    character.source_front_image.save(path.name, ContentFile(path.read_bytes()), save=True)


def uses_master_reference(config: VideoCharacterConfig | None) -> bool:
    if config is None:
        return False
    identity = config.identity_snapshot or {}
    return bool(identity.get("master_reference_image") or identity.get("master_reference_version"))


def master_reference_path(config: VideoCharacterConfig | None) -> Path | None:
    if config is None:
        return None
    identity = config.identity_snapshot or {}
    name = str(identity.get("master_reference_image") or "").strip()
    if name:
        path = Path(settings.MEDIA_ROOT) / name
        if path.is_file():
            return path
    try:
        for asset in config.project.assets.filter(kind=VideoAsset.Kind.IMAGE).order_by("id"):
            meta = asset.metadata or {}
            if not meta.get("master_reference"):
                continue
            if asset.file and Path(asset.file.path).is_file():
                return Path(asset.file.path)
    except Exception:
        pass
    return None


def _save_reference(character: Character, upload, view_type: str, sort_order: int) -> CharacterReferenceImage:
    name, _ = _image_bytes(upload)
    data = validate_image_upload(upload)
    view = view_type if view_type in CharacterView.values else CharacterView.OTHER
    if view != CharacterView.OTHER:
        character.references.filter(view_type=view).delete()
    ref = CharacterReferenceImage(character=character, view_type=view, sort_order=sort_order)
    ref.image.save(name, ContentFile(data), save=True)
    return ref


def _uploads_from_request(request) -> list[tuple[str, object]]:
    found = []
    seen = set()
    for angle in (*PRESENTER_ANGLES, "other"):
        upload = request.FILES.get(f"reference_{angle}") or request.FILES.get(f"presenter_{angle}")
        if upload:
            found.append((angle, upload))
            seen.add(id(upload))
    extras = list(request.FILES.getlist("reference_image")) + list(request.FILES.getlist("reference_images"))
    extras += list(request.FILES.getlist("photo")) + list(request.FILES.getlist("image"))
    views = request.data.getlist("reference_view") if hasattr(request.data, "getlist") else []
    for index, upload in enumerate(extras):
        if id(upload) in seen:
            continue
        view = str(views[index] if index < len(views) else "front" if not found else "other")
        found.append((view, upload))
        seen.add(id(upload))
    if not found:
        for key in request.FILES:
            upload = request.FILES.get(key)
            if not upload or id(upload) in seen:
                continue
            content = (getattr(upload, "content_type", "") or "").lower()
            name = (getattr(upload, "name", "") or "").lower()
            if content.startswith("image/") or name.endswith(IMAGE_SUFFIXES):
                found.append(("front" if not found else "other", upload))
                seen.add(id(upload))
    return found


def _expected_upload_count(request) -> int:
    raw = request.data.get("reference_count") if request is not None else None
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _require_visual(character: Character) -> None:
    if character.appearance_description.strip() or character.references.exists() or character.source_front_image:
        return
    raise CharacterError("Add an appearance description or one front-facing photo.")


def apply_character_fields(character: Character, data: dict, *, partial: bool = False) -> Character:
    if not partial or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise CharacterError("Character name is required.")
        character.name = name[:120]
    if not partial or "description" in data:
        character.description = str(data.get("description") or "").strip()
    if not partial or "gender" in data:
        gender = str(data.get("gender") or "").strip()
        if gender not in GenderChoice.values:
            raise CharacterError("Choose Female, Male, or Neutral. Gender is not guessed from the name.")
        character.gender = gender
    if not partial or "appearance_description" in data:
        character.appearance_description = str(data.get("appearance_description") or data.get("appearance") or "").strip()
    if not partial or "personality_description" in data:
        character.personality_description = str(
            data.get("personality_description") or data.get("personality") or ""
        ).strip()
    if not partial or "wardrobe_description" in data:
        character.wardrobe_description = str(data.get("wardrobe_description") or data.get("wardrobe") or "").strip()
    if not character.default_language:
        character.default_language = LanguageChoice.CONVERSATIONAL_BM
    if "default_language" in data or "language" in data:
        raw_language = data.get("default_language") if "default_language" in data else data.get("language")
        if raw_language not in (None, ""):
            character.default_language = _require_choice(raw_language, LanguageChoice, "language")
    if not character.default_tone:
        character.default_tone = StyleChoice.WARM
    if "default_tone" in data or "tone" in data or "speaking_style" in data:
        if "default_tone" in data:
            raw_tone = data.get("default_tone")
        elif "tone" in data:
            raw_tone = data.get("tone")
        else:
            raw_tone = data.get("speaking_style")
        if raw_tone not in (None, ""):
            character.default_tone = _require_choice(raw_tone, StyleChoice, "tone")
    voice_id = str(data.get("default_voice_id") or data.get("voice_id") or "")
    if not partial or voice_id or "default_voice_id" in data or "voice_id" in data:
        voice = resolve_voice(character.default_language, character.gender, voice_id)
        character.default_voice_provider = voice["voice_provider"]
        character.default_voice_id = voice["voice_id"]
        character.default_voice_name = voice["voice_name"]
    return character


def create_character(user, data: dict, request=None) -> Character:
    brand_id = data.get("brand") or data.get("brand_id")
    if request is not None and not brand_id:
        brand_id = acting_brand_id(request)
    brand = user.brands.filter(pk=brand_id).first() if brand_id else None
    if not brand:
        raise CharacterError("Choose a brand for this character.")
    with transaction.atomic():
        character = Character(owner=user, brand=brand, gender=GenderChoice.FEMALE)
        apply_character_fields(character, data, partial=False)
        character.save()
        uploads = _uploads_from_request(request) if request is not None else []
        expected = _expected_upload_count(request) if request is not None else 0
        if request is not None:
            logger.info(
                "Character upload character_id=%s file_fields=%s received=%s expected=%s",
                character.pk,
                list(getattr(request, "FILES", {})),
                len(uploads),
                expected,
            )
        if expected and not uploads:
            raise CharacterError("The reference image did not reach the server. Please try the upload again.")
        for index, (view, upload) in enumerate(uploads):
            ref = _save_reference(character, upload, view, index)
            if ref.view_type == CharacterView.FRONT:
                persist_front_source(character, Path(ref.image.path))
                character.master_reference_status = MasterReferenceStatus.PENDING
                character.save(update_fields=["master_reference_status", "updated_at"])
        persist_front_source(character)
        _require_visual(character)
    return character


def update_character(character: Character, data: dict, request=None) -> Character:
    with transaction.atomic():
        apply_character_fields(character, data, partial=True)
        character.save()
        uploads = _uploads_from_request(request) if request is not None else []
        expected = _expected_upload_count(request) if request is not None else 0
        if request is not None:
            logger.info(
                "Character upload character_id=%s file_fields=%s received=%s expected=%s",
                character.pk,
                list(getattr(request, "FILES", {})),
                len(uploads),
                expected,
            )
        if expected and not uploads:
            raise CharacterError("The reference image did not reach the server. Please try the upload again.")
        for index, (view, upload) in enumerate(uploads):
            ref = _save_reference(character, upload, view, index)
            if ref.view_type == CharacterView.FRONT:
                persist_front_source(character, Path(ref.image.path))
                character.master_reference_status = MasterReferenceStatus.PENDING
                character.save(update_fields=["master_reference_status", "updated_at"])
        persist_front_source(character)
        _require_visual(character)
    return character


def archive_character(character: Character) -> Character:
    character.status = CharacterStatus.ARCHIVED
    character.save(update_fields=["status", "updated_at"])
    return character


def restore_character(character: Character) -> Character:
    character.status = CharacterStatus.ACTIVE
    character.save(update_fields=["status", "updated_at"])
    return character


def delete_character(character: Character) -> None:
    if character.video_configs.exists():
        raise CharacterError("This character is used by existing videos. Archive it instead of deleting it.")
    character.delete()


def duplicate_character(character: Character, name: str = "") -> Character:
    label = (name or f"{character.name} copy").strip()[:120]
    clone = Character.objects.create(
        owner=character.owner,
        brand=character.brand,
        name=label,
        description=character.description,
        gender=character.gender,
        appearance_description=character.appearance_description,
        personality_description=character.personality_description,
        wardrobe_description=character.wardrobe_description,
        default_language=character.default_language,
        default_tone=character.default_tone,
        default_voice_provider=character.default_voice_provider,
        default_voice_id=character.default_voice_id,
        default_voice_name=character.default_voice_name,
        status=CharacterStatus.ACTIVE,
    )
    for ref in character.references.all():
        if not ref.image:
            continue
        copy = CharacterReferenceImage(
            character=clone,
            view_type=ref.view_type,
            sort_order=ref.sort_order,
        )
        copy.image.name = ref.image.name
        copy.save()
    if character.source_front_image:
        clone.source_front_image.name = character.source_front_image.name
    if character.master_reference_image and character.master_reference_status == MasterReferenceStatus.READY:
        clone.master_reference_image.name = character.master_reference_image.name
        clone.master_reference_status = MasterReferenceStatus.READY
        clone.master_reference_version = 1
        clone.master_reference_prompt = character.master_reference_prompt
        clone.master_reference_created_at = character.master_reference_created_at
    clone.save()
    persist_front_source(clone)
    if clone.master_reference_image:
        from django.utils import timezone

        version = CharacterMasterReference.objects.create(
            character=clone,
            version=1,
            prompt=clone.master_reference_prompt,
            identity_facts=_identity_snapshot(character).get("master_identity_facts") or {},
            approved_at=timezone.now(),
        )
        version.image.name = clone.master_reference_image.name
        if character.source_front_image:
            version.source_image.name = character.source_front_image.name
        version.save()
        clone.current_master = version
        clone.save(update_fields=["current_master", "updated_at"])
    return clone


def character_from_presenter(project: VideoProject, data: dict) -> Character:
    brief = project.creative_brief or {}
    presenter = brief.get("presenter") if isinstance(brief.get("presenter"), dict) else {}
    payload = {
        "brand": project.product.brand_id,
        "name": data.get("name") or "",
        "description": data.get("description") or "",
        "gender": data.get("gender") or project.speaker_gender or presenter.get("gender") or "",
        "appearance_description": data.get("appearance_description") or presenter.get("look") or "",
        "personality_description": data.get("personality_description") or "",
        "wardrobe_description": data.get("wardrobe_description") or "",
        "default_language": data.get("default_language") or project.language,
        "default_tone": data.get("default_tone") or project.speaking_style,
        "default_voice_id": data.get("default_voice_id") or "",
    }
    character = Character(owner=project.owner, brand=project.product.brand, gender=GenderChoice.FEMALE)
    apply_character_fields(character, payload, partial=False)
    character.save()
    linked = False
    assets = project.assets.filter(kind=VideoAsset.Kind.IMAGE).order_by("id")
    for asset in assets:
        meta = asset.metadata or {}
        if not (meta.get("presenter_reference") or meta.get("presenter_photo") or meta.get("presenter_identity")):
            continue
        if not asset.file:
            continue
        view = str(meta.get("angle") or "front")
        if view not in CharacterView.values:
            view = CharacterView.OTHER
        ref = CharacterReferenceImage(character=character, view_type=view, sort_order=ANGLE_ORDER.get(view, 9))
        ref.image.name = asset.file.name
        ref.save()
        linked = True
    persist_front_source(character)
    if not linked and not character.appearance_description.strip():
        character.delete()
        raise CharacterError("Add an appearance description or at least one presenter photo before saving a character.")
    return character


def _identity_snapshot(character: Character) -> dict:
    master = character.current_master
    master_name = ""
    if character.master_reference_image:
        master_name = character.master_reference_image.name
    elif master and master.image:
        master_name = master.image.name
    facts = {}
    if master and master.identity_facts:
        facts = master.identity_facts
    return {
        "id": character.pk,
        "character_id": character.pk,
        "character_name": character.name,
        "name": character.name,
        "description": character.description,
        "appearance": character.appearance_description,
        "personality": character.personality_description,
        "wardrobe": character.wardrobe_description,
        "visual_gender": character.gender,
        "gender": character.gender,
        "master_reference_image": master_name,
        "master_reference_version": character.master_reference_version or (master.version if master else 0),
        "master_identity_facts": facts,
        "language": character.default_language,
        "tone": character.default_tone,
        "voice": character.default_voice_name or character.default_voice_id,
    }


def _reference_snapshot(character: Character) -> list[dict]:
    rows = []
    for ref in character.references.all():
        if not ref.image:
            continue
        rows.append({"view_type": ref.view_type, "storage_name": ref.image.name, "id": ref.pk})
    return rows


def storage_name_is_character_photo(name: str) -> bool:
    return bool(name) and CharacterReferenceImage.objects.filter(image=name).exists()


def _link_master_asset(project: VideoProject, storage_name: str, character_id) -> None:
    if not storage_name:
        return
    source = Path(settings.MEDIA_ROOT) / storage_name
    if not source.is_file():
        return
    for asset in list(project.assets.filter(kind=VideoAsset.Kind.IMAGE)):
        meta = asset.metadata or {}
        if not (meta.get("presenter_reference") or meta.get("presenter_photo") or meta.get("presenter_identity") or meta.get("master_reference")):
            continue
        if asset.file and asset.file.name == storage_name:
            stamp_presenter_reference(project)
            return
        if asset.file and asset.file.name not in {storage_name} and not storage_name_is_character_photo(asset.file.name):
            try:
                asset.file.delete(save=False)
            except Exception:
                pass
        asset.delete()
    asset = VideoAsset(
        project=project,
        kind=VideoAsset.Kind.IMAGE,
        prompt="presenter-reference",
        metadata={
            "presenter_reference": True,
            "presenter_photo": True,
            "master_reference": True,
            "character_reference": True,
            "character_id": character_id,
            "angle": "front",
        },
    )
    asset.file.save(source.name, ContentFile(source.read_bytes()), save=True)
    stamp_presenter_reference(project)


def _link_snapshot_assets(project: VideoProject, snapshot: list[dict], character_id) -> None:
    wanted = [row for row in snapshot if row.get("storage_name")]
    if not wanted:
        return
    names = {row["storage_name"] for row in wanted}
    for asset in list(project.assets.filter(kind=VideoAsset.Kind.IMAGE)):
        meta = asset.metadata or {}
        if not (meta.get("presenter_reference") or meta.get("presenter_photo") or meta.get("presenter_identity")):
            continue
        if asset.file and asset.file.name not in names:
            if not storage_name_is_character_photo(asset.file.name):
                try:
                    asset.file.delete(save=False)
                except Exception:
                    pass
            asset.delete()
    existing_names = set()
    for asset in project.assets.filter(kind=VideoAsset.Kind.IMAGE):
        if asset.file:
            existing_names.add(asset.file.name)
    for row in wanted:
        name = row["storage_name"]
        if name in existing_names:
            continue
        source = Path(settings.MEDIA_ROOT) / name
        if not source.is_file():
            continue
        asset = VideoAsset(
            project=project,
            kind=VideoAsset.Kind.IMAGE,
            prompt="presenter-reference",
            metadata={
                "presenter_reference": True,
                "presenter_photo": True,
                "character_reference": True,
                "character_id": character_id,
                "angle": row.get("view_type") or "front",
            },
        )
        asset.file.save(source.name, ContentFile(source.read_bytes()), save=True)
        existing_names.add(asset.file.name)
    stamp_presenter_reference(project)


def _stamp_scene_character(project: VideoProject, config: VideoCharacterConfig) -> None:
    identity = config.identity_snapshot or {}
    character_id = identity.get("id") or config.character_id
    name = identity.get("name") or ""
    for scene in project.scenes.all():
        meta = dict(scene.metadata or {})
        meta["character_id"] = character_id
        meta["character_name"] = name
        meta["primary_character"] = True
        Scene.objects.filter(pk=scene.pk).update(metadata=meta)


def sync_project_character(
    project: VideoProject,
    character_id,
    *,
    language: str,
    tone: str,
    gender: str,
    voice_id: str = "",
) -> VideoCharacterConfig | None:
    """Write this video's overrides. Does not change the Character record."""
    if character_id in (None, "", "none", "null"):
        replacing = bool((project.creative_brief or {}).get("generate_character"))
        generated = project.status != "draft" or bool(
            project.preview_video or project.final_video or project.export_file
        )
        if generated and not replacing:
            return _existing_config(project)
        VideoCharacterConfig.objects.filter(project=project).delete()
        brief = dict(project.creative_brief or {})
        brief.pop("character_id", None)
        presenter = dict(brief.get("presenter") or {})
        presenter.pop("character_id", None)
        brief["presenter"] = presenter
        project.creative_brief = brief
        project.save(update_fields=["creative_brief", "updated_at"])
        return None

    character = Character.objects.filter(pk=character_id, owner=project.owner).first()
    if not character or character.status != CharacterStatus.ACTIVE:
        raise CharacterError("Choose an active character from your library.")
    language = _require_choice(language, LanguageChoice, "language")
    tone = _require_choice(tone, StyleChoice, "tone")
    gender = _require_choice(gender, GenderChoice, "gender")
    if character.brand_id != project.product.brand_id:
        raise CharacterError("Choose a character from this product's brand.")
    requested_voice = (voice_id or "").strip()
    if requested_voice:
        voice = resolve_voice(language, gender, requested_voice)
    else:
        inherited = character.default_voice_id if gender == character.gender else ""
        try:
            voice = resolve_voice(language, gender, inherited)
        except CharacterError:
            voice = resolve_voice(language, gender, "")
    identity = _identity_snapshot(character)
    identity["language"] = language
    identity["tone"] = tone
    identity["voice"] = voice["voice_name"] or voice["voice_id"]
    if character.master_reference_image:
        references = [
            {
                "view_type": "front",
                "storage_name": character.master_reference_image.name,
                "id": character.current_master_id,
                "master": True,
                "version": character.master_reference_version,
            }
        ]
    else:
        references = _reference_snapshot(character)
    config, _created = VideoCharacterConfig.objects.update_or_create(
        project=project,
        defaults={
            "character": character,
            "language": language,
            "tone": tone,
            "gender": gender,
            "voice_provider": voice["voice_provider"],
            "voice_id": voice["voice_id"],
            "voice_name": voice["voice_name"],
            "appearance_snapshot": character.appearance_description,
            "identity_snapshot": identity,
            "reference_snapshot": references,
        },
    )
    brief = dict(project.creative_brief or {})
    presenter = dict(brief.get("presenter") or {})
    presenter["character_id"] = character.pk
    if character.appearance_description:
        presenter["look"] = character.appearance_description
    if references:
        presenter["mode"] = "upload"
    brief["character_id"] = character.pk
    brief["presenter"] = presenter
    remain = list(brief.get("must_remain_exact") or [])
    if "presenter" not in remain:
        remain.append("presenter")
    brief["must_remain_exact"] = remain
    project.creative_brief = brief
    project.save(update_fields=["creative_brief", "updated_at"])
    master_name = (identity.get("master_reference_image") or "") if identity else ""
    if master_name:
        _link_master_asset(project, master_name, character.pk)
    else:
        _link_snapshot_assets(project, references, character.pk)
    _stamp_scene_character(project, config)
    return config


def materialize_character_references(project: VideoProject) -> None:
    """Attach the frozen reference files before Omni runs. Does not read live Character defaults."""
    config = _existing_config(project)
    if not config:
        return
    identity = config.identity_snapshot or {}
    master_name = str(identity.get("master_reference_image") or "").strip()
    if master_name:
        _link_master_asset(project, master_name, identity.get("id") or config.character_id)
        _stamp_scene_character(project, config)
        return
    snapshot = list(config.reference_snapshot or [])
    identity = config.identity_snapshot or {}
    _link_snapshot_assets(project, snapshot, identity.get("id") or config.character_id)
    _stamp_scene_character(project, config)


def project_has_generated_media(project: VideoProject) -> bool:
    if bool(project.preview_video) or bool(project.final_video) or bool(getattr(project, "export_file", None)):
        return True
    return any(bool(scene.video_clip) for scene in project.scenes.all())


def refresh_unfrozen_character_snapshot(project: VideoProject) -> VideoCharacterConfig | None:
    """Freeze the approved master onto a draft that has not generated yet.

    Videos that already have clips keep their stored snapshot.
    """
    config = _existing_config(project)
    if config is None or not config.character_id:
        return config
    if uses_master_reference(config) or project_has_generated_media(project):
        return config
    if project.status in {
        VideoProjectStatus.READY_FOR_REVIEW,
        VideoProjectStatus.READY,
        VideoProjectStatus.APPROVED,
        VideoProjectStatus.EXPORTED,
        VideoProjectStatus.CORRECTING,
        VideoProjectStatus.QA,
        VideoProjectStatus.QA_RUNNING,
    }:
        return config
    from ai.services.master_character import character_is_video_ready

    character = config.character
    if character is None or not character_is_video_ready(character):
        return config
    return sync_project_character(
        project,
        character.pk,
        language=config.language or project.language,
        tone=config.tone or project.speaking_style,
        gender=config.gender or project.speaker_gender,
        voice_id=config.voice_id or "",
    )


def _existing_config(project: VideoProject) -> VideoCharacterConfig | None:
    if not getattr(project, "pk", None):
        return None
    try:
        return project.character_config
    except ObjectDoesNotExist:
        return None


def character_prompt_lines(project: VideoProject | None, *, include_labels: bool = True) -> list[str]:
    config = _existing_config(project) if project else None
    if not config:
        return []
    identity = config.identity_snapshot or {}
    name = identity.get("name") or identity.get("character_name") or ""
    character_id = identity.get("id") or identity.get("character_id") or config.character_id or ""
    master = uses_master_reference(config)
    lines = ["CHARACTER IDENTITY — LOCKED"]
    if master:
        lines.extend(
            [
                "Preserve the exact identity represented by the approved Master Character Reference.",
                "Do not redesign the person.",
                "Do not beautify.",
                "Do not alter facial structure.",
                "Do not change apparent age.",
                "Do not change skin tone.",
                "Do not change hair color.",
                "Do not change hairstyle unless explicitly required by the scene.",
                "Do not change body proportions.",
                "Do not substitute another person.",
                "The character name is NOT an identity reference. Do not invent a face from the name.",
            ]
        )
        if include_labels and (name or character_id):
            lines.append(f"Character identifier: {name or 'character'} (id {character_id}).")
    else:
        if include_labels:
            lines.append(f"CHARACTER IDENTITY — id {character_id}, name {name or 'the selected character'}.")
        lines.append("Use this same person in every scene. Do not invent a new face or regenerate a different identity.")
    if config.appearance_snapshot:
        lines.append(f"Identity description: {config.appearance_snapshot}")
    if identity.get("wardrobe"):
        lines.append(f"Wardrobe (provided by user, do not invent extras): {identity['wardrobe']}")
    if identity.get("personality"):
        lines.append(f"Personality: {identity['personality']}")
    facts = identity.get("master_identity_facts") or {}
    provided = facts.get("provided_by_user") or {}
    if provided.get("wardrobe") and not identity.get("wardrobe"):
        lines.append(f"Wardrobe (provided by user): {provided['wardrobe']}")
    if master:
        lines.append(
            "The master character reference photograph is included. Match that person. "
            "That photo is the person, not the product."
        )
    elif config.reference_snapshot:
        lines.append(
            "Character reference photographs are included. Match that person. "
            "These photos are the person, not the product."
        )
    lines.append("CHARACTER BEHAVIOR")
    lines.append(
        "The presenter may change expression, gesture, pose and action according to the scene. "
        "The person's identity must not change between scenes."
    )
    spoken_id = config.language or ""
    spoken_code = LANGUAGE_CODES.get(spoken_id, "")
    voice_label = config.voice_name or config.voice_id or "unspecified"
    if spoken_id == "hokkien":
        voice_line = (
            "Preferred speaking voice: native Hokkien speaker. "
            "Ignore Mandarin / Taiwan Mandarin catalog ids. Do not speak Putonghua or Cantonese."
        )
    elif spoken_id == "cantonese":
        voice_line = (
            f"Preferred speaking voice: {voice_label} (Cantonese yue-HK). "
            "Speak Cantonese. Do not speak Mandarin."
        )
    elif spoken_id in {"chinese", "mandarin_my"}:
        voice_line = (
            f"Preferred speaking voice: {voice_label} (Mandarin). "
            "Speak Mandarin. Do not speak Cantonese or Hokkien."
        )
    else:
        voice_line = f"Preferred speaking voice: {voice_label}."
    lines.append(
        f"This video's speaking settings: tone {config.tone}, voice gender {config.gender}, "
        f"spoken language {spoken_id or 'unspecified'}"
        f"{f' ({spoken_code})' if spoken_code else ''}. "
        f"{voice_line} "
        f"{speech_lock(spoken_id)} "
        "This is a preference only. Spoken audio is generated with the scene by Omni. "
        "Do not claim a separate voice track was synthesized. "
        "Do not change the character's face to match a different voice gender."
    )
    lines.append("Product photographs and product locks stay authoritative. The character may interact with the product.")
    return lines
