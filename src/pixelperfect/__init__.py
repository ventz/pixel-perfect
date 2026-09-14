"""pixelperfect — restore AI 'pixel art' into true, 100% pixel-perfect images.

Public API:

    from pixelperfect import restore, analyze, PipelineParams
    result = restore(rgb_array, PipelineParams(palette_size=16, upscale=8))
    result.native   # (ny, nx, 3/4) uint8 — the pixel-perfect image
    result.preview  # NN-upscaled for display
    result.score.confidence  # 0..1
"""

from __future__ import annotations

from .editor import export_indexed, render_indexed
from .pipeline import (
    PipelineParams,
    PipelineResult,
    analyze,
    restore,
    to_rgba,
    upscale,
)

__version__ = "0.1.0"

__all__ = [
    "PipelineParams",
    "PipelineResult",
    "analyze",
    "restore",
    "upscale",
    "to_rgba",
    "render_indexed",
    "export_indexed",
    "__version__",
]
