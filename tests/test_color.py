"""Color-space round trips and perceptual distance sanity."""

import numpy as np

from pixelperfect import color


def test_srgb_oklab_roundtrip():
    rng = np.random.default_rng(0)
    rgb = rng.integers(0, 256, size=(200, 3), dtype=np.uint8)
    back = color.oklab_to_srgb(color.srgb_to_oklab(rgb)) * 255
    assert np.max(np.abs(back - rgb)) <= 1.5  # within rounding


def test_delta_e_zero_for_identical():
    lab = color.srgb_to_oklab(np.array([[120, 30, 200]], np.uint8))
    assert color.delta_e(lab, lab)[0] == 0.0


def test_nearest_color_picks_closest():
    pal = np.array([[0, 0, 0], [255, 255, 255], [255, 0, 0]], np.uint8)
    lab_pal = color.srgb_to_oklab(pal)
    probe = color.srgb_to_oklab(np.array([[250, 10, 10]], np.uint8))
    assert color.nearest_color(probe, lab_pal)[0] == 2  # red
