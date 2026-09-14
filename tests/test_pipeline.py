"""End-to-end round-trip tests: damaged sprite -> pixel-perfect recovery."""

import numpy as np
import pytest

from pixelperfect import PipelineParams, restore
from pixelperfect.color import delta_e, srgb_to_oklab


def _perceptual_error(native, recovered):
    return float(delta_e(srgb_to_oklab(recovered[..., :3]), srgb_to_oklab(native)).mean())


@pytest.mark.parametrize(
    "seed,nx,ny,cell,drift,blur,jpeg,ncol",
    [
        (0, 16, 16, 32, 0.05, 0.8, 90, 8),
        (1, 32, 32, 16, 0.10, 0.6, 92, 8),
        (2, 16, 16, 40, 0.15, 1.2, 82, 6),
        (3, 24, 24, 28, 0.08, 0.9, 88, 10),
        (4, 32, 16, 20, 0.12, 0.7, 85, 8),
    ],
)
def test_roundtrip_recovers_grid_and_palette(synth, seed, nx, ny, cell, drift, blur, jpeg, ncol):
    make_native, distort = synth
    native = make_native(seed, nx, ny, ncol)
    damaged = distort(native, seed=seed, avg_cell=cell, drift=drift, blur=blur, jpeg=jpeg)

    res = restore(damaged, PipelineParams(palette_size=ncol))

    # 1. correct native grid dimensions
    assert (res.nx, res.ny) == (nx, ny)
    # 2. output is genuinely pixel-perfect: one image pixel per logical pixel
    assert res.native.shape[:2] == (ny, nx)
    # 3. limited palette honored
    assert len(res.palette) <= ncol
    uniq = np.unique(res.native[..., :3].reshape(-1, 3), axis=0)
    assert uniq.shape[0] <= ncol
    # 4. colors are perceptually faithful to the ground truth
    assert _perceptual_error(native, res.native) < 0.03


def test_no_antialiasing_in_output(synth):
    make_native, distort = synth
    native = make_native(0, 16, 16, 8)
    damaged = distort(native, blur=1.2)
    res = restore(damaged, PipelineParams(palette_size=8))
    # Every cell is exactly one palette color: no intermediate AA shades.
    colors = set(map(tuple, res.native[..., :3].reshape(-1, 3)))
    assert len(colors) <= 8


def test_manual_native_override(synth):
    make_native, distort = synth
    native = make_native(5, 16, 16, 8)
    damaged = distort(native, drift=0.2, blur=1.5, jpeg=78)  # hard case
    res = restore(damaged, PipelineParams(native_w=16, native_h=16, palette_size=8))
    assert (res.nx, res.ny) == (16, 16)  # override forces the right grid


def test_named_palette_snapping(synth):
    make_native, distort = synth
    native = make_native(1, 16, 16, 8)
    damaged = distort(native)
    res = restore(damaged, PipelineParams(palette_name="sweetie-16"))
    from pixelperfect.palette import BUILTIN_PALETTES

    allowed = set(map(tuple, BUILTIN_PALETTES["sweetie-16"].tolist()))
    used = set(map(tuple, res.native[..., :3].reshape(-1, 3).tolist()))
    assert used <= allowed  # only palette colors appear


def test_confidence_high_on_clean_detection(synth):
    make_native, distort = synth
    native = make_native(0, 16, 16, 8)
    damaged = distort(native, drift=0.05, blur=0.8)
    res = restore(damaged, PipelineParams(palette_size=8))
    assert res.score.confidence > 0.8
