from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from ai.exceptions import MissingAPIKeyError, ProviderError
from ai.providers.google.speech import SpeechProvider
from ai.providers.intelligence import IntelligenceClient
from brands.models import Product

logger = logging.getLogger(__name__)

from .snapshots import product_snapshot, snapshot_paths
from .validation import missing_product_fields

PRODUCT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "summary": {"type": "string"},
        "variants": {"type": "array", "items": {"type": "string"}},
        "dimensions": {"type": "string"},
        "materials": {"type": "string"},
        "price": {"type": "string"},
        "offer": {"type": "string"},
        "offer_expiry": {"type": "string"},
        "approved_claims": {"type": "array", "items": {"type": "string"}},
        "prohibited_claims": {"type": "array", "items": {"type": "string"}},
        "certifications": {"type": "array", "items": {"type": "string"}},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "facts": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "content_ideas": {"type": "array", "items": {"type": "string"}},
        "customer_objections": {"type": "array", "items": {"type": "string"}},
        "merchant_instructions": {"type": "string"},
    },
    "required": ["name", "summary", "facts"],
}


class ProductAnalysisService:
    def __init__(
        self,
        gemini: IntelligenceClient | None = None,
        speech: SpeechProvider | None = None,
    ):
        self.gemini = gemini or IntelligenceClient()
        self.speech = speech or SpeechProvider()

    def analyze(
        self,
        product: Product,
        *,
        overrides: dict | None = None,
        instructions: str = "",
        voice_bytes: bytes | None = None,
        language: str = "conversational_bm",
    ) -> dict:
        snapshot = product_snapshot(product, overrides)
        spoken = ""
        if voice_bytes:
            spoken = self.speech.transcribe(voice_bytes, language=language)
        merchant_notes = "\n".join(part for part in [instructions, spoken] if part)
        image_files = [
            path
            for path in snapshot_paths(snapshot)
            if Path(settings.MEDIA_ROOT, Path(path).name).exists() or Path(path).exists()
        ]
        existing = [
            str(Path(settings.MEDIA_ROOT) / path) if not Path(path).is_absolute() else path
            for path in snapshot_paths(snapshot)
        ]
        existing = [path for path in existing if Path(path).exists()]
        prompt = (
            "Extract only facts that are supported by the product record and images. "
            "Do not invent claims, prices, certifications, or offers. "
            "Flag any claim that is not clearly supported. "
            "List missing information a merchant should confirm. "
            "Suggest original content ideas and likely customer objections "
            "using only approved facts.\n\n"
            f"Product record:\n{snapshot}\n\n"
            f"Merchant notes:\n{merchant_notes or 'None'}"
        )
        try:
            analysis = self.gemini.generate_json(
                prompt,
                schema=PRODUCT_SCHEMA,
                files=existing[:6] or image_files[:6],
                system=(
                    "You extract product facts for advertising. "
                    "Return structured JSON only. Never invent product information."
                ),
                operation="product_analyze",
                owner=getattr(product.brand, "owner", None),
            )
        except (ProviderError, MissingAPIKeyError):
            logger.warning("Product analysis fell back to the product record for %s", getattr(product, "pk", None))
            analysis = self._from_snapshot(snapshot, merchant_notes)
        analysis["merchant_instructions"] = merchant_notes
        analysis["snapshot"] = snapshot
        analysis["spoken_instructions"] = spoken
        detected = missing_product_fields(snapshot)
        existing_missing = analysis.get("missing_information") or []
        analysis["missing_information"] = list(dict.fromkeys([*existing_missing, *detected]))
        return analysis

    def _from_snapshot(self, snapshot: dict, merchant_notes: str) -> dict:
        name = str(snapshot.get("name") or "").strip()
        facts = [
            item
            for item in [
                name,
                snapshot.get("price"),
                snapshot.get("offer"),
                snapshot.get("materials"),
                snapshot.get("dimensions"),
                snapshot.get("description"),
            ]
            if item
        ]
        return {
            "name": name,
            "summary": str(snapshot.get("description") or name).strip(),
            "variants": snapshot.get("variants") or [],
            "dimensions": snapshot.get("dimensions") or "",
            "materials": snapshot.get("materials") or "",
            "price": snapshot.get("price") or "",
            "offer": snapshot.get("offer") or "",
            "offer_expiry": snapshot.get("offer_expiry") or "",
            "approved_claims": snapshot.get("approved_claims") or [],
            "prohibited_claims": snapshot.get("prohibited_claims") or [],
            "certifications": snapshot.get("certifications") or [],
            "unsupported_claims": [],
            "facts": facts,
            "missing_information": missing_product_fields(snapshot),
            "content_ideas": [],
            "customer_objections": [],
            "merchant_instructions": merchant_notes,
        }
