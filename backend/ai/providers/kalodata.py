from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from ai.exceptions import MissingAPIKeyError, ProviderError

logger = logging.getLogger(__name__)


class KalodataProvider:
    """Authorized Kalodata Open API. Never scrape the dashboard."""

    def category_intelligence(self, *, category: str = "", product_name: str = "") -> dict[str, Any]:
        key = (getattr(settings, "KALODATA_API_KEY", "") or "").strip()
        base = (getattr(settings, "KALODATA_API_BASE", "") or "").rstrip("/")
        if not key or not base:
            raise MissingAPIKeyError(
                "Kalodata is not configured. Add KALODATA_API_KEY to backend/.env."
            )
        try:
            import httpx

            response = httpx.get(
                f"{base}/open/v1/category/intelligence",
                headers={"Authorization": f"Bearer {key}", "X-API-Key": key},
                params={"category": category, "product": product_name},
                timeout=30,
            )
            if response.status_code == 404:
                return self._empty("Kalodata endpoint is not enabled for this account.")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return self._empty("Kalodata returned an unexpected payload.")
            return {
                "available": True,
                "category_scripts": data.get("category_scripts") or data.get("scripts") or [],
                "winning_structures": data.get("winning_structures") or data.get("structures") or [],
                "shot_plans": data.get("shot_plans") or [],
                "customer_objections": data.get("customer_objections") or data.get("objections") or [],
                "content_ideas": data.get("content_ideas") or data.get("ideas") or [],
            }
        except MissingAPIKeyError:
            raise
        except Exception as exc:
            logger.exception("Kalodata request failed")
            raise ProviderError(
                "Commerce intelligence is temporarily unavailable.",
                retryable=True,
            ) from exc

    def _empty(self, note: str) -> dict[str, Any]:
        return {
            "available": False,
            "note": note,
            "category_scripts": [],
            "winning_structures": [],
            "shot_plans": [],
            "customer_objections": [],
            "content_ideas": [],
        }
