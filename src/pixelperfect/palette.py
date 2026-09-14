"""Palette derivation and snapping — done AFTER cells are collapsed.

Quantizing before grid collapse wastes palette slots on anti-aliasing
gray-tones. Working on the already-collapsed cell colors instead, the palette
falls out cleanly:

1. **Auto color count** — agglomerative merge of cell colors in OKLab using a
   perceptual ΔE threshold, so near-identical colors fuse and the natural
   palette size emerges.
2. **Optional cap** — if the user asks for at most K colors and there are more,
   k-means in OKLab reduces to K, then each centroid is **snapped to an actual
   cell color (medoid)** so no invented colors enter a "pixel-perfect" result.
3. **Named palettes** — alternatively snap to a fixed art palette (Lospec-style)
   via nearest-neighbor in OKLab.

Dithering is intentionally never applied: it scatters lone pixels that violate
the clean-cluster rule pixel art requires.
"""

from __future__ import annotations

import numpy as np

from . import color as _color
from .sample import CellField

__all__ = ["build_palette", "apply_palette", "quantize", "BUILTIN_PALETTES", "hex_to_rgb"]


def hex_to_rgb(hexes: list[str]) -> np.ndarray:
    """``['#1a1c2c', ...]`` -> ``(K, 3)`` uint8."""
    out = []
    for h in hexes:
        h = h.lstrip("#")
        out.append([int(h[i : i + 2], 16) for i in (0, 2, 4)])
    return np.array(out, dtype=np.uint8)


# A few well-known Lospec palettes for "snap to this palette" mode.
BUILTIN_PALETTES: dict[str, np.ndarray] = {
    "sweetie-16": hex_to_rgb(
        [
            "1a1c2c", "5d275d", "b13e53", "ef7d57", "ffcd75", "a7f070", "38b764", "257179",
            "29366f", "3b5dc9", "41a6f6", "73eff7", "f4f4f4", "94b0c2", "566c86", "333c57",
        ]
    ),
    "pico-8": hex_to_rgb(
        [
            "000000", "1d2b53", "7e2553", "008751", "ab5236", "5f574f", "c2c3c7", "fff1e8",
            "ff004d", "ffa300", "ffec27", "00e436", "29adff", "83769c", "ff77a8", "ffccaa",
        ]
    ),
    "endesga-32": hex_to_rgb(
        [
            "be4a2f", "d77643", "ead4aa", "e4a672", "b86f50", "733e39", "3e2731", "a22633",
            "e43b44", "f77622", "feae34", "fee761", "63c74d", "3e8948", "265c42", "193c3e",
            "124e89", "0099db", "2ce8f5", "ffffff", "c0cbdc", "8b9bb4", "5a6988", "3a4466",
            "262b44", "181425", "ff0044", "68386c", "b55088", "f6757a", "e8b796", "c28569",
        ]
    ),
}


def _cell_colors_and_weights(field: CellField) -> tuple[np.ndarray, np.ndarray]:
    """Unique cell colors (uint8 ``(M,3)``) and their occurrence counts.

    Transparent cells are excluded so they don't claim a palette slot.
    """
    rgb = field.rgb.reshape(-1, 3)
    if field.alpha is not None:
        mask = field.alpha.reshape(-1) >= 128
        rgb = rgb[mask]
    if rgb.shape[0] == 0:
        return np.zeros((0, 3), np.uint8), np.zeros((0,), int)
    uniq, counts = np.unique(rgb, axis=0, return_counts=True)
    return uniq.astype(np.uint8), counts


def build_palette(
    field: CellField,
    max_colors: int | None = None,
    merge_threshold: float = 0.035,
) -> np.ndarray:
    """Derive a palette (``(K, 3)`` uint8) from collapsed cell colors.

    ``merge_threshold`` is the OKLab ΔE below which colors are fused (auto count).
    ``max_colors`` optionally caps the result via k-means + medoid snapping.
    """
    colors, counts = _cell_colors_and_weights(field)
    if colors.shape[0] == 0:
        return np.zeros((0, 3), np.uint8)
    if colors.shape[0] == 1:
        return colors

    # Agglomerative clustering is O(M^2) in memory; a photo-sized input can have
    # tens of thousands of unique colors. Pre-merge perceptually identical
    # colors (well under the merge threshold) so clustering stays bounded.
    if colors.shape[0] > _MAX_CLUSTER_COLORS:
        colors, counts = _prereduce(colors, counts, merge_threshold, _MAX_CLUSTER_COLORS)

    lab = _color.srgb_to_oklab(colors)
    labels = _agglomerative(lab, merge_threshold)
    palette = _reps_nearest_center(colors, lab, labels, counts)

    if max_colors is not None and palette.shape[0] > max_colors:
        palette = _kmeans_reduce(colors, counts, max_colors)
    return palette


# Upper bound on colors fed to agglomerative clustering (memory ~ M^2 / 2 floats).
_MAX_CLUSTER_COLORS = 2048


def _prereduce(
    colors: np.ndarray, counts: np.ndarray, merge_threshold: float, limit: int
) -> tuple[np.ndarray, np.ndarray]:
    """Collapse a huge unique-color set to at most ``limit`` weighted colors.

    First buckets colors on an OKLab lattice finer than the merge threshold (so
    only colors that would fuse anyway are combined), then, if that is still
    too many, runs weighted k-means straight to ``limit``. Each bucket keeps a
    real member color, so no invented colors enter the palette.
    """
    lab = _color.srgb_to_oklab(colors)
    step = max(merge_threshold / 2.0, 1e-3)
    keys = np.round(lab / step).astype(np.int64)
    _, labels = np.unique(keys, axis=0, return_inverse=True)
    labels = labels.reshape(-1)
    if labels.max() + 1 > limit:
        from sklearn.cluster import MiniBatchKMeans

        km = MiniBatchKMeans(n_clusters=limit, n_init=1, random_state=0, batch_size=4096)
        labels = km.fit_predict(lab, sample_weight=counts.astype(float))
    reps = _reps_nearest_center(colors, lab, labels, counts)
    rep_counts = np.bincount(np.unique(labels, return_inverse=True)[1].reshape(-1), weights=counts)
    return reps, rep_counts.astype(int)


def _agglomerative(lab: np.ndarray, threshold: float) -> np.ndarray:
    """Merge colors within ``threshold`` OKLab distance. Returns cluster labels."""
    if lab.shape[0] <= 1:
        return np.zeros(lab.shape[0], dtype=int)
    from sklearn.cluster import AgglomerativeClustering

    model = AgglomerativeClustering(
        n_clusters=None, distance_threshold=threshold, linkage="average"
    )
    return model.fit_predict(lab)


def _reps_nearest_center(
    colors: np.ndarray, lab: np.ndarray, labels: np.ndarray, counts: np.ndarray
) -> np.ndarray:
    """Per cluster, pick the real member color nearest the weighted OKLab center.

    Choosing by frequency alone lets a noisy variant on the cluster's edge win
    just because it occurs twice; the weighted center is robust to that, and
    snapping to a member keeps the palette free of invented colors. Ordered by
    label so results are deterministic.
    """
    labels = np.asarray(labels).reshape(-1)
    w = counts.astype(np.float64)
    reps = []
    for lbl in np.unique(labels):
        members = np.flatnonzero(labels == lbl)
        center = np.average(lab[members], axis=0, weights=w[members])
        d = np.sum((lab[members] - center) ** 2, axis=1)
        # Tie-break toward the more frequent color.
        order = np.lexsort((-w[members], d))
        reps.append(colors[members[order[0]]])
    return np.array(reps, dtype=np.uint8)


def _kmeans_reduce(colors: np.ndarray, counts: np.ndarray, k: int) -> np.ndarray:
    """k-means in OKLab (frequency-weighted) then snap centroids to real colors."""
    from sklearn.cluster import KMeans

    lab = _color.srgb_to_oklab(colors)
    k = min(k, colors.shape[0])
    km = KMeans(n_clusters=k, n_init=4, random_state=0)
    labels = km.fit_predict(lab, sample_weight=counts.astype(float))
    return _reps_nearest_center(colors, lab, labels, counts)


def apply_palette(field: CellField, palette: np.ndarray) -> CellField:
    """Snap every cell color to its nearest palette entry (OKLab)."""
    if palette.shape[0] == 0:
        return field
    lab_cells = _color.srgb_to_oklab(field.rgb).reshape(-1, 3)
    lab_pal = _color.srgb_to_oklab(palette)
    idx = _color.nearest_color(lab_cells, lab_pal)
    snapped = palette[idx].reshape(field.rgb.shape).astype(np.uint8)
    return CellField(snapped, field.alpha)


def quantize(
    field: CellField,
    max_colors: int | None = None,
    palette: np.ndarray | None = None,
    merge_threshold: float = 0.035,
) -> tuple[CellField, np.ndarray]:
    """Build (or accept) a palette and snap the field to it.

    Returns ``(new_field, palette)``.
    """
    if palette is None:
        palette = build_palette(field, max_colors=max_colors, merge_threshold=merge_threshold)
    return apply_palette(field, palette), palette
