"""Color-space conversions and perceptual distance.

Pixel-art restoration lives or dies on *perceptual* color decisions: which
colors count as "the same", which cell color best represents a block, how to
collapse a palette. RGB Euclidean distance is a poor proxy for that, so the
whole pipeline works in OKLab, a modern perceptually-uniform space where
plain Euclidean distance approximates perceived difference well.

All functions operate on float arrays in [0, 1] unless noted, and accept
arrays of any leading shape (``(..., 3)``) so they vectorize over images and
over flat lists of colors alike.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "srgb_to_linear",
    "linear_to_srgb",
    "srgb_to_oklab",
    "oklab_to_srgb",
    "delta_e",
    "nearest_color",
]


def _as_float(rgb: np.ndarray) -> np.ndarray:
    """Coerce uint8 [0,255] or float [0,1] RGB into float64 [0,1]."""
    arr = np.asarray(rgb)
    if arr.dtype == np.uint8 or arr.max(initial=0) > 1.0:
        arr = arr.astype(np.float64) / 255.0
    return arr.astype(np.float64, copy=False)


def srgb_to_linear(srgb: np.ndarray) -> np.ndarray:
    """sRGB (gamma-encoded, [0,1]) -> linear-light RGB."""
    s = np.clip(_as_float(srgb), 0.0, 1.0)
    return np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(linear: np.ndarray) -> np.ndarray:
    """Linear-light RGB -> sRGB (gamma-encoded, [0,1])."""
    lin = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)


# Linear-sRGB -> LMS, and LMS' -> OKLab matrices (Björn Ottosson, 2020).
_M1 = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
_M2 = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
_M1_INV = np.linalg.inv(_M1)
_M2_INV = np.linalg.inv(_M2)


def srgb_to_oklab(srgb: np.ndarray) -> np.ndarray:
    """sRGB ([0,1] or uint8) -> OKLab. Shape ``(..., 3)`` preserved."""
    lin = srgb_to_linear(srgb)
    lms = lin @ _M1.T
    lms_ = np.cbrt(lms)
    return lms_ @ _M2.T


def oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    """OKLab -> sRGB ([0,1], clipped). Shape ``(..., 3)`` preserved."""
    lab = np.asarray(lab, dtype=np.float64)
    lms_ = lab @ _M2_INV.T
    lms = lms_ ** 3
    lin = lms @ _M1_INV.T
    return np.clip(linear_to_srgb(lin), 0.0, 1.0)


def delta_e(lab_a: np.ndarray, lab_b: np.ndarray) -> np.ndarray:
    """Perceptual distance between two OKLab colors/arrays (Euclidean in OKLab).

    Broadcasts over leading dimensions; reduces the final length-3 axis.
    """
    a = np.asarray(lab_a, dtype=np.float64)
    b = np.asarray(lab_b, dtype=np.float64)
    return np.sqrt(np.sum((a - b) ** 2, axis=-1))


def nearest_color(lab_colors: np.ndarray, lab_palette: np.ndarray) -> np.ndarray:
    """Index of the nearest palette entry (OKLab) for each input color.

    Parameters
    ----------
    lab_colors : ``(N, 3)`` OKLab colors to snap.
    lab_palette : ``(K, 3)`` OKLab palette.

    Returns
    -------
    ``(N,)`` int array of palette indices.
    """
    colors = np.asarray(lab_colors, dtype=np.float64).reshape(-1, 3)
    palette = np.asarray(lab_palette, dtype=np.float64).reshape(-1, 3)
    if palette.shape[0] == 0:
        return np.zeros(colors.shape[0], dtype=int)
    # (N, K) pairwise squared distances without forming the full diff tensor,
    # chunked so a multi-megapixel input never allocates N x K at once.
    pal_sq = np.sum(palette**2, axis=1)[None, :]
    out = np.empty(colors.shape[0], dtype=np.intp)
    chunk = max(1, _CHUNK_ELEMS // palette.shape[0])
    for i in range(0, colors.shape[0], chunk):
        c = colors[i : i + chunk]
        d = np.sum(c**2, axis=1)[:, None] - 2.0 * c @ palette.T + pal_sq
        out[i : i + chunk] = np.argmin(d, axis=1)
    return out


# Max elements in one distance block (~32 MB of float64).
_CHUNK_ELEMS = 4_000_000
