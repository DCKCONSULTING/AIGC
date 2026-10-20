from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any

from brands.models import Product


def _as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return _as_list(parsed)
        return [part.strip() for part in stripped.split(",") if part.strip()]
    if isinstance(value, list):
        if len(value) == 1 and isinstance(value[0], str) and value[0].strip().startswith("["):
            return _as_list(value[0])
        items = []
        for item in value:
            if isinstance(item, (list, dict)):
                items.extend(_as_list(item) if not isinstance(item, dict) else [str(item)])
            elif str(item).strip():
                items.append(str(item).strip())
        return items
    text = str(value).strip()
    return [text] if text else []


def _url(field) -> str:
    try:
        return field.url if field else ""
    except ValueError:
        return ""


def snapshot_price_amount(snapshot: dict) -> float:
    raw = str(snapshot.get("price") or "").replace("RM", "").replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def generation_blocker(snapshot: dict) -> str:
    if not (snapshot.get("product_images") or []):
        return "Add a product photo before generating."
    return ""


def product_snapshot(product: Product, overrides: dict | None = None) -> dict[str, Any]:
    extras = overrides or {}

    def pick(name: str, fallback):
        if name in extras and extras[name] not in (None, ""):
            return extras[name]
        return fallback

    offer_expiry = pick("offer_expiry", product.offer_expiry)
    if isinstance(offer_expiry, (date, datetime)):
        offer_expiry = offer_expiry.isoformat()

    price = pick("price", product.price)
    if isinstance(price, Decimal):
        price = f"{price:.2f}"

    return {
        "product_id": product.id,
        "name": pick("name", product.name),
        "description": pick("description", product.description),
        "variants": _as_list(pick("variants", product.variants)),
        "dimensions": pick("dimensions", product.dimensions or ""),
        "materials": pick("materials", product.materials or ""),
        "price": str(price),
        "offer": pick("offer", product.offer or ""),
        "offer_expiry": offer_expiry or "",
        "approved_claims": _as_list(pick("approved_claims", product.approved_claims)),
        "prohibited_claims": _as_list(pick("prohibited_claims", product.prohibited_claims)),
        "certifications": _as_list(pick("certifications", product.certifications)),
        "supported_benefits": _as_list(
            pick("supported_benefits", pick("approved_claims", product.approved_claims))
        ),
        "evidence": _as_list(pick("evidence", getattr(product, "evidence", []))),
        "shipping_conditions": pick(
            "shipping_conditions", getattr(product, "shipping_conditions", "") or ""
        ),
        "known_mistakes": _as_list(pick("known_mistakes", getattr(product, "known_mistakes", []))),
        "prohibited_representations": _as_list(
            pick(
                "prohibited_representations",
                getattr(product, "prohibited_representations", []),
            )
        ),
        "product_link": pick("product_url", product.product_url or ""),
        "product_images": [
            {"id": image.id, "url": _url(image.image), "path": getattr(image.image, "path", "")}
            for image in product.images.all()
        ],
        "demonstration_videos": [
            {"id": video.id, "url": _url(video.video), "path": getattr(video.video, "path", "")}
            for video in product.demo_videos.all()
        ],
        "version": 1,
        "captured_at": datetime.utcnow().isoformat() + "Z",
    }


def snapshot_paths(snapshot: dict) -> list[str]:
    paths = []
    for item in snapshot.get("product_images") or []:
        if item.get("path"):
            paths.append(item["path"])
    return paths
