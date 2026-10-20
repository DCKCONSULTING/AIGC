from __future__ import annotations

import logging
import re

from ai.exceptions import MissingAPIKeyError, ProviderError
from ai.providers.intelligence import IntelligenceClient

logger = logging.getLogger(__name__)

LANGUAGE_GUIDE = {
    "conversational_bm": (
        "Language: ms-MY (Malaysian Malay). Speak natural Malaysian Malay out loud. "
        "Natural Malaysian Malay pronunciation. Write captions in Bahasa Malaysia."
    ),
    "formal_bm": (
        "Language: ms-MY (Malaysian Malay). Speak formal, polite Malaysian Malay. "
        "Natural Malaysian Malay pronunciation. Write captions in Bahasa Malaysia."
    ),
    "bm_english": (
        "Language: ms-MY. Speak the mix of Bahasa Malaysia and simple English Malaysian shoppers already use. "
        "Write captions the same way."
    ),
    "english": (
        "Language: en-US (American English). Speak clear natural American English out loud. "
        "Natural American English pronunciation. Write captions in English."
    ),
    "chinese": (
        "Language: zh-CN / cmn-CN. Speak Standard Mandarin Chinese (Putonghua) out loud, with correct Mandarin tones. "
        "Write voice-over and captions in Mandarin Chinese. "
        "Do not speak Cantonese or Hokkien."
    ),
    "cantonese": (
        "Language: yue-HK. Speak Cantonese (粵語 / 广东话) out loud — Hong Kong or Malaysian Cantonese. "
        "This is NOT Mandarin. Use Cantonese pronunciation, tones, and spoken grammar "
        "(particles such as 嘅、係、唔、喺、咗、喇、囉). "
        "Write the voice-over as spoken Cantonese. If the line is in Chinese characters, "
        "read every syllable in Cantonese, never Putonghua. "
        "Write captions in Chinese characters that match the spoken Cantonese line."
    ),
    "hokkien": (
        "Language: nan / Hokkien. Speak Hokkien (福建话 / 闽南语) out loud — Malaysian or Taiwanese Hokkien. "
        "This is NOT Mandarin and NOT Cantonese. Use Hokkien pronunciation and spoken grammar. "
        "Write the voice-over as spoken Hokkien. If the line is in Chinese characters, "
        "read every syllable in Hokkien, never Putonghua. "
        "Write captions in Chinese characters that match the spoken Hokkien line."
    ),
    "mandarin_my": (
        "Language: zh-MY (Malaysian Mandarin). Speak Malaysian Mandarin that sounds natural for local shoppers. "
        "Natural Malaysian Mandarin pronunciation, not Cantonese or Hokkien. "
        "Write captions in Chinese characters."
    ),
    "tamil_my": (
        "Language: ta-MY (Malaysian Tamil). Speak Malaysian Tamil that sounds natural for local shoppers. "
        "Write captions in Tamil."
    ),
}

SPEECH_LOCK = {
    "chinese": (
        "SPEECH LOCK — MANDARIN ONLY. The presenter must speak Standard Mandarin (Putonghua) out loud. "
        "Do not speak Cantonese, Hokkien, Malay, or English except for an unchanged brand name. "
        "必须用普通话朗读，不要用粤语或闽南语。Reading the line as Cantonese or Hokkien is a failed take."
    ),
    "cantonese": (
        "SPEECH LOCK — CANTONESE ONLY. The presenter must speak Cantonese (粵語) in the generated audio. "
        "Forbidden: Mandarin / Putonghua / 普通话 / 國語, Hokkien, Malay, or English except an unchanged brand name. "
        "必須用粵語口語講出聲，唔好用普通話讀漢字。 "
        "Sound like a native Cantonese presenter. Reading Chinese characters as Mandarin is a failed take."
    ),
    "hokkien": (
        "SPEECH LOCK — HOKKIEN ONLY. The presenter must speak Hokkien (福建话 / 闽南语) in the generated audio. "
        "Forbidden: Mandarin / Putonghua / 普通话, Cantonese / 粵語, Malay, or English except an unchanged brand name. "
        "愛用福建話（閩南語）講，莫用普通話，莫用廣東話。 "
        "Sound like a native Hokkien presenter. Reading Chinese characters as Mandarin is a failed take."
    ),
    "mandarin_my": (
        "SPEECH LOCK — MALAYSIAN MANDARIN ONLY. Speak Malaysian Mandarin, not Cantonese or Hokkien. "
        "必须用马来西亚华语／普通话朗读，不要用粤语或福建话。"
    ),
}

SPOKEN_COPY = {
    "chinese": (
        "Write every voice-over line in spoken Mandarin Chinese (普通话). Do not write Cantonese or Hokkien."
    ),
    "cantonese": (
        "Write every voice-over line in spoken Cantonese (粵語), not Mandarin. "
        "Use Cantonese wording and particles (嘅、係、唔、喺、咗、喇、囉). "
        "A Mandarin sentence that is only labelled Cantonese is wrong."
    ),
    "hokkien": (
        "Write every voice-over line in spoken Hokkien (福建话 / 闽南语), not Mandarin or Cantonese. "
        "Use Hokkien wording and particles (毋、佇、矣、無、嘛、喔). "
        "A Mandarin sentence that is only labelled Hokkien is wrong."
    ),
    "mandarin_my": "Write every voice-over line in Malaysian Mandarin, not Cantonese or Hokkien.",
}

CHINESE_VARIETIES = frozenset({"chinese", "cantonese", "hokkien", "mandarin_my"})


def speech_lock(language: str) -> str:
    return SPEECH_LOCK.get(language or "", "")


def spoken_copy_instruction(language: str) -> str:
    return SPOKEN_COPY.get(language or "", "Write natural spoken commercial copy for the selected language, not a literal translation.")


PRONUNCIATION_GUIDE = {
    "cantonese": (
        "PRONUNCIATION — CANTONESE / Jyutping, never Mandarin Pinyin. "
        "係 hai, 唔 m, 嘅 ge, 喺 hai, 咗 zo, 喇 la, 冇 mou, 佢 keoi, 哋 dei, "
        "呢 ni, 個 go, 咩 me, 點 dim, 而家 yi ga, 唔好 m hou. "
        "Never pronounce 的 as de, 是 as shi, 不 as bu, or 在 as zai. "
        "If the written line still has Mandarin words, speak the Cantonese equivalent out loud."
    ),
    "hokkien": (
        "PRONUNCIATION — HOKKIEN / 闽南语, never Mandarin Pinyin. "
        "Do not pronounce 的 as de, 是 as shi, or 不 as bu. Speak Hokkien tones."
    ),
    "chinese": (
        "PRONUNCIATION — Standard Mandarin / Pinyin. Use Putonghua tones, not Cantonese."
    ),
    "mandarin_my": (
        "PRONUNCIATION — Malaysian Mandarin. Use Mandarin tones, not Cantonese or Hokkien."
    ),
}

CANTONESE_SWAPS = (
    ("不是", "唔係"),
    ("沒有", "冇"),
    ("没有", "冇"),
    ("不要", "唔好"),
    ("不會", "唔會"),
    ("不会", "唔會"),
    ("我們", "我哋"),
    ("我们", "我哋"),
    ("他們", "佢哋"),
    ("他们", "佢哋"),
    ("你們", "你哋"),
    ("你们", "你哋"),
    ("這個", "呢個"),
    ("这个", "呢個"),
    ("這裡", "呢度"),
    ("这里", "呢度"),
    ("什麼", "咩"),
    ("什么", "咩"),
    ("怎麼", "點樣"),
    ("怎么", "點樣"),
    ("現在", "而家"),
    ("现在", "而家"),
    ("還是", "定係"),
    ("还是", "定係"),
    ("但是", "但係"),
    ("的", "嘅"),
    ("在", "喺"),
    ("了", "咗"),
    ("是", "係"),
    ("不", "唔"),
)

_CANTONESE_MARKERS = re.compile(r"[嘅係唔喺咗喇囉冇哋佢喎咩]")

_LOCALE_NEEDLES = (
    ("cantonese", ("cantonese", "yue-hk", "yue_hk", "粵語", "粤语", "广东话", "廣東話", "廣東語", "广东语")),
    ("hokkien", ("hokkien", "hoklo", "nan-tw", "福建話", "福建话", "閩南", "闽南", "福建語")),
    ("chinese", ("putonghua", "mandarin", "普通话", "普通話", "國語", "国语", "华语", "華語", "zh-cn", "cmn-cn")),
    ("english", ("english", "en-us", "american english")),
    ("conversational_bm", ("bahasa malaysia", "conversational bm", "bm santai")),
)


def spoken_audio_block(language: str, voice: str = "") -> str:
    """Front-of-prompt audio lock. Omni has no language field, so speech is prompt-only."""
    language = language or ""
    guide = LANGUAGE_GUIDE.get(language, "")
    code = LANGUAGE_CODES.get(language, "")
    lock = speech_lock(language)
    spoken = nativize_spoken_copy(language, voice)
    variety_rule = (
        "Do not switch to another Chinese variety. Wrong spoken language is a failed take."
        if language in CHINESE_VARIETIES
        else "Speak only the locked language out loud. Do not switch language mid-sentence."
    )
    parts = [
        "SPOKEN AUDIO — LOCKED LANGUAGE (do this first)",
        f"Audio locale: {code}" if code else "",
        f"Spoken language id: {language}" if language else "",
        guide,
        lock,
        PRONUNCIATION_GUIDE.get(language, ""),
        (
            f"Voice-over to speak EXACTLY in that locked language, native pronunciation, word for word: {spoken}"
            if spoken
            else ""
        ),
        variety_rule,
        "On-screen captions are burned later from this exact spoken sentence. Speak it in full.",
    ]
    return "\n".join(part for part in parts if part)


def locale_from_instruction(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    blob = raw.lower()
    for language, needles in _LOCALE_NEEDLES:
        for needle in needles:
            if needle.lower() in blob or needle in raw:
                return language
    if "中文" in raw or re.search(r"\bchinese\b", blob):
        return "chinese"
    return ""


def apply_instruction_locale(project, text: str) -> str:
    """If the merchant names a spoken locale, lock the project to it before regeneration."""
    language = locale_from_instruction(text)
    if not language:
        return getattr(project, "language", "") or ""
    if language != (project.language or ""):
        project.language = language
        brief = dict(project.creative_brief or {})
        brief["language"] = language
        project.creative_brief = brief
    return language


def nativize_spoken_copy(language: str, text: str) -> str:
    """Light Cantonese particle swap so Mandarin-looking VO is spoken as Cantonese."""
    spoken = str(text or "").strip()
    if not spoken or language != "cantonese":
        return spoken
    if _CANTONESE_MARKERS.search(spoken):
        return spoken
    converted = spoken
    for source, dest in CANTONESE_SWAPS:
        converted = converted.replace(source, dest)
    return converted

LANGUAGE_CODES = {
    "conversational_bm": "ms-MY",
    "formal_bm": "ms-MY",
    "bm_english": "ms-MY",
    "english": "en-US",
    "chinese": "zh-CN",
    "cantonese": "yue-HK",
    "hokkien": "nan-TW",
    "mandarin_my": "zh-MY",
    "tamil_my": "ta-MY",
}

STYLE_GUIDE = {
    "warm": "Warm, helpful, and close.",
    "bold": "Energetic, confident, and punchy.",
    "calm": "Calm, clear, and trustworthy.",
    "luxury": "Refined, premium, and unhurried.",
}

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "audience": {"type": "string"},
        "hook": {"type": "string"},
        "promise": {"type": "string"},
        "proof_points": {"type": "array", "items": {"type": "string"}},
        "cta": {"type": "string"},
        "tone": {"type": "string"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "content_ideas": {"type": "array", "items": {"type": "string"}},
        "customer_objections": {"type": "array", "items": {"type": "string"}},
        "directions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "concept": {"type": "string"},
                    "script": {"type": "string"},
                    "shot_plan": {"type": "string"},
                },
            },
        },
    },
    "required": ["title", "hook", "promise", "cta", "tone"],
}

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "duration_seconds": {"type": "integer"},
        "language": {"type": "string"},
        "style": {"type": "string"},
        "hook": {"type": "string"},
        "title": {"type": "string"},
        "full_script": {"type": "string"},
        "cta": {"type": "string"},
        "claims": {"type": "array", "items": {"type": "string"}},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene": {"type": "integer"},
                    "scene_key": {"type": "string"},
                    "order": {"type": "integer"},
                    "title": {"type": "string"},
                    "visual": {"type": "string"},
                    "narration": {"type": "string"},
                    "caption": {"type": "string"},
                    "duration": {"type": "number"},
                    "product_facts": {"type": "array", "items": {"type": "string"}},
                    "cta": {"type": "boolean"},
                },
                "required": [
                    "visual",
                    "narration",
                    "caption",
                    "duration",
                ],
            },
        },
    },
    "required": ["scenes"],
}

SHOT_SCHEMA = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene_key": {"type": "string"},
                    "camera": {"type": "string"},
                    "image_prompt": {"type": "string"},
                    "video_prompt": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                },
                "required": ["scene_key", "image_prompt", "video_prompt"],
            },
        }
    },
    "required": ["shots"],
}


class ScriptService:
    def __init__(self, gemini: IntelligenceClient | None = None):
        self.gemini = gemini or IntelligenceClient()

    def build_brief(self, project) -> dict:
        prompt = self._context(project) + (
            "\nCreate a creative brief for a 9:16 product video between 30 and 60 seconds. "
            "Use only approved product facts. Flag unsupported claims. "
            "Include content ideas, customer objections, and three creative directions "
            "(demonstrate how it works, answer a common question, explain a verified offer). "
            "Each direction needs hook, concept, script, and shot plan. "
            "Write Malaysian copy naturally. Do not translate English word-for-word."
        )
        try:
            return self.gemini.generate_json(
                prompt,
                schema=BRIEF_SCHEMA,
                system="You write advertising briefs. Never invent product facts.",
                operation="brief",
                project=project,
            )
        except (ProviderError, MissingAPIKeyError):
            logger.warning("Brief generation fell back to product facts for project %s", getattr(project, "pk", None))
            return self._fallback_brief(project)

    def generate_script(self, project) -> dict:
        duration = self._duration(project)
        prompt = self._context(project) + (
            f"\nWrite an original {duration}-second 9:16 video script with independently "
            "identifiable scenes. Each scene needs visual, narration, caption, and duration. "
            "Scene keys must look like scene-1. Use only approved product information. "
            "Flag unsupported claims. Do not copy the reference video."
        )
        try:
            script = self.gemini.generate_json(
                prompt,
                schema=SCRIPT_SCHEMA,
                system="You write original product video scripts. Never invent product facts.",
                operation="script",
                project=project,
            )
        except (ProviderError, MissingAPIKeyError):
            logger.warning("Script generation fell back to product facts for project %s", getattr(project, "pk", None))
            script = self._fallback_script(project, duration)
        return self._normalize_script(script, project, duration)

    def _normalize_script(self, script: dict, project, duration: int) -> dict:
        scenes = []
        for index, scene in enumerate(script.get("scenes") or [], start=1):
            number = int(scene.get("scene") or scene.get("order") or index)
            scenes.append(
                {
                    "scene": number,
                    "scene_key": scene.get("scene_key") or f"scene-{number}",
                    "order": scene.get("order") or number,
                    "title": scene.get("title") or f"Scene {number}",
                    "visual": scene.get("visual") or "",
                    "narration": scene.get("narration") or "",
                    "caption": scene.get("caption") or "",
                    "duration": float(scene.get("duration") or 5),
                    "product_facts": scene.get("product_facts") or [],
                    "cta": bool(scene.get("cta")),
                }
            )
        return {
            "duration_seconds": int(script.get("duration_seconds") or duration),
            "language": script.get("language") or LANGUAGE_CODES.get(project.language, "ms-MY"),
            "style": script.get("style") or project.speaking_style,
            "hook": script.get("hook") or (project.creative_brief or {}).get("hook") or "",
            "title": script.get("title") or "",
            "full_script": script.get("full_script") or " ".join(item["narration"] for item in scenes),
            "scenes": scenes,
            "cta": script.get("cta") or (project.creative_brief or {}).get("cta") or "",
            "claims": script.get("claims") or [],
            "unsupported_claims": script.get("unsupported_claims") or [],
        }

    def plan_shots(self, project) -> dict:
        prompt = self._context(project) + (
            "\nCreate a shot plan for each scene. Image prompts must keep the real product "
            "unchanged and only describe scene, lighting, and background."
        )
        try:
            return self.gemini.generate_json(
                prompt,
                schema=SHOT_SCHEMA,
                system="You plan original product shots. Preserve the real product.",
                operation="shot_plan",
                project=project,
            )
        except (ProviderError, MissingAPIKeyError):
            logger.warning("Shot plan fell back to scene visuals for project %s", getattr(project, "pk", None))
            return self._fallback_shots(project)

    def _duration(self, project) -> int:
        text = " ".join(
            part
            for part in [
                getattr(project, "merchant_instructions", "") or "",
                str((project.creative_brief or {}).get("legacy_instructions") or ""),
            ]
            if part
        ).lower()
        if re.search(r"\b60[\s-]*(second|sec|s)\b", text) or "60-second" in text:
            return 60
        if re.search(r"\b30[\s-]*(second|sec|s)\b", text) or "30-second" in text:
            return 30
        from ai.services.durations import supported_duration

        return supported_duration(getattr(project, "duration_seconds", None) or 45)

    def _product_facts(self, project) -> tuple[str, str, str]:
        snap = project.product_snapshot or {}
        brief = project.creative_brief or {}
        name = str(snap.get("name") or getattr(getattr(project, "product", None), "name", "") or "produk ini").strip()
        from ai.services.director import selling_price_text

        price = selling_price_text(brief, snap)
        benefit = str(brief.get("main_benefit") or brief.get("promise") or snap.get("description") or name).strip()
        return name, price, benefit

    def _blocks_presenter(self, project) -> bool:
        text = " ".join(
            part
            for part in [
                getattr(project, "merchant_instructions", "") or "",
                str((project.creative_brief or {}).get("must_not_show") or ""),
                str((project.creative_brief or {}).get("legacy_instructions") or ""),
            ]
            if part
        ).lower()
        return any(
            token in text
            for token in (
                "no presenter",
                "do not generate a presenter",
                "don't generate a presenter",
                "do not add a presenter",
                "no talent",
                "no hands",
                "without a presenter",
                "product photos only",
                "supplied product photos",
            )
        )

    def _fallback_brief(self, project) -> dict:
        from ai.services.director import normalize_brief

        existing = dict(project.creative_brief or {})
        name, price, benefit = self._product_facts(project)
        instructions = getattr(project, "merchant_instructions", "") or existing.get("legacy_instructions") or ""
        duration = self._duration(project)
        must_not = str(existing.get("must_not_show") or "").strip()
        if self._blocks_presenter(project) and "presenter" not in must_not.lower():
            extra = "presenter, hands, packaging, new product views"
            must_not = f"{must_not}, {extra}".strip(", ")
        if existing.get("schema_version") == 2 or existing.get("objective"):
            return normalize_brief(
                {
                    **existing,
                    "duration": duration,
                    "legacy_instructions": instructions,
                    "must_not_show": must_not,
                    "platform": existing.get("platform") or ("tiktok" if "tiktok" in instructions.lower() else existing.get("platform") or ""),
                    "must_remain_exact": existing.get("must_remain_exact")
                    or ["product_appearance", "product_name", "price", "brand_colors"],
                },
                project,
            )
        return {
            "title": f"{name} video",
            "audience": existing.get("audience") or existing.get("customer") or "Malaysian shoppers",
            "hook": existing.get("hook") or name,
            "promise": existing.get("promise") or benefit,
            "proof_points": existing.get("proof_points") or [item for item in [price, name] if item],
            "cta": existing.get("cta") or f"Dapatkan {name}" + (f" · {price}" if price else ""),
            "tone": existing.get("tone") or getattr(project, "speaking_style", "") or "warm",
            "unsupported_claims": [],
            "content_ideas": existing.get("content_ideas") or [],
            "customer_objections": existing.get("customer_objections") or [],
            "directions": existing.get("directions") or [],
        }

    def _fallback_script(self, project, duration: int) -> dict:
        from ai.services.captions import wrap_caption
        from ai.services.director import commercial_cta

        name, price, benefit = self._product_facts(project)
        brief = project.creative_brief or {}
        cta = commercial_cta(brief, project.product_snapshot or {}, getattr(project, "language", "") or "")
        product_only = self._blocks_presenter(project)
        if product_only:
            titles = ["Hook", "Product detail", "Shade close-up", "Texture", "Name and price", "Hero + CTA"]
            visuals = [
                f"9:16 vertical. Use only the supplied {name} product photos. Slow push-in on the full product. Do not add a presenter, hands, packaging, or a new product view.",
                f"Crop and slow zoom into the distinctive colour and finish of {name}. Keep the photographed appearance exact.",
                f"Hold on the rose or hero shade of {name} using the original photo. Simple pan only.",
                f"Gentle pan across the product surface from the supplied photos. Clean cut. No extra objects.",
                f"Product-hero crop from the original photo. Leave safe space for the name and {price or 'price'} caption.",
                f"Final product hold from the original photo. Clean transition in. No presenter.",
            ]
            lines = [
                f"Tengok {name} ni.",
                benefit or f"{name} nampak exact macam photo.",
                f"Shade and finish stay exactly as photographed.",
                f"{name} — warna dan bentuk tak berubah.",
                f"{price} je." if price else f"{name}, terus dari photo rasmi.",
                cta,
            ]
            captions = [
                name,
                benefit or name,
                name,
                name,
                f"{name} · {price}" if price else name,
                cta,
            ]
        else:
            titles = ["Hook", "Product in use", "Product detail", "Benefit", "Hero + CTA"]
            visuals = [
                f"9:16 vertical opening on the supplied {name} product photo. Slow push-in.",
                f"Keep {name} identical to the product photos while showing a simple use moment.",
                f"Tight crop of {name} from the original photos. Preserve colour and shape.",
                f"Hold {name} clear in frame. Do not invent claims.",
                f"Hero shot of {name} from the original photos with space for the CTA.",
            ]
            lines = [
                f"Kenalan dengan {name}.",
                benefit or f"{name} sesuai untuk harian.",
                f"{name} nampak exact macam photo rasmi.",
                f"{price} je." if price else f"Dapatkan {name}.",
                cta,
            ]
            captions = [
                name,
                benefit or name,
                name,
                f"{name} · {price}" if price else name,
                cta,
            ]
        count = len(titles)
        each = round(duration / count, 2)
        scenes = []
        for index, title in enumerate(titles, start=1):
            scenes.append(
                {
                    "scene": index,
                    "scene_key": f"scene-{index}",
                    "order": index,
                    "title": title,
                    "visual": visuals[index - 1],
                    "narration": lines[index - 1],
                    "caption": wrap_caption(captions[index - 1]),
                    "duration": each,
                    "product_facts": [item for item in [name, price] if item],
                    "cta": index == count,
                }
            )
        return {
            "duration_seconds": duration,
            "language": LANGUAGE_CODES.get(getattr(project, "language", ""), "ms-MY"),
            "style": getattr(project, "speaking_style", "") or "warm",
            "hook": lines[0],
            "title": name,
            "full_script": " ".join(lines),
            "cta": cta,
            "claims": [item for item in [name, price] if item],
            "unsupported_claims": [],
            "scenes": scenes,
        }

    def _fallback_shots(self, project) -> dict:
        scenes = (project.script or {}).get("scenes") or []
        if not scenes:
            scenes = [
                {"scene_key": scene.scene_key, "visual": scene.visual, "caption": scene.caption}
                for scene in project.scenes.all()
            ]
        if not scenes:
            scenes = self._fallback_script(project, self._duration(project)).get("scenes") or []
        name, _price, _benefit = self._product_facts(project)
        shots = []
        for index, item in enumerate(scenes, start=1):
            visual = item.get("visual") or f"Keep {name} identical to the supplied product photos."
            shots.append(
                {
                    "scene_key": item.get("scene_key") or f"scene-{index}",
                    "camera": "slow push-in" if index == 1 else "simple pan or crop",
                    "image_prompt": (
                        f"Use only the original {name} product photographs. {visual} "
                        "Do not redesign the product."
                    ),
                    "video_prompt": (
                        f"{visual} Camera: simple pan, crop, or zoom. Clean cut transitions. "
                        "Do not generate a presenter, hands, packaging, or a new product view."
                    ),
                    "on_screen_text": item.get("caption") or "",
                }
            )
        return {"shots": shots}

    def _extra_instruction(self, project) -> str:
        from ai.services.director import extra_instruction_requirement

        return extra_instruction_requirement(getattr(project, "creative_brief", None) or {}, project)

    def _context(self, project) -> str:
        language = LANGUAGE_GUIDE.get(project.language, LANGUAGE_GUIDE["conversational_bm"])
        style = STYLE_GUIDE.get(project.speaking_style, STYLE_GUIDE["warm"])
        gender = getattr(project, "speaker_gender", "") or "female"
        return (
            f"Language: {language}\n"
            f"{speech_lock(project.language)}\n"
            f"Style: {style}\n"
            f"Speaker gender: {gender}\n"
            f"Product snapshot:\n{project.product_snapshot}\n"
            f"Product analysis:\n{project.product_analysis}\n"
            f"Reference analysis:\n{project.reference_analysis or 'None'}\n"
            f"Commerce intelligence:\n{getattr(project, 'kalodata_insights', None) or 'None'}\n"
            f"Creative brief:\n{project.creative_brief or 'None'}\n"
            f"Script:\n{project.script or 'None'}\n"
            f"Merchant instructions:\n{project.merchant_instructions or 'None'}\n"
            f"{self._extra_instruction(project)}\n"
        )
