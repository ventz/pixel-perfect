"""Indexed-image rendering for the manual pixel editor.

The browser editor keeps an *indexed* document — a palette of RGBA colors plus a
grid of palette indices — as its canonical state. This module turns that indexed
document back into pixels, so the same rendering/encoding path is reused by the
web ``/api/export`` endpoint, the Python library, and any automation. Keeping it
here (not in the JS) preserves the project's "one core, all surfaces" rule and
guarantees a manually-edited result is still emitted as a true pixel-perfect PNG.
"""

from __future__ import annotations

import numpy as np

from .pipeline import clamp_upscale, upscale

__all__ = ["hex_to_rgba", "render_indexed", "MAX_EDIT_PIXELS", "EditPayloadError"]

# Upper bound on an editable grid (defensive: bounds API payload + memory).
MAX_EDIT_PIXELS = 512 * 512


class EditPayloadError(ValueError):
    """Raised when an indexed-document payload is malformed."""


def hex_to_rgba(color: str) -> tuple[int, int, int, int]:
    """Parse ``#rgb`` / ``#rrggbb`` / ``#rrggbbaa`` into an ``(r, g, b, a)`` tuple."""
    h = color.lstrip("#")
    if len(h) == 3:  # #rgb shorthand
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        h += "ff"
    if len(h) != 8:
        raise EditPayloadError(f"Invalid hex color: {color!r}")
    try:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]
    except ValueError:
        raise EditPayloadError(f"Invalid hex color: {color!r}")


def render_indexed(
    width: int,
    height: int,
    palette: list[str],
    indices: list[int] | np.ndarray,
) -> np.ndarray:
    """Render an indexed document to an ``(height, width, 4)`` uint8 RGBA array.

    Parameters
    ----------
    width, height : grid dimensions in logical pixels.
    palette : list of hex colors (``#rrggbb`` or ``#rrggbbaa``).
    indices : ``width * height`` palette indices, row-major. A negative index
        (e.g. ``-1``) denotes a transparent pixel.

    Raises
    ------
    EditPayloadError : on any dimension/length/index/color inconsistency.
    """
    if width <= 0 or height <= 0:
        raise EditPayloadError("width and height must be positive.")
    if width * height > MAX_EDIT_PIXELS:
        raise EditPayloadError(f"Grid too large: max {MAX_EDIT_PIXELS} pixels.")
    if not palette:
        raise EditPayloadError("palette must have at least one color.")

    idx = np.asarray(indices, dtype=np.int64).reshape(-1)
    if idx.size != width * height:
        raise EditPayloadError(
            f"indices length {idx.size} != width*height {width * height}."
        )
    if int(idx.max(initial=0)) >= len(palette):
        raise EditPayloadError("index out of palette range.")

    lut = np.array([hex_to_rgba(c) for c in palette], dtype=np.uint8)  # (K, 4)
    out = np.zeros((idx.size, 4), dtype=np.uint8)
    transparent = idx < 0
    opaque = ~transparent
    out[opaque] = lut[idx[opaque]]
    # transparent rows stay (0, 0, 0, 0)
    return out.reshape(height, width, 4)


def export_indexed(
    width: int,
    height: int,
    palette: list[str],
    indices: list[int] | np.ndarray,
    upscale_factor: int = 0,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Render an indexed document plus an optional N× nearest-neighbor preview.

    Returns ``(native_rgba, preview_rgba_or_None)``.
    """
    native = render_indexed(width, height, palette, indices)
    factor = clamp_upscale(width, height, upscale_factor or 0)
    preview = upscale(native, factor) if factor > 1 else None
    return native, preview
