"""Active Studio video provider. Exactly one of omni, veo, minimax, or seedance. No fallback."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

VIDEO_PROVIDERS = ("omni", "veo", "minimax", "seedance")


def video_provider_name() -> str:
    value = str(getattr(settings, "VIDEO_PROVIDER", "omni") or "omni").strip().lower()
    if value not in VIDEO_PROVIDERS:
        raise ImproperlyConfigured(
            f"VIDEO_PROVIDER={value!r} is not supported. Use omni, veo, minimax, or seedance."
        )
    return value


def get_video_generation_provider():
    """Return the configured video generator. Never switches on failure."""
    name = video_provider_name()
    if name == "veo":
        from ai.providers.google.veo import VeoProvider

        return VeoProvider()
    if name == "minimax":
        from ai.providers.minimax import MiniMaxProvider

        return MiniMaxProvider()
    if name == "seedance":
        from ai.providers.seedance import SeedanceProvider

        return SeedanceProvider()
    from ai.providers.google.omni import GeminiOmniProvider

    return GeminiOmniProvider()


def video_model_name(provider=None) -> str:
    if provider is not None:
        return str(getattr(provider, "model", "") or "")
    name = video_provider_name()
    if name == "veo":
        return str(getattr(settings, "VEO_MODEL", "") or "veo-3.1-generate-preview")
    if name == "minimax":
        return str(getattr(settings, "MINIMAX_VIDEO_MODEL", "") or "MiniMax-H3")
    if name == "seedance":
        return str(getattr(settings, "SEEDANCE_MODEL", "") or "dreamina-seedance-2-5-260628")
    return str(getattr(settings, "GEMINI_OMNI_MODEL", "") or "gemini-omni-1.1-flash")
