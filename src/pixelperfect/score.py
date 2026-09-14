"""Reconstruction-residual scoring — how we know the grid is right.

The core insight: a candidate grid is good if collapsing the image onto it and
then *re-rendering* (nearest-neighbor, back into the original warped cell
layout) reproduces the source. The best grid is the one under which the source
is most explainable as damaged pixel art. This dominates pure edge-energy
metrics on images with smooth gradients between similar-colored cells, where
there's little edge to lock onto but the per-cell-flat assumption still holds.

The same residual gives us:
* a **global confidence** score for the result (how well the output explains
  the source),
* a separate **grid confidence** (how much periodic edge structure supports
  the chosen cell size — near zero for noise or photos, zero when no period was
  found and a default grid had to be used), and
* a **per-cell heatmap** that flags exactly which cells are ambiguous (bimodal
  cells, mislocated boundaries) so the UI can show the user where to nudge.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import color as _color
from .grid import COMMON_SIZES, GridResult, fit_gridlines, gradient_profiles, periodicity
from .sample import CellField, _as_u8, collapse, gather_cells

__all__ = ["GridScore", "reconstruction_residual", "select_grid"]

# OKLab residual at/above which a cell is considered badly explained. ~0.10 is
# a clearly visible perceptual error; we map [0, this] -> confidence [1, 0].
_RESIDUAL_BAD = 0.10

# Mean edge-profile autocorrelation at the chosen period that counts as fully
# periodic. Measured: real (damaged) pixel art 0.42-0.85, random noise ~0.03,
# flat images 0. Residual separation between candidates was tried first and
# rejected: on sprites with large flat backgrounds an off-by-one grid explains
# the image almost equally well, so separation reads ~0 on correct results.
_PERIODICITY_FULL = 0.4


@dataclass
class GridScore:
    grid: GridResult
    field: CellField
    residual: float  # robust global OKLab residual (lower = better)
    per_cell: np.ndarray  # (ny, nx) mean OKLab residual per cell
    confidence: float  # 0..1, higher = better
    grid_confidence: float | None = None  # 0..1; None when the size was forced
    fallback: bool = False  # True if no period was detected (default grid used)

    def confidence_map(self) -> np.ndarray:
        """``(ny, nx)`` uint8 confidence heatmap (255 = perfect cell)."""
        conf = np.clip(1.0 - self.per_cell / _RESIDUAL_BAD, 0.0, 1.0)
        return np.round(conf * 255).astype(np.uint8)


def reconstruction_residual(
    source_rgb: np.ndarray,
    grid: GridResult,
    field: CellField,
    interior_frac: float = 0.5,
    src_lab: np.ndarray | None = None,
    alpha_threshold: int = 128,
) -> tuple[float, np.ndarray]:
    """Compare the cell color to the source over each cell's eroded interior.

    Scoring the *interior* (not the full cell) is what makes this usable for
    choosing N: a too-fine grid has interiors that straddle the true cell
    edges, so its interior residual stays high instead of dropping as cells
    shrink. The AA rim is excluded so it can't inflate the residual of a
    correctly-detected grid.

    With an alpha channel, a pixel whose opacity disagrees with its cell costs
    :data:`_RESIDUAL_BAD`, and pixels transparent in both cost nothing — so the
    hidden RGB under transparent pixels never influences the score, and an
    alpha-only silhouette still scores its grid.

    Returns ``(global_residual, per_cell_residual)`` in OKLab units.
    """
    arr = _as_u8(source_rgb)
    if src_lab is None:
        src_lab = _color.srgb_to_oklab(arr[..., :3])
    cell_lab = _color.srgb_to_oklab(field.rgb)  # (ny, nx, 3)

    blocks, valid = gather_cells(src_lab, grid, interior_frac)
    d = np.sqrt(np.sum((blocks - cell_lab[:, :, None, :]) ** 2, axis=-1))  # (ny, nx, K)

    if arr.shape[2] == 4 and field.alpha is not None:
        a_blocks, _ = gather_cells(arr[..., 3], grid, interior_frac)
        px_opaque = a_blocks[..., 0] >= alpha_threshold
        cell_opaque = (field.alpha >= alpha_threshold)[:, :, None]
        d = np.where(px_opaque & cell_opaque, d, 0.0)
        d = np.where(px_opaque != cell_opaque, _RESIDUAL_BAD, d)

    cnt = valid.sum(axis=2)
    safe = np.maximum(cnt, 1)
    dv = np.where(valid, d, 0.0)
    mean = dv.sum(axis=2) / safe
    var = np.maximum((dv * dv).sum(axis=2) / safe - mean * mean, 0.0)
    # Mean captures bias; the cell's internal spread captures "straddling two
    # true colors", the signature of a misplaced/too-fine grid.
    per_cell = np.where(cnt > 0, mean + 0.5 * np.sqrt(var), 0.0)

    weights = cnt.astype(np.float64)
    if weights.sum() == 0:
        return float("inf"), per_cell
    # Area-weighted mean for a fair global number, but blend in the 90th
    # percentile so a few catastrophic cells (wrong grid) are penalized.
    flat = per_cell.reshape(-1)
    w = weights.reshape(-1)
    mean_res = float(np.average(flat, weights=w))
    p90 = float(np.percentile(flat[w > 0], 90))
    return 0.7 * mean_res + 0.3 * p90, per_cell


def _is_subdivision(fine: GridScore, coarse: GridScore) -> bool:
    """True if ``fine`` splits every cell of ``coarse`` into an integer sub-grid."""
    f, c = fine.grid, coarse.grid
    return (
        (f.nx, f.ny) != (c.nx, c.ny)
        and f.nx % c.nx == 0
        and f.ny % c.ny == 0
    )


def select_grid(
    rgb: np.ndarray,
    x_candidates: list[int],
    y_candidates: list[int],
    *,
    top_k: int = 4,
    interior_frac: float = 0.5,
    method: str = "median",
    fit_kwargs: dict | None = None,
) -> GridScore:
    """Pick the best ``(nx, ny)`` by reconstruction residual.

    Tries the top ``top_k`` candidates from each axis (already ranked best-first
    by :func:`~pixelperfect.grid.candidate_cell_counts`), fits + collapses +
    scores each combination, and returns the winner with its confidence. The
    image's OKLab conversion, edge profiles, and per-axis gridline fits are
    computed once and shared across combinations.
    """
    fit_kwargs = fit_kwargs or {}
    arr = _as_u8(rgb)
    h, w = arr.shape[:2]
    lab = _color.srgb_to_oklab(arr[..., :3])
    prof_x, prof_y = gradient_profiles(arr, lab)

    fallback = not x_candidates or not y_candidates
    k = max(1, int(top_k))
    xs = (x_candidates or [16])[:k]
    ys = (y_candidates or [16])[:k]
    x_fits = {nx: fit_gridlines(prof_x, nx, w, **fit_kwargs) for nx in xs}
    y_fits = {ny: fit_gridlines(prof_y, ny, h, **fit_kwargs) for ny in ys}

    scored: list[GridScore] = []
    for nx in xs:
        for ny in ys:
            grid = GridResult(x_fits[nx], y_fits[ny], int(nx), int(ny), w / nx, h / ny)
            field = collapse(arr, grid, interior_frac=interior_frac, method=method, lab=lab)
            residual, per_cell = reconstruction_residual(
                arr, grid, field, interior_frac=interior_frac, src_lab=lab
            )
            conf = float(np.clip(1.0 - residual / _RESIDUAL_BAD, 0.0, 1.0))
            scored.append(GridScore(grid, field, residual, per_cell, conf, fallback=fallback))

    best_res = min(s.residual for s in scored)
    # The candidate set is kept tight around the autocorrelation period
    # estimate, so the true N shows up as the minimum-residual local elbow
    # (residual would resume falling for much finer grids that overfit, but
    # those are never proposed). We therefore take the minimum residual, using
    # only a tiny *relative* tolerance (plus a noise-level floor) to break
    # near-exact ties. An absolute floor comparable to a clean image's residual
    # would let a clearly worse grid count as "tied".
    tol = best_res * 0.02 + 1e-4
    ok = [s for s in scored if s.residual <= best_res + tol]
    # An exact subdivision of a tied grid explains the image equally well by
    # construction (its interiors never straddle a true edge); prefer the coarser.
    ok = [s for s in ok if not any(_is_subdivision(s, t) for t in ok)]

    def tiebreak(s: GridScore):
        common = -((s.grid.nx in COMMON_SIZES) + (s.grid.ny in COMMON_SIZES))
        return (common, s.grid.nx + s.grid.ny)

    ok.sort(key=lambda s: (tiebreak(s), s.residual))
    chosen = ok[0]
    if fallback:
        chosen.grid_confidence = 0.0
    elif len(xs) == 1 and len(ys) == 1:
        chosen.grid_confidence = None  # size was forced; nothing was detected
    else:
        evidence = 0.5 * (
            periodicity(prof_x, w / chosen.grid.nx) + periodicity(prof_y, h / chosen.grid.ny)
        )
        chosen.grid_confidence = float(np.clip(evidence / _PERIODICITY_FULL, 0.0, 1.0))
    return chosen
