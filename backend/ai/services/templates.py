from __future__ import annotations

TEMPLATES = [
    {
        "id": "smart_selling",
        "title": "SMART Selling",
        "style": "smart_selling",
        "strategy": "Specific problem → measurable benefit → action/demo → relevant proof → time-based CTA.",
        "objectives": ["buy", "enquire"],
        "platforms": ["tiktok", "instagram", "facebook", ""],
        "why": "Best for professional and educational selling.",
    },
    {
        "id": "product_demo",
        "title": "Product Demonstration",
        "style": "product_demo",
        "strategy": "Show the product, main features, how it works, then the final result.",
        "objectives": ["buy", "enquire", "visit"],
        "platforms": ["tiktok", "instagram", "facebook", ""],
        "why": "Shoppers see exactly how it works before they decide.",
    },
    {
        "id": "ugc_creator",
        "title": "UGC Creator",
        "style": "ugc_creator",
        "strategy": "Natural smartphone-style content with casual human delivery for short-form social.",
        "objectives": ["buy", "follow", "enquire"],
        "platforms": ["tiktok", "instagram", ""],
        "why": "Feels native on TikTok, Xiaohongshu, and short-form feeds.",
    },
    {
        "id": "before_after",
        "title": "Before and After",
        "style": "before_after",
        "strategy": "Before → product/use → after. Make the improvement visually obvious without inventing results.",
        "objectives": ["buy", "enquire"],
        "platforms": ["tiktok", "instagram", ""],
        "why": "Makes the benefit visible in seconds.",
    },
    {
        "id": "unboxing",
        "title": "Unboxing",
        "style": "unboxing",
        "strategy": "Package → opening → product close-ups → first impression → initial test.",
        "objectives": ["buy", "follow"],
        "platforms": ["tiktok", "instagram", ""],
        "why": "Packaging and first impression do the selling.",
    },
    {
        "id": "listicle",
        "title": "Listicle",
        "style": "listicle",
        "strategy": "Numbered structure such as 3 reasons to buy, 5 common mistakes, or 4 benefits.",
        "objectives": ["buy", "enquire", "follow"],
        "platforms": ["tiktok", "instagram", "facebook", ""],
        "why": "Clear educational structure that is easy to follow.",
    },
    {
        "id": "live_selling",
        "title": "Live-Selling Host",
        "style": "live_selling",
        "strategy": "Attention → product → benefits → offer → urgency → purchase CTA with energetic hosting.",
        "objectives": ["buy", "visit"],
        "platforms": ["tiktok", "facebook", "instagram", ""],
        "why": "High-energy conversion for offers and urgency.",
    },
    {
        "id": "faceless_explainer",
        "title": "Faceless Explainer",
        "style": "faceless_explainer",
        "strategy": "No presenter. Use product footage, graphics, captions, and voice-over.",
        "objectives": ["buy", "enquire", "visit"],
        "platforms": ["tiktok", "instagram", "facebook", ""],
        "why": "Works when no on-camera presenter is required.",
        "requires_character": False,
    },
]


def suggest_templates(brief: dict, category: str = "", platform: str = "", count: int = 3) -> list[dict]:
    objective = str(brief.get("objective") or "buy")
    has_offer = bool(str(brief.get("offer_price") or brief.get("offer_text") or brief.get("offer") or "").strip())
    category_l = (category or "").lower()
    platform = (platform or brief.get("platform") or "").strip().lower()
    scored = []
    for item in TEMPLATES:
        score = 0
        if objective in (item.get("objectives") or []):
            score += 4
        if platform in (item.get("platforms") or []):
            score += 2
        if item["id"] == "live_selling" and has_offer:
            score += 5
        if item["id"] == "live_selling" and not has_offer:
            score -= 2
        if item["id"] == "product_demo" and any(
            word in category_l for word in ("home", "kitchen", "gadget", "tool", "electronic")
        ):
            score += 2
        if item["id"] == "ugc_creator" and platform in {"tiktok", ""}:
            score += 1
        if item["id"] == "smart_selling":
            score += 1
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [item for _, item in scored] or list(TEMPLATES)
    try:
        wanted = int(count or 3)
    except (TypeError, ValueError):
        wanted = 3
    wanted = max(1, min(wanted, 10))
    picked: list[dict] = []
    seen: set[str] = set()
    index = 0
    while len(picked) < wanted and ranked:
        base = ranked[index % len(ranked)]
        round_no = index // len(ranked)
        index += 1
        item = dict(base)
        if round_no:
            item = {
                **base,
                "id": f"{base['id']}-{round_no + 1}",
                "title": f"{base['title']} {round_no + 1}",
            }
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        picked.append(item)
    return picked[:wanted]


def template_by_id(template_id: str) -> dict | None:
    return next((item for item in TEMPLATES if item["id"] == template_id), None)


def template_requires_character(template_id: str) -> bool:
    item = template_by_id(template_id)
    if not item:
        return True
    return item.get("requires_character", True) is not False
