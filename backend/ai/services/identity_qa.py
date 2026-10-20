"""Per-scene character identity and narration gates.

Gemini Omni does not accept a numeric face seed. Character consistency is the
same stored Character reference image, passed as an input image on every
scene through GeminiOmniProvider.start(image_paths=...). This module does not
invent a seed and does not invent a confidence score.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile

from ai.models import CharacterReferenceImage, QAStatus, Scene, VideoAsset, VideoProject
from ai.services.director import media_exists
from ai.services.ffmpeg import extract_audio, inspect_audio, sample_frames
from ai.services.visual_qa import transcription_similarity

logger = logging.getLogger(__name__)

IDENTITY_PASS_THRESHOLD = 0.90

# What Omni actually supports for keeping one face across scenes.
CHARACTER_IDENTITY_MECHANISM = "same_character_reference_image"

IDENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "face_detected": {"type": "boolean"},
        "face_count": {"type": "integer"},
        "identified": {"type": "boolean"},
        "ambiguous": {"type": "boolean"},
        "confidence": {"type": "number"},
        "message": {"type": "string"},
        "frame_index": {"type": "integer"},
    },
    "required": ["face_detected"],
}


def _parse_confidence(value):
    """Return a real 0-1 score, including 0. None when the score is missing."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        text = value.strip().rstrip("%")
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        if text.endswith("%") or value > 1:
            value = value / 100.0
    if not isinstance(value, (int, float)):
        return None
    score = float(value)
    if score != score:
        return None
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return score


def decide_identity(
    *,
    confidence=None,
    comparison_performed=False,
    face_detected=False,
    ambiguous=False,
) -> dict:
    """PASS only when a real comparison scored at least IDENTITY_PASS_THRESHOLD.

    Zero, null, a skipped comparison, and a missing face all fail. Do not use
    `if confidence` — 0 is a real score and it fails.
    """
    performed = comparison_performed is True
    detected = face_detected is True
    result = {
        "status": QAStatus.FAILED,
        "confidence": None,
        "threshold": IDENTITY_PASS_THRESHOLD,
        "comparison_performed": performed,
        "face_detected": detected,
        "reason": "",
    }
    if not performed:
        result["reason"] = "Identity comparison did not run"
        return result
    if not detected:
        result["confidence"] = 0.0
        result["reason"] = "Expected character face was not detected"
        return result
    if ambiguous is True:
        result["confidence"] = 0.0 if _parse_confidence(confidence) is None else _parse_confidence(confidence)
        result["reason"] = "Expected character could not be reliably identified"
        return result
    score = _parse_confidence(confidence)
    if score is None:
        result["reason"] = "Identity confidence is unknown"
        return result
    result["confidence"] = score
    if score < IDENTITY_PASS_THRESHOLD:
        result["reason"] = "Generated face does not match Character reference"
        return result
    result["status"] = QAStatus.PASSED
    result["reason"] = ""
    return result


def decide_audio(
    *,
    narration_required=False,
    has_audio_stream=None,
    speech_detected=None,
    verification_available=True,
    duration_seconds=None,
    silent=False,
) -> dict:
    """A required narration passes only when speech was actually detected."""
    result = {
        "status": QAStatus.PASSED,
        "required": narration_required is True,
        "has_audio_stream": has_audio_stream is True,
        "speech_detected": speech_detected is True,
        "duration_seconds": duration_seconds,
        "reason": "",
    }
    if narration_required is not True:
        result["status"] = QAStatus.PASSED
        result["speech_detected"] = speech_detected is True
        return result
    if speech_detected is True and has_audio_stream is not False and silent is not True:
        result["status"] = QAStatus.PASSED
        result["has_audio_stream"] = True
        result["speech_detected"] = True
        return result
    if has_audio_stream is not True or silent is True:
        result["status"] = QAStatus.FAILED
        result["speech_detected"] = False
        result["reason"] = "Expected narration is silent or missing"
        return result
    if verification_available is not True or speech_detected is None:
        result["status"] = QAStatus.FAILED
        result["speech_detected"] = False
        result["reason"] = "Audio QA could not verify expected narration"
        return result
    result["status"] = QAStatus.FAILED
    result["speech_detected"] = False
    result["reason"] = "Expected narration was not detected"
    return result


def project_gates_pass(gates: list[dict]) -> bool:
    """Every required scene must pass identity and audio."""
    if not gates:
        return True
    for gate in gates:
        identity = gate.get("identity") or {}
        audio = gate.get("audio") or {}
        if identity.get("required") and identity.get("status") != QAStatus.PASSED:
            return False
        if audio.get("required") and audio.get("status") != QAStatus.PASSED:
            return False
    return True


def scenes_requiring_regeneration(project: VideoProject) -> list[int]:
    """Scene primary keys whose identity or narration gate failed."""
    failed = []
    for scene in project.scenes.all().order_by("order", "id"):
        meta = scene.metadata or {}
        identity = meta.get("identity") or {}
        audio = meta.get("audio") or {}
        if identity.get("status") == QAStatus.FAILED or audio.get("status") == QAStatus.FAILED:
            failed.append(scene.pk)
    return failed


def _character_config(project: VideoProject):
    try:
        config = project.character_config
    except ObjectDoesNotExist:
        return None
    identity = config.identity_snapshot or {}
    if not (config.character_id or identity.get("id")):
        return None
    return config


REFERENCE_UNAVAILABLE = "Character reference image unavailable"


def _character_id(config) -> int | None:
    raw = config.character_id or (config.identity_snapshot or {}).get("id")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _snapshot_reference_ids(config) -> list[int]:
    ids = []
    for row in config.reference_snapshot or []:
        try:
            ids.append(int(row.get("id")))
        except (TypeError, ValueError, AttributeError):
            continue
    return ids


def character_reference_images(config) -> list[CharacterReferenceImage]:
    """The selected Character's own reference rows, front view first.

    A frozen snapshot id is preferred when that row still belongs to this
    Character. Project stills and other Characters are never included.
    """
    character_id = _character_id(config)
    if not character_id:
        return []
    rows = list(CharacterReferenceImage.objects.filter(character_id=character_id))
    preferred = set(_snapshot_reference_ids(config))

    def rank(ref: CharacterReferenceImage):
        return (
            0 if preferred and ref.pk in preferred else 1,
            0 if ref.view_type == "front" else 1,
            ref.sort_order,
            ref.pk,
        )

    rows.sort(key=rank)
    return rows


def open_character_reference(ref: CharacterReferenceImage) -> tuple[Path | None, str]:
    """Open one CharacterReferenceImage through Django storage."""
    field = ref.image
    name = str(getattr(field, "name", "") or "")
    if not name:
        return None, f"{REFERENCE_UNAVAILABLE}: CharacterReferenceImage {ref.pk} has no storage name"
    try:
        exists = field.storage.exists(name)
    except Exception as exc:
        return None, f"{REFERENCE_UNAVAILABLE}: {name}: {exc}"
    if not exists:
        return None, f"{REFERENCE_UNAVAILABLE}: {name} is not in storage"
    try:
        path = Path(field.path)
    except Exception as exc:
        return None, f"{REFERENCE_UNAVAILABLE}: {name}: {exc}"
    if not path.is_file():
        return None, f"{REFERENCE_UNAVAILABLE}: {path} is not a file"
    return path, ""


def load_reference_bytes(ref: CharacterReferenceImage) -> bytes:
    """Read the exact stored bytes. Raises FileNotFoundError when unavailable."""
    _path, error = open_character_reference(ref)
    if error:
        raise FileNotFoundError(error)
    with ref.image.open("rb") as handle:
        return handle.read()


def resolve_character_references(config) -> tuple[int | None, int | None, list[Path], str]:
    """Return character id, primary image id, readable files, and an error."""
    character_id = _character_id(config)
    from ai.services.characters import master_reference_path, uses_master_reference

    if uses_master_reference(config):
        master = master_reference_path(config)
        if master is None:
            return character_id, None, [], REFERENCE_UNAVAILABLE
        identity = config.identity_snapshot or {}
        image_id = identity.get("master_reference_version") or None
        return character_id, image_id, [master], ""
    rows = character_reference_images(config)
    if not rows:
        return character_id, None, [], REFERENCE_UNAVAILABLE
    paths = []
    primary_id = None
    errors = []
    for ref in rows:
        path, error = open_character_reference(ref)
        if path is None:
            errors.append(error)
            continue
        if primary_id is None:
            primary_id = ref.pk
        paths.append(path)
    if not paths:
        return character_id, rows[0].pk, [], errors[0] if errors else REFERENCE_UNAVAILABLE
    return character_id, primary_id, paths, ""


def _media_url(path: Path | None) -> str:
    if not path or not path.is_file():
        return ""
    try:
        relative = path.resolve().relative_to(Path(settings.MEDIA_ROOT).resolve())
    except ValueError:
        return ""
    return f"{settings.MEDIA_URL}{relative.as_posix()}"


def _clip_path(scene: Scene) -> Path | None:
    for field in (scene.video_clip, scene.image):
        if not media_exists(field):
            continue
        try:
            path = Path(field.path)
        except (ValueError, OSError):
            continue
        if path.is_file():
            return path
    return None


def _frame_paths(scene: Scene, clip: Path, tmp_dir: Path) -> list[Path]:
    if clip.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return [clip]
    sampled = sample_frames(clip, tmp_dir / "frames")
    return [path for _, path in sampled if path.is_file()]


def _compare(gemini, references: list[Path], frames: list[Path]) -> dict:
    prompt = (
        "The images before the generated frames are this Character's reference photos. "
        "The first of those is the authoritative face. Later reference images are other "
        "views of the same person. Compare them with the faces in the generated frames.\n"
        "This is a visual comparison of the pictures. Do not assume the character "
        "appears just because they were requested.\n"
        "Set face_detected true only if a human face is visible in the generated frames.\n"
        "If several faces are visible and you cannot tell which one is the reference person, "
        "set ambiguous true and identified false.\n"
        "confidence is how closely the generated face matches the reference photo, from 0 to 1. "
        "Use 0 when the face is a different person. Omit confidence if you cannot judge it.\n"
        "Return JSON only."
    )
    try:
        payload = gemini.generate_json(
            prompt,
            schema=IDENTITY_SCHEMA,
            files=[*references, *frames[:3]],
            system="You compare faces in photographs. Return only the JSON schema.",
        )
    except Exception:
        logger.exception("Character identity comparison failed")
        return {"comparison_performed": False}
    if not isinstance(payload, dict) or "face_detected" not in payload:
        return {"comparison_performed": False}
    face_count = payload.get("face_count")
    identified = payload.get("identified")
    ambiguous = payload.get("ambiguous") is True
    if isinstance(face_count, int) and face_count > 1 and identified is not True:
        ambiguous = True
    return {
        "comparison_performed": True,
        "face_detected": payload.get("face_detected") is True,
        "ambiguous": ambiguous,
        "confidence": payload.get("confidence", None),
        "message": str(payload.get("message") or ""),
        "frame_index": payload.get("frame_index") if isinstance(payload.get("frame_index"), int) else 0,
    }


def _save_face_frame(project: VideoProject, scene: Scene, frame: Path) -> str:
    asset = VideoAsset(
        project=project,
        scene=scene,
        kind=VideoAsset.Kind.IMAGE,
        prompt="identity-frame",
        metadata={"identity_frame": True, "scene_key": scene.scene_key},
    )
    asset.file.save(
        f"{scene.scene_key}-identity.jpg",
        ContentFile(frame.read_bytes()),
        save=True,
    )
    if asset.file and media_exists(asset.file):
        return asset.file.url
    return ""


def _speech_text(gemini, clip: Path, tmp_dir: Path, language: str) -> tuple[bool, str]:
    """Return (verification_available, transcript). An empty transcript is not speech."""
    extracted = extract_audio(clip, tmp_dir / "speech.mp3")
    if not extracted or not Path(extracted).is_file():
        return False, ""
    try:
        text = gemini.transcribe(extracted, language=language) or ""
    except Exception:
        logger.info("Speech transcription unavailable for narration QA")
        return False, ""
    return True, str(text).strip()


def evaluate_scene_identity(project, scene, config, gemini) -> dict:
    identity_snapshot = config.identity_snapshot or {}
    character_id, image_id, references, reference_error = resolve_character_references(config)
    reference = references[0] if references else None
    name = str(identity_snapshot.get("name") or "")
    base = {
        "required": True,
        "reference_character_id": character_id,
        "reference_image_id": image_id,
        "character_name": name,
        "reference_url": _media_url(reference),
        "generated_face_url": "",
        "mechanism": CHARACTER_IDENTITY_MECHANISM,
        "reference_error": reference_error,
    }
    clip = _clip_path(scene)
    if reference is None or clip is None:
        decision = decide_identity(comparison_performed=False, face_detected=False)
        if reference is None:
            decision["reason"] = REFERENCE_UNAVAILABLE
            decision["confidence"] = None
        elif clip is None:
            decision = decide_identity(comparison_performed=False, face_detected=False)
            decision["reason"] = "Generated scene was not available to inspect"
            decision["confidence"] = None
        return {**base, **decision}

    with tempfile.TemporaryDirectory() as tmp:
        frames = _frame_paths(scene, clip, Path(tmp))
        if not frames:
            decision = decide_identity(comparison_performed=False, face_detected=False)
            decision["confidence"] = 0.0
            decision["reason"] = "Expected character face was not detected"
            return {**base, **decision}
        compared = _compare(gemini, references, frames)
        if compared.get("comparison_performed") is not True:
            decision = decide_identity(comparison_performed=False, face_detected=False)
            return {**base, **decision}
        frame_index = compared.get("frame_index") or 0
        if not isinstance(frame_index, int) or frame_index < 0 or frame_index >= len(frames):
            frame_index = 0
        face_url = ""
        if compared.get("face_detected") is True:
            try:
                face_url = _save_face_frame(project, scene, frames[frame_index])
            except Exception:
                logger.exception("Could not store the identity frame for %s", scene.scene_key)
                face_url = ""
        decision = decide_identity(
            confidence=compared.get("confidence"),
            comparison_performed=True,
            face_detected=compared.get("face_detected") is True,
            ambiguous=compared.get("ambiguous") is True,
        )
        if compared.get("message") and decision["status"] != QAStatus.PASSED and not decision.get("reason"):
            decision["reason"] = compared["message"]
        return {**base, **decision, "generated_face_url": face_url}


def evaluate_scene_audio(project, scene, gemini) -> dict:
    narration = (scene.narration or "").strip()
    required = bool(narration)
    clip = _clip_path(scene)
    if not required:
        decision = decide_audio(narration_required=False)
        return decision
    if clip is None:
        decision = decide_audio(narration_required=True, has_audio_stream=False, speech_detected=False)
        return decision
    try:
        report = inspect_audio(clip)
    except Exception:
        logger.exception("Audio inspection failed for %s", scene.scene_key)
        decision = decide_audio(
            narration_required=True,
            has_audio_stream=False,
            speech_detected=None,
            verification_available=False,
        )
        return decision
    duration = report.get("audio_duration")
    if duration is None:
        duration = report.get("duration")
    has_stream = report.get("has_audio") is True
    silent = bool(report.get("silent")) or report.get("audible") is not True
    if not has_stream or silent:
        return decide_audio(
            narration_required=True,
            has_audio_stream=has_stream,
            speech_detected=False,
            silent=True,
            duration_seconds=duration,
            verification_available=True,
        )
    with tempfile.TemporaryDirectory() as tmp:
        available, transcript = _speech_text(gemini, clip, Path(tmp), project.language or "")
    speech = None
    if available:
        speech = bool(transcript) and transcription_similarity(narration, transcript) >= 0.45
    return decide_audio(
        narration_required=True,
        has_audio_stream=True,
        speech_detected=speech,
        verification_available=available,
        silent=False,
        duration_seconds=duration,
    )


def _identity_check(scene: Scene, identity: dict) -> dict:
    status = identity.get("status") or QAStatus.FAILED
    confidence = identity.get("confidence")
    detail = identity.get("reason") or (
        f"Identity {int(round(float(confidence) * 100))}% matches the character reference."
        if status == QAStatus.PASSED and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        else "Character identity was not verified."
    )
    return {
        "name": "character_identity",
        "status": status,
        "detail": detail,
        "reason": identity.get("reason") or "",
        "source": "vision",
        "qa_category": "presenter",
        "confidence": confidence,
        "threshold": IDENTITY_PASS_THRESHOLD,
        "comparison_performed": identity.get("comparison_performed") is True,
        "face_detected": identity.get("face_detected") is True,
        "scene_id": scene.scene_key,
        "affected_scenes": [scene.scene_key],
        "frame_url": identity.get("generated_face_url") or "",
        "reference_url": identity.get("reference_url") or "",
        "checked": identity.get("comparison_performed") is True,
        "verified": False,
        "severity": "high" if status == QAStatus.FAILED else "info",
    }


def _audio_check(scene: Scene, audio: dict) -> dict | None:
    if audio.get("required") is not True:
        return None
    status = audio.get("status") or QAStatus.FAILED
    return {
        "name": "scene_narration",
        "status": status,
        "detail": audio.get("reason") or (
            "Narration speech was detected." if status == QAStatus.PASSED else "Expected narration was not detected"
        ),
        "reason": audio.get("reason") or "",
        "source": "ffmpeg",
        "qa_category": "audio",
        "scene_id": scene.scene_key,
        "affected_scenes": [scene.scene_key],
        "has_audio_stream": audio.get("has_audio_stream") is True,
        "speech_detected": audio.get("speech_detected") is True,
        "duration_seconds": audio.get("duration_seconds"),
        "checked": True,
        "verified": True,
        "severity": "high" if status == QAStatus.FAILED else "info",
    }


def apply_scene_gates(project: VideoProject, scenes: list[Scene], gemini) -> tuple[list[dict], list[dict]]:
    """Persist honest per-scene identity and audio results. Returns checks and gates."""
    config = _character_config(project)
    checks = []
    gates = []
    for scene in scenes:
        meta = dict(scene.metadata or {})
        if config:
            identity = evaluate_scene_identity(project, scene, config, gemini)
        else:
            identity = {"required": False, "status": QAStatus.PASSED, "comparison_performed": False}
        audio = evaluate_scene_audio(project, scene, gemini)
        meta["identity"] = identity
        meta["audio"] = audio
        scene.metadata = meta
        scene.save(update_fields=["metadata"])
        gate = {
            "scene_id": scene.pk,
            "scene_key": scene.scene_key,
            "order": scene.order,
            "label": scene.title or scene.scene_key,
            "identity": identity,
            "audio": audio,
        }
        gates.append(gate)
        if identity.get("required"):
            checks.append(_identity_check(scene, identity))
        audio_check = _audio_check(scene, audio)
        if audio_check:
            checks.append(audio_check)
    return checks, gates
