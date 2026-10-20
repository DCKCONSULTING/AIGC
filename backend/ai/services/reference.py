from __future__ import annotations

from pathlib import Path

from ai.providers.intelligence import IntelligenceClient

REFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "structure": {"type": "array", "items": {"type": "string"}},
        "pacing": {"type": "string"},
        "shot_sequence": {"type": "array", "items": {"type": "string"}},
        "camera_style": {"type": "string"},
        "storytelling_pattern": {"type": "string"},
        "storytelling_structure": {"type": "string"},
        "cta_structure": {"type": "string"},
        "offer_placement": {"type": "string"},
        "notes": {"type": "string"},
        "duration": {"type": "string"},
        "scene_count": {"type": "integer"},
        "scene_durations": {"type": "array", "items": {"type": "number"}},
        "lighting": {"type": "string"},
        "visual_style": {"type": "string"},
        "caption_style": {"type": "string"},
        "language": {"type": "string"},
        "transitions": {"type": "string"},
        "presenter_behavior": {"type": "string"},
        "product_interaction": {"type": "string"},
    },
    "required": [
        "hook",
        "structure",
        "pacing",
        "shot_sequence",
        "camera_style",
        "storytelling_pattern",
        "cta_structure",
    ],
}


class ReferenceAnalysisService:
    def __init__(self, gemini: IntelligenceClient | None = None):
        self.gemini = gemini or IntelligenceClient()

    def analyze(
        self,
        video_path: str | Path | None = None,
        *,
        reference_url: str = "",
        product_snapshot: dict | None = None,
    ) -> dict:
        path = Path(video_path) if video_path else None
        prompt = (
            "Analyse this reference video as creative guidance only. "
            "Extract hook, pacing, shot structure, camera style, camera movement, "
            "lighting, location type, presenter behavior, product interaction, "
            "transition style, caption style, visual composition, language, "
            "scene count, approximate scene durations, storytelling structure, CTA, and offer placement. "
            "Do not copy brand names, product identities, packaging, people, or claims from the reference. "
            "The new video must be original and must use only the selected product and presenter.\n"
        )
        if reference_url:
            prompt += f"\nReference URL (guidance only): {reference_url}\n"
        if product_snapshot:
            prompt += f"\nSelected product facts:\n{product_snapshot}\n"
        files = [path] if path and path.exists() else None
        if not files and not reference_url:
            raise ValueError("Upload a reference video or paste a video link.")
        analysis = self.gemini.generate_json(
            prompt,
            schema=REFERENCE_SCHEMA,
            files=files,
            system=(
                "You analyse short-form reference videos for original advertising. "
                "Return structured JSON only. Never copy the reference product."
            ),
        )
        if not analysis.get("storytelling_structure"):
            analysis["storytelling_structure"] = analysis.get("storytelling_pattern") or ""
        return analysis
