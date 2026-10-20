from __future__ import annotations

from ai.exceptions import MissingAPIKeyError, ProviderError
from ai.providers.kalodata import KalodataProvider


class KalodataService:
    def insights(self, *, category: str = "", product_name: str = "") -> dict:
        try:
            return KalodataProvider().category_intelligence(
                category=category,
                product_name=product_name,
            )
        except (MissingAPIKeyError, ProviderError):
            return {
                "available": False,
                "category_scripts": [],
                "winning_structures": [],
                "shot_plans": [],
                "customer_objections": [],
                "content_ideas": [],
            }
