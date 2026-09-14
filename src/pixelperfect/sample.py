"""Collapse each grid cell down to a single representative color.

Once the grid is known, every cell must become exactly one color. The trap is
anti-aliasing: a cell's border pixels are blends with its neighbors, so a naive
mean drags the color toward the average of the sprite. Two defenses:

* **Eroded interior** — only the central fraction of each cell votes, discarding
  the AA-contaminated rim.
* **Robust statistic in OKLab** — channel-wise median (default) or modal exact
  color, computed perceptually, so a few stray blend pixels can't shift the
  result the way a mean would.

Transparent source pixels never vote for an opaque cell's color, so whatever
RGB happens to sit under alpha=0 cannot leak into the result.

Output is a small ``(ny, nx, 3)`` color array (the true native-resolution
image) plus an optional alpha plane for cut-out sprites.
"""

from __future__ import annotations

import numpy as np

from . import color as _color
from .grid import GridResult

__all__ = ["collapse", "CellField", "inset_span", "gather_cells"]


class CellField:
    """Native-resolution result of collapsing a grid.

    Attributes
    ----------
    rgb : ``(ny, nx, 3)`` uint8 — one color per cell.
    alpha : ``(ny, nx)`` uint8 or ``None`` — per-cell opacity (cut-out sprites).
    """

    def __init__(self, rgb: np.ndarray, alpha: np.ndarray | None = None):
        self.rgb = rgb
        self.alpha = alpha

    @property
    def shape(self):
        return self.rgb.shape[:2]


def _representative(lab_pixels: np.ndarray, method: str) -> np.ndarray:
    """Return one OKLab color summarizing a set of OKLab pixels."""
    if lab_pixels.shape[0] == 0:
        return np.zeros(3)
    if method == "mean":
        return lab_pixels.mean(axis=0)
    if method == "mode":
        # Quantize finely and take the most common bucket's mean — exact-ish
        # modal color, good when cells are already nearly flat.
        q = np.round(lab_pixels * 64).astype(np.int64)
        _, inv, counts = np.unique(q, axis=0, return_inverse=True, return_counts=True)
        winner = int(np.argmax(counts))
        return lab_pixels[inv.reshape(-1) == winner].mean(axis=0)
    if method == "medoid":
        # Actual pixel minimizing summed distance to the rest (no invented
        # color). Subsample for speed on large cells.
        pts = lab_pixels
        if pts.shape[0] > 256:
            idx = np.linspace(0, pts.shape[0] - 1, 256).astype(int)
            pts = pts[idx]
        d = (
            np.sum(pts**2, axis=1)[:, None]
            - 2 * pts @ pts.T
            + np.sum(pts**2, axis=1)[None, :]
        )
        return pts[int(np.argmin(d.sum(axis=1)))]
    # default: channel-wise median in OKLab — robust and cheap.
    return np.median(lab_pixels, axis=0)


def _spans(bounds: np.ndarray, frac: float) -> tuple[np.ndarray, np.ndarray]:
    """Interior ``[lo, hi)`` per cell along one axis (full cell if erosion empties it)."""
    b = np.round(bounds).astype(int)
    lo = np.empty(b.size - 1, dtype=int)
    hi = np.empty(b.size - 1, dtype=int)
    for i in range(b.size - 1):
        lo[i], hi[i] = inset_span(int(b[i]), int(b[i + 1]), frac)
    return lo, hi


def gather_cells(
    arr: np.ndarray, grid: GridResult, interior_frac: float
) -> tuple[np.ndarray, np.ndarray]:
    """Gather each cell's interior pixels into a padded block, vectorized.

    Returns ``(blocks, valid)``: ``blocks`` is ``(ny, nx, K, C)`` (``K`` = the
    largest interior pixel count), ``valid`` the ``(ny, nx, K)`` mask of real
    (non-padding) pixels. Replaces a per-cell Python loop, which dominated
    runtime when many candidate grids are scored.
    """
    a = arr if arr.ndim == 3 else arr[..., None]
    ylo, yhi = _spans(grid.y_bounds, interior_frac)
    xlo, xhi = _spans(grid.x_bounds, interior_frac)
    ky = max(1, int((yhi - ylo).max(initial=1)))
    kx = max(1, int((xhi - xlo).max(initial=1)))
    h, w = a.shape[:2]
    oy = np.arange(ky)
    ox = np.arange(kx)
    rows = ylo[:, None] + oy[None, :]  # (ny, ky)
    cols = xlo[:, None] + ox[None, :]  # (nx, kx)
    rvalid = (oy[None, :] < (yhi - ylo)[:, None]) & (rows < h)
    cvalid = (ox[None, :] < (xhi - xlo)[:, None]) & (cols < w)
    rows = np.clip(rows, 0, h - 1)
    cols = np.clip(cols, 0, w - 1)
    blk = a[rows[:, :, None, None], cols[None, None, :, :]]  # (ny, ky, nx, kx, C)
    blk = blk.transpose(0, 2, 1, 3, 4)
    ny, nx = grid.ny, grid.nx
    blocks = blk.reshape(ny, nx, ky * kx, a.shape[-1])
    valid = (rvalid[:, None, :, None] & cvalid[None, :, None, :]).reshape(ny, nx, ky * kx)
    return blocks, valid


def collapse(
    rgb: np.ndarray,
    grid: GridResult,
    interior_frac: float = 0.5,
    method: str = "median",
    alpha_threshold: int = 128,
    lab: np.ndarray | None = None,
) -> CellField:
    """Reduce ``rgb`` to one color per grid cell.

    Parameters
    ----------
    rgb : ``(H, W, 3)`` or ``(H, W, 4)`` image (uint8 or float).
    grid : fitted :class:`~pixelperfect.grid.GridResult`.
    interior_frac : fraction of each cell (centered) that votes; the rest
        (the AA rim) is ignored.
    method : ``"median"`` | ``"mode"`` | ``"medoid"`` | ``"mean"``.
    alpha_threshold : if an alpha channel is present, cells whose median alpha
        is below this become fully transparent, and pixels below it never vote
        for an opaque cell's color.
    lab : optional precomputed OKLab of ``rgb[..., :3]`` (saves a conversion).
    """
    arr = _as_u8(rgb)
    has_alpha = arr.shape[2] == 4
    if lab is None:
        lab = _color.srgb_to_oklab(arr[..., :3])

    blocks, valid = gather_cells(lab, grid, interior_frac)  # (ny, nx, K, 3)
    vote = valid
    out_alpha = None
    if has_alpha:
        a_blocks, _ = gather_cells(arr[..., 3], grid, interior_frac)
        a_blocks = a_blocks[..., 0].astype(np.float64)
        a_med = np.nanmedian(np.where(valid, a_blocks, np.nan), axis=2)
        a_med = np.nan_to_num(a_med, nan=0.0)
        out_alpha = np.where(np.floor(a_med) < alpha_threshold, 0, 255).astype(np.uint8)
        opaque = valid & (a_blocks >= alpha_threshold)
        # Opaque cells: only opaque pixels vote. Transparent cells: prefer
        # opaque pixels for a plausible hidden color, else anything valid.
        has_opaque = opaque.any(axis=2)
        vote = np.where(has_opaque[..., None], opaque, valid)

    n_vote = vote.sum(axis=2)
    if method in ("median", "mean"):
        masked = np.where(vote[..., None], blocks, np.nan)
        with np.errstate(all="ignore"):
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                rep = (
                    np.nanmedian(masked, axis=2) if method == "median" else np.nanmean(masked, axis=2)
                )
        rep = np.nan_to_num(rep, nan=0.0)
    else:
        rep = np.zeros((grid.ny, grid.nx, 3))
        for r in range(grid.ny):
            for c in range(grid.nx):
                rep[r, c] = _representative(blocks[r, c][vote[r, c]], method)
    rep[n_vote == 0] = 0.0

    out_rgb = np.round(_color.oklab_to_srgb(rep) * 255).astype(np.uint8)
    return CellField(out_rgb, out_alpha)


def _as_u8(rgb: np.ndarray) -> np.ndarray:
    """Coerce to an ``(H, W, 3|4)`` uint8 array (grayscale is expanded to RGB)."""
    arr = np.asarray(rgb)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.dtype != np.uint8:
        arr = np.clip(arr * (255 if arr.max() <= 1.0 else 1), 0, 255).astype(np.uint8)
    return arr


def inset_span(a: int, b: int, frac: float) -> tuple[int, int]:
    """Centered interior span of ``[a, b)`` keeping ``frac`` of the length."""
    size = b - a
    if size <= 2:
        return a, b
    inset = int(round((1.0 - frac) / 2.0 * size))
    lo, hi = a + inset, b - inset
    if hi <= lo:
        return a, b
    return lo, hi
