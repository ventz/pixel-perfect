"""Image IO helpers shared by the CLI and the web API.

Kept tiny and dependency-light (Pillow only) so the same load/encode paths back
every entry point.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

__all__ = ["load_rgb", "load_bytes", "to_png_bytes", "save_png", "MAX_PIXELS", "ALLOWED_FORMATS"]

# Pixel art is small; cap decoded size to defuse decompression bombs (a tiny
# file can otherwise decode to a multi-gigapixel array). ~2048x2048.
MAX_PIXELS = 4_000_000

# Formats we accept. Pillow supports many obscure parsers; narrowing the set
# shrinks the attack surface for untrusted uploads.
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "BMP"}

# Hard ceiling for Pillow itself (it raises before allocating beyond this).
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ImageTooLargeError(ValueError):
    """Raised when an image exceeds :data:`MAX_PIXELS`."""


class UnsupportedImageError(ValueError):
    """Raised when an image's format is not in :data:`ALLOWED_FORMATS`."""


def load_rgb(path: str) -> np.ndarray:
    """Load an image file as an ``(H, W, 3|4)`` uint8 array (alpha preserved)."""
    return _to_array(_open(path))


def load_bytes(data: bytes) -> np.ndarray:
    """Load image bytes (an upload) as an ``(H, W, 3|4)`` uint8 array.

    Raises :class:`UnsupportedImageError` for disallowed formats and
    :class:`ImageTooLargeError` for images exceeding :data:`MAX_PIXELS`.
    """
    return _to_array(_open(io.BytesIO(data)))


def _open(src) -> Image.Image:
    # Pillow raises its own DecompressionBombError at open() for images far over
    # MAX_IMAGE_PIXELS; surface it as the same "too large" error as the soft cap.
    try:
        return Image.open(src)
    except Image.DecompressionBombError as e:
        raise ImageTooLargeError(
            f"Image exceeds the {MAX_PIXELS}-pixel limit (~2048x2048)."
        ) from e


def _to_array(img: Image.Image) -> np.ndarray:
    if img.format is not None and img.format not in ALLOWED_FORMATS:
        raise UnsupportedImageError(
            f"Unsupported image format: {img.format}. Allowed: {sorted(ALLOWED_FORMATS)}"
        )
    if img.width * img.height > MAX_PIXELS:
        raise ImageTooLargeError(
            f"Image is {img.width}x{img.height}; max is {MAX_PIXELS} pixels (~2048x2048)."
        )
    # Transparency can live outside an alpha band: palette PNG/GIF and RGB/L
    # PNGs carry it in ``info["transparency"]``. Converting to RGBA applies it.
    has_alpha = "A" in img.getbands() or img.has_transparency_data
    return np.array(img.convert("RGBA" if has_alpha else "RGB"))


def to_png_bytes(arr: np.ndarray) -> bytes:
    """Encode an ``(H, W, 3|4)`` uint8 array as PNG bytes."""
    mode = "RGBA" if arr.shape[-1] == 4 else "RGB"
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8), mode).save(buf, format="PNG")
    return buf.getvalue()


def save_png(arr: np.ndarray, path: str) -> None:
    """Write an ``(H, W, 3|4)`` uint8 array to a PNG file."""
    with open(path, "wb") as f:
        f.write(to_png_bytes(arr))
