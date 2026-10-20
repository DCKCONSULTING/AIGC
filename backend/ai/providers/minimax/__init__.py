"""MiniMax video generation provider (VIDEO_PROVIDER=minimax)."""

from .video import (
    MINIMAX_MAX_CLIP_SECONDS,
    MiniMaxProvider,
    plan_minimax_generation,
    require_minimax_api_key,
    select_minimax_reference_paths,
)

__all__ = [
    "MINIMAX_MAX_CLIP_SECONDS",
    "MiniMaxProvider",
    "plan_minimax_generation",
    "require_minimax_api_key",
    "select_minimax_reference_paths",
]
