"""Pixel-grid recovery: the crux of the tool.

An AI "pixel-art" image is a small logical grid that has been upscaled by a
*non-constant* factor and blurred, so the cell boundaries no longer sit on a
clean integer lattice. We recover, per axis:

1. the **period** (average cell size in source pixels) — via autocorrelation of
   the edge-projection profile, refined to sub-pixel precision from several
   harmonics, with an FFT estimate as a cross-check;
2. the **cell count N** — ``length / period``, snapped toward common pixel-art
   sizes, returned as a tight ranked candidate list so the pipeline can pick
   the winner by reconstruction residual;
3. the **gridline positions** — not assumed uniform. We place the ``N+1``
   boundaries with a dynamic program over every integer position, where each
   cell's width may deviate from the mean period under a spacing prior. Drift
   can therefore *accumulate* (a run of 17px cells followed by 15px cells), not
   just jitter around a uniform lattice.

Everything keys off 1-D *edge projection profiles*: summing the perceptual
(OKLab, alpha-aware) difference between neighboring columns yields a signal
whose peaks are the vertical gridlines (and symmetrically for rows). This is
more robust than a raw 2-D FFT, which smears once the period drifts, and than
luminance alone, which is blind to edges between equally bright colors.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import color as _color

__all__ = [
    "GridResult",
    "edge_features",
    "gradient_profiles",
    "autocorr_period",
    "fft_period",
    "candidate_cell_counts",
    "fit_gridlines",
    "build_grid",
]

# Sizes the pixel-art community gravitates to; detection snaps toward these
# when the raw estimate is close, since artists rarely pick 33x33.
COMMON_SIZES = (8, 16, 24, 32, 48, 64, 96, 128, 160, 192, 256)

# FFT and autocorrelation estimates further apart than this (relative) are
# treated as a harmonic conflict; the FFT estimate is then ignored.
_HARMONIC_TOL = 0.2


@dataclass
class GridResult:
    """A fitted grid. ``x_bounds`` has ``nx + 1`` entries, ``y_bounds`` ``ny + 1``."""

    x_bounds: np.ndarray
    y_bounds: np.ndarray
    nx: int
    ny: int
    period_x: float
    period_y: float

    def cell_slices(self):
        """Yield ``(row, col, (y0, y1), (x0, x1))`` integer pixel spans per cell."""
        xb = np.round(self.x_bounds).astype(int)
        yb = np.round(self.y_bounds).astype(int)
        for r in range(self.ny):
            for c in range(self.nx):
                yield r, c, (yb[r], yb[r + 1]), (xb[c], xb[c + 1])


def edge_features(rgb: np.ndarray, lab: np.ndarray | None = None) -> np.ndarray:
    """Per-pixel feature vectors whose differences define edge strength.

    OKLab color (perceptual, so equal-luminance hues still differ), premultiplied
    by alpha when present so the hidden RGB under transparent pixels carries no
    signal, plus the alpha itself so a silhouette edge counts as an edge.
    ``lab`` may be passed in when the caller already converted the image.
    """
    arr = np.asarray(rgb)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if lab is None:
        lab = _color.srgb_to_oklab(arr[..., :3])
    if arr.shape[-1] != 4:
        return lab
    a = arr[..., 3].astype(np.float64)
    if arr.dtype == np.uint8 or a.max(initial=0.0) > 1.0:
        a = a / 255.0
    return np.concatenate([lab * a[..., None], a[..., None]], axis=-1)


def gradient_profiles(
    rgb: np.ndarray, lab: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(prof_x, prof_y)`` edge-projection profiles.

    ``prof_x`` has length W; its peaks mark vertical gridlines (columns).
    ``prof_y`` has length H; its peaks mark horizontal gridlines (rows).
    """
    feat = edge_features(rgb, lab)
    # Per-pixel perceptual step to the neighbor (Euclidean over feature channels).
    gx = np.sqrt(np.sum(np.diff(feat, axis=1) ** 2, axis=-1))  # (H, W-1)
    gy = np.sqrt(np.sum(np.diff(feat, axis=0) ** 2, axis=-1))  # (H-1, W)
    # Sum across the orthogonal axis to collapse to 1-D, pad to full length so
    # profile index lines up with pixel coordinates.
    prof_x = np.zeros(feat.shape[1])
    prof_x[1:] = gx.sum(axis=0)
    prof_y = np.zeros(feat.shape[0])
    prof_y[1:] = gy.sum(axis=1)
    return prof_x, prof_y


def _autocorr(profile: np.ndarray) -> np.ndarray | None:
    """Normalized linear (non-circular) autocorrelation, or ``None`` if flat."""
    x = np.asarray(profile, dtype=np.float64)
    x = x - x.mean()
    n = x.size
    fsize = 1 << int(np.ceil(np.log2(max(2 * n - 1, 2))))
    f = np.fft.rfft(x, fsize)
    ac = np.fft.irfft(f * np.conj(f), fsize)[:n]
    if ac[0] <= 1e-12:
        return None
    return ac / ac[0]


def _local_peak(ac: np.ndarray, center: float, radius: float) -> float | None:
    """Sub-pixel location of the highest local maximum of ``ac`` near ``center``."""
    lo = max(1, int(np.floor(center - radius)))
    hi = min(ac.size - 2, int(np.ceil(center + radius)))
    if hi < lo:
        return None
    i = lo + int(np.argmax(ac[lo : hi + 1]))
    if not (ac[i] >= ac[i - 1] and ac[i] >= ac[i + 1]):
        return None
    # Parabolic interpolation through the three samples around the peak.
    denom = ac[i - 1] - 2 * ac[i] + ac[i + 1]
    shift = 0.5 * (ac[i - 1] - ac[i + 1]) / denom if denom < 0 else 0.0
    return i + float(np.clip(shift, -0.5, 0.5))


def autocorr_period(profile: np.ndarray, min_period: int = 2) -> float:
    """Period from the first prominent autocorrelation peak, refined sub-pixel.

    The integer lag of the first prominent peak locates the period; the peaks
    at its multiples (2p, 3p, ...) are then fit through the origin, which turns
    the integer estimate into a fractional one (a 10.5px scale no longer reads
    as 10 or 11). Returns ``nan`` if no clear period is found.
    """
    x = np.asarray(profile, dtype=np.float64)
    n = x.size
    if n < 2 * min_period:
        return float("nan")
    ac = _autocorr(x)
    if ac is None:
        return float("nan")
    hi = n // 2
    if hi <= min_period + 1:
        return float("nan")
    # Local maxima over lags [min_period, hi), min_period itself included.
    peaks = [
        i
        for i in range(max(min_period, 1), hi)
        if i + 1 < n and ac[i] > ac[i - 1] and ac[i] >= ac[i + 1]
    ]
    if not peaks:
        return float("nan")
    thresh = 0.30 * max(ac[p] for p in peaks)
    p0 = next((p for p in peaks if ac[p] >= thresh), peaks[0])

    # Refine with harmonics: least-squares slope of (k, lag_k) through origin.
    ks, lags = [], []
    k = 1
    while k * p0 < hi:
        lag = _local_peak(ac, k * (lags[-1] / ks[-1] if ks else p0), max(1.0, 0.15 * p0))
        if lag is None:
            break
        ks.append(k)
        lags.append(lag)
        k += 1
    if not ks:
        return float(p0)
    ks_a, lags_a = np.array(ks, float), np.array(lags, float)
    return float(np.sum(ks_a * lags_a) / np.sum(ks_a * ks_a))


def fft_period(profile: np.ndarray, min_period: int = 2) -> float:
    """Dominant-frequency period estimate (validator for autocorrelation)."""
    x = np.asarray(profile, dtype=np.float64)
    x = x - x.mean()
    n = x.size
    if n < 2 * min_period:
        return float("nan")
    spec = np.abs(np.fft.rfft(x * np.hanning(n)))
    kmax = n // min_period
    if kmax <= 1:
        return float("nan")
    spec[0] = 0.0
    if not np.any(spec[1:kmax] > 0):
        return float("nan")
    k = int(np.argmax(spec[1:kmax]) + 1)
    # Reject a "peak" that is really just noise floor.
    if spec[k] < 1e-9 * max(spec.max(), 1e-12):
        return float("nan")
    return float(n / k)


def periodicity(profile: np.ndarray, period: float) -> float:
    """Autocorrelation at ``period`` in ``[0, 1]`` — how periodic the profile is."""
    if not np.isfinite(period) or period < 1:
        return 0.0
    ac = _autocorr(profile)
    if ac is None or period >= ac.size - 1:
        return 0.0
    lag = _local_peak(ac, period, max(1.0, 0.15 * period))
    val = ac[int(round(lag))] if lag is not None else ac[int(round(period))]
    return float(np.clip(val, 0.0, 1.0))


def candidate_cell_counts(
    profile: np.ndarray,
    length: int,
    max_cells: int = 256,
    snap_tolerance: float = 0.12,
) -> list[int]:
    """Ranked candidate cell-counts for one axis.

    Converts the autocorrelation period to a cell count, snaps toward
    :data:`COMMON_SIZES`, and adds the immediate neighbors — a deliberately
    *tight* list (see ``score.select_grid``). The FFT estimate only contributes
    when it agrees with autocorrelation (or autocorrelation found nothing), so a
    harmonic can't smuggle a much finer grid into the candidate set.
    """
    candidates: list[int] = []

    def add(n: float) -> None:
        if not np.isfinite(n):
            return
        n_int = int(round(n))
        for val in (n_int, _snap_common(n_int, snap_tolerance)):
            if 2 <= val <= max_cells and val not in candidates:
                candidates.append(val)

    p_ac = autocorr_period(profile)
    p_fft = fft_period(profile)
    if np.isfinite(p_ac):
        add(length / p_ac)
        # Autocorrelation can lock onto a *multiple* of the true period when a
        # sparse sprite has negative correlation at one cell (thin lines on a
        # background). Accept the FFT estimate when it agrees with the period or
        # with p_ac / 2 or p_ac / 3; any other disagreement is a harmonic
        # conflict and is ignored. A finer candidate that is an exact
        # subdivision can never win a residual tie (see ``score.select_grid``).
        if np.isfinite(p_fft) and any(
            abs(p_fft - p_ac / k) <= _HARMONIC_TOL * (p_ac / k) for k in (1, 2, 3)
        ):
            add(length / p_fft)
    elif np.isfinite(p_fft):
        add(length / p_fft)
    # Also offer the immediate neighbors of the primary estimate, since an
    # off-by-one in N is the most common detection error.
    if candidates:
        primary = candidates[0]
        for delta in (-1, 1, -2, 2):
            v = primary + delta
            if 2 <= v <= max_cells and v not in candidates:
                candidates.append(v)
    return candidates


def _snap_common(n: int, tol: float) -> int:
    """Snap a cell-count to the nearest common size if within ``tol`` fraction."""
    if n <= 0:
        return n
    best = n
    best_rel = tol
    for c in COMMON_SIZES:
        rel = abs(c - n) / n
        if rel < best_rel:
            best_rel = rel
            best = c
    return best


def fit_gridlines(
    profile: np.ndarray,
    n: int,
    length: int,
    window_frac: float = 0.35,
    smoothness: float = 0.15,
) -> np.ndarray:
    """Place ``n+1`` gridlines along one axis, tolerating non-uniform cells.

    The outer boundaries are pinned at ``0`` and ``length``. Interior lines are
    positioned by a dynamic program over *every* integer position: each cell
    width may range over ``period * (1 ± window_frac)``, and the path maximizes
    edge energy at the chosen lines minus ``smoothness``-weighted squared
    relative deviation of each width from the mean period. Because widths (not
    positions relative to a uniform lattice) are constrained, drift may
    accumulate across the image.

    Returns a float array of ``n+1`` boundary positions.
    """
    n = int(n)
    length = int(length)
    if n < 1:
        return np.array([0.0, float(length)])
    period = length / n
    uniform = np.linspace(0.0, length, n + 1)
    if n == 1 or length < 4:
        return uniform

    # Smoothed edge-energy lookup, normalized to [0, 1].
    energy = _smooth(np.asarray(profile, dtype=np.float64), max(1, int(round(period * 0.15))))
    if energy.max() > 0:
        energy = energy / energy.max()
    e = np.zeros(length + 1)
    m = min(energy.size, length)
    e[:m] = energy[:m]

    dmin = max(1, int(np.floor(period * (1.0 - window_frac))))
    dmax = max(dmin, int(np.ceil(period * (1.0 + window_frac))))
    if n * dmin > length or n * dmax < length:
        return uniform
    widths = np.arange(dmin, dmax + 1)
    pen = smoothness * ((widths - period) / period) ** 2

    neg = -np.inf
    score = np.full(length + 1, neg)
    score[0] = 0.0
    back = np.zeros((n, length + 1), dtype=np.int32)
    for i in range(1, n + 1):
        best = np.full(length + 1, neg)
        arg = np.zeros(length + 1, dtype=np.int32)
        for d, pd in zip(widths, pen):
            cand = np.full(length + 1, neg)
            cand[d:] = score[: length + 1 - d] - pd
            better = cand > best
            best[better] = cand[better]
            arg[better] = d
        if i < n:
            best = best + e
            best[0] = neg
            best[length] = neg  # interior lines stay strictly inside
        score = best
        back[i - 1] = arg

    if not np.isfinite(score[length]):
        return uniform
    bounds = [float(length)]
    pos = length
    for i in range(n, 0, -1):
        pos -= int(back[i - 1][pos])
        bounds.append(float(pos))
    bounds.reverse()
    out = np.array(bounds)
    if out[0] != 0.0 or np.any(np.diff(out) <= 0):
        return uniform
    return out


def _smooth(x: np.ndarray, radius: int) -> np.ndarray:
    """Simple box smoothing with edge handling."""
    if radius <= 0:
        return x
    k = np.ones(2 * radius + 1) / (2 * radius + 1)
    return np.convolve(x, k, mode="same")


def build_grid(
    rgb: np.ndarray,
    nx: int,
    ny: int,
    *,
    profiles: tuple[np.ndarray, np.ndarray] | None = None,
    **fit_kwargs,
) -> GridResult:
    """Fit a full grid for explicit cell counts ``nx`` x ``ny``.

    Pass precomputed ``profiles`` (from :func:`gradient_profiles`) to avoid
    recomputing them when fitting many candidate grids on one image.
    """
    h, w = np.asarray(rgb).shape[:2]
    prof_x, prof_y = profiles if profiles is not None else gradient_profiles(rgb)
    x_bounds = fit_gridlines(prof_x, nx, w, **fit_kwargs)
    y_bounds = fit_gridlines(prof_y, ny, h, **fit_kwargs)
    return GridResult(
        x_bounds=x_bounds,
        y_bounds=y_bounds,
        nx=int(nx),
        ny=int(ny),
        period_x=w / nx,
        period_y=h / ny,
    )
