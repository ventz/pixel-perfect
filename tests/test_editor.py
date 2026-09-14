"""Tests for indexed-document rendering and the /api/export endpoint."""

import base64
import io

import numpy as np
import pytest
from PIL import Image

from pixelperfect import export_indexed, render_indexed
from pixelperfect.editor import EditPayloadError, hex_to_rgba


def test_hex_to_rgba_forms():
    assert hex_to_rgba("#ff0000") == (255, 0, 0, 255)
    assert hex_to_rgba("ff0000") == (255, 0, 0, 255)
    assert hex_to_rgba("#f00") == (255, 0, 0, 255)
    assert hex_to_rgba("#11223344") == (0x11, 0x22, 0x33, 0x44)
    with pytest.raises(EditPayloadError):
        hex_to_rgba("#xyz123")


def test_render_indexed_exact_colors():
    img = render_indexed(2, 2, ["#ff0000", "#00ff00", "#0000ff"], [0, 1, 2, 0])
    assert img.shape == (2, 2, 4)
    assert tuple(img[0, 0]) == (255, 0, 0, 255)
    assert tuple(img[0, 1]) == (0, 255, 0, 255)
    assert tuple(img[1, 0]) == (0, 0, 255, 255)


def test_render_indexed_transparency():
    img = render_indexed(2, 1, ["#ffffff"], [-1, 0])
    assert tuple(img[0, 0]) == (0, 0, 0, 0)  # transparent
    assert tuple(img[0, 1]) == (255, 255, 255, 255)


def test_render_indexed_preserves_alpha_palette():
    img = render_indexed(1, 1, ["#11223380"], [0])
    assert tuple(img[0, 0]) == (0x11, 0x22, 0x33, 0x80)


def test_export_indexed_upscale_is_nearest_neighbor():
    native, preview = export_indexed(2, 2, ["#ff0000", "#00ff00"], [0, 1, 1, 0], 4)
    assert native.shape == (2, 2, 4)
    assert preview.shape == (8, 8, 4)
    # each native cell becomes a solid 4x4 block (no interpolation)
    assert tuple(preview[0, 0]) == (255, 0, 0, 255)
    assert tuple(preview[0, 7]) == (0, 255, 0, 255)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width": 2, "height": 2, "palette": ["#fff"], "indices": [0, 0, 0]},  # length
        {"width": 2, "height": 2, "palette": ["#fff"], "indices": [0, 0, 0, 5]},  # range
        {"width": 2, "height": 2, "palette": [], "indices": [0, 0, 0, 0]},  # empty palette
        {"width": 0, "height": 2, "palette": ["#fff"], "indices": []},  # bad dim
        {"width": 1000, "height": 1000, "palette": ["#fff"], "indices": [0]},  # too large
    ],
)
def test_render_indexed_rejects_bad_payloads(kwargs):
    with pytest.raises(EditPayloadError):
        render_indexed(**kwargs)


# ---- API endpoint -----------------------------------------------------------
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from pixelperfect.web.api import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_export_endpoint_roundtrip(client):
    payload = {
        "width": 2,
        "height": 2,
        "palette": ["#ff0000", "#00ff00", "#0000ff"],
        "indices": [0, 1, 2, -1],
        "upscale": 8,
    }
    r = client.post("/api/export", json=payload)
    assert r.status_code == 200
    d = r.json()
    assert d["width"] == 2 and d["height"] == 2 and d["n_colors"] == 3
    native = np.array(Image.open(io.BytesIO(base64.b64decode(d["native_png"].split(",")[1]))))
    assert native.shape == (2, 2, 4)
    assert tuple(native[0, 0]) == (255, 0, 0, 255)
    assert native[1, 1, 3] == 0  # transparent cell
    preview = np.array(Image.open(io.BytesIO(base64.b64decode(d["preview_png"].split(",")[1]))))
    assert preview.shape == (16, 16, 4)


def test_export_endpoint_validates(client):
    r = client.post("/api/export", json={"width": 2, "height": 2, "palette": ["#fff"], "indices": [0]})
    assert r.status_code == 422


def test_export_endpoint_clamps_upscale(client):
    r = client.post(
        "/api/export",
        json={"width": 1, "height": 1, "palette": ["#fff"], "indices": [0], "upscale": 9999},
    )
    assert r.status_code == 200
    assert r.json()["upscale"] <= 32
