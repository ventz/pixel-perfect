"""Regression tests for detection robustness, resource limits, and validation."""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pixelperfect import PipelineParams, restore
from pixelperfect import io as pio
from pixelperfect.color import nearest_color
from pixelperfect.grid import autocorr_period, fit_gridlines, gradient_profiles
from pixelperfect.palette import build_palette
from pixelperfect.pipeline import MAX_OUTPUT_PIXELS, clamp_upscale
from pixelperfect.sample import CellField
from pixelperfect.web.api import app

from conftest import make_native


def _blockfill(native, xb, yb):
    ny, nx = native.shape[:2]
    big = np.zeros((int(yb[-1]), int(xb[-1]), 3), np.uint8)
    for r in range(ny):
        for c in range(nx):
            big[yb[r]:yb[r + 1], xb[c]:xb[c + 1]] = native[r, c]
    return big


def _png(arr) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def sprite_png():
    native = make_native(1, 16, 16, 6)
    b = np.r_[0, np.cumsum(np.full(16, 12))]
    return _png(_blockfill(native, b, b))


# --- grid detection ----------------------------------------------------------


def test_accumulated_drift_is_tracked(synth):
    """17px cells then 15px cells: boundaries drift 16px off a uniform lattice."""
    _, distort = synth
    native = make_native(4, 32, 32, 8)
    w = np.r_[np.full(16, 17), np.full(16, 15)]
    b = np.r_[0, np.cumsum(w)]
    res = restore(_blockfill(native, b, b), PipelineParams(denoise_strength=0))
    assert (res.nx, res.ny) == (32, 32)
    # Exact up to the OKLab round-trip.
    assert np.abs(res.native.astype(int) - native.astype(int)).max() <= 2


def test_gridline_fit_reaches_every_integer_position():
    """A true boundary at an odd pixel must be selectable (no round-half-even gaps).

    With a uniform center of 7.5, rounding ``center + offset`` half-to-even can
    only ever produce even positions; the true boundary here is at 7.
    """
    length, n = 15, 2
    prof = np.zeros(length)
    prof[5:10] = [0.2, 0.6, 1.0, 0.6, 0.2]  # unique maximum at 7 after smoothing
    bounds = fit_gridlines(prof, n, length, smoothness=0.0)
    assert bounds[1] == 7


def test_fractional_period_estimate():
    native = make_native(2, 48, 48, 8)
    b = np.round(np.arange(49) * 10.5).astype(int)
    px, _ = gradient_profiles(_blockfill(native, b, b))
    assert abs(autocorr_period(px) - 10.5) < 0.1


def test_equal_luminance_edges_detected():
    """Colors with identical luma still produce grid evidence (OKLab, not gray)."""
    pal = np.array([[200, 100, 100], [100, 150, 110], [90, 120, 250]], np.uint8)
    idx = np.random.default_rng(0).integers(0, 3, (16, 16))
    native = pal[idx]
    b = np.r_[0, np.cumsum(np.full(16, 20))]
    res = restore(_blockfill(native, b, b), PipelineParams(denoise_strength=0))
    assert (res.nx, res.ny) == (16, 16)


def test_flat_image_reports_fallback():
    res = restore(np.full((96, 96, 3), 128, np.uint8), PipelineParams())
    assert res.score.fallback is True
    assert res.score.grid_confidence == 0.0


def test_forced_size_has_no_grid_confidence(synth):
    make, distort = synth
    img = distort(make(0, 16, 16, 6))
    res = restore(img, PipelineParams(native_w=16, native_h=16))
    assert res.score.grid_confidence is None
    assert res.score.fallback is False


def test_thin_sprite_autodetect(thin):
    make_thin_sprite, distort, thin_metrics, _ = thin
    gt = make_thin_sprite(40, 40)
    img = distort(gt, seed=0, avg_cell=16, drift=0.08, blur=0.8, jpeg=88)
    res = restore(img, PipelineParams())
    assert (res.nx, res.ny) == (40, 40)
    assert thin_metrics(gt, res.native)["exact"] > 0.97


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"native_w": -5},
        {"native_w": 10_000},
        {"denoise_strength": float("nan")},
        {"denoise_strength": float("inf")},
        {"denoise_strength": -1.0},
        {"interior_frac": float("nan")},
        {"fit_window_frac": 1.5},
    ],
)
def test_params_rejected(kwargs):
    with pytest.raises(ValueError):
        PipelineParams(**kwargs).validate()


def test_native_size_larger_than_image_rejected():
    with pytest.raises(ValueError):
        restore(np.zeros((40, 40, 3), np.uint8), PipelineParams(native_w=64, native_h=16))


def test_top_k_clamped():
    assert PipelineParams(top_k=0).validate().top_k == 1


def test_clamp_upscale_respects_output_budget():
    f = clamp_upscale(512, 512, 32)
    assert f >= 1 and 512 * 512 * f * f <= MAX_OUTPUT_PIXELS
    assert clamp_upscale(16, 16, 8) == 8
    assert clamp_upscale(16, 16, 0) == 0


# --- palette / color memory ------------------------------------------------------


def test_build_palette_many_unique_colors_is_bounded():
    rng = np.random.default_rng(0)
    rgb = rng.integers(0, 256, (300, 300, 3), dtype=np.uint8)  # ~90k unique colors
    pal = build_palette(CellField(rgb), max_colors=16)
    assert 1 <= len(pal) <= 16
    # Every palette entry is a real input color.
    flat = {tuple(c) for c in rgb.reshape(-1, 3)}
    assert all(tuple(c) in flat for c in pal)


def test_palette_representative_is_central_not_just_frequent():
    # One cluster: a central color seen once each, plus an edge variant seen twice.
    center = np.array([[100, 100, 100], [101, 100, 100], [100, 101, 100], [100, 100, 101]], np.uint8)
    edge = np.array([[112, 100, 100]] * 2, np.uint8)
    rgb = np.concatenate([center, edge]).reshape(1, -1, 3)
    pal = build_palette(CellField(rgb), merge_threshold=0.2)
    assert len(pal) == 1
    assert tuple(pal[0]) != (112, 100, 100)


def test_nearest_color_chunked_matches_direct():
    rng = np.random.default_rng(1)
    colors = rng.random((50_000, 3))
    pal = rng.random((300, 3))
    direct = np.argmin(((colors[:, None, :] - pal[None, :, :]) ** 2).sum(-1), axis=1)
    assert np.array_equal(nearest_color(colors, pal), direct)


# --- IO --------------------------------------------------------------------------


def test_palette_png_transparency_loads_as_rgba():
    img = Image.new("P", (8, 8), 0)
    img.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    img.paste(1, (2, 2, 6, 6))
    img.info["transparency"] = 0
    buf = io.BytesIO()
    img.save(buf, format="PNG", transparency=0)
    arr = pio.load_bytes(buf.getvalue())
    assert arr.shape[-1] == 4
    assert arr[0, 0, 3] == 0 and arr[3, 3, 3] == 255


def test_decompression_bomb_is_too_large_error():
    buf = io.BytesIO()
    Image.new("L", (3000, 3000)).save(buf, format="PNG")
    with pytest.raises(pio.ImageTooLargeError):
        pio.load_bytes(buf.getvalue())


# --- API ----------------------------------------------------------------------------


def test_api_negative_native_is_422(client, sprite_png):
    r = client.post("/api/restore", files={"file": ("s.png", sprite_png)}, data={"native_w": "-5"})
    assert r.status_code == 422


def test_api_native_exceeding_image_is_422(client, sprite_png):
    r = client.post(
        "/api/restore", files={"file": ("s.png", sprite_png)}, data={"native_w": "400", "native_h": "8"}
    )
    assert r.status_code == 422


@pytest.mark.parametrize("endpoint", ["/api/analyze", "/api/restore", "/api/denoise", "/api/detect-grid"])
def test_api_nan_denoise_is_422(client, sprite_png, endpoint):
    r = client.post(endpoint, files={"file": ("s.png", sprite_png)}, data={"denoise_strength": "nan"})
    assert r.status_code == 422


def test_api_quantize_bad_palette_size_is_clamped_or_rejected(client, sprite_png):
    r = client.post("/api/quantize", files={"file": ("s.png", sprite_png)}, data={"palette_size": "-1"})
    assert r.status_code == 200  # clamped to 1 color, like the pipeline
    out = np.array(Image.open(io.BytesIO(r.content)))
    assert np.unique(out.reshape(-1, out.shape[-1]), axis=0).shape[0] == 1
    r = client.post("/api/quantize", files={"file": ("s.png", sprite_png)}, data={"palette_size": "abc"})
    assert r.status_code == 422


def test_api_stage_endpoints_preserve_alpha(client):
    rgba = np.zeros((48, 48, 4), np.uint8)
    rgba[12:36, 12:36] = (200, 50, 50, 255)
    png = _png(rgba)
    for ep in ("/api/denoise", "/api/quantize"):
        r = client.post(ep, files={"file": ("a.png", png)})
        assert r.status_code == 200, ep
        out = np.array(Image.open(io.BytesIO(r.content)))
        assert out.shape[-1] == 4, ep
        assert out[0, 0, 3] == 0 and out[24, 24, 3] == 255, ep


def test_api_decompression_bomb_is_413(client):
    buf = io.BytesIO()
    Image.new("L", (3000, 3000)).save(buf, format="PNG")
    r = client.post("/api/analyze", files={"file": ("big.png", buf.getvalue())})
    assert r.status_code == 413


def test_api_body_over_limit_rejected_before_parsing(client, monkeypatch):
    from pixelperfect.web import api

    mw = next(m for m in app.user_middleware if m.cls is api.BodySizeLimitMiddleware)
    monkeypatch.setitem(mw.kwargs, "limit", 1024)
    app.middleware_stack = None  # rebuild with the patched limit
    try:
        local = TestClient(app, raise_server_exceptions=False)
        r = local.post("/api/analyze", files={"file": ("x.png", b"\0" * 4096)})
        assert r.status_code == 413
    finally:
        monkeypatch.undo()
        app.middleware_stack = None


def test_api_export_indices_length_capped(client):
    r = client.post(
        "/api/export",
        json={"width": 1, "height": 1, "palette": ["#000000"], "indices": [0] * (512 * 512 + 1)},
    )
    assert r.status_code == 422


def test_api_reports_grid_confidence(client, sprite_png):
    r = client.post("/api/analyze", files={"file": ("s.png", sprite_png)})
    body = r.json()
    assert r.status_code == 200
    assert "grid_confidence" in body and "fallback" in body


# --- CLI ------------------------------------------------------------------------------


def test_cli_batch_continues_past_bad_file(tmp_path, sprite_png):
    from typer.testing import CliRunner

    from pixelperfect.cli import app as cli_app

    (tmp_path / "a_good.png").write_bytes(sprite_png)
    (tmp_path / "b_bad.png").write_bytes(b"not an image")
    (tmp_path / "c_good.png").write_bytes(sprite_png)
    out = tmp_path / "out"
    result = CliRunner().invoke(cli_app, ["restore", str(tmp_path / "*.png"), str(out), "--batch"])
    assert result.exit_code == 1
    assert (out / "a_good.png").exists() and (out / "c_good.png").exists()
