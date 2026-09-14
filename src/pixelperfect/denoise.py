"""Pre-cleaning: remove JPEG/compression noise before grid detection.

AI exports are usually JPEGs, so cells that should be flat carry 8x8 DCT
ringing and chroma noise. That noise corrupts both the gradient profiles grid
detection relies on and the per-cell color vote. We denoise *edge-preservingly*
so true cell boundaries survive while intra-cell noise is flattened.

OpenCV's Non-Local Means is the default; a separable median is the fallback
when the optional ``cv2`` dependency is missing or for very small images.
"""

from __future__ import annotations

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - cv2 is a hard dep but stay defensive
    cv2 = None

__all__ = ["denoise"]


def denoise(rgb: np.ndarray, strength: float = 1.0) -> np.ndarray:
    """Edge-preserving denoise of a uint8 RGB image.

    Parameters
    ----------
    rgb : ``(H, W, 3)`` uint8 image.
    strength : 0 disables denoising; 1.0 is a sensible default; larger is
        more aggressive. Scales the NLM filter strength / median radius.

    Returns
    -------
    ``(H, W, 3)`` uint8 image.
    """
    img = np.asarray(rgb)
    if strength <= 0 or img.size == 0:
        return img.astype(np.uint8, copy=False)
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)

    # OpenCV's color denoisers accept 3-channel only; process RGB and pass any
    # alpha channel through untouched so transparent sprites don't crash.
    if img.ndim == 3 and img.shape[2] == 4:
        rgb_out = denoise(img[..., :3], strength)
        return np.dstack([rgb_out, img[..., 3]])

    if cv2 is not None:
        h = float(np.clip(3.0 * strength, 1.0, 30.0))
        # Bilateral first to protect hard edges, then NLM for residual grain.
        bilat = cv2.bilateralFilter(img, d=5, sigmaColor=25 * strength, sigmaSpace=5)
        return cv2.fastNlMeansDenoisingColored(bilat, None, h, h, 7, 21)

    return _median_rgb(img, radius=max(1, int(round(strength))))


def _median_rgb(img: np.ndarray, radius: int) -> np.ndarray:
    """NumPy-only separable-ish median fallback (per channel, square window)."""
    from scipy.ndimage import median_filter

    size = 2 * radius + 1
    out = np.empty_like(img)
    for c in range(img.shape[2]):
        out[..., c] = median_filter(img[..., c], size=size, mode="nearest")
    return out
