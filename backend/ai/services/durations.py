"""Canonical Studio durations. Never rewrite 15 seconds into 30."""

from __future__ import annotations

SUPPORTED_DURATIONS = (15, 30, 45, 60)

# Storyboard scene counts. These are editing units, not Omni request counts.
# A full Studio generation follows plan_omni_chains(), which stays inside the
# verified Omni window: 3–10 seconds per clip, 40 seconds per extension chain.
SCENE_COUNTS = {15: 3, 30: 5, 45: 6, 60: 6}
MIN_SCENE_SECONDS = 3.0
MAX_SCENE_SECONDS = 10.0

# Verified against Gemini Omni 1.1 Flash docs and the installed google-genai SDK.
# Do not invent a 45s or 60s single-request duration.
MAX_SINGLE_OMNI_DURATION = 10
MAX_EXTENSION_HOP = 10
MAX_EXTENSION_CHAIN = 40
OMNI_MAX_CONTINUOUS_DURATION_SECONDS = 40
OMNI_MIN_SECONDS = 3
OMNI_MAX_SEGMENT_SECONDS = MAX_SINGLE_OMNI_DURATION
OMNI_MAX_CHAIN_SECONDS = OMNI_MAX_CONTINUOUS_DURATION_SECONDS
# Omni cannot extend one interaction past this. A later chain is a NEW
# generation, not an extension. Joining the files does not continue the same
# performance.
CONTINUITY_BOUNDARY_SECONDS = OMNI_MAX_CONTINUOUS_DURATION_SECONDS


def supported_duration(value, default: int = 45) -> int:
    if value in (None, ""):
        value = default
    try:
        duration = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Choose 15, 30, 45, or 60 seconds."
        ) from exc
    if duration not in SUPPORTED_DURATIONS:
        raise ValueError(
            f"{duration}-second videos are not currently supported. Choose 15, 30, 45, or 60 seconds."
        )
    return duration


def scene_count_for_duration(duration: int) -> int:
    duration = supported_duration(duration)
    return SCENE_COUNTS[duration]


def scene_duration_fits(duration: float) -> bool:
    try:
        value = float(duration)
    except (TypeError, ValueError):
        return False
    return MIN_SCENE_SECONDS <= value <= MAX_SCENE_SECONDS


def plan_omni_segments(duration: int) -> list[int]:
    """Split a requested length into 3–10 second Omni clips, preferring 10 seconds."""
    remaining = int(duration)
    if remaining < OMNI_MIN_SECONDS:
        raise ValueError(
            f"{remaining}-second videos are not currently supported. Choose 15, 30, 45, or 60 seconds."
        )
    parts: list[int] = []
    while remaining > 0:
        if remaining <= OMNI_MAX_SEGMENT_SECONDS:
            if remaining < OMNI_MIN_SECONDS and parts:
                need = OMNI_MIN_SECONDS - remaining
                if parts[-1] - need >= OMNI_MIN_SECONDS:
                    parts[-1] -= need
                    remaining += need
            parts.append(remaining)
            break
        hop = min(remaining, MAX_SINGLE_OMNI_DURATION)
        parts.append(hop)
        remaining -= hop
    return parts


def plan_omni_chains(duration: int) -> list[list[int]]:
    """Group Omni hops into chains of at most OMNI_MAX_CONTINUOUS_DURATION_SECONDS.

    Chain 0 can use previous_interaction_id extensions. Chain 1+ is a NEW
    Omni generation. 15=[10,5], 30=[10,10,10], 40=[10,10,10,10],
    45=[10,10,10,10]+[5], 60=[10,10,10,10]+[10,10].
    """
    requested = supported_duration(duration) if duration in SUPPORTED_DURATIONS else int(duration)
    segments = plan_omni_segments(requested)
    chains: list[list[int]] = []
    current: list[int] = []
    total = 0
    for segment in segments:
        if current and total + segment > OMNI_MAX_CONTINUOUS_DURATION_SECONDS:
            chains.append(current)
            current = []
            total = 0
        current.append(segment)
        total += segment
    if current:
        chains.append(current)
    return chains


def chain_is_new_generation(chain_index: int) -> bool:
    """True when this chain cannot use previous_interaction_id."""
    return int(chain_index) > 0
