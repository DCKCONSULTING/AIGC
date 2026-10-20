from __future__ import annotations

from datetime import date, datetime


def _as_list(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def missing_product_fields(snapshot: dict) -> list[str]:
    missing = []
    if not str(snapshot.get("name") or "").strip():
        missing.append("name")
    if not str(snapshot.get("description") or "").strip():
        missing.append("description")
    if not str(snapshot.get("price") or "").strip():
        missing.append("price")
    if not _as_list(snapshot.get("variants")):
        missing.append("variants")
    if not str(snapshot.get("dimensions") or "").strip():
        missing.append("dimensions")
    if not str(snapshot.get("materials") or "").strip():
        missing.append("materials")
    if not snapshot.get("product_images"):
        missing.append("product images")
    if not _as_list(snapshot.get("approved_claims")):
        missing.append("approved claims")
    return missing


def offer_is_expired(snapshot: dict, today: date | None = None) -> bool:
    raw = snapshot.get("offer_expiry") or ""
    if not raw:
        return False
    if isinstance(raw, datetime):
        expiry = raw.date()
    elif isinstance(raw, date):
        expiry = raw
    else:
        try:
            expiry = date.fromisoformat(str(raw)[:10])
        except ValueError:
            return False
    return expiry < (today or date.today())


def unsupported_claims(text: str, snapshot: dict) -> list[str]:
    blob = (text or "").lower()
    flagged = []
    for claim in _as_list(snapshot.get("prohibited_claims")):
        if claim.lower() in blob:
            flagged.append(claim)
    return flagged
