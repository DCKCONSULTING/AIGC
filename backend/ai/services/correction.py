from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from ai.exceptions import MissingAPIKeyError
from ai.models import Scene, VideoProject, VideoProjectStatus, VideoProjectVersion
from ai.providers.google.client import speech_configured
from ai.providers.google.speech import SpeechProvider
from ai.providers.intelligence import IntelligenceClient

logger = logging.getLogger(__name__)

CORRECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "update_price",
                "change_tone",
                "replace_scene",
                "change_narration",
                "update_product_fact",
                "other",
            ],
        },
        "instruction": {"type": "string"},
        "fields": {"type": "object"},
        "scene_key": {"type": "string"},
        "regenerate": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent", "instruction", "regenerate"],
}


class CorrectionService:
    def __init__(
        self,
        gemini: IntelligenceClient | None = None,
        speech: SpeechProvider | None = None,
    ):
        self.gemini = gemini or IntelligenceClient()
        self.speech = speech or SpeechProvider()

    def apply(
        self,
        project: VideoProject,
        instruction: str = "",
        *,
        voice_bytes: bytes | None = None,
    ) -> dict:
        spoken = ""
        if voice_bytes:
            spoken = self._transcribe(project, voice_bytes)
        text = "\n".join(part for part in [instruction, spoken] if part).strip()
        if not text:
            raise ValueError("Enter a correction or record a voice note.")

        self._store_version(project, note=text[:255])
        parsed = self.gemini.generate_json(
            (
                "Parse this merchant correction. Identify the smallest set of components to regenerate. "
                "Allowed regenerate values: product_snapshot, brief, script, shot_plan, scene, "
                "narration, captions, video, qa.\n"
                f"Correction: {text}\n"
                f"Snapshot: {project.product_snapshot}\n"
                f"Script: {project.script}\n"
                f"Scenes: {[scene.scene_key for scene in project.scenes.all()]}"
            ),
            schema=CORRECTION_SCHEMA,
            system="You parse video corrections. Return JSON only.",
        )
        fields = parsed.get("fields") or {}
        snapshot = dict(project.product_snapshot or {})
        if "price" in fields:
            snapshot["price"] = str(fields["price"])
        for key in ("name", "offer", "dimensions", "materials"):
            if key in fields:
                snapshot[key] = fields[key]
        project.product_snapshot = snapshot
        project.merchant_instructions = "\n".join(
            part for part in [project.merchant_instructions, text] if part
        )
        project.version += 1
        project.status = VideoProjectStatus.CORRECTING
        project.stage_label = "Applying your changes"
        project.progress = 10
        project.save()

        scene_key = parsed.get("scene_key") or ""
        if scene_key:
            self._mark_scene(project, scene_key)
        return parsed

    def prepare_regenerate(self, project: VideoProject, instruction: str = "") -> dict:
        from ai.services.snapshots import product_snapshot

        text = (instruction or "").strip()
        self._store_version(project, note=(text or "Regenerate")[:255])
        project.product_snapshot = product_snapshot(project.product, project.product_snapshot)
        if text:
            from ai.services.script import apply_instruction_locale

            apply_instruction_locale(project, text)
            self._sync_locale_voice(project)
            project.merchant_instructions = "\n".join(
                part for part in [project.merchant_instructions, text] if part
            )
            brief = dict(project.creative_brief or {})
            existing = str(brief.get("legacy_instructions") or "").strip()
            if text not in existing:
                brief["legacy_instructions"] = "\n".join(part for part in [existing, text] if part)
                brief["language"] = project.language
                project.creative_brief = brief
        project.version += 1
        project.status = VideoProjectStatus.CORRECTING
        project.stage_label = "Applying your changes"
        project.progress = 10
        project.error_message = ""
        project.save()
        for scene in project.scenes.all():
            self._mark_scene(project, scene.scene_key)
        regenerate = ["scene", "video", "narration", "captions"]
        if text:
            regenerate = ["brief", "script", "shot_plan", *regenerate]
        return {
            "intent": "other",
            "instruction": text or "Regenerate using the product photos.",
            "regenerate": regenerate,
        }

    def _mark_scene(self, project: VideoProject, scene_key: str) -> None:
        scene = project.scenes.filter(scene_key=scene_key).first()
        if not scene:
            return
        scene.metadata = {**(scene.metadata or {}), "needs_regeneration": True}
        scene.save(update_fields=["metadata"])

    def _transcribe(self, project: VideoProject, voice_bytes: bytes) -> str:
        if speech_configured():
            try:
                return self.speech.transcribe(voice_bytes, language=project.language)
            except MissingAPIKeyError:
                pass
        suffix = ".webm"
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(voice_bytes)
                path = Path(tmp.name)
            return self.gemini.transcribe(path, language=project.language, owner=project.owner, project=project)
        finally:
            if path:
                path.unlink(missing_ok=True)

    def _sync_locale_voice(self, project: VideoProject) -> None:
        try:
            config = project.character_config
        except Exception:
            return
        character_id = getattr(config, "character_id", None)
        if not character_id:
            return
        try:
            from ai.services.characters import sync_project_character

            sync_project_character(
                project,
                character_id,
                language=project.language,
                tone=config.tone or project.speaking_style or "warm",
                gender=config.gender or project.speaker_gender or "female",
                voice_id="",
            )
        except Exception:
            logger.exception("Locale voice sync skipped for project %s", project.pk)

    def _store_version(self, project: VideoProject, note: str) -> None:
        VideoProjectVersion.objects.create(
            project=project,
            version=project.version,
            note=note,
            snapshot={
                "product_snapshot": project.product_snapshot,
                "creative_brief": project.creative_brief,
                "script": project.script,
                "shot_plan": project.shot_plan,
                "narration": project.narration,
                "captions": project.captions,
                "qa_results": project.qa_results,
                "scenes": [
                    {
                        "scene_key": scene.scene_key,
                        "visual": scene.visual,
                        "narration": scene.narration,
                        "caption": scene.caption,
                        "duration": scene.duration,
                    }
                    for scene in project.scenes.all()
                ],
            },
        )
