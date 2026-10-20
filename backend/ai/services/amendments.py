from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from ai.models import VideoProject
from ai.services.director import DirectorService, is_video_fallback, record_event

logger = logging.getLogger(__name__)

CHECK_RECIPES = {
    "product": {
        "type": "product_consistency",
        "severity": "high",
        "amendment": "Keep the approved product appearance identical in the affected scenes.",
        "benefit": "Viewers see the real product, not a redesigned version.",
    },
    "product_consistency": {
        "type": "product_consistency",
        "severity": "high",
        "amendment": "Regenerate the affected scene with the product lock on.",
        "benefit": "The product stays visually consistent.",
    },
    "product_representation": {
        "type": "product_consistency",
        "severity": "medium",
        "amendment": "Show the approved product clearly in every scene that is missing it.",
        "benefit": "Shoppers can recognise what they are buying.",
    },
    "price": {
        "type": "offer",
        "severity": "high",
        "amendment": "Use the approved price exactly in the caption and voice-over.",
        "benefit": "The offer stays legally and commercially accurate.",
    },
    "expired_offer": {
        "type": "offer",
        "severity": "high",
        "amendment": "Remove or replace the expired offer with the current approved offer only.",
        "benefit": "Prevents publishing an invalid promotion.",
    },
    "claims": {
        "type": "script",
        "severity": "high",
        "amendment": "Remove unsupported claims and keep only approved product facts.",
        "benefit": "Protects the brand from invented promises.",
    },
    "captions": {
        "type": "captions",
        "severity": "medium",
        "amendment": "Make the on-screen caption the exact spoken sentence, word for word. Do not shorten or paraphrase.",
        "benefit": "Viewers read the same sentence they hear.",
    },
    "visible_captions": {
        "type": "captions",
        "severity": "medium",
        "amendment": "Add the exact spoken voice-over as the on-screen caption.",
        "benefit": "The video works with the sound off and still matches the audio.",
    },
    "narration": {
        "type": "audio",
        "severity": "medium",
        "amendment": "Restore the approved voice-over for scenes with missing or unclear audio.",
        "benefit": "The story stays intelligible.",
    },
    "pronunciation": {
        "type": "audio",
        "severity": "low",
        "amendment": "Keep the approved product name and price pronunciation.",
        "benefit": "The brand name stays clear.",
    },
    "scene_completeness": {
        "type": "timeline",
        "severity": "high",
        "amendment": "Complete missing scene visuals, voice-over, or captions before approval.",
        "benefit": "The storyboard stays complete.",
    },
    "video_generation": {
        "type": "timeline",
        "severity": "high",
        "amendment": "Regenerate the fallback scene with the current locked product and script.",
        "benefit": "Replaces still-image fallbacks with real motion.",
    },
    "presenter_consistency": {
        "type": "presenter_consistency",
        "severity": "high",
        "amendment": "Keep the same presenter in every scene. Lock the presenter and regenerate the changed scene.",
        "benefit": "The face and outfit stay consistent.",
    },
    "product_visual_consistency": {
        "type": "product_consistency",
        "severity": "high",
        "amendment": (
            "Regenerate this scene using the approved product reference. "
            "Keep the current script, presenter, location and caption locked."
        ),
        "benefit": "The generated product stays aligned with the approved reference.",
    },
    "presenter_visual_consistency": {
        "type": "presenter_consistency",
        "severity": "high",
        "amendment": "Regenerate this scene with the presenter lock on. Keep the same person and outfit.",
        "benefit": "The presenter stays consistent with the approved identity.",
    },
    "presenter_continuity": {
        "type": "presenter_consistency",
        "severity": "medium",
        "amendment": "Regenerate this scene so the presenter matches earlier scenes.",
        "benefit": "The presenter does not change mid-video.",
    },
    "scene_visual_match": {
        "type": "timeline",
        "severity": "medium",
        "amendment": "Regenerate this scene so it matches the planned location, shot, and action.",
        "benefit": "The scene matches the approved storyboard.",
    },
    "caption_visual": {
        "type": "captions",
        "severity": "medium",
        "amendment": "Keep the approved caption and regenerate this scene so the text stays readable and inside safe margins.",
        "benefit": "On-screen text stays readable and does not cover the product.",
    },
    "voiceover_mismatch": {
        "type": "audio",
        "severity": "medium",
        "amendment": "Keep the approved script locked and regenerate this scene only.",
        "benefit": "Spoken audio matches the approved narration.",
    },
    "audio_missing": {
        "type": "audio",
        "severity": "high",
        "amendment": "Regenerate this scene because generated audio is missing or effectively silent.",
        "benefit": "The scene has audible speech.",
        "needs_regeneration": True,
    },
    "audio_silent": {
        "type": "audio",
        "severity": "high",
        "amendment": "Regenerate this scene because generated audio is missing or effectively silent.",
        "benefit": "The scene has audible narration and sound.",
        "needs_regeneration": True,
    },
    "audio_stream": {
        "type": "audio",
        "severity": "high",
        "amendment": "Regenerate this scene because generated audio is missing or effectively silent.",
        "benefit": "The scene has an audible audio track.",
        "needs_regeneration": True,
    },
    "audio_duration": {
        "type": "audio",
        "severity": "high",
        "amendment": "Regenerate this scene so spoken audio covers the full shot.",
        "benefit": "Narration is heard for the whole scene.",
        "needs_regeneration": True,
    },
    "assembled_audio": {
        "type": "audio",
        "severity": "high",
        "amendment": "Regenerate the silent scene so the final video has audible audio.",
        "benefit": "The final video has audible audio.",
        "needs_regeneration": True,
    },
    "caption_lines": {
        "type": "captions",
        "severity": "high",
        "amendment": "Keep the exact spoken sentence on screen. Wrap it to at most three lines. Do not cut words.",
        "benefit": "On-screen text stays readable and still matches the audio.",
    },
    "cta_complete": {
        "type": "offer",
        "severity": "high",
        "amendment": "Write a commercially complete CTA with the product name, approved price, and a purchase action. Do not invent a website or offer.",
        "benefit": "Viewers know what to buy and what to do next.",
    },
    "scene_variety": {
        "type": "timeline",
        "severity": "medium",
        "amendment": "Replace a repetitive static shot with a meaningful product-use, detail, or lifestyle action.",
        "benefit": "The video does not feel like the same shot repeated.",
        "needs_regeneration": True,
    },
    "malay_copy": {
        "type": "script",
        "severity": "medium",
        "amendment": "Rewrite the caption and voice-over in the selected locale. For Cantonese use 粵語 pronunciation, not Mandarin.",
        "benefit": "Speech and captions match the chosen language.",
    },
    "product_component": {
        "type": "product_consistency",
        "severity": "high",
        "amendment": "Restore missing handle and preserve original product geometry, glaze, and markings from the approved photos.",
        "benefit": "The generated product matches the real product.",
        "needs_regeneration": True,
    },
}


class AmendmentService:
    def recommend(self, project: VideoProject) -> list[dict]:
        checks = list((project.qa_results or {}).get("checks") or [])
        scenes = list(project.scenes.all())
        recommendations = []
        seen = set()
        cursor = 0.0
        scene_windows = []
        for scene in scenes:
            start = float((scene.metadata or {}).get("start_time") or cursor)
            end = float((scene.metadata or {}).get("end_time") or start + float(scene.duration or 5))
            scene_windows.append((scene, start, end))
            cursor = end

        for check in sorted(checks, key=self._priority):
            if check.get("status") not in {"failed", "warning"}:
                continue
            name = str(check.get("name") or "")
            recipe = CHECK_RECIPES.get(name)
            if not recipe or recipe["type"] in seen:
                continue
            seen.add(recipe["type"])
            affected = self._affected_scenes(name, scenes, check)
            start, end = self._window(affected, scene_windows)
            if check.get("start") not in (None, 0) or check.get("timestamp") not in (None, 0):
                start = float(check.get("start") or check.get("timestamp") or start)
            if check.get("end"):
                end = float(check.get("end") or end)
            amendment = check.get("recommended_action") or self._personalize(
                recipe["amendment"], project, check
            )
            needs_regen = bool(recipe.get("needs_regeneration", True))
            if name in {"caption_visual", "caption_lines"} and "cover" not in str(check.get("detail") or "").lower():
                needs_regen = False
            recommendations.append(
                {
                    "id": f"amd-{uuid4().hex[:8]}",
                    "type": recipe["type"],
                    "issue": name,
                    "detected_problem": check.get("detail") or recipe["amendment"],
                    "reason": check.get("reason") or check.get("detail") or recipe["amendment"],
                    "severity": check.get("severity") or recipe["severity"],
                    "start": start,
                    "end": end,
                    "timestamp": start,
                    "affected_scenes": [scene.scene_key for scene in affected] or (
                        [scenes[-1].scene_key] if scenes else []
                    ),
                    "suggested_amendment": amendment,
                    "proposed_correction": amendment,
                    "expected_benefit": recipe["benefit"],
                    "needs_regeneration": needs_regen,
                    "selected": False,
                    "editable_text": amendment,
                    "confidence": check.get("confidence"),
                    "frame_url": check.get("frame_url") or "",
                    "source": check.get("source") or "structural",
                    "scene_id": check.get("scene_id") or (affected[0].scene_key if affected else ""),
                    "stage": check.get("stage") or "",
                }
            )
            if len(recommendations) >= 3:
                break

        if len(recommendations) < 3 and scenes:
            last = scenes[-1]
            brief = project.creative_brief or {}
            offer = brief.get("offer_text") or brief.get("offer_price") or (project.product_snapshot or {}).get("offer")
            cta_missing = not any(
                (scene.caption or "").strip() and (scene.metadata or {}).get("end_time", 0) >= (
                    project.duration_seconds or 0
                ) - 8
                for scene in scenes[-2:]
            )
            if offer and cta_missing and "offer" not in seen:
                recommendations.append(
                    {
                        "id": f"amd-{uuid4().hex[:8]}",
                        "type": "offer",
                        "detected_problem": "The ending does not clearly show the approved offer or CTA.",
                        "severity": "medium",
                        "start": float((last.metadata or {}).get("start_time") or 0),
                        "end": float((last.metadata or {}).get("end_time") or last.duration or 0),
                        "affected_scenes": [last.scene_key],
                        "suggested_amendment": f"Add the approved offer and CTA to the final scene: {offer}.",
                        "expected_benefit": "Viewers know exactly what to do next.",
                        "selected": False,
                        "editable_text": f"Add the approved offer and CTA to the final scene: {offer}.",
                    }
                )

        project.amendment_recommendations = recommendations[:3]
        project.save(update_fields=["amendment_recommendations", "updated_at"])
        logger.info(
            "Generated %s amendment recommendations for project %s",
            len(project.amendment_recommendations),
            project.pk,
        )
        return project.amendment_recommendations

    def apply(self, project: VideoProject, recommendation_ids: list[str], edits: dict | None = None) -> list[str]:
        edits = edits or {}
        director = DirectorService()
        chosen = [
            item
            for item in (project.amendment_recommendations or [])
            if item.get("id") in recommendation_ids
        ]
        if not chosen:
            raise ValueError("Select at least one improvement to apply.")
        from ai.services.correction import CorrectionService
        from ai.services.script import apply_instruction_locale

        combined = "\n".join(
            str(edits.get(item["id"]) or item.get("editable_text") or item.get("suggested_amendment") or "").strip()
            for item in chosen
        ).strip()
        if combined:
            apply_instruction_locale(project, combined)
            CorrectionService()._sync_locale_voice(project)
            project.merchant_instructions = "\n".join(
                part for part in [project.merchant_instructions, combined] if part
            )
            brief = dict(project.creative_brief or {})
            existing = str(brief.get("legacy_instructions") or "").strip()
            if combined not in existing:
                brief["legacy_instructions"] = "\n".join(part for part in [existing, combined] if part)
            brief["language"] = project.language
            project.creative_brief = brief
        affected_keys: list[str] = []
        history = list(project.amendment_history or [])
        for item in chosen:
            text = str(edits.get(item["id"]) or item.get("editable_text") or item.get("suggested_amendment") or "").strip()
            keys = item.get("affected_scenes") or []
            for key in keys:
                scene = project.scenes.filter(scene_key=key).first()
                if not scene:
                    continue
                self._apply_to_scene(scene, item, text)
                affected_keys.append(key)
            history.append(
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "text": text,
                    "affected_scenes": keys,
                    "accepted": True,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            record_event(project, "amendment_accepted", {"id": item.get("id"), "scenes": keys})
        rejected = [
            item
            for item in (project.amendment_recommendations or [])
            if item.get("id") not in recommendation_ids
        ]
        for item in rejected:
            history.append(
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "accepted": False,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            record_event(project, "amendment_rejected", {"id": item.get("id")})
        project.amendment_history = history[-100:]
        project.amendment_recommendations = [
            {**item, "selected": item.get("id") in recommendation_ids}
            for item in (project.amendment_recommendations or [])
        ]
        project.save(update_fields=["amendment_history", "amendment_recommendations", "creative_brief", "merchant_instructions", "language", "updated_at"])
        director._align_captions_to_speech(project)
        director._refresh_script_from_scenes(project)
        return list(dict.fromkeys(affected_keys))

    def _apply_to_scene(self, scene, recommendation: dict, text: str) -> None:
        meta = dict(scene.metadata or {})
        kind = recommendation.get("type")
        visual_source = recommendation.get("source") in {"multimodal", "transcription", "OCR"}
        if kind == "product_consistency":
            meta["product_locked"] = True
        if kind == "presenter_consistency":
            meta["presenter_locked"] = True
        if visual_source:
            if kind == "captions":
                meta["caption_locked"] = True
                meta["caption_placement"] = "top"
            if kind == "audio":
                meta["script_locked"] = True
        else:
            if kind in {"offer", "captions"} and not meta.get("caption_locked"):
                from ai.services.captions import spoken_caption

                scene.caption = spoken_caption(scene.narration, text)
                meta["on_screen_caption"] = scene.caption
            if kind in {"offer", "script", "audio"} and not meta.get("script_locked"):
                from ai.services.script import nativize_spoken_copy

                scene.narration = nativize_spoken_copy(scene.project.language, text)
                meta["voice_over"] = scene.narration
                if kind in {"offer", "script", "audio"} and not meta.get("caption_locked"):
                    from ai.services.captions import spoken_caption

                    scene.caption = spoken_caption(scene.narration, scene.caption)
                    meta["on_screen_caption"] = scene.caption
        needs_regen = recommendation.get("needs_regeneration")
        if needs_regen is None:
            needs_regen = kind not in {"captions"} or recommendation.get("source") not in {"multimodal", "structural"}
        if kind == "captions" and recommendation.get("source") == "multimodal":
            meta["needs_reassemble"] = True
            meta["needs_regeneration"] = False
        elif kind == "audio" or kind == "product_consistency" or needs_regen:
            meta["needs_regeneration"] = True
        else:
            meta["needs_reassemble"] = True
            meta["needs_regeneration"] = bool(needs_regen)
        meta["status"] = "ready"
        meta["approved"] = False
        scene.metadata = meta
        scene.save()

    def _affected_scenes(self, name: str, scenes, check: dict) -> list:
        mentioned = check.get("affected_scenes") or []
        matched = [scene for scene in scenes if scene.scene_key in mentioned]
        if matched:
            return matched
        if name in {"price", "expired_offer", "visible_captions"} and scenes:
            return scenes[-1:]
        if name in {"product", "product_consistency", "product_representation", "product_visual_consistency"}:
            return [
                scene
                for scene in scenes
                if not scene.image and not scene.video_clip or is_video_fallback(scene.metadata)
            ] or scenes[:1]
        if name in {
            "narration",
            "pronunciation",
            "voiceover_mismatch",
            "audio_missing",
            "audio_silent",
            "audio_stream",
            "audio_duration",
            "assembled_audio",
        }:
            return [scene for scene in scenes if not scene.narration] or scenes[:1]
        if name == "video_generation":
            return [scene for scene in scenes if is_video_fallback(scene.metadata)] or scenes[:1]
        return scenes[-1:] if scenes else []

    def _priority(self, check: dict) -> tuple:
        source_rank = 0 if check.get("source") in {"multimodal", "transcription", "OCR"} else 1
        severity = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(
            str(check.get("severity") or ""), 2
        )
        return (source_rank, severity)

    def _window(self, scenes, windows) -> tuple[float, float]:
        keys = {scene.scene_key for scene in scenes}
        hits = [item for item in windows if item[0].scene_key in keys]
        if not hits:
            return 0.0, 0.0
        return hits[0][1], hits[-1][2]

    def _personalize(self, amendment: str, project: VideoProject, check: dict) -> str:
        snapshot = project.product_snapshot or {}
        brief = project.creative_brief or {}
        price = brief.get("offer_price") or brief.get("price") or snapshot.get("price") or ""
        text = amendment
        if price and "{price}" not in text and check.get("name") == "price":
            text = f"{amendment} Approved price: {price}."
        return text
