from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")


def _is_cjk_caption(text: str) -> bool:
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return False
    return sum(1 for ch in chars if _CJK_RE.match(ch)) >= max(1, (len(chars) + 2) // 3)


def _caption_units(text: str, *, cjk: bool) -> list[str]:
    if not cjk:
        return text.split()
    units: list[str] = []
    buf = ""
    for ch in text:
        if _CJK_RE.match(ch) or ch in "，。！？、；：":
            if buf.strip():
                units.append(buf.strip())
                buf = ""
            units.append(ch)
        elif ch.isspace():
            if buf.strip():
                units.append(buf.strip())
                buf = ""
        else:
            buf += ch
    if buf.strip():
        units.append(buf.strip())
    return units


def _join_unit(current: str, unit: str, *, cjk: bool) -> str:
    if not current:
        return unit
    if not cjk:
        return f"{current} {unit}"
    if unit in "，。！？、；：,.!?":
        return current + unit
    if _CJK_RE.match(unit) or _CJK_RE.match(current[-1]):
        return current + unit
    return f"{current} {unit}"


def wrap_caption(text: str, *, max_lines: int = 3, max_chars: int = 36) -> str:
    """Wrap the spoken sentence for 9:16. Never shorten, paraphrase, or add an ellipsis."""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return ""
    cjk = _is_cjk_caption(raw)
    width = 16 if cjk else max_chars
    units = _caption_units(raw, cjk=cjk)
    lines: list[str] = []
    current = ""
    for unit in units:
        trial = _join_unit(current, unit, cjk=cjk)
        if current and len(trial) > width and len(lines) < max_lines - 1:
            lines.append(current)
            current = unit
        else:
            current = trial
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        extra = "".join(lines[max_lines - 1 :]) if cjk else " ".join(lines[max_lines - 1 :])
        lines = [*lines[: max_lines - 1], extra]
    return "\n".join(lines[:max_lines])


def caption_line_count(text: str) -> int:
    wrapped = wrap_caption(text)
    if not wrapped:
        return 0
    return len([line for line in wrapped.split("\n") if line.strip()])


def spoken_caption(narration: str, caption: str = "") -> str:
    """On-screen text must be the exact spoken line when voice-over exists."""
    spoken = re.sub(r"\s+", " ", str(narration or "")).strip()
    if spoken:
        return wrap_caption(spoken)
    return wrap_caption(caption)
