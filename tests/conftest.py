"""Shared test fixtures: a synthetic-distortion generator.

We can't rely on real AI exports in CI, so we manufacture ground-truth pixel
art and then *damage* it the way an AI generator does — block-fill at a
non-constant cell pitch (drift), Gaussian blur (VAE/AA), additive noise, and a
JPEG round-trip. The pipeline must recover the original grid and a perceptually
matching palette. This gives the tests something exact to assert against.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from pixelperfect.color import nearest_color, srgb_to_oklab

_PALETTE = np.array(
    [
        [26, 28, 44], [177, 62, 83], [239, 125, 87], [255, 205, 117],
        [167, 240, 112], [56, 183, 100], [65, 166, 246], [244, 244, 244],
        [148, 176, 194], [51, 60, 87], [255, 0, 77], [255, 163, 0],
    ],
    dtype=np.uint8,
)


def make_native(seed: int, nx: int, ny: int, ncolors: int) -> np.ndarray:
    """A clean ground-truth sprite: ``(ny, nx, 3)`` uint8 from a small palette."""
    rng = np.random.default_rng(seed)
    pal = _PALETTE[:ncolors]
    idx = rng.integers(0, len(pal), size=(ny, nx))
    return pal[idx].astype(np.uint8)


def distort(
    native: np.ndarray,
    *,
    seed: int = 0,
    avg_cell: int = 28,
    drift: float = 0.1,
    blur: float = 1.0,
    noise: float = 3.0,
    jpeg: int = 85,
) -> np.ndarray:
    """Damage a clean sprite like an AI generator would (drift + blur + jpeg)."""
    ny, nx = native.shape[:2]
    rng = np.random.default_rng(seed + 1000)
    cw = np.round(avg_cell * (1 + drift * rng.uniform(-1, 1, nx))).astype(int).clip(3)
    ch = np.round(avg_cell * (1 + drift * rng.uniform(-1, 1, ny))).astype(int).clip(3)
    xb = np.concatenate([[0], np.cumsum(cw)])
    yb = np.concatenate([[0], np.cumsum(ch)])
    big = np.zeros((int(yb[-1]), int(xb[-1]), 3), np.uint8)
    for r in range(ny):
        for c in range(nx):
            big[yb[r]:yb[r + 1], xb[c]:xb[c + 1]] = native[r, c]
    if blur:
        big = cv2.GaussianBlur(big, (0, 0), blur)
    if noise:
        big = np.clip(big + rng.normal(0, noise, big.shape), 0, 255).astype(np.uint8)
    if jpeg:
        ok, enc = cv2.imencode(
            ".jpg", cv2.cvtColor(big, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), jpeg]
        )
        big = cv2.cvtColor(cv2.imdecode(enc, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    return big


@pytest.fixture
def synth():
    """Return ``(make_native, distort)`` helpers to tests."""
    return make_native, distort


# --- thin-feature sprites + cell-label metrics ------------------------------
# Reusable harness for evaluating collapse accuracy on the structures that are
# hardest to recover (1px lines, tapering tips, diagonals, isolated pixels,
# multi-class overlaps). Kept for future edge-accuracy work.

# A small deliberate palette: background + four object classes.
THIN_PALETTE = np.array(
    [
        [244, 244, 244],  # 0 background
        [56, 183, 100],   # 1 body
        [65, 166, 246],   # 2 cape
        [26, 28, 44],     # 3 outline/dark
        [255, 205, 117],  # 4 accent
    ],
    dtype=np.uint8,
)
THIN_BG_INDEX = 0


def make_thin_sprite(nx: int = 48, ny: int = 48) -> np.ndarray:
    """A clean sprite full of the features that break per-cell collapse.

    Contains: a solid body, a 1px vertical line, a 1px diagonal, a cape that
    tapers to a 1px tip (the over-extension case), and isolated single pixels.
    Returns ``(ny, nx, 3)`` uint8. Use with :data:`THIN_PALETTE`.
    """
    P = THIN_PALETTE
    img = np.tile(P[0], (ny, nx, 1)).astype(np.uint8)

    def put(yy, xx, ci):
        if 0 <= yy < ny and 0 <= xx < nx:
            img[yy, xx] = P[ci]

    # Solid body block.
    img[14:38, 20:32] = P[1]
    # 1px vertical line (thin feature on background).
    for y in range(6, 42):
        put(y, 8, 3)
    # 1px diagonal line.
    for k in range(0, 28):
        put(6 + k, 36 + k // 2, 3)
    # Cape: triangle left of the body, tapering to a 1px tip at the bottom.
    for r in range(14, 41):
        w = max(1, (40 - r) // 3)
        for x in range(16 - w, 16):
            put(r, x, 2)
    # Accent buckle on the body.
    img[24:26, 25:27] = P[4]
    # Isolated single pixels.
    for (yy, xx, ci) in [(4, 4, 3), (44, 44, 4), (3, 44, 2), (45, 6, 1)]:
        put(yy, xx, ci)
    return img


def cell_labels(rgb: np.ndarray, palette: np.ndarray = THIN_PALETTE) -> np.ndarray:
    """Label each cell by its nearest palette index (OKLab). Shape ``(ny, nx)``."""
    lab = srgb_to_oklab(rgb[..., :3]).reshape(-1, 3)
    idx = nearest_color(lab, srgb_to_oklab(palette))
    return idx.reshape(rgb.shape[:2])


def thin_metrics(
    gt_rgb: np.ndarray,
    rec_rgb: np.ndarray,
    palette: np.ndarray = THIN_PALETTE,
    bg_index: int = THIN_BG_INDEX,
) -> dict:
    """Compare a recovered sprite to ground truth at the cell-label level.

    - ``false_thicken``: fraction of true-background cells painted foreground.
    - ``false_erode``: fraction of true-foreground cells dropped to background.
    - ``exact``: fraction of cells whose class label matches.
    """
    gt = cell_labels(gt_rgb, palette)
    rec = cell_labels(rec_rgb, palette)
    gt_fg = gt != bg_index
    rec_fg = rec != bg_index
    n_bg = int((~gt_fg).sum())
    n_fg = int(gt_fg.sum())
    return {
        "false_thicken": float((rec_fg & ~gt_fg).sum()) / max(1, n_bg),
        "false_erode": float((~rec_fg & gt_fg).sum()) / max(1, n_fg),
        "exact": float((gt == rec).mean()),
    }


@pytest.fixture
def thin():
    """Return ``(make_thin_sprite, distort, thin_metrics, THIN_PALETTE)``."""
    return make_thin_sprite, distort, thin_metrics, THIN_PALETTE
