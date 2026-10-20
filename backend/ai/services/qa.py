from __future__ import annotations

import logging
import re

from pathlib import Path

from django.core.exceptions import ObjectDoesNotExist

from ai.models import QAStatus, Scene, VideoProject
from ai.providers.intelligence import IntelligenceClient
from ai.services.captions import caption_line_count
from ai.services.director import _cta_is_complete, is_video_fallback
from ai.services.ffmpeg import inspect_audio
from ai.services.identity_qa import apply_scene_gates, project_gates_pass
from ai.services.validation import offer_is_expired, unsupported_claims
from ai.services.visual_qa import VisualQAService, build_qa_layers, serious_visual_issues

logger = logging.getLogger(__name__)


def qa_stage_id(stage: str) -> str:
    value = str(stage or "").strip().lower()
    if value in {"seedance", "byteplus", "ark", "veo", "gemini", "gemini_omni", "omni"}:
        return "video_generation"
    if value in {"assembly", "assemble", "ffmpeg"}:
        return "assembly"
    return value.replace(" ", "_") or "video_generation"


def _character_consistency_check(project: VideoProject, checks: list[dict]) -> dict:
    """Report a real visual comparison when one ran. Otherwise leave the check unchecked."""
    try:
        config = project.character_config
    except ObjectDoesNotExist:
        config = None
    visual = next(
        (
            item
            for item in checks
            if item.get("name") == "presenter_visual_consistency"
            and item.get("checked") is not False
            and item.get("status") in {QAStatus.PASSED, QAStatus.FAILED, QAStatus.WARNING, "passed", "failed", "warning"}
        ),
        None,
    )
    if config and visual:
        return {
            "name": "character_consistency",
            "status": visual.get("status"),
            "detail": visual.get("detail") or "Generated scenes were compared with the character reference.",
            "source": visual.get("source") or "multimodal",
            "qa_category": "character",
            "checked": True,
            "verified": bool(visual.get("verified")),
            "affected_scenes": visual.get("affected_scenes") or [],
            "scene_id": visual.get("scene_id") or "",
            "severity": visual.get("severity") or "",
        }
    return {
        "name": "character_consistency",
        "status": "not_checked",
        "detail": "Character consistency was not compared with the reference images in this run.",
        "qa_category": "character",
        "checked": False,
        "verified": False,
    }


def qa_stage_label(stage: str) -> str:
    ident = qa_stage_id(stage)
    return ident.replace("_", " ")

STRUCTURAL_CATEGORIES = {
    "product": "product",
    "product_consistency": "product",
    "product_representation": "product",
    "variant": "product",
    "price": "offer",
    "expired_offer": "offer",
    "claims": "claim",
    "captions": "caption",
    "visible_captions": "caption",
    "narration": "audio",
    "pronunciation": "audio",
    "audio_stream": "audio",
    "audio_silent": "audio",
    "audio_duration": "audio",
    "assembled_audio": "audio",
    "caption_lines": "caption",
    "cta_complete": "offer",
    "scene_variety": "scene",
    "malay_copy": "safety",
    "scene_completeness": "scene",
    "video_generation": "scene",
    "presenter_consistency": "presenter",
    "ai_review": "safety",
}

QA_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["passed", "warning", "failed"]},
        "summary": {"type": "string"},
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "status": {"type": "string", "enum": ["passed", "warning", "failed"]},
                    "detail": {"type": "string"},
                },
                "required": ["name", "status", "detail"],
            },
        },
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "pronunciation": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary", "checks"],
}


def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def spoken_text(project: VideoProject, scenes: list[Scene]) -> str:
    return " ".join(
        [
            str(project.script),
            str(project.narration),
            str(project.captions),
            " ".join(scene.narration for scene in scenes),
            " ".join(scene.caption for scene in scenes),
        ]
    )


class QAService:
    def __init__(self, gemini: IntelligenceClient | None = None):
        self.gemini = gemini or IntelligenceClient()

    def run(self, project: VideoProject, *, force: bool = False) -> dict:
        snapshot = project.product_snapshot or {}
        scenes = list(project.scenes.all())
        checks = []
        checks.extend(self._truth_checks(snapshot, project, scenes))
        checks.extend(self._scene_checks(scenes))
        gemini_qa = {}
        try:
            gemini_qa = self.gemini.generate_json(
                (
                    "Validate this video project against approved product facts. "
                    "Check product, variant, price, dimensions, claims, captions, "
                    "narration, pronunciation, scene completeness, product consistency, "
                    "natural Malaysian Malay copy, commercial CTA, and scene variety.\n"
                    f"Snapshot: {snapshot}\n"
                    f"Script: {project.script}\n"
                    f"Captions: {project.captions}\n"
                    f"Narration: {project.narration}\n"
                    f"Scenes: {[self._scene_payload(scene) for scene in scenes]}"
                ),
                schema=QA_SCHEMA,
                system="You QA product videos. Flag invented claims. Return JSON only.",
            )
            checks.extend(gemini_qa.get("checks") or [])
        except Exception:
            checks.append(
                {
                    "name": "ai_review",
                    "status": QAStatus.WARNING,
                    "detail": (
                        "Automated language review was unavailable. "
                        "Please review the copy manually or run AI Review again."
                    ),
                    "source": "provider",
                    "qa_category": "safety",
                    "checked": False,
                    "verified": False,
                }
            )

        try:
            checks.extend(
                VisualQAService(self.gemini).analyze_project(project, scenes=scenes, force=force)
            )
        except Exception:
            logger.exception("Visual QA failed for project %s", project.pk)

        checks.append(_character_consistency_check(project, checks))
        checks.extend(self._file_audio_checks(project, scenes))
        gate_checks, scene_gates = apply_scene_gates(project, scenes, self.gemini)
        checks.extend(gate_checks)
        checks.extend(self._caption_structure(scenes))
        checks.extend(self._cta_check(project, scenes))
        checks.extend(self._scene_variety(scenes))
        if project.preview_video and not any(
            item.get("name") == "product_visual_consistency" and item.get("status") not in {"skipped", "not_checked"}
            for item in checks
        ):
            checks.append(
                {
                    "name": "product_visual_consistency",
                    "status": "not_checked",
                    "detail": (
                        "Original product photos were not compared with the generated video. "
                        "AI visual review could not be completed."
                    ),
                    "source": "multimodal",
                    "qa_category": "product",
                    "severity": "high",
                    "checked": False,
                    "verified": False,
                }
            )

        checks = [self._decorate(check) for check in checks]
        status = self._roll_up(checks)
        if gemini_qa.get("status") == QAStatus.FAILED:
            status = QAStatus.FAILED
        elif gemini_qa.get("status") == QAStatus.WARNING and status == QAStatus.PASSED:
            status = QAStatus.WARNING

        flagged = list(
            dict.fromkeys(
                [
                    *(gemini_qa.get("unsupported_claims") or []),
                    *unsupported_claims(spoken_text(project, scenes), snapshot),
                ]
            )
        )
        result = {
            "status": status,
            "summary": gemini_qa.get("summary")
            or self._summary(status, checks),
            "checks": checks,
            "unsupported_claims": flagged,
            "pronunciation": gemini_qa.get("pronunciation") or [],
            "issues": self._issues(checks, scenes),
            "layers": build_qa_layers(checks),
            "serious_issues": serious_visual_issues(checks),
            "release_blocking": release_blocking_issues(checks, has_preview=bool(project.preview_video)),
            "scene_gates": scene_gates,
            "scene_gates_passed": project_gates_pass(scene_gates),
            "disclaimer": (
                "AI checks are not guaranteed compliance. Visual and audio checks are AI assessments, not pixel-perfect proof."
            ),
        }
        tiktok = self._tiktok_checks(snapshot, project, scenes)
        result["tiktok_shop"] = tiktok
        project.qa_results = result
        project.qa_status = status
        project.tiktok_checks = tiktok
        project.save(update_fields=["qa_results", "qa_status", "tiktok_checks", "updated_at"])
        return result

    def _tiktok_checks(self, snapshot: dict, project: VideoProject, scenes: list[Scene]) -> dict:
        captions = bool((project.captions or {}).get("lines") or any(scene.caption for scene in scenes))
        link = snapshot.get("product_link") or ""
        expired = offer_is_expired(snapshot)
        checks = [
            {
                "name": "product_price",
                "status": QAStatus.FAILED if not snapshot.get("price") else QAStatus.PASSED,
                "detail": "Product and price are present in the approved snapshot.",
            },
            {
                "name": "visible_captions",
                "status": QAStatus.PASSED if captions else QAStatus.FAILED,
                "detail": "Captions are present." if captions else "Add visible captions before export.",
            },
            {
                "name": "product_link",
                "status": QAStatus.PASSED if link else QAStatus.WARNING,
                "detail": "Product link is set." if link else "Add the product link before TikTok Shop export.",
            },
            {
                "name": "expired_offer",
                "status": QAStatus.FAILED if expired else QAStatus.PASSED,
                "detail": "Offer is current." if not expired else "The offer has expired.",
            },
            {
                "name": "disclosures",
                "status": QAStatus.WARNING,
                "detail": "Add required AI/commercial disclosures before posting. Approval is not guaranteed.",
            },
            {
                "name": "music_rights",
                "status": QAStatus.WARNING,
                "detail": "Confirm music rights. This studio does not license third-party tracks.",
            },
        ]
        statuses = {item["status"] for item in checks}
        status = QAStatus.FAILED if QAStatus.FAILED in statuses else (
            QAStatus.WARNING if QAStatus.WARNING in statuses else QAStatus.PASSED
        )
        return {
            "status": status,
            "checks": checks,
            "disclaimer": "TikTok Shop checks are guidance only. Approval is not guaranteed.",
        }

    def _truth_checks(self, snapshot: dict, project: VideoProject, scenes: list[Scene]) -> list[dict]:
        blob = _norm(spoken_text(project, scenes))
        checks = []
        if offer_is_expired(snapshot):
            checks.append(
                {
                    "name": "expired_offer",
                    "status": QAStatus.FAILED,
                    "detail": "The approved offer has expired. Remove or update it before publishing.",
                }
            )
        name = snapshot.get("name") or ""
        if name:
            checks.append(
                self._contains(
                    "product",
                    name,
                    blob,
                    f'Wrong product or missing name. Use "{name}".',
                )
            )
        price = snapshot.get("price") or ""
        if price:
            checks.append(self._contains("price", str(price), blob, f"Use the approved price {price}."))
        dimensions = snapshot.get("dimensions") or ""
        if dimensions:
            checks.append(
                self._contains(
                    "dimensions",
                    dimensions,
                    blob,
                    f"Keep dimensions as {dimensions}.",
                    warning_if_missing=True,
                )
            )
        variants = snapshot.get("variants") or []
        if variants:
            matched = any(_norm(variant) in blob for variant in variants)
            checks.append(
                {
                    "name": "variant",
                    "status": QAStatus.PASSED if matched else QAStatus.WARNING,
                    "detail": "A listed variant appears in the script."
                    if matched
                    else "No listed variant was mentioned.",
                }
            )
        for claim in snapshot.get("prohibited_claims") or []:
            if _norm(claim) and _norm(claim) in blob:
                checks.append(
                    {
                        "name": "claims",
                        "status": QAStatus.FAILED,
                        "detail": f'Prohibited claim found: "{claim}".',
                    }
                )
        if not any(check["name"] == "claims" for check in checks):
            checks.append(
                {
                    "name": "claims",
                    "status": QAStatus.PASSED,
                    "detail": "No prohibited claims were found.",
                }
            )
        representation = (
            QAStatus.PASSED
            if all(scene.image or scene.video_clip for scene in scenes)
            else QAStatus.WARNING
        )
        checks.append(
            {
                "name": "product_representation",
                "status": representation,
                "detail": "Each scene has a product visual."
                if representation == QAStatus.PASSED
                else "Some scenes may not show the approved product.",
            }
        )
        return checks

    def _scene_checks(self, scenes: list[Scene]) -> list[dict]:
        if not scenes:
            return [
                {
                    "name": "scene_completeness",
                    "status": QAStatus.FAILED,
                    "detail": "No scenes were generated.",
                }
            ]
        missing = []
        fallbacks = []
        for scene in scenes:
            if not (scene.visual and scene.narration and scene.caption and scene.duration):
                missing.append(scene.scene_key)
            if not (scene.image or scene.video_clip):
                missing.append(f"{scene.scene_key} assets")
            if is_video_fallback(scene.metadata):
                fallbacks.append(scene.scene_key)
        checks = []
        if fallbacks:
            all_fallback = len(fallbacks) == len(scenes)
            checks.append(
                {
                    "name": "video_generation",
                    "status": QAStatus.FAILED if all_fallback else QAStatus.WARNING,
                    "detail": (
                        "Every scene used a still-image fallback because video generation failed."
                        if all_fallback
                        else "Some scenes used a still-image fallback: " + ", ".join(fallbacks)
                    ),
                }
            )
        if missing:
            return [
                *checks,
                {
                    "name": "scene_completeness",
                    "status": QAStatus.FAILED,
                    "detail": "Incomplete scenes: " + ", ".join(missing),
                },
                {
                    "name": "product_consistency",
                    "status": QAStatus.WARNING,
                    "detail": "Some scenes are missing visuals or product assets.",
                },
            ]
        audio_ok = all(scene.narration for scene in scenes)
        presenter_lock = any((scene.metadata or {}).get("presenter_locked") for scene in scenes)
        complete = [
            *checks,
            {
                "name": "scene_completeness",
                "status": QAStatus.PASSED,
                "detail": f"{len(scenes)} scenes are complete.",
            },
            {
                "name": "captions",
                "status": QAStatus.PASSED,
                "detail": "Every scene has a caption.",
            },
            {
                "name": "narration",
                "status": QAStatus.PASSED if audio_ok else QAStatus.WARNING,
                "detail": "Every scene has narration." if audio_ok else "Some scenes are missing voice-over.",
            },
            {
                "name": "product_consistency",
                "status": QAStatus.PASSED,
                "detail": "Each scene has a generated visual. This is not a visual product comparison.",
                "source": "structural",
                "qa_category": "product",
            },
        ]
        if presenter_lock:
            complete.append(
                {
                    "name": "presenter_consistency",
                    "status": QAStatus.PASSED,
                    "detail": "Presenter lock is set.",
                    "source": "structural",
                    "qa_category": "presenter",
                    "verified": False,
                }
            )
        return complete

    def _file_audio_checks(self, project: VideoProject, scenes: list[Scene]) -> list[dict]:
        checks = []
        for scene in scenes:
            clip = None
            try:
                if scene.video_clip:
                    clip = Path(scene.video_clip.path)
            except (ValueError, OSError):
                clip = None
            if not clip or not clip.exists():
                if scene.narration:
                    checks.append(
                        {
                            "name": "audio_stream",
                            "status": QAStatus.FAILED,
                            "detail": "No generated scene file is available to inspect for audio.",
                            "source": "ffmpeg",
                            "qa_category": "audio",
                            "severity": "high",
                            "affected_scenes": [scene.scene_key],
                            "scene_id": scene.scene_key,
                            "stage": "video_generation",
                            "reason": "Missing scene video",
                            "verified": True,
                        }
                    )
                continue
            report = inspect_audio(clip)
            raw_stage = ((scene.metadata or {}).get("pipeline_error") or {}).get("stage") or "video_generation"
            stage = qa_stage_id(raw_stage)
            stage_label = qa_stage_label(stage)
            if not report.get("has_audio"):
                checks.append(
                    {
                        "name": "audio_stream",
                        "status": QAStatus.FAILED,
                        "detail": "Audio: FAILED. Reason: No audio stream in the generated file. "
                        f"Stage: {stage_label}.",
                        "source": "ffmpeg",
                        "qa_category": "audio",
                        "severity": "high",
                        "affected_scenes": [scene.scene_key],
                        "scene_id": scene.scene_key,
                        "stage": stage,
                        "reason": report.get("reason") or "No audio stream",
                        "mean_volume": report.get("mean_volume"),
                        "verified": True,
                    }
                )
                continue
            if report.get("silent") or not report.get("audible"):
                checks.append(
                    {
                        "name": "audio_silent",
                        "status": QAStatus.FAILED,
                        "detail": (
                            "Audio: FAILED. Reason: Audio track is present but effectively silent. "
                            f"Stage: {stage_label}."
                        ),
                        "source": "ffmpeg",
                        "qa_category": "audio",
                        "severity": "high",
                        "affected_scenes": [scene.scene_key],
                        "scene_id": scene.scene_key,
                        "stage": stage,
                        "reason": "Audio track is present but effectively silent",
                        "mean_volume": report.get("mean_volume"),
                        "verified": True,
                    }
                )
            elif report.get("coverage", 1) < 0.5:
                checks.append(
                    {
                        "name": "audio_duration",
                        "status": QAStatus.FAILED,
                        "detail": "Audio: FAILED. Reason: Audio does not cover the expected video duration. "
                        f"Stage: {stage_label}.",
                        "source": "ffmpeg",
                        "qa_category": "audio",
                        "severity": "high",
                        "affected_scenes": [scene.scene_key],
                        "scene_id": scene.scene_key,
                        "stage": stage,
                        "reason": report.get("reason") or "Short audio duration",
                        "verified": True,
                    }
                )
            else:
                mean = report.get("mean_volume")
                checks.append(
                    {
                        "name": "audio_stream",
                        "status": QAStatus.PASSED,
                        "detail": (
                            f"Scene audio is audible"
                            + (f" ({mean:.1f} dB mean)." if mean is not None else ".")
                        ),
                        "source": "ffmpeg",
                        "qa_category": "audio",
                        "severity": "info",
                        "affected_scenes": [scene.scene_key],
                        "scene_id": scene.scene_key,
                        "verified": True,
                    }
                )
        preview = None
        try:
            if project.preview_video:
                preview = Path(project.preview_video.path)
        except (ValueError, OSError):
            preview = None
        if preview and preview.exists():
            report = inspect_audio(preview)
            if not report.get("audible"):
                checks.append(
                    {
                        "name": "assembled_audio",
                        "status": QAStatus.FAILED,
                        "detail": (
                            "Audio: FAILED. Reason: "
                            f"{report.get('reason') or 'Final assembled video has no audible audio'}. "
                            "Stage: assembly."
                        ),
                        "source": "ffmpeg",
                        "qa_category": "audio",
                        "severity": "high",
                        "stage": "assembly",
                        "reason": report.get("reason") or "Final video has no audible audio",
                        "mean_volume": report.get("mean_volume"),
                        "verified": True,
                    }
                )
            else:
                mean = report.get("mean_volume")
                checks.append(
                    {
                        "name": "assembled_audio",
                        "status": QAStatus.PASSED,
                        "detail": (
                            "Final assembled video contains audible audio"
                            + (f" ({mean:.1f} dB mean)." if mean is not None else ".")
                        ),
                        "source": "ffmpeg",
                        "qa_category": "audio",
                        "severity": "info",
                        "verified": True,
                    }
                )
        elif scenes and any(scene.video_clip for scene in scenes):
            checks.append(
                {
                    "name": "assembled_audio",
                    "status": "not_checked",
                    "detail": "Final assembled video was not available to inspect.",
                    "source": "ffmpeg",
                    "qa_category": "audio",
                    "severity": "high",
                    "checked": False,
                    "verified": False,
                }
            )
        return checks

    def _caption_structure(self, scenes: list[Scene]) -> list[dict]:
        checks = []
        for scene in scenes:
            if not scene.caption:
                continue
            lines = caption_line_count(scene.caption)
            if lines > 2:
                checks.append(
                    {
                        "name": "caption_lines",
                        "status": QAStatus.FAILED,
                        "detail": "Captions must be a maximum of two lines.",
                        "source": "structural",
                        "qa_category": "caption",
                        "severity": "high",
                        "affected_scenes": [scene.scene_key],
                        "scene_id": scene.scene_key,
                        "verified": True,
                    }
                )
        if not any(check["name"] == "caption_lines" for check in checks) and any(scene.caption for scene in scenes):
            checks.append(
                {
                    "name": "caption_lines",
                    "status": QAStatus.PASSED,
                    "detail": "Captions are within two lines.",
                    "source": "structural",
                    "qa_category": "caption",
                    "verified": True,
                }
            )
        return checks

    def _cta_check(self, project: VideoProject, scenes: list[Scene]) -> list[dict]:
        last = scenes[-1] if scenes else None
        if not last:
            return []
        text = f"{last.caption} {last.narration} {(project.script or {}).get('cta') or ''}"
        complete = _cta_is_complete(text, project)
        return [
            {
                "name": "cta_complete",
                "status": QAStatus.PASSED if complete else QAStatus.FAILED,
                "detail": (
                    "The ending CTA includes the product, approved price, and a purchase action."
                    if complete
                    else "The ending CTA is not commercially complete. Include product name, approved price, and a purchase action."
                ),
                "source": "structural",
                "qa_category": "offer",
                "severity": "high" if not complete else "info",
                "affected_scenes": [last.scene_key],
                "scene_id": last.scene_key,
                "verified": True,
            }
        ]

    def _scene_variety(self, scenes: list[Scene]) -> list[dict]:
        if len(scenes) < 3:
            return []
        similar = 0
        for left, right in zip(scenes, scenes[1:]):
            if _shot_overlap(left.visual, right.visual) >= 0.72:
                similar += 1
        if similar >= max(2, len(scenes) // 2):
            return [
                {
                    "name": "scene_variety",
                    "status": QAStatus.FAILED,
                    "detail": "Scenes look repetitive. Replace a static product shot with a distinct action, detail, or lifestyle beat.",
                    "source": "structural",
                    "qa_category": "scene",
                    "severity": "medium",
                    "affected_scenes": [scene.scene_key for scene in scenes],
                    "verified": True,
                }
            ]
        return [
            {
                "name": "scene_variety",
                "status": QAStatus.PASSED,
                "detail": "Scenes have distinct planned shots.",
                "source": "structural",
                "qa_category": "scene",
                "verified": True,
            }
        ]

    def _contains(
        self,
        name: str,
        needle: str,
        blob: str,
        detail: str,
        warning_if_missing: bool = False,
    ) -> dict:
        found = _norm(needle) in blob
        if found:
            passed = (
                "Product information/claims match the product record."
                if name == "product"
                else f"{name.title()} matches the product record."
            )
            return {"name": name, "status": QAStatus.PASSED, "detail": passed}
        status = QAStatus.WARNING if warning_if_missing else QAStatus.FAILED
        return {"name": name, "status": status, "detail": detail}

    def _roll_up(self, checks: list[dict]) -> str:
        statuses = {
            check.get("status")
            for check in checks
            if check.get("status") not in {"skipped", "not_checked"}
        }
        if QAStatus.FAILED in statuses:
            return QAStatus.FAILED
        if QAStatus.WARNING in statuses:
            return QAStatus.WARNING
        return QAStatus.PASSED

    def _decorate(self, check: dict) -> dict:
        name = str(check.get("name") or "")
        source = check.get("source") or ("provider" if name == "ai_review" else "structural")
        decorated = {
            **check,
            "qa_category": check.get("qa_category") or STRUCTURAL_CATEGORIES.get(name, "scene"),
            "source": source,
            "confidence": check.get("confidence", 1.0 if source == "structural" else 0),
            "severity": check.get("severity")
            or (
                "high"
                if check.get("status") == QAStatus.FAILED
                else "medium"
                if check.get("status") == QAStatus.WARNING
                else "info"
            ),
            "checked": check.get("checked", check.get("status") != "skipped"),
            "verified": check.get(
                "verified",
                source == "structural" and name in {"product", "price", "claims", "expired_offer"},
            ),
        }
        if decorated.get("status") in {"not_checked", "skipped"}:
            decorated["checked"] = False
            decorated["verified"] = False
            decorated["confidence"] = None
        return decorated

    def _summary(self, status: str, checks: list[dict]) -> str:
        failed = [check["name"] for check in checks if check.get("status") == QAStatus.FAILED]
        if status == QAStatus.PASSED:
            return "The video matches the approved product information."
        if failed:
            return "Fix: " + ", ".join(failed)
        return "Review the warnings before you approve this video."

    def _issues(self, checks: list[dict], scenes: list[Scene]) -> list[dict]:
        issues = []
        for check in checks:
            if check.get("status") not in {QAStatus.FAILED, QAStatus.WARNING}:
                continue
            issues.append(
                {
                    "type": check.get("name"),
                    "severity": check.get("severity")
                    or ("high" if check.get("status") == QAStatus.FAILED else "medium"),
                    "confidence": check.get("confidence"),
                    "start": check.get("start") or check.get("timestamp") or 0,
                    "end": check.get("end") or 0,
                    "timestamp": check.get("timestamp"),
                    "scene_id": check.get("scene_id"),
                    "message": check.get("detail"),
                    "recommended_action": check.get("recommended_action") or check.get("detail"),
                    "affected_scenes": check.get("affected_scenes")
                    or [scene.scene_key for scene in scenes[-1:]],
                    "frame_url": check.get("frame_url") or "",
                    "source": check.get("source") or "structural",
                    "qa_category": check.get("qa_category"),
                }
            )
        self._stamp_scene_qa(scenes, checks)
        return issues[:12]

    def _stamp_scene_qa(self, scenes: list[Scene], checks: list[dict]) -> None:
        for scene in scenes:
            meta = dict(scene.metadata or {})
            if meta.get("status") == "failed":
                continue
            own = [
                check
                for check in checks
                if scene.scene_key in (check.get("affected_scenes") or [])
            ]
            if not own:
                meta["qa_status"] = meta.get("qa_status") or QAStatus.PASSED
                scene.metadata = meta
                scene.save(update_fields=["metadata"])
                continue
            statuses = {check.get("status") for check in own}
            if QAStatus.FAILED in statuses:
                meta["qa_status"] = QAStatus.FAILED
                meta["status"] = "qa_failed"
            elif QAStatus.WARNING in statuses:
                meta["qa_status"] = QAStatus.WARNING
                if meta.get("status") in {"generated", "ready", ""}:
                    meta["status"] = "qa_warning"
            else:
                meta["qa_status"] = QAStatus.PASSED
            meta["qa_results"] = own
            scene.metadata = meta
            scene.save(update_fields=["metadata"])

    def _scene_payload(self, scene: Scene) -> dict:
        return {
            "scene_key": scene.scene_key,
            "visual": scene.visual,
            "narration": scene.narration,
            "caption": scene.caption,
            "duration": scene.duration,
            "has_image": bool(scene.image),
            "has_video": bool(scene.video_clip),
        }


def _shot_overlap(left: str, right: str) -> float:
    a = set(_norm(left).split())
    b = set(_norm(right).split())
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


RELEASE_BLOCKING_NAMES = {
    "character_identity",
    "scene_narration",
    "audio_silent",
    "audio_stream",
    "audio_duration",
    "assembled_audio",
    "product_visual_consistency",
    "product_component",
    "caption_visual",
    "caption_lines",
    "claims",
    "cta_complete",
    "expired_offer",
}


def release_blocking_issues(checks: list[dict], *, has_preview: bool = False) -> list[dict]:
    """Failures (and unchecked release gates) that must block approval."""
    blocking = []
    seen_names = {str(check.get("name") or "") for check in checks}
    for check in checks:
        name = str(check.get("name") or "")
        if name not in RELEASE_BLOCKING_NAMES:
            continue
        status = check.get("status")
        if status == QAStatus.FAILED:
            blocking.append(check)
            continue
        # SKIPPED / not_checked must never be treated as FAIL.
        if status in {"not_checked", "skipped"}:
            continue
        if (
            name == "caption_visual"
            and status == QAStatus.FAILED
            or (
                name == "caption_visual"
                and status == QAStatus.WARNING
                and "cover" in str(check.get("detail") or "").lower()
                and float(check.get("confidence") or 0) >= 0.85
            )
        ):
            if check not in blocking:
                blocking.append(check)
        if name == "product_visual_consistency" and status == QAStatus.FAILED:
            if check not in blocking:
                blocking.append(check)
    return blocking
