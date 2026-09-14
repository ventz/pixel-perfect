"""End-to-end orchestration: imperfect image -> pixel-perfect result.

Ties the stages together (denoise -> detect/select grid -> collapse cells ->
quantize palette -> emit native + upscaled output) behind one
:class:`PipelineParams` knob-set, so the CLI, the FastAPI layer, and the tests
all drive the exact same code. Every stage is also exposed individually for
callers that want to inspect or override intermediate results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as _field

import numpy as np

from . import palette as _palette
from .denoise import denoise
from .grid import candidate_cell_counts, gradient_profiles
from .sample import CellField
from .score import GridScore, select_grid

__all__ = [
    "PipelineParams",
    "PipelineResult",
    "analyze",
    "restore",
    "upscale",
    "to_rgba",
    "VALID_METHODS",
    "MAX_UPSCALE",
    "MAX_NATIVE_CELLS",
    "MAX_OUTPUT_PIXELS",
    "clamp_upscale",
]

VALID_METHODS = ("median", "mode", "medoid", "mean")
MAX_UPSCALE = 32  # guards against accidental gigapixel previews
MAX_NATIVE_CELLS = 512  # per-axis cap on a forced grid (matches the editor's 512x512)
MAX_OUTPUT_PIXELS = 16_000_000  # cap on any N× preview (~4000x4000 RGBA ≈ 64 MB)
MAX_DENOISE = 10.0


def clamp_upscale(width: int, height: int, factor: int) -> int:
    """Largest factor ``<= factor`` whose ``width*height*factor²`` fits the output cap."""
    factor = max(0, min(int(factor), MAX_UPSCALE))
    area = max(1, int(width) * int(height))
    fit = int(math.isqrt(MAX_OUTPUT_PIXELS // area))
    return max(1, min(factor, fit)) if factor >= 1 else 0


@dataclass
class PipelineParams:
    denoise_strength: float = 1.0
    native_w: int | None = None  # override detected grid width (cells)
    native_h: int | None = None  # override detected grid height (cells)
    palette_size: int | None = None  # max colors; None = auto count
    palette_name: str | None = None  # snap to a BUILTIN_PALETTES entry instead
    interior_frac: float = 0.5  # central fraction of each cell that votes
    sample_method: str = "median"  # median | mode | medoid | mean
    merge_threshold: float = 0.035
    upscale: int = 0  # 0 = no preview; else NN upscale factor for output
    top_k: int = 4  # candidate cell-counts to score per axis
    fit_smoothness: float = 0.5  # drift-fit stiffness (higher = nearer uniform)
    fit_window_frac: float = 0.35

    def _fit_kwargs(self) -> dict:
        return {"smoothness": self.fit_smoothness, "window_frac": self.fit_window_frac}

    def validate(self) -> "PipelineParams":
        """Validate and clamp parameters. Raises ``ValueError`` on bad input."""
        if self.sample_method not in VALID_METHODS:
            raise ValueError(
                f"Unknown sample_method {self.sample_method!r}; choose from {VALID_METHODS}."
            )
        if self.palette_name and self.palette_name not in _palette.BUILTIN_PALETTES:
            raise ValueError(
                f"Unknown palette_name {self.palette_name!r}; "
                f"choose from {sorted(_palette.BUILTIN_PALETTES)}."
            )
        for name in (
            "denoise_strength", "interior_frac", "merge_threshold",
            "fit_smoothness", "fit_window_frac",
        ):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be a finite number.")
        if not (0.0 < self.interior_frac <= 1.0):
            raise ValueError("interior_frac must be in (0, 1].")
        if self.denoise_strength < 0:
            raise ValueError("denoise_strength must be >= 0.")
        if self.merge_threshold < 0 or self.fit_smoothness < 0:
            raise ValueError("merge_threshold and fit_smoothness must be >= 0.")
        if not (0.0 < self.fit_window_frac < 1.0):
            raise ValueError("fit_window_frac must be in (0, 1).")
        for name in ("native_w", "native_h"):
            v = getattr(self, name)
            if v is None:
                continue
            v = int(v)
            if not (1 <= v <= MAX_NATIVE_CELLS):
                raise ValueError(f"{name} must be between 1 and {MAX_NATIVE_CELLS}.")
            setattr(self, name, v)
        # Clamp numeric ranges rather than reject, so the UI sliders are forgiving.
        self.denoise_strength = min(float(self.denoise_strength), MAX_DENOISE)
        self.upscale = max(0, min(int(self.upscale), MAX_UPSCALE))
        self.top_k = max(1, min(int(self.top_k), 16))
        if self.palette_size is not None:
            self.palette_size = max(1, min(int(self.palette_size), 256))
        return self


@dataclass
class PipelineResult:
    native: np.ndarray  # (ny, nx, 3) or (ny, nx, 4) uint8 — the pixel-perfect image
    palette: np.ndarray  # (K, 3) uint8
    score: GridScore
    nx: int
    ny: int
    preview: np.ndarray | None = None  # NN-upscaled native for display
    candidates: dict = _field(default_factory=dict)  # detection diagnostics


def _select(rgb: np.ndarray, params: PipelineParams) -> tuple[GridScore, dict]:
    """Run grid detection/selection honoring any explicit size override."""
    h, w = rgb.shape[:2]
    if params.native_w and params.native_w > w:
        raise ValueError(f"native_w ({params.native_w}) exceeds the image width ({w}px).")
    if params.native_h and params.native_h > h:
        raise ValueError(f"native_h ({params.native_h}) exceeds the image height ({h}px).")
    prof_x, prof_y = gradient_profiles(rgb)
    if params.native_w and params.native_h:
        xs, ys = [int(params.native_w)], [int(params.native_h)]
    else:
        xs = candidate_cell_counts(prof_x, w)
        ys = candidate_cell_counts(prof_y, h)
        if params.native_w:
            xs = [int(params.native_w)]
        if params.native_h:
            ys = [int(params.native_h)]
    score = select_grid(
        rgb,
        xs,
        ys,
        top_k=params.top_k,
        interior_frac=params.interior_frac,
        method=params.sample_method,
        fit_kwargs=params._fit_kwargs(),
    )
    diag = {
        "x_candidates": xs,
        "y_candidates": ys,
        "period_x": score.grid.period_x,
        "period_y": score.grid.period_y,
        "grid_confidence": score.grid_confidence,
        "fallback": score.fallback,
    }
    return score, diag


def analyze(rgb: np.ndarray, params: PipelineParams | None = None) -> tuple[GridScore, dict]:
    """Detect the grid and report it *without* producing a final image.

    Returns ``(GridScore, diagnostics)`` — feeds the web UI's "what did you
    find?" panel and confidence heatmap before the user commits.
    """
    params = (params or PipelineParams()).validate()
    clean = denoise(rgb, params.denoise_strength)
    return _select(clean, params)


def restore(rgb: np.ndarray, params: PipelineParams | None = None) -> PipelineResult:
    """Full restoration: returns the pixel-perfect native image + diagnostics."""
    params = (params or PipelineParams()).validate()
    clean = denoise(rgb, params.denoise_strength)
    score, diag = _select(clean, params)

    # Selection already collapsed the winning grid with these exact parameters.
    field = score.field

    pal = None
    if params.palette_name:
        pal = _palette.BUILTIN_PALETTES.get(params.palette_name)
    field, pal = _palette.quantize(
        field,
        max_colors=params.palette_size,
        palette=pal,
        merge_threshold=params.merge_threshold,
    )

    native = _compose_rgba(field)
    factor = clamp_upscale(native.shape[1], native.shape[0], params.upscale)
    preview = upscale(native, factor) if factor > 1 else None

    return PipelineResult(
        native=native,
        palette=pal,
        score=score,
        nx=score.grid.nx,
        ny=score.grid.ny,
        preview=preview,
        candidates=diag,
    )


def _compose_rgba(field: CellField) -> np.ndarray:
    if field.alpha is None:
        return field.rgb
    out = np.dstack([field.rgb, field.alpha])
    return out.astype(np.uint8)


def upscale(arr: np.ndarray, factor: int) -> np.ndarray:
    """Exact integer nearest-neighbor upscale (no interpolation, ever)."""
    factor = int(factor)
    if factor <= 1:
        return arr
    return np.repeat(np.repeat(arr, factor, axis=0), factor, axis=1)


def to_rgba(arr: np.ndarray) -> np.ndarray:
    """Ensure a 4-channel uint8 array for consistent PNG output."""
    a = np.asarray(arr)
    if a.shape[-1] == 4:
        return a.astype(np.uint8)
    alpha = np.full(a.shape[:2] + (1,), 255, dtype=np.uint8)
    return np.concatenate([a.astype(np.uint8), alpha], axis=-1)
