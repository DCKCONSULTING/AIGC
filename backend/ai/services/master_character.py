"""Create and approve a frozen Master Character Reference from one front photo."""

from __future__ import annotations

import logging
from pathlib import Path

from django.core.files.base import ContentFile
from django.db.models import Max
from django.utils import timezone

from ai.exceptions import GoogleProviderError, ProviderError
from ai.models import Character, CharacterMasterReference, MasterReferenceStatus
from ai.providers.google.nano_banana import NanoBananaProvider
from ai.services.characters import CharacterError, front_source_path, persist_front_source

logger = logging.getLogger(__name__)

MASTER_REQUIRED_ERROR = (
    "This character does not have an approved Master Character Reference. "
    "Generate or approve the master character before creating a video."
)

MASTER_PROMPT = """Create a photorealistic Master Character Reference from the uploaded front-facing photograph.

Preserve the exact identity of the person in the source image.

Do not redesign the person.

Do not change:
- facial identity
- face shape
- eyes
- nose
- mouth
- jaw
- skin tone
- hair
- hair color
- apparent age
- distinctive facial characteristics
- visible body proportions

Do not beautify or transform the person into a different person.

Do not invent body, clothing, or accessory details that are not visible in the source photo and not provided below.

Composition:
- front-facing or a slight natural 3/4 orientation
- full face clearly visible
- neutral natural expression
- consistent lighting
- clean background
- upper body visible only if the source photo already shows it
- clothing clearly visible only if present in the source
- no text, watermark, logo, or distracting objects
- no dramatic camera angle, excessive pose, illustration, or avatar style

Remain photorealistic if the source is photorealistic. Identity consistency, not artistic enhancement.
"""


def _user_facts(character: Character) -> dict:
    provided = {}
    if character.appearance_description.strip():
        provided["appearance"] = character.appearance_description.strip()
    if character.wardrobe_description.strip():
        provided["wardrobe"] = character.wardrobe_description.strip()
    if character.personality_description.strip():
        provided["personality"] = character.personality_description.strip()
    if character.description.strip():
        provided["description"] = character.description.strip()
    if character.gender:
        provided["gender"] = character.gender
    return provided


def identity_facts_for(character: Character) -> dict:
    provided = _user_facts(character)
    return {
        "observed_from_photo": [],
        "provided_by_user": provided,
        "generated_or_normalized": [
            "neutral lighting",
            "clean background",
            "front-facing or slight 3/4 framing",
        ],
    }


def _prompt_for(character: Character) -> str:
    provided = _user_facts(character)
    extra = []
    if provided.get("appearance"):
        extra.append(f"User-provided appearance (do not invent beyond this): {provided['appearance']}")
    if provided.get("wardrobe"):
        extra.append(
            "User-provided wardrobe (use for clothing only if the source photo does not show it clearly): "
            f"{provided['wardrobe']}"
        )
    if provided.get("gender"):
        extra.append(f"User-provided gender: {provided['gender']}. Do not change the face to match a different gender.")
    extra.append("Do not invent shoes, full-body proportions, or other details that are not in the photo or the user text.")
    return MASTER_PROMPT + "\n\n" + "\n".join(extra)


def _copy_field(field, dest, filename: str) -> None:
    if not field:
        return
    try:
        field.open("rb")
        dest.save(filename, ContentFile(field.read()), save=True)
    finally:
        try:
            field.close()
        except Exception:
            pass


class MasterCharacterService:
    def __init__(self, images: NanoBananaProvider | None = None):
        self.images = images or NanoBananaProvider()

    def generate(self, character: Character) -> CharacterMasterReference:
        source = front_source_path(character)
        if source is None:
            raise CharacterError("Upload one clear front-facing photo before generating the master character.")
        persist_front_source(character, source)
        character.refresh_from_db()
        previous_status = character.master_reference_status
        character.master_reference_status = MasterReferenceStatus.PROCESSING
        character.save(update_fields=["master_reference_status", "updated_at"])
        prompt = _prompt_for(character)
        try:
            image_bytes = self.images.generate_image(
                prompt,
                reference_images=[source],
                aspect_ratio="3:4",
                system_lock="",
            )
        except (GoogleProviderError, ProviderError, Exception) as exc:
            logger.exception("Master character generation failed for character %s", character.pk)
            if character.current_master_id:
                character.master_reference_status = MasterReferenceStatus.READY
            else:
                character.master_reference_status = MasterReferenceStatus.FAILED
            character.save(update_fields=["master_reference_status", "updated_at"])
            if isinstance(exc, CharacterError):
                raise
            raise CharacterError("Master character generation failed. The original photo was kept.") from exc
        next_version = (character.master_versions.aggregate(Max("version")).get("version__max") or 0) + 1
        record = CharacterMasterReference(
            character=character,
            version=next_version,
            prompt=prompt,
            identity_facts=identity_facts_for(character),
        )
        record.image.save(f"master-v{next_version}.png", ContentFile(image_bytes), save=True)
        if character.source_front_image:
            _copy_field(character.source_front_image, record.source_image, Path(character.source_front_image.name).name)
        else:
            record.source_image.save(source.name, ContentFile(source.read_bytes()), save=True)
        if previous_status == MasterReferenceStatus.READY and character.current_master_id:
            character.master_reference_status = MasterReferenceStatus.READY
        else:
            character.master_reference_status = MasterReferenceStatus.PENDING
        character.save(update_fields=["master_reference_status", "updated_at"])
        return record

    def approve(self, character: Character, version: int | None = None) -> CharacterMasterReference:
        if version is not None:
            record = character.master_versions.filter(version=version).first()
        else:
            record = character.master_versions.order_by("-version", "-id").first()
        if record is None or not record.image:
            raise CharacterError("Generate a master character before approving it.")
        record.approved_at = timezone.now()
        record.save(update_fields=["approved_at"])
        character.current_master = record
        character.master_reference_status = MasterReferenceStatus.READY
        character.master_reference_version = record.version
        character.master_reference_prompt = record.prompt
        character.master_reference_created_at = record.created_at
        if record.image:
            _copy_field(record.image, character.master_reference_image, Path(record.image.name).name)
        character.save()
        return record


def character_is_video_ready(character: Character | None) -> bool:
    if character is None:
        return False
    return (
        character.master_reference_status == MasterReferenceStatus.READY
        and bool(character.current_master_id)
        and bool(character.master_reference_image)
    )


def require_approved_master(character: Character | None) -> None:
    if not character_is_video_ready(character):
        raise CharacterError(MASTER_REQUIRED_ERROR)
