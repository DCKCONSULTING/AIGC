from __future__ import annotations

import re

from ai.models import Scene, VideoProject
from ai.services.captions import spoken_caption
from ai.services.characters import character_prompt_lines
from ai.services.director import (
    extra_instruction_requirement,
    explicit_location_change,
    original_price_text,
    selling_price_text,
    suppress_price,
    suppress_website,
)
from ai.services.presenter import presenter_identity_text, presenter_image_paths
from ai.services.script import (
    CHINESE_VARIETIES,
    LANGUAGE_CODES,
    LANGUAGE_GUIDE,
    STYLE_GUIDE,
    speech_lock,
    spoken_audio_block,
)

LOCK_INSTRUCTIONS = {
    "product": (
        "The product must remain visually identical to the original approved product photographs. "
        "Do not redesign, reshape, recolor, damage, or substitute the product. "
        "Keep every distinctive physical feature exactly as photographed: shape, proportions, "
        "handle or attachments, surface, glaze, colour, rim, markings, and logo."
    ),
    "presenter": (
        "Keep the same presenter throughout every scene. Do not change face, age, gender presentation, "
        "skin tone, clothing, accessories, outfit identity, or hairstyle. If a presenter reference photograph is supplied, "
        "match that exact person. Do not invent a different face."
    ),
    "location": (
        "Keep the approved location, background, lighting, and visual world. "
        "Do not move the scene to a different place unless the storyboard names a location change."
    ),
    "script": (
        "Use the approved voice-over exactly. Do not rewrite, shorten, or invent new spoken lines."
    ),
    "caption": (
        "The approved caption must match the spoken voice-over word for word. "
        "Do not paint captions, titles, price cards, or extra on-screen text. "
        "Captions are composited after generation so only one line appears."
    ),
}

MUST_REMAIN_LOCKS = {
    "product_appearance": "product",
    "logo": "product",
    "packaging": "product",
    "presenter": "presenter",
    "product_name": "product",
    "price": "caption",
    "brand_colors": "product",
}


def scene_locks(scene: Scene, brief: dict | None = None) -> dict[str, bool]:
    meta = scene.metadata or {}
    locks = {
        "product": bool(meta.get("product_locked")),
        "presenter": bool(meta.get("presenter_locked")),
        "location": bool(meta.get("location_locked")),
        "script": bool(meta.get("script_locked")),
        "caption": bool(meta.get("caption_locked")),
    }
    for item in (brief or {}).get("must_remain_exact") or []:
        mapped = MUST_REMAIN_LOCKS.get(str(item))
        if mapped:
            locks[mapped] = True
    return locks


def compile_scene_prompt(
    scene: Scene,
    project: VideoProject,
    *,
    provider: str = "gemini_omni",
) -> str:
    """Compile director + product-truth instructions for a video provider.

    Product facts come only from the trusted snapshot/brief. Creative direction
    may invent camera, story, and pacing — never prices, claims, or product identity.
    """
    del provider  # reserved for future provider-specific variants
    brief = project.creative_brief or {}
    snapshot = project.product_snapshot or {}
    meta = scene.metadata or {}
    locks = scene_locks(scene, brief)
    identity = presenter_identity_text(project)
    has_presenter_photo = bool(presenter_image_paths(project) or (scene.metadata or {}).get("presenter_reference"))
    continuity = dict(brief.get("continuity_state") or {})
    needs_previous = bool(meta.get("requires_previous_scene_continuity"))
    if identity or has_presenter_photo:
        locks["presenter"] = True
    if continuity.get("location") and not explicit_location_change(
        meta, {"location": continuity.get("location")}, continuity.get("location") or ""
    ):
        locks["location"] = True
    locks["product"] = True

    visual = (
        meta.get("video_prompt")
        or meta.get("shot_description")
        or scene.visual
        or ""
    )
    presenter = meta.get("presenter_action") or ""
    camera = " ".join(
        part
        for part in [
            meta.get("camera_framing") or meta.get("camera") or "",
            meta.get("camera_movement") or "",
            meta.get("lens") or "",
            meta.get("composition") or "",
            meta.get("depth_of_field") or "",
        ]
        if part
    )
    lighting = meta.get("lighting") or ""
    location = meta.get("location") or meta.get("background") or brief.get("location") or ""
    pace = meta.get("pace") or ""
    transition = meta.get("transition") or ""
    voice = scene.narration or meta.get("voice_over") or ""
    if meta.get("caption_locked"):
        exact_caption = " ".join(str(scene.caption or meta.get("on_screen_caption") or "").split())
        if exact_caption:
            voice = exact_caption
    caption = spoken_caption(voice, scene.caption or meta.get("on_screen_caption") or "")
    hide_price = suppress_price(brief)
    hide_website = suppress_website(brief)
    benefit = meta.get("benefit") or meta.get("approved_claim") or ""
    sound = meta.get("sound_direction") or ""
    features = distinctive_features(snapshot, brief)

    product_name = snapshot.get("name") or getattr(project.product, "name", "")
    currency = "" if hide_price else _approved_currency(brief, snapshot)
    price = "" if hide_price else _display_price(brief, snapshot)
    original = "" if hide_price else original_price_text(brief, snapshot)
    offer = "" if hide_price else _approved_offer(brief, snapshot)
    website = "" if hide_website else str(brief.get("website") or snapshot.get("website") or "").strip()
    cta = str(brief.get("cta") or brief.get("call_to_action") or "").strip()
    product_duration = str(brief.get("product_duration") or snapshot.get("duration") or "").strip()
    approved_claims = snapshot.get("approved_claims") or brief.get("approved_claims") or []
    prohibited = [
        *(snapshot.get("prohibited_claims") or []),
        *(snapshot.get("prohibited_bboxes") or []),
        *([brief.get("must_not_show")] if brief.get("must_not_show") else []),
    ]
    language = LANGUAGE_GUIDE.get(project.language, LANGUAGE_GUIDE["conversational_bm"])
    language_code = LANGUAGE_CODES.get(project.language, "ms-MY")
    style = STYLE_GUIDE.get(project.speaking_style, STYLE_GUIDE["warm"])

    product_truth = [
        "PRODUCT TRUTH — never invent or change these facts:",
        "PRODUCT REFERENCE — LOCKED: preserve packaging, logo, product shape, product colors, and visible text where possible.",
        "Do not invent another product. Do not redesign packaging.",
        f"product_name: {product_name}" if product_name else "",
        f"Description: {snapshot.get('description')}" if snapshot.get("description") else "",
        "COMMERCIAL FIELDS — keep these separate. Never merge price, currency, and duration into one phrase:",
        (
            "original_price: (hidden — do not speak or show any original price)"
            if hide_price
            else (f"original_price: {original}" if original and original != price else "")
        ),
        (
            "price: (hidden — do not speak, invent, or show any price, price card, RM amount, or cost)"
            if hide_price
            else (f"price: {price}" if price else "price: (none — do not invent a price)")
        ),
        (
            "currency: (hidden — do not show a currency or price card)"
            if hide_price
            else (f"currency: {currency}" if currency else "currency: (none — do not invent a currency)")
        ),
        f"duration: {product_duration}" if product_duration else "duration: (none — do not invent a session/lesson duration)",
        (
            "offer: (hidden — do not invent a discount or offer)"
            if hide_price
            else (f"offer: {offer}" if offer else "offer: (none — do not invent a discount or offer)")
        ),
        (
            "Do not show a price card, price tag, strikethrough price, or any RM/USD amount."
            if hide_price
            else "Use original_price and price exactly as spoken when a price is part of the approved voice-over. Do not prefix RM onto USD or another currency. Do not invent a price card unless the spoken line contains the price."
        ),
        f"cta: {cta}" if cta else "",
        (
            "website: (hidden — do not show any website, URL, domain, QR code, or handle)"
            if hide_website
            else (f"website: {website}" if website else "website: (none — do not invent or show a website or URL)")
        ),
        f"Variants: {', '.join(snapshot.get('variants') or [])}" if snapshot.get("variants") else "",
        f"Dimensions: {snapshot.get('dimensions')}" if snapshot.get("dimensions") else "",
        f"Materials: {snapshot.get('materials')}" if snapshot.get("materials") else "",
        f"Approved claims only: {', '.join(approved_claims)}" if approved_claims else "Do not invent product claims.",
        f"Scene benefit / approved claim: {benefit}" if benefit else "",
        "Authoritative product appearance: the original product photographs only. "
        "Never copy or reuse an earlier AI-generated frame as the product reference.",
        f"Preserve these distinctive features exactly: {'; '.join(features)}" if features else (
            "Preserve the exact photographed shape, proportions, attachments, surface, colour, and markings."
        ),
    ]

    analysis = project.reference_analysis or {}
    reference_style = ""
    if analysis:
        reference_style = " ".join(
            part
            for part in [
                "REFERENCE STYLE ONLY. Match pacing, camera language, and story structure.",
                "Do not copy the reference presenter, product, brand, logo, or dialogue.",
                f"Hook type: {analysis.get('hook')}" if analysis.get("hook") else "",
                f"Camera style: {analysis.get('camera_style')}" if analysis.get("camera_style") else "",
                f"Pacing: {analysis.get('pacing')}" if analysis.get("pacing") else "",
                f"Lighting style: {analysis.get('lighting')}" if analysis.get("lighting") else "",
                f"CTA structure: {analysis.get('cta_structure')}" if analysis.get("cta_structure") else "",
            ]
            if part
        )
    creative = [
        "CREATIVE DIRECTION — you may interpret these as filmmaking instructions:",
        (
            "CONTINUITY — CONTINUE NATURALLY FROM THE PREVIOUS SHOT. "
            "This is not a new standalone advertisement. "
            "Keep the same presenter, clothing, hairstyle, accessories, product, location, "
            "lighting, camera world, props, product position, and visual tone. "
            "Begin from the previous scene's final visual state. "
            "A previous-scene last frame is included as a strong continuity reference for "
            "environment, presenter position, clothing, and lighting. "
            "Do not use that frame to redesign the product — product appearance comes only "
            "from the original product photographs."
        )
        if needs_previous
        else (
            "Keep this video visually continuous with the rest of the story. "
            "Same presenter, clothing, product, lighting, and world unless the storyboard "
            "names a deliberate location change."
        ),
        f"Shot: {visual}" if visual else "",
        f"Presenter action: {presenter}" if presenter else "",
        f"Presenter identity (keep this exact person in every scene): {identity}" if identity else "",
        *character_prompt_lines(project),
        (
            "PRESENTER CONTINUITY: A presenter reference photograph is included. "
            "Use that same face, hair, body, clothing, and accessories in this scene. "
            "Do not generate a different person or change the outfit."
        )
        if has_presenter_photo
        else (
            "Keep the same presenter identity, face, clothing, and hair if a presenter appears. "
            "Do not invent a presenter reference photo that was not supplied."
        )
        if presenter or locks["presenter"] or identity
        else "",
        f"Camera: {camera or continuity.get('camera_style') or ''}".rstrip()
        if (camera or continuity.get("camera_style"))
        else "",
        f"Lighting: {lighting or continuity.get('lighting') or ''}".rstrip()
        if (lighting or continuity.get("lighting"))
        else "",
        f"Location / background: {location or continuity.get('location') or ''}".rstrip()
        if (location or continuity.get("location"))
        else "",
        f"Locked wardrobe: {continuity.get('wardrobe')}" if continuity.get("wardrobe") else "",
        f"Pace: {pace}" if pace else "",
        f"Transition: {transition or 'match cut — continue the same shot without resetting camera, wardrobe, or lighting'}",
        "Do not hard-cut to a new standalone advertisement. Continue motion from the previous frame.",
        "SCENE — dialogue must come from the approved scene script. Do not rewrite commercial meaning.",
        f"Voice-over to speak EXACTLY, word for word, with no paraphrase or shortening: {voice}" if voice else "",
        "ON-SCREEN TEXT: Do not render captions, titles, subtitles, price cards, websites, URLs, logos you invent, "
        "lower-thirds, or any other on-screen graphics. Spoken audio only. One caption is composited after generation.",
        f"Approved spoken line that later becomes the only caption: {caption}" if caption else "",
        f"Sound / music: {sound}" if sound else "Generate natural scene sound that matches the action.",
        "AUDIO: Generate spoken narration and scene audio together with the video. "
        "Speak the approved voice-over exactly, in the locked spoken language. "
        "The voice-over must be clearly audible. Do not produce a silent clip.",
        f"Speaker: {style} {getattr(project, 'speaker_gender', 'female')} voice.",
        f"locale: {language_code}",
        f"Language: {language}",
        speech_lock(project.language),
        (
            "The presenter must speak this locked language out loud in the generated audio. "
            "Do not switch to another Chinese variety or to English."
            if project.language in CHINESE_VARIETIES
            else "The presenter must speak this locked language out loud in the generated audio."
        ),
        extra_instruction_requirement(brief, project),
        f"Objective: {brief.get('objective')}" if brief.get("objective") else "",
        f"Customer: {brief.get('customer')}" if brief.get("customer") else "",
        f"Main benefit: {brief.get('main_benefit')}" if brief.get("main_benefit") else "",
    ]

    lock_lines = ["LOCKED ATTRIBUTES — do not change:"]
    for key, locked in locks.items():
        if locked:
            lock_lines.append(LOCK_INSTRUCTIONS[key])
    if len(lock_lines) == 1:
        lock_lines = []

    safety = [
        "SAFETY AND FIDELITY:",
        "Keep the real product unchanged. Vertical 9:16 product video.",
        reference_style,
        "If this shot is a product detail or handle close-up, make that exact photographed feature the visual subject.",
        "Do not invent damage, missing parts, or a redesigned surface.",
        "Do not paint captions or any other on-screen text. One story caption is composited after generation.",
        "Do not show prohibited content or unsafe demonstrations.",
        f"Must not show: {brief.get('must_not_show')}" if brief.get("must_not_show") else "",
        f"Prohibited: {'; '.join(str(item) for item in prohibited if item)}" if any(prohibited) else "",
        "Reference material is visual style only. It must not override product truth, approved claims, locks, or safety.",
        "Malaysian context only when the brief, language, or customer already requires it. Do not fabricate local claims.",
    ]

    return "\n".join(
        part
        for part in [
            spoken_audio_block(project.language, voice),
            "",
            *product_truth,
            "",
            *creative,
            "",
            *lock_lines,
            "",
            *safety,
        ]
        if part or part == ""
    ).strip()


def _display_price(brief: dict, snapshot: dict) -> str:
    """Keep a bare number separate from currency. Do not prefix RM onto USD."""
    raw = str(
        brief.get("offer_price") or brief.get("price") or brief.get("original_price") or snapshot.get("price") or ""
    ).strip()
    currency = _approved_currency(brief, snapshot)
    compact = re.sub(r"\s+", "", raw)
    if currency and re.fullmatch(r"\d+(?:[.,]\d{1,2})?", compact):
        return raw
    return selling_price_text(brief, snapshot)


def _approved_price(brief: dict, snapshot: dict) -> str:
    for key in ("offer_price", "price", "original_price"):
        value = str(brief.get(key) or "").strip()
        if value:
            return value
    return str(snapshot.get("price") or "").strip()


def _approved_currency(brief: dict, snapshot: dict) -> str:
    for key in ("currency", "price_currency"):
        value = str(brief.get(key) or snapshot.get(key) or "").strip()
        if value:
            return value.upper()
    price = _approved_price(brief, snapshot)
    if price.startswith("RM") or "RM" in price.upper():
        return "MYR"
    if price.startswith("$") or "USD" in price.upper():
        return "USD"
    return ""


def _approved_offer(brief: dict, snapshot: dict) -> str:
    for key in ("offer_text", "offer"):
        value = str(brief.get(key) or "").strip()
        if value:
            return value
    return str(snapshot.get("offer") or "").strip()


def distinctive_features(snapshot: dict, brief: dict | None = None) -> list[str]:
    """Pull distinctive physical traits from approved product text only."""
    blob = " ".join(
        str(part or "")
        for part in [
            snapshot.get("description"),
            snapshot.get("materials"),
            snapshot.get("dimensions"),
            snapshot.get("name"),
            (brief or {}).get("main_benefit"),
        ]
    )
    found = []
    patterns = (
        r"\b[\w-]*(?:handle|pemegang|lid|cover|spout|rim|bibir|glaze|glazed|berglaz|speckle\w*|bintik\w*|marking\w*|logo|shape|bentuk|proportion\w*)\b[^.]*",
        r"\b(?:cream|krim|brown|coklat|white|putih|black|hitam|stoneware|ceramic|seramik)[^.]*",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, blob, flags=re.I):
            phrase = re.sub(r"\s+", " ", match.group(0)).strip(" ,.")
            if 3 < len(phrase) < 80 and phrase.lower() not in {item.lower() for item in found}:
                found.append(phrase)
    extras = [item for item in (snapshot.get("known_mistakes") or []) if str(item).strip()]
    return [*found[:8], *extras[:3]]


_EXACT_SPEECH = (
    "Speak the supplied dialogue exactly as written.\n"
    "Do not paraphrase.\n"
    "Do not shorten it.\n"
    "Do not add words.\n"
    "Do not remove words.\n"
    "Do not change the language.\n"
    "Do not invent additional dialogue.\n"
    "The spoken dialogue must match the locked caption text exactly."
)


def format_beat_span(start: float, end: float) -> str:
    """Keep a short overlap visible. 7.5–8.0 must not round to [8-8s]."""
    start_value = float(start)
    end_value = float(end)

    def label(value: float, digits: int) -> str:
        if digits == 0 or abs(value - round(value)) < 1e-6:
            return f"{value:.0f}"
        return f"{value:.{digits}f}"

    fractional = (
        abs(start_value - round(start_value)) > 1e-6
        or abs(end_value - round(end_value)) > 1e-6
    )
    digits = 1 if fractional else 0
    left = label(start_value, digits)
    right = label(end_value, digits)
    if left == right and abs(end_value - start_value) >= 1e-6:
        left = f"{start_value:.2f}"
        right = f"{end_value:.2f}"
    return f"[{left}-{right}s]"


def _character_names(project: VideoProject | None) -> list[str]:
    if not project or not getattr(project, "pk", None):
        return []
    from django.core.exceptions import ObjectDoesNotExist

    try:
        config = project.character_config
    except ObjectDoesNotExist:
        return []
    identity = config.identity_snapshot or {}
    names = []
    for key in ("name", "character_name"):
        value = str(identity.get(key) or "").strip()
        if value and value not in names:
            names.append(value)
    return names


def redact_veo_character_labels(text: str, names: list[str]) -> str:
    """Drop internal character names and ids from text sent to Veo."""
    cleaned = str(text or "")
    for name in sorted(names, key=len, reverse=True):
        if len(name) < 2:
            continue
        cleaned = re.sub(rf"(?i)\b{re.escape(name)}\b", "the presenter", cleaned)
    cleaned = re.sub(r"(?im)^.*Character identifier:.*(?:\n|$)", "", cleaned)
    cleaned = re.sub(r"(?i)\(id\s*\d+\)", "", cleaned)
    cleaned = re.sub(r"(?i)\bid\s+\d+\b", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,])", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _scene_spans(scenes: list[Scene]) -> list[tuple[float, float, Scene]]:
    cursor = 0.0
    spans: list[tuple[float, float, Scene]] = []
    for scene in scenes:
        duration = float(scene.duration or 0)
        spans.append((cursor, cursor + duration, scene))
        cursor += duration
    return spans


def _window_scenes(scenes: list[Scene], start: float, end: float) -> list[tuple[float, float, Scene]]:
    rows = []
    for scene_start, scene_end, scene in _scene_spans(scenes):
        if scene_end <= start + 0.05 or scene_start >= end - 0.05:
            continue
        rows.append((max(scene_start, start), min(scene_end, end), scene))
    return rows


# Internal pipeline labels that must never become spoken audio.
_WORKFLOW_LEAK_RE = re.compile(
    r"(?i)\b("
    r"bulk\s+existing\s+video|existing_video|existing\s+video|master_spec|master\s+spec|"
    r"bulk_generation|bulk\s+generation|bulk\s+mode|from_project|generation_plan|"
    r"reference_location|reference_character"
    r")\b"
)


class PromptValidationError(ValueError):
    """Hard failure: prompt content is unsafe to submit as-is."""


def sanitize_spoken_line(text: str) -> str:
    """Remove workflow labels and collapse duplicate sentences from spoken copy."""
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return ""
    cleaned = _WORKFLOW_LEAK_RE.sub(" ", value)
    cleaned = " ".join(cleaned.split()).strip(" ·-–,")
    if not cleaned:
        return ""
    # Drop exact consecutive duplicate sentences.
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    deduped: list[str] = []
    for part in parts:
        if deduped and deduped[-1].lower() == part.lower():
            continue
        deduped.append(part)
    return " ".join(deduped).strip()


def validate_film_prompt_inputs(
    project: VideoProject,
    window: list[tuple[float, float, Scene]],
    *,
    start: float,
    end: float,
) -> list[str]:
    """Return recoverable warnings. Raises PromptValidationError for hard failures."""
    warnings: list[str] = []
    brief = project.creative_brief or {}
    snapshot = project.product_snapshot or {}
    product_name = str(snapshot.get("name") or getattr(project.product, "name", "") or "").strip()
    spoken_lines: list[str] = []
    locations: list[str] = []
    for _, _, scene in window:
        meta = scene.metadata or {}
        voice = sanitize_spoken_line(scene.narration or meta.get("voice_over") or "")
        visual = str(meta.get("video_prompt") or meta.get("shot_description") or scene.visual or "")
        if _WORKFLOW_LEAK_RE.search(str(scene.narration or "")) or _WORKFLOW_LEAK_RE.search(
            str(meta.get("voice_over") or "")
        ):
            warnings.append(f"scene {scene.order}: workflow label scrubbed from narration")
        if _WORKFLOW_LEAK_RE.search(visual):
            warnings.append(f"scene {scene.order}: workflow label in visual instructions")
        if voice:
            spoken_lines.append(voice)
        loc = str(meta.get("location") or meta.get("background") or "").strip().lower()
        if loc:
            locations.append(loc)
    if len(spoken_lines) >= 2 and len(set(line.lower() for line in spoken_lines)) == 1:
        warnings.append("duplicated dialogue across scene window")
    if product_name and not any(
        product_name.lower() in str(
            (scene.metadata or {}).get("video_prompt")
            or (scene.metadata or {}).get("shot_description")
            or scene.visual
            or ""
        ).lower()
        for _, _, scene in window
    ):
        warnings.append("product identity may be missing from visual instructions")
    requested = float(project.duration_seconds or 0)
    window_len = max(0.0, float(end) - float(start))
    if requested and window_len > requested + 1.5:
        raise PromptValidationError(
            f"Clip window {window_len:.1f}s exceeds requested duration {requested:.0f}s."
        )
    # Price must not appear unless brief/snapshot approve it.
    approved_price = str(
        brief.get("offer_price") or brief.get("price") or snapshot.get("price") or ""
    ).strip()
    if not approved_price:
        for line in spoken_lines:
            if re.search(r"(?i)\b(?:rm|myr|usd|\$)\s*\d", line) or re.search(r"\b\d+\.\d{2}\b", line):
                raise PromptValidationError("Spoken lines include a price that is not approved.")
    return warnings


def compile_film_prompt(
    project: VideoProject,
    scenes: list[Scene],
    start: float,
    end: float,
    *,
    extend: bool,
    boundary: bool = False,
    provider: str = "omni",
) -> str:
    """One Omni prompt: global direction once, then only the time range being generated."""
    brief = project.creative_brief or {}
    snapshot = project.product_snapshot or {}
    window = _window_scenes(scenes, start, end)
    provider_name = str(provider or "omni").lower()
    veo = provider_name == "veo"
    minimax = provider_name == "minimax"
    seedance = provider_name == "seedance"
    names = _character_names(project) if veo else []
    identity = presenter_identity_text(project, include_labels=not veo)
    language = LANGUAGE_GUIDE.get(project.language, LANGUAGE_GUIDE["conversational_bm"])
    style = STYLE_GUIDE.get(project.speaking_style, STYLE_GUIDE["warm"])
    product_name = snapshot.get("name") or getattr(project.product, "name", "")
    features = distinctive_features(snapshot, brief)
    locked = any(bool((scene.metadata or {}).get("caption_locked")) for _, _, scene in window)
    character_lines = character_prompt_lines(project, include_labels=not veo)
    validate_film_prompt_inputs(project, window, start=start, end=end)
    lines = []
    spoken_parts: list[str] = []
    for beat_start, beat_end, scene in window:
        meta = scene.metadata or {}
        # Visual instructions stay visual; only scrub workflow leaks (never treat as dialogue).
        visual = _WORKFLOW_LEAK_RE.sub(
            " ",
            str(meta.get("video_prompt") or meta.get("shot_description") or scene.visual or ""),
        )
        visual = " ".join(visual.split()).strip()
        action = str(meta.get("presenter_action") or "").strip()
        voice = sanitize_spoken_line(scene.narration or meta.get("voice_over") or "")
        if meta.get("caption_locked"):
            exact = sanitize_spoken_line(scene.caption or meta.get("on_screen_caption") or "")
            if exact:
                voice = exact
        if veo:
            visual = redact_veo_character_labels(str(visual), names)
            action = redact_veo_character_labels(str(action), names)
            voice = redact_veo_character_labels(str(voice), names)
        if voice:
            spoken_parts.append(voice)
        lines.append(
            "\n".join(
                part
                for part in [
                    format_beat_span(beat_start, beat_end),
                    f"Picture: {visual}" if visual else "",
                    f"Action: {action}" if action else "",
                    f"Speak exactly: {voice}" if voice else "No new spoken line in this beat.",
                    f'The presenter says exactly:\n"{voice}"' if voice and meta.get("caption_locked") else "",
                ]
                if part
            )
        )
    spoken = sanitize_spoken_line(" ".join(spoken_parts))
    timeline = "\n\n".join(lines) or f"{format_beat_span(start, end)}\nContinue the same product story."
    if veo and spoken:
        spoken = redact_veo_character_labels(spoken, names)

    def finish(text: str) -> str:
        if veo:
            return redact_veo_character_labels(text, names)
        return text

    if extend:
        return finish("\n".join(
            part
            for part in [
                "Continue this video from the exact last frame. Do not restart the story.",
                "Keep the same person, face, clothing, product, voice, language, lighting, and location.",
                f"Add only the next {max(1, round(end - start))} seconds. Do not repeat earlier beats.",
                _EXACT_SPEECH if locked else "Speak the supplied lines exactly. Do not invent extra dialogue.",
                spoken_audio_block(project.language, spoken),
                timeline,
                "Do not paint captions or other on-screen text. Speech is audio only.",
                "Keep the product identical to the reference photographs already established.",
                f"Product: {product_name}" if product_name else "",
            ]
            if part
        ).strip())
    if boundary:
        return finish("\n".join(
            part
            for part in [
                "This is a new generation. The previous chain cannot be extended past 40 seconds.",
                "Match the same character, wardrobe, product, environment, camera, lighting, and voice.",
                "Do not copy a previous frame pixel for pixel. There is no previous interaction to continue.",
                "GLOBAL STYLE",
                f"Voice: {style} {getattr(project, 'speaker_gender', 'female')} voice.",
                f"Language: {language}",
                speech_lock(project.language),
                f"Presenter: {identity}" if identity else "Keep one consistent presenter if a person appears.",
                *character_lines,
                "CHARACTER STATE",
                identity or "Same presenter identity as the reference photographs.",
                "PRODUCT STATE",
                f"Product: {product_name}" if product_name else "Same photographed product.",
                (
                    f"Features: {'; '.join(features)}"
                    if features
                    else "Keep the product identical to the reference photographs."
                ),
                "ENVIRONMENT STATE",
                str(brief.get("location") or "Continue the same location and lighting."),
                "STORY STATE",
                f"The story has already covered 0–{start:.0f}s. Generate only {start:.0f}–{end:.0f}s.",
                "This is a NEW generation. Do not send or expect previous_interaction_id.",
                "NEXT TIMELINE",
                timeline,
                _EXACT_SPEECH if locked else "Speak the supplied lines exactly. Do not invent extra dialogue.",
                spoken_audio_block(project.language, spoken),
                "Do not paint captions or other on-screen text.",
            ]
            if part
        ).strip())
    analysis = project.reference_analysis or {}
    style_line = ""
    if analysis:
        style_line = " ".join(
            part
            for part in [
                "Match the approved camera and pacing style only.",
                f"Camera style: {analysis.get('camera_style')}" if analysis.get("camera_style") else "",
                f"Pacing: {analysis.get('pacing')}" if analysis.get("pacing") else "",
            ]
            if part
        )
    opening = "Create one continuous vertical 9:16 product video with native spoken audio."
    if veo:
        opening = (
            "Create one continuous vertical 9:16 product video with native spoken audio. "
            "Keep dialogue, sound effects, and music in the generated soundtrack."
        )
    elif minimax or seedance:
        opening = (
            "Create one continuous vertical 9:16 product video with native spoken audio. "
            "Keep the same person, face, clothing, product, lighting, and location throughout. "
            "Keep dialogue, sound effects, and music in the generated soundtrack."
        )
    later = (
        f"This request covers only {start:.0f}–{end:.0f} seconds. Later beats will be added by extending this video."
        if not (minimax or seedance)
        else (
            f"This request covers only {start:.0f}–{end:.0f} seconds. "
            "Later beats may be generated as separate clips that continue from the last frame."
        )
    )
    return finish(
        "\n".join(
        part
        for part in [
            opening,
            later,
            "GLOBAL",
            f"Product: {product_name}" if product_name else "",
            f"Description: {snapshot.get('description')}" if snapshot.get("description") else "",
            (
                f"Preserve these photographed features exactly: {'; '.join(features)}"
                if features
                else "Keep the product identical to the reference photographs. Do not redesign it."
            ),
            "Do not invent prices, claims, websites, or packaging.",
            f"Presenter: {identity}" if identity else "Keep one consistent presenter if a person appears.",
            *character_lines,
            f"Voice: {style} {getattr(project, 'speaker_gender', 'female')} voice.",
            f"Language: {language}",
            speech_lock(project.language),
            style_line,
            extra_instruction_requirement(brief, project),
            f"Customer: {brief.get('customer')}" if brief.get("customer") else "",
            f"Main benefit: {brief.get('main_benefit')}" if brief.get("main_benefit") else "",
            "Do not paint captions, titles, subtitles, or price cards. Captions are added after generation.",
            _EXACT_SPEECH if locked else "Speak the supplied lines exactly. Do not invent extra dialogue.",
            spoken_audio_block(project.language, spoken),
            "TIMELINE",
            timeline,
        ]
        if part
    ).strip()
    )
