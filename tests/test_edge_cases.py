"""Edge-case and robustness tests added for the public release."""

import numpy as np
import pytest

from pixelperfect import PipelineParams, restore
from pixelperfect.color import nearest_color, srgb_to_oklab
from pixelperfect.grid import _snap_common, build_grid
from pixelperfect.sample import collapse


def _cutout(synth, hidden_rgb=(0, 0, 0)):
    """A block-filled cut-out sprite: opaque blob on alpha=0, hidden RGB beneath."""
    make_native, distort = synth
    native = make_native(0, 16, 16, 8)
    yy, xx = np.mgrid[:16, :16]
    mask = ((yy - 7.5) ** 2 + (xx - 7.5) ** 2) < 42  # round silhouette
    alpha_native = np.where(mask, 255, 0).astype(np.uint8)
    rgb_native = np.where(mask[..., None], native, np.array(hidden_rgb, np.uint8))
    rgba_native = np.dstack([rgb_native, alpha_native])
    big_rgb = distort(rgba_native[..., :3], blur=0.8)
    big_a = distort(np.dstack([alpha_native] * 3), blur=0.0, noise=0, jpeg=0)[..., 0]
    return native, mask, np.dstack([big_rgb, big_a])


def test_rgba_input_preserves_alpha(synth):
    native, mask, rgba = _cutout(synth)
    res = restore(rgba, PipelineParams(palette_size=8))
    assert res.native.shape[-1] == 4  # alpha survived
    assert (res.nx, res.ny) == (16, 16)
    assert np.array_equal(res.native[..., 3] == 255, mask)  # silhouette exact


def test_hidden_rgb_under_transparency_is_ignored(synth):
    _, _, black = _cutout(synth, hidden_rgb=(0, 0, 0))
    _, _, pink = _cutout(synth, hidden_rgb=(255, 0, 255))
    a = restore(black, PipelineParams(palette_size=8, denoise_strength=0))
    b = restore(pink, PipelineParams(palette_size=8, denoise_strength=0))
    assert (a.nx, a.ny) == (b.nx, b.ny) == (16, 16)
    opaque = a.native[..., 3] == 255
    assert np.array_equal(a.native[..., 3], b.native[..., 3])
    assert np.array_equal(a.native[opaque], b.native[opaque])
    # The hidden color must never claim a palette slot.
    assert not any((tuple(c) == (255, 0, 255)) for c in b.palette)


def test_single_color_image():
    flat = np.full((128, 128, 3), (50, 120, 200), np.uint8)
    res = restore(flat, PipelineParams(palette_size=4))
    # A flat image must collapse to exactly one color (denoising may shift the
    # exact value by a step, so check the count, not the literal RGB).
    assert len(res.palette) == 1
    assert np.unique(res.native[..., :3].reshape(-1, 3), axis=0).shape[0] == 1


def test_non_square_grid(synth):
    make_native, distort = synth
    native = make_native(3, 32, 16, 8)  # wider than tall
    big = distort(native, avg_cell=20, blur=0.8)
    res = restore(big, PipelineParams(native_w=32, native_h=16, palette_size=8))
    assert (res.nx, res.ny) == (32, 16)


def test_grayscale_collapse_returns_rgb():
    gray = np.tile(np.repeat(np.arange(0, 160, 10, dtype=np.uint8), 8), (128, 1))
    grid = build_grid(gray, 16, 16)
    field = collapse(gray, grid)
    assert field.rgb.shape == (16, 16, 3)


@pytest.mark.parametrize("method", ["median", "mode", "medoid", "mean"])
def test_all_sample_methods(synth, method):
    make_native, distort = synth
    native = make_native(0, 16, 16, 8)
    big = distort(native, blur=0.8)
    res = restore(big, PipelineParams(palette_size=8, sample_method=method))
    assert (res.nx, res.ny) == (16, 16)


def test_invalid_method_rejected():
    with pytest.raises(ValueError):
        restore(np.zeros((32, 32, 3), np.uint8), PipelineParams(sample_method="bogus"))


def test_invalid_palette_name_rejected():
    with pytest.raises(ValueError):
        restore(np.zeros((32, 32, 3), np.uint8), PipelineParams(palette_name="does-not-exist"))


def test_upscale_clamped():
    p = PipelineParams(upscale=10_000).validate()
    assert p.upscale <= 32


def test_snap_common_no_divzero():
    assert _snap_common(0, 0.1) == 0  # must not raise


def test_nearest_color_empty_palette():
    colors = srgb_to_oklab(np.array([[10, 20, 30]], np.uint8))
    assert nearest_color(colors, np.zeros((0, 3))).shape == (1,)
