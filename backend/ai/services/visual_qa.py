from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile

from ai.exceptions import GoogleProviderError, MissingAPIKeyError, ProviderError
from ai.models import Scene, VideoAsset, VideoProject
from ai.providers.google.client import speech_configured
from ai.providers.intelligence import IntelligenceClient
from ai.services.director import scene_generation_id
from ai.services.ffmpeg import extract_audio, inspect_audio, sample_frames
from ai.services.snapshots import snapshot_paths

logger = logging.getLogger(__name__)

QA_VERSION = 2

VISUAL_SCHEMA = {
    "type": "object",
    "properties": {
        "product": {
            "type": "object",
            "properties": {
                "checked": {"type": "boolean"},
                "match": {"type": "boolean"},
                "confidence": {"type": "number"},
                "message": {"type": "string"},
                "timestamp": {"type": "number"},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
        },
        "presenter": {
            "type": "object",
            "properties": {
                "checked": {"type": "boolean"},
                "match": {"type": "boolean"},
                "confidence": {"type": "number"},
                "message": {"type": "string"},
                "timestamp": {"type": "number"},
                "continuity_only": {"type": "boolean"},
            },
        },
        "scene": {
            "type": "object",
            "properties": {
                "checked": {"type": "boolean"},
                "match": {"type": "boolean"},
                "confidence": {"type": "number"},
                "message": {"type": "string"},
                "timestamp": {"type": "number"},
            },
        },
        "caption": {
            "type": "object",
            "properties": {
                "checked": {"type": "boolean"},
                "visible": {"type": "boolean"},
                "clipped": {"type": "boolean"},
                "outside_safe_area": {"type": "boolean"},
                "overlaps_product": {"type": "boolean"},
                "contrast_ok": {"type": "boolean"},
                "text_seen": {"type": "string"},
                "confidence": {"type": "number"},
                "message": {"type": "string"},
                "unavailable": {"type": "boolean"},
            },
        },
    },
}


def media_path(field) -> Path | None:
    if not field:
        return None
    try:
        path = Path(field.path)
    except (ValueError, OSError, NotImplementedError):
        return None
    return path if path.exists() else None


def generation_key(scene: Scene) -> str:
    meta = scene.metadata or {}
    return str(
        scene_generation_id(meta)
        or (scene.video_clip.name if scene.video_clip else "")
        or (scene.image.name if scene.image else "")
        or f"scene-{scene.pk}"
    )


def _clamp(value, low=0.0, high=1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(low, min(high, number))


def _norm(value) -> str:
    text = re.sub(r"rm\s*", "", str(value or "").lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def transcription_similarity(expected: str, actual: str) -> float:
    left = set(_norm(expected).split())
    right = set(_norm(actual).split())
    if not left or not right:
        return 0.0
    return round(len(left & right) / max(len(left | right), 1), 3)


class VisualQAService:
    def __init__(self, gemini: IntelligenceClient | None = None):
        self.gemini = gemini or IntelligenceClient()

    def analyze_project(
        self,
        project: VideoProject,
        *,
        scenes: list[Scene] | None = None,
        force: bool = False,
    ) -> list[dict]:
        work = list(scenes or project.scenes.all())
        checks: list[dict] = []
        presenter_anchor = self._presenter_anchor(work, project)
        product_refs = self._product_refs(project)
        for scene in work:
            cached = None if force else self._cached(scene)
            if cached is not None:
                logger.info("Reusing visual QA cache for %s", scene.scene_key)
                checks.extend(cached.get("checks") or [])
                continue
            try:
                result = self.analyze_scene(
                    project,
                    scene,
                    product_refs=product_refs,
                    presenter_anchor=presenter_anchor,
                )
                checks.extend(result.get("checks") or [])
            except Exception:
                logger.exception("Visual QA failed for scene %s", scene.scene_key)
                checks.append(
                    self._unavailable(scene, "visual", "Visual analysis could not run for this scene.")
                )
        return checks

    def analyze_scene(
        self,
        project: VideoProject,
        scene: Scene,
        *,
        product_refs: list[Path] | None = None,
        presenter_anchor: Path | None = None,
    ) -> dict:
        product_refs = product_refs if product_refs is not None else self._product_refs(project)
        clip = media_path(scene.video_clip) or media_path(scene.image)
        meta = dict(scene.metadata or {})
        locked = {
            "product": bool(meta.get("product_locked")),
            "presenter": bool(meta.get("presenter_locked")),
            "caption": bool(meta.get("caption_locked")),
            "script": bool(meta.get("script_locked")),
        }

        if not clip:
            payload = {
                "qa_version": QA_VERSION,
                "generation_id": generation_key(scene),
                "frames": [],
                "checks": [
                    self._unavailable(
                        scene, "visual", "No generated scene video or still was available to inspect."
                    )
                ],
            }
            self._store(scene, payload)
            return payload

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            sampled = self._collect_frames(project, scene, clip, tmp_dir)
            if not sampled:
                payload = {
                    "qa_version": QA_VERSION,
                    "generation_id": generation_key(scene),
                    "frames": [],
                    "checks": [
                        self._unavailable(
                            scene, "visual", "Frame extraction failed, so visual QA could not run."
                        )
                    ],
                }
                self._store(scene, payload)
                return payload
            frames = self._persist_frames(project, scene, sampled)
            visual = self._multimodal(
                project,
                scene,
                product_refs=product_refs,
                frame_paths=[path for _, path in sampled],
                presenter_anchor=presenter_anchor or self._scene_presenter_ref(scene),
                locked=locked,
            )
            checks = []
            checks.extend(self._product_checks(scene, visual.get("product") or {}, locked, product_refs, frames))
            checks.extend(
                self._presenter_checks(
                    scene,
                    visual.get("presenter") or {},
                    locked,
                    bool(presenter_anchor or self._scene_presenter_ref(scene)),
                    frames,
                )
            )
            checks.extend(self._scene_match_checks(scene, visual.get("scene") or {}, frames))
            checks.extend(self._caption_checks(scene, visual.get("caption") or {}, locked, frames))
            checks.extend(self._audio_checks(project, scene, clip, tmp_dir, locked))

        payload = {
            "qa_version": QA_VERSION,
            "generation_id": generation_key(scene),
            "sample_plan": [item.get("timestamp") for item in frames],
            "frames": [{key: value for key, value in item.items() if key != "path"} for item in frames],
            "checks": checks,
        }
        self._store(scene, payload)
        return payload

    def _cached(self, scene: Scene) -> dict | None:
        meta = scene.metadata or {}
        cached = meta.get("visual_qa") or {}
        if not cached:
            return None
        if cached.get("qa_version") != QA_VERSION:
            return None
        if cached.get("generation_id") != generation_key(scene):
            return None
        if meta.get("needs_regeneration"):
            return None
        return cached

    def _store(self, scene: Scene, payload: dict) -> None:
        meta = dict(scene.metadata or {})
        meta["visual_qa"] = payload
        scene.metadata = meta
        scene.save(update_fields=["metadata"])

    def _product_refs(self, project: VideoProject) -> list[Path]:
        paths = []
        for item in snapshot_paths(project.product_snapshot or {}):
            path = Path(item)
            if path.exists():
                paths.append(path)
        try:
            for image in project.product.images.all():
                path = media_path(image.image)
                if path:
                    paths.append(path)
        except Exception:
            pass
        unique = []
        seen = set()
        for path in paths:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique[:2]

    def _scene_presenter_ref(self, scene: Scene) -> Path | None:
        meta = scene.metadata or {}
        raw = meta.get("presenter_reference") or meta.get("presenter_image")
        if raw:
            path = Path(str(raw))
            if path.exists():
                return path
        return None

    def _presenter_anchor(self, scenes: list[Scene], project: VideoProject | None = None) -> Path | None:
        for scene in scenes:
            ref = self._scene_presenter_ref(scene)
            if ref:
                return ref
        if project:
            from ai.services.presenter import presenter_image_paths

            for path in presenter_image_paths(project):
                resolved = Path(path)
                if resolved.exists():
                    return resolved
        return None

    def _collect_frames(
        self, project: VideoProject, scene: Scene, clip: Path, tmp_dir: Path
    ) -> list[tuple[float, Path]]:
        frames: list[tuple[float, Path]] = []
        if clip.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            dest_dir = tmp_dir / "frames"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"still{clip.suffix.lower()}"
            dest.write_bytes(clip.read_bytes())
            frames.append((0.0, dest))
        else:
            frames.extend(sample_frames(clip, tmp_dir / "frames"))
        preview = media_path(project.preview_video)
        if preview and preview.resolve() != clip.resolve():
            start = float((scene.metadata or {}).get("start_time") or 0)
            duration = float(scene.duration or 0)
            stamps = [max(start + 0.15, 0.0)]
            if duration > 3:
                stamps.append(start + duration * 0.5)
            frames.extend(sample_frames(preview, tmp_dir / "preview", stamps))
        return frames

    def _persist_frames(
        self, project: VideoProject, scene: Scene, sampled: list[tuple[float, Path]]
    ) -> list[dict]:
        frames = []
        for stamp, path in sampled:
            asset = VideoAsset(
                project=project,
                scene=scene,
                kind=VideoAsset.Kind.IMAGE,
                prompt="qa-frame",
                metadata={"qa_frame": True, "timestamp": stamp, "qa_version": QA_VERSION},
            )
            asset.file.save(
                f"{scene.scene_key}-t{int(stamp * 1000)}.jpg",
                ContentFile(path.read_bytes()),
                save=True,
            )
            frames.append(
                {
                    "timestamp": stamp,
                    "asset_id": asset.id,
                    "url": asset.file.url if asset.file else "",
                    "path": str(path),
                }
            )
        return frames

    def _multimodal(
        self,
        project: VideoProject,
        scene: Scene,
        *,
        product_refs: list[Path],
        frame_paths: list[Path],
        presenter_anchor: Path | None,
        locked: dict,
    ) -> dict:
        files = [
            path
            for path in [
                *product_refs[:2],
                *frame_paths[:5],
                *([presenter_anchor] if presenter_anchor else []),
            ]
            if path and path.exists()
        ]
        if not files:
            return {}
        meta = scene.metadata or {}
        prompt = (
            "You are doing visual QA for a product video. This is an AI visual assessment, not pixel-perfect proof.\n"
            "The first image(s) marked PRODUCT REFERENCE are the only approved product appearance. "
            "Never treat generated frames as the new product truth. "
            "Flag missing required components (handle, lid, attachments, markings) and major "
            "shape, colour, glaze, or surface changes.\n"
            f"Product locked: {locked['product']}\n"
            f"Presenter locked: {locked['presenter']}\n"
            f"Scene key: {scene.scene_key}\n"
            f"Shot: {meta.get('shot_description') or scene.visual}\n"
            f"Presenter action: {meta.get('presenter_action') or ''}\n"
            f"Location: {meta.get('location') or meta.get('background') or ''}\n"
            f"Approved caption: {scene.caption}\n"
            f"Product name: {(project.product_snapshot or {}).get('name')}\n"
            "Later images are generated frames from this scene, in time order.\n"
            "If a presenter reference image is included after the frames, compare identity against that photo only. "
            "If no presenter photo is included, set presenter.checked false unless you are only judging continuity.\n"
            "For captions: report whether on-screen text is visible, clipped, outside a 9:16 safe margin, "
            "or covering the product. If you cannot read text, set caption.unavailable true and caption.checked false.\n"
            "Return JSON only. Confidence must be 0-1."
        )
        try:
            return self.gemini.generate_json(
                prompt,
                schema=VISUAL_SCHEMA,
                files=files,
                system=(
                    "You inspect product video frames. Flag only obvious mismatches. "
                    "Do not invent certainty. Return JSON only."
                ),
                operation="visual_qa",
                project=project,
            )
        except (MissingAPIKeyError, ProviderError, GoogleProviderError):
            logger.info("Multimodal visual QA unavailable for %s", scene.scene_key)
            return {}
        except Exception:
            logger.exception("Multimodal visual QA error for %s", scene.scene_key)
            return {}

    def _product_checks(self, scene, visual: dict, locked: dict, refs: list[Path], frames: list[dict]) -> list[dict]:
        if not refs or not visual or visual.get("checked") is False:
            return []
        match = bool(visual.get("match", True))
        confidence = _clamp(visual.get("confidence") or (0.9 if match else 0.5))
        issues = [str(item) for item in (visual.get("issues") or []) if str(item).strip()]
        missing = [
            item
            for item in issues
            if any(word in item.lower() for word in ("handle", "pemegang", "missing", "lid", "component", "marking"))
        ]
        extra = []
        if missing:
            extra.append(
                self._check(
                    scene,
                    name="product_component",
                    category="product",
                    source="multimodal",
                    status=self._status(max(confidence, 0.85), "high", True),
                    severity="high",
                    confidence=max(confidence, 0.85),
                    detail=" ".join(missing) or "A required product component appears to be missing.",
                    recommended="Restore missing components and preserve the original product geometry from the approved photos.",
                    frames=frames,
                    timestamp=visual.get("timestamp"),
                    locked=locked["product"],
                )
            )
        if match and not missing:
            return [
                self._check(
                    scene,
                    name="product_visual_consistency",
                    category="product",
                    source="multimodal",
                    status="passed",
                    severity="info",
                    confidence=confidence,
                    detail=visual.get("message")
                    or f"Visual comparison passed — {int(confidence * 100)}% confidence.",
                    frames=frames,
                    timestamp=visual.get("timestamp"),
                    locked=locked["product"],
                )
            ]
        severity = "high" if locked["product"] or confidence >= 0.85 or missing else "medium"
        return [
            self._check(
                scene,
                name="product_visual_consistency",
                category="product",
                source="multimodal",
                status=self._status(confidence, severity, locked["product"]),
                severity=severity,
                confidence=confidence,
                detail=visual.get("message")
                or "Generated product appears visually different from the approved reference.",
                recommended="Regenerate this scene using the approved product reference. Keep the current script, presenter, location and caption locked.",
                frames=frames,
                timestamp=visual.get("timestamp"),
                locked=locked["product"],
            ),
            *extra,
        ]

    def _presenter_checks(
        self,
        scene,
        visual: dict,
        locked: dict,
        has_reference: bool,
        frames: list[dict],
    ) -> list[dict]:
        if not locked["presenter"] and not has_reference:
            return []
        if not visual:
            return []
        if visual.get("checked") is False and not visual.get("continuity_only"):
            return []
        match = visual.get("match") is True
        raw_confidence = visual.get("confidence")
        if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
            confidence = None
        else:
            confidence = _clamp(raw_confidence)
        score = 0.0 if confidence is None else confidence
        continuity = bool(visual.get("continuity_only")) or (locked["presenter"] and not has_reference)
        name = "presenter_continuity" if continuity else "presenter_visual_consistency"
        # Identity passes only against a reference photo at or above 90%.
        # A missing score is not turned into a pass. 0 stays 0.
        if has_reference and not continuity and match and confidence is not None and score >= 0.90:
            detail = visual.get("message") or (
                "AI compared this scene to earlier scenes — no approved presenter photo."
                if continuity
                else f"Presenter visual comparison passed — {int(confidence * 100)}% confidence."
            )
            return [
                self._check(
                    scene,
                    name=name,
                    category="presenter",
                    source="multimodal",
                    status="passed",
                    severity="info",
                    confidence=confidence,
                    detail=detail,
                    frames=frames,
                    timestamp=visual.get("timestamp"),
                    locked=locked["presenter"],
                )
            ]
        severity = "high" if locked["presenter"] or score >= 0.85 else "medium"
        status = "failed" if has_reference or locked["presenter"] else self._status(score, severity, False)
        return [
            self._check(
                scene,
                name=name,
                category="presenter",
                source="multimodal",
                status=status,
                severity=severity,
                confidence=score,
                detail=visual.get("message")
                or "A different presenter or a major appearance change appears in this scene.",
                recommended="Regenerate this scene with the presenter lock on. Keep the same person and outfit.",
                frames=frames,
                timestamp=visual.get("timestamp"),
                locked=locked["presenter"],
            )
        ]

    def _scene_match_checks(self, scene, visual: dict, frames: list[dict]) -> list[dict]:
        if not visual or visual.get("checked") is False:
            return []
        match = bool(visual.get("match", True))
        confidence = _clamp(visual.get("confidence") or 0.7)
        if match:
            return [
                self._check(
                    scene,
                    name="scene_visual_match",
                    category="scene",
                    source="multimodal",
                    status="passed",
                    severity="info",
                    confidence=confidence,
                    detail=visual.get("message")
                    or f"Scene broadly matches the planned shot — {int(confidence * 100)}% confidence.",
                    frames=frames,
                    timestamp=visual.get("timestamp"),
                )
            ]
        return [
            self._check(
                scene,
                name="scene_visual_match",
                category="scene",
                source="multimodal",
                status=self._status(confidence, "medium", False),
                severity="medium" if confidence >= 0.6 else "low",
                confidence=confidence,
                detail=visual.get("message")
                or "Generated frames do not broadly match the planned location, shot, or action.",
                recommended="Edit the scene description or regenerate this scene only.",
                frames=frames,
                timestamp=visual.get("timestamp"),
            )
        ]

    def _caption_checks(self, scene, visual: dict, locked: dict, frames: list[dict]) -> list[dict]:
        if not visual or visual.get("unavailable") or visual.get("checked") is False:
            return []
        confidence = _clamp(visual.get("confidence") or 0.6)
        problems = []
        if visual.get("visible") is False:
            problems.append("Caption does not appear to be visible in sampled frames.")
        if visual.get("clipped"):
            problems.append("On-screen text looks clipped.")
        if visual.get("outside_safe_area"):
            problems.append("On-screen text may sit outside the safe area.")
        if visual.get("overlaps_product"):
            problems.append("On-screen text appears to cover the product.")
        if visual.get("contrast_ok") is False:
            problems.append("Caption contrast looks too low to read.")
        if not problems:
            return [
                self._check(
                    scene,
                    name="caption_visual",
                    category="caption",
                    source="multimodal",
                    status="passed",
                    severity="info",
                    confidence=confidence,
                    detail=visual.get("message")
                    or f"Caption appears readable in sampled frames — {int(confidence * 100)}% confidence.",
                    frames=frames,
                )
            ]
        severity = "high" if locked["caption"] else "medium"
        return [
            self._check(
                scene,
                name="caption_visual",
                category="caption",
                source="multimodal",
                status=self._status(confidence, severity, locked["caption"]),
                severity=severity,
                confidence=confidence,
                detail=visual.get("message") or " ".join(problems),
                recommended=(
                    "Keep the approved caption and regenerate this scene so the text stays readable "
                    "and inside safe margins."
                ),
                frames=frames,
                locked=locked["caption"],
            )
        ]

    def _audio_checks(
        self,
        project: VideoProject,
        scene: Scene,
        clip: Path,
        tmp_dir: Path,
        locked: dict,
    ) -> list[dict]:
        expected = (scene.narration or "").strip()
        if clip.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            return []
        report = inspect_audio(clip)
        if report.get("has_audio") and (report.get("silent") or not report.get("audible")):
            return []
        if not expected:
            return []
        extracted = media_path(scene.audio) or extract_audio(clip, tmp_dir / "audio.mp3")
        if not extracted:
            if expected:
                return [
                    self._check(
                        scene,
                        name="audio_missing",
                        category="audio",
                        source="ffmpeg",
                        status="failed",
                        severity="high",
                        confidence=0.9,
                        detail="No speech audio could be extracted from the generated scene.",
                        recommended="Regenerate this scene because generated audio is missing or effectively silent.",
                        locked=locked["script"],
                    )
                ]
            return []
        text = ""
        try:
            text = (
                self.gemini.transcribe(extracted, language=project.language, project=project) or ""
            ).strip()
        except (MissingAPIKeyError, ProviderError, GoogleProviderError):
            if speech_configured():
                try:
                    from ai.providers.google.speech import SpeechProvider

                    text = SpeechProvider().transcribe(
                        Path(extracted).read_bytes(), language=project.language
                    ).strip()
                except Exception:
                    logger.info("Speech transcription unavailable for %s", scene.scene_key)
                    return []
            else:
                return []
        except Exception:
            logger.exception("Transcription failed for %s", scene.scene_key)
            return []
        if not text:
            return [
                self._check(
                    scene,
                    name="audio_missing",
                    category="audio",
                    source="transcription",
                    status="warning",
                    severity="medium",
                    confidence=0.8,
                    detail="No speech was recognised in the generated audio.",
                    recommended="Regenerate this scene so the approved voice-over is spoken.",
                    locked=locked["script"],
                )
            ]
        score = transcription_similarity(expected, text)
        if score >= 0.45:
            return [
                self._check(
                    scene,
                    name="voiceover_mismatch",
                    category="audio",
                    source="transcription",
                    status="passed",
                    severity="info",
                    confidence=score,
                    detail=f"Generated speech broadly matches the approved narration — {int(score * 100)}% overlap.",
                    locked=locked["script"],
                )
            ]
        severity = "high" if locked["script"] else "medium"
        mismatch = 0.9 if score < 0.15 else round(1 - score, 3)
        return [
            self._check(
                scene,
                name="voiceover_mismatch",
                category="audio",
                source="transcription",
                status=self._status(mismatch, severity, locked["script"]),
                severity=severity,
                confidence=mismatch,
                detail="Generated speech differs materially from the approved narration.",
                recommended="Keep the approved script locked and regenerate this scene only.",
                locked=locked["script"],
            )
        ]

    def _status(self, confidence: float, severity: str, locked: bool) -> str:
        if confidence < 0.6:
            return "warning"
        if confidence >= 0.85 and severity in {"high", "critical"} and locked:
            return "failed"
        if confidence >= 0.85 and severity == "critical":
            return "failed"
        return "warning"

    def _check(
        self,
        scene: Scene,
        *,
        name: str,
        category: str,
        source: str,
        status: str,
        severity: str,
        confidence: float,
        detail: str,
        recommended: str = "",
        frames: list[dict] | None = None,
        timestamp=None,
        locked: bool = False,
    ) -> dict:
        start = float((scene.metadata or {}).get("start_time") or 0)
        local = float(timestamp) if timestamp is not None else (frames[0]["timestamp"] if frames else 0)
        frame = None
        if frames:
            frame = min(frames, key=lambda item: abs(float(item.get("timestamp") or 0) - local))
        return {
            "name": name,
            "status": status,
            "detail": detail,
            "qa_category": category,
            "source": source,
            "confidence": _clamp(confidence),
            "severity": severity,
            "scene_id": scene.scene_key,
            "affected_scenes": [scene.scene_key],
            "timestamp": round(start + local, 2),
            "start": start,
            "end": float((scene.metadata or {}).get("end_time") or start + float(scene.duration or 0)),
            "frame_url": (frame or {}).get("url") or "",
            "recommended_action": recommended or detail,
            "evidence": "AI visual assessment" if source == "multimodal" else source,
            "checked": True,
            "verified": source == "structural",
            "locked": locked,
        }

    def _unavailable(self, scene: Scene, category: str, detail: str) -> dict:
        start = float((scene.metadata or {}).get("start_time") or 0)
        return {
            "name": f"{category}_unavailable",
            "status": "skipped",
            "detail": detail,
            "qa_category": category,
            "source": "multimodal",
            "confidence": 0,
            "severity": "info",
            "scene_id": scene.scene_key,
            "affected_scenes": [scene.scene_key],
            "timestamp": start,
            "start": start,
            "end": start + float(scene.duration or 0),
            "frame_url": "",
            "recommended_action": "",
            "checked": False,
            "verified": False,
        }


def build_qa_layers(checks: list[dict]) -> dict:
    def pick(category: str, names: list[str]) -> dict:
        matched = [
            item
            for item in checks
            if item.get("qa_category") == category or item.get("name") in names
        ]
        visual = [
            item
            for item in matched
            if item.get("source") in {"multimodal", "transcription", "OCR"}
        ]
        structural = [
            item
            for item in matched
            if item.get("source") not in {"multimodal", "transcription", "OCR"}
        ]
        visual_checked = [
            item
            for item in visual
            if item.get("checked") is not False and item.get("status") != "skipped"
        ]
        structural_checked = [item for item in structural if item.get("status") != "skipped"]

        def worst(items):
            if any(item.get("status") == "failed" for item in items):
                return "failed"
            if any(item.get("status") == "warning" for item in items):
                return "warning"
            if items:
                return "passed"
            return "not_checked"

        confidence = 0.0
        if visual_checked:
            confidence = max(float(item.get("confidence") or 0) for item in visual_checked)
        return {
            "structural": {
                "status": worst(structural_checked) if structural_checked else "not_checked",
                "detail": (
                    structural_checked[0].get("detail")
                    if structural_checked
                    else "Not checked in the script."
                ),
            },
            "visual": {
                "status": worst(visual_checked) if visual_checked else "not_checked",
                "confidence": confidence,
                "source": visual_checked[0].get("source") if visual_checked else "",
                "detail": (
                    visual_checked[0].get("detail")
                    if visual_checked
                    else "Visual comparison not available."
                ),
            },
        }

    return {
        "product": pick(
            "product",
            ["product", "product_consistency", "product_representation", "product_visual_consistency", "product_component", "variant"],
        ),
        "presenter": pick(
            "presenter",
            ["presenter_consistency", "presenter_visual_consistency", "presenter_continuity"],
        ),
        "scene": pick("scene", ["scene_completeness", "scene_visual_match", "video_generation"]),
        "caption": pick("caption", ["captions", "visible_captions", "caption_visual", "caption_lines"]),
        "audio": pick(
            "audio",
            [
                "narration",
                "pronunciation",
                "voiceover_mismatch",
                "audio_missing",
                "audio_silent",
                "audio_stream",
                "audio_duration",
                "assembled_audio",
            ],
        ),
        "offer": pick("offer", ["price", "expired_offer", "cta_complete"]),
        "claim": pick("claim", ["claims"]),
        "safety": pick("safety", ["ai_review", "disclosures"]),
    }


def serious_visual_issues(checks: list[dict]) -> list[dict]:
    serious = []
    for check in checks:
        if check.get("status") not in {"failed", "warning"}:
            continue
        if check.get("source") not in {"multimodal", "transcription", "OCR"}:
            continue
        if float(check.get("confidence") or 0) < 0.85:
            continue
        if check.get("severity") not in {"high", "critical"}:
            continue
        serious.append(check)
    return serious
