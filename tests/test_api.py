"""Smoke tests for the FastAPI surface — every stage is reachable."""

import base64
import io

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from pixelperfect.io import to_png_bytes  # noqa: E402
from pixelperfect.web.api import app  # noqa: E402


@pytest.fixture
def client(synth):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def damaged_png(synth):
    make_native, distort = synth
    native = make_native(0, 16, 16, 8)
    return to_png_bytes(distort(native, blur=1.0))


def _files(png):
    return {"file": ("m.png", png, "image/png")}


def test_index_and_palettes(client):
    assert client.get("/").status_code == 200
    assert "sweetie-16" in client.get("/api/palettes").json()


def test_analyze(client, damaged_png):
    d = client.post("/api/analyze", files=_files(damaged_png)).json()
    assert (d["nx"], d["ny"]) == (16, 16)
    assert 0.0 <= d["confidence"] <= 1.0
    assert d["confidence_map"].startswith("data:image/png")


def test_restore_returns_pixel_perfect(client, damaged_png):
    d = client.post(
        "/api/restore", files=_files(damaged_png), data={"palette_size": "8", "upscale": "6"}
    ).json()
    assert (d["nx"], d["ny"]) == (16, 16)
    native = np.array(Image.open(io.BytesIO(base64.b64decode(d["native_png"].split(",")[1]))))
    assert native.shape[:2] == (16, 16)
    assert d["n_colors"] <= 8


def test_stage_endpoints(client, damaged_png):
    for ep in ("/api/denoise", "/api/detect-grid"):
        r = client.post(ep, files=_files(damaged_png))
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    r = client.post("/api/quantize", files=_files(damaged_png), data={"palette_name": "pico-8"})
    assert r.status_code == 200


def test_non_image_upload_returns_400(client):
    r = client.post("/api/restore", files={"file": ("x.txt", b"not an image", "text/plain")})
    assert r.status_code == 400


def test_empty_upload_returns_400(client):
    r = client.post("/api/restore", files={"file": ("e.png", b"", "image/png")})
    assert r.status_code == 400


@pytest.mark.parametrize(
    "data",
    [{"palette_size": "abc"}, {"method": "nope"}, {"palette_name": "nope"}, {"interior": "x"}],
)
def test_bad_params_return_422(client, damaged_png, data):
    r = client.post("/api/restore", files=_files(damaged_png), data=data)
    assert r.status_code == 422


def test_no_stack_trace_in_error_body(client):
    r = client.post("/api/restore", files={"file": ("x.txt", b"nope", "text/plain")})
    body = r.text.lower()
    assert "traceback" not in body and "/users/" not in body
