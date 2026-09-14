"""FastAPI service exposing the pixel-perfect pipeline.

Every stage is an independent endpoint so the tool is fully API-callable (the
browser UI is just one consumer):

    POST /api/analyze       -> detect grid + confidence (no mutation)
    POST /api/restore       -> full pipeline, returns native + preview + palette
    POST /api/denoise       -> just the denoise stage
    POST /api/detect-grid   -> grid as an overlay on the source
    POST /api/quantize      -> reduce an image's palette (treats pixels as cells)
    POST /api/export        -> render an edited indexed document to PNG
    GET  /api/palettes      -> built-in named palettes

Run: ``uvicorn pixelperfect.web.api:app --reload`` then open http://localhost:8000

Security posture: this service is unauthenticated and compute-intensive. It
binds to localhost by default. Request bodies are capped before they are read,
decoded images are capped by pixel count, inputs are validated, and heavy work
runs off the event loop behind a small concurrency limit — but if you expose it
to a network put it behind a reverse proxy with TLS, auth, and rate limiting.
See SECURITY.md.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from .. import io as _io
from ..denoise import denoise
from ..editor import MAX_EDIT_PIXELS, EditPayloadError, export_indexed
from ..palette import BUILTIN_PALETTES, quantize as _quantize
from ..pipeline import (
    PipelineParams,
    analyze as _analyze,
    clamp_upscale,
    restore as _restore,
    upscale as _upscale,
)
from ..sample import CellField

log = logging.getLogger("pixelperfect")

app = FastAPI(title="pixelperfect", version=__version__)

_STATIC = os.path.join(os.path.dirname(__file__), "static")

# Max upload size (bytes). A decoded-pixel cap also lives in pixelperfect.io.
MAX_UPLOAD_BYTES = int(os.environ.get("PIXELPERFECT_MAX_UPLOAD_MB", "20")) * 1024 * 1024
# Whole-request cap: the upload plus multipart framing / form fields.
MAX_BODY_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024

# Concurrent image jobs. Each can use significant CPU/RAM; extra requests wait.
MAX_JOBS = max(1, int(os.environ.get("PIXELPERFECT_MAX_JOBS", "2")))
_jobs: asyncio.Semaphore | None = None

# Optional CORS allow-list (comma-separated origins). Empty = same-origin only.
_CORS = [o.strip() for o in os.environ.get("PIXELPERFECT_ALLOW_ORIGINS", "").split(",") if o.strip()]
if _CORS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject request bodies over ``limit`` bytes *before* they are buffered.

    FastAPI parses multipart forms (spooling files to disk) before an endpoint
    runs, so a size check inside the endpoint is too late. This checks
    ``Content-Length`` up front and counts streamed bytes for chunked requests.
    """

    def __init__(self, app, limit: int):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            return await self._reject(send)

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send):
        body = json.dumps(
            {"detail": f"Request exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


app.add_middleware(BodySizeLimitMiddleware, limit=MAX_BODY_BYTES)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace to clients; log server-side instead."""
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"error": "Internal processing error."}, status_code=500)


async def _run(fn, *args):
    """Run CPU-heavy work off the event loop, limited to ``MAX_JOBS`` at once.

    ``ValueError`` from parameter validation becomes a 422.
    """
    global _jobs
    if _jobs is None:
        _jobs = asyncio.Semaphore(MAX_JOBS)
    async with _jobs:
        try:
            return await run_in_threadpool(fn, *args)
        except (_io.ImageTooLargeError, _io.UnsupportedImageError):
            raise
        except ValueError as e:
            raise HTTPException(422, str(e))


async def _load_upload(file: UploadFile) -> np.ndarray:
    """Read an upload (size-capped) and decode it, mapping failures to 4xx."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    if not size:
        raise HTTPException(400, "Empty upload.")
    try:
        return await run_in_threadpool(_io.load_bytes, b"".join(chunks))
    except (_io.ImageTooLargeError, _io.UnsupportedImageError) as e:
        raise HTTPException(413, str(e))
    except Exception:
        raise HTTPException(400, "Could not decode image. Upload a PNG, JPEG, WebP, GIF, or BMP.")


def _b64_png(arr: np.ndarray) -> str:
    return "data:image/png;base64," + base64.b64encode(_io.to_png_bytes(arr)).decode()


def _hexes(palette: np.ndarray) -> list[str]:
    return ["#%02x%02x%02x" % tuple(int(v) for v in c) for c in palette]


def _opt_int(v, name: str):
    if v in (None, "", "0", 0):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{name} must be an integer, got {v!r}.")


def _flt(v, name: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{name} must be a number, got {v!r}.")


def _validated(params: PipelineParams) -> PipelineParams:
    try:
        return params.validate()
    except ValueError as e:
        raise HTTPException(422, str(e))


def _params_from_form(
    native_w, native_h, palette_size, palette_name, denoise_strength, method, interior, upscale
) -> PipelineParams:
    return _validated(
        PipelineParams(
            native_w=_opt_int(native_w, "native_w"),
            native_h=_opt_int(native_h, "native_h"),
            palette_size=_opt_int(palette_size, "palette_size"),
            palette_name=palette_name or None,
            denoise_strength=_flt(denoise_strength, "denoise_strength"),
            sample_method=method or "median",
            interior_frac=_flt(interior, "interior"),
            upscale=_opt_int(upscale, "upscale") or 0,
        )
    )


def _round_opt(v, digits):
    return None if v is None else round(v, digits)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with open(os.path.join(_STATIC, "index.html")) as f:
        return HTMLResponse(f.read())


@app.get("/api/palettes")
def palettes() -> JSONResponse:
    return JSONResponse({name: _hexes(pal) for name, pal in BUILTIN_PALETTES.items()})


@app.post("/api/analyze")
async def api_analyze(file: UploadFile = File(...), denoise_strength: str = Form("1.0")) -> JSONResponse:
    rgb = await _load_upload(file)
    params = _validated(PipelineParams(denoise_strength=_flt(denoise_strength, "denoise_strength")))
    score, diag = await _run(_analyze, rgb, params)
    return JSONResponse(
        {
            "nx": score.grid.nx,
            "ny": score.grid.ny,
            "period_x": round(diag["period_x"], 2),
            "period_y": round(diag["period_y"], 2),
            "x_candidates": diag["x_candidates"],
            "y_candidates": diag["y_candidates"],
            "confidence": round(score.confidence, 3),
            "grid_confidence": _round_opt(score.grid_confidence, 3),
            "fallback": score.fallback,
            "residual": round(score.residual, 4),
            "confidence_map": _b64_png(_upscale(_gray_to_rgb(score.confidence_map()), 8)),
        }
    )


@app.post("/api/restore")
async def api_restore(
    file: UploadFile = File(...),
    native_w: str | None = Form(None),
    native_h: str | None = Form(None),
    palette_size: str | None = Form(None),
    palette_name: str | None = Form(None),
    denoise_strength: str = Form("1.0"),
    method: str = Form("median"),
    interior: str = Form("0.5"),
    upscale: str | None = Form("8"),
) -> JSONResponse:
    rgb = await _load_upload(file)
    params = _params_from_form(
        native_w, native_h, palette_size, palette_name, denoise_strength, method, interior, upscale
    )
    res = await _run(_restore, rgb, params)
    preview = res.preview if res.preview is not None else res.native
    return JSONResponse(
        {
            "nx": res.nx,
            "ny": res.ny,
            "n_colors": int(len(res.palette)),
            "palette": _hexes(res.palette),
            "confidence": round(res.score.confidence, 3),
            "grid_confidence": _round_opt(res.score.grid_confidence, 3),
            "fallback": res.score.fallback,
            "residual": round(res.score.residual, 4),
            "native_png": _b64_png(res.native),
            "preview_png": _b64_png(preview),
            "confidence_map": _b64_png(_upscale(_gray_to_rgb(res.score.confidence_map()), 8)),
        }
    )


@app.post("/api/denoise")
async def api_denoise(file: UploadFile = File(...), denoise_strength: str = Form("1.0")) -> Response:
    rgb = await _load_upload(file)
    params = _validated(PipelineParams(denoise_strength=_flt(denoise_strength, "denoise_strength")))
    out = await _run(denoise, rgb, params.denoise_strength)  # alpha passes through
    return Response(_io.to_png_bytes(out), media_type="image/png")


@app.post("/api/detect-grid")
async def api_detect_grid(file: UploadFile = File(...), denoise_strength: str = Form("1.0")) -> Response:
    rgb = await _load_upload(file)
    params = _validated(PipelineParams(denoise_strength=_flt(denoise_strength, "denoise_strength")))
    score, _ = await _run(_analyze, rgb, params)
    return Response(_io.to_png_bytes(_overlay_grid(rgb[..., :3], score.grid)), media_type="image/png")


def _quantize_image(rgb: np.ndarray, params: PipelineParams) -> np.ndarray:
    alpha = rgb[..., 3] if rgb.shape[-1] == 4 else None
    cell_alpha = None if alpha is None else np.where(alpha >= 128, 255, 0).astype(np.uint8)
    field = CellField(rgb[..., :3].astype(np.uint8), cell_alpha)
    pal = BUILTIN_PALETTES.get(params.palette_name) if params.palette_name else None
    out, _ = _quantize(field, max_colors=params.palette_size, palette=pal)
    # Keep the source's own alpha (not the thresholded mask) in the output.
    return out.rgb if alpha is None else np.dstack([out.rgb, alpha])


@app.post("/api/quantize")
async def api_quantize(
    file: UploadFile = File(...),
    palette_size: str | None = Form(None),
    palette_name: str | None = Form(None),
) -> Response:
    """Reduce an image's palette directly (each pixel treated as a cell).

    Unique colors are pre-merged before clustering, so memory stays bounded even
    for photo-like uploads; alpha is preserved.
    """
    rgb = await _load_upload(file)
    params = _validated(
        PipelineParams(
            palette_size=_opt_int(palette_size, "palette_size"),
            palette_name=palette_name or None,
        )
    )
    out = await _run(_quantize_image, rgb, params)
    return Response(_io.to_png_bytes(out), media_type="image/png")


class ExportRequest(BaseModel):
    """Indexed-document export payload from the editor (or automation)."""

    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    palette: list[str] = Field(..., min_length=1, max_length=4096)
    indices: list[int] = Field(..., max_length=MAX_EDIT_PIXELS)
    upscale: int = Field(0, ge=0)


@app.post("/api/export")
def api_export(req: ExportRequest) -> JSONResponse:
    """Render an edited indexed document to a pixel-perfect PNG (+ optional N×).

    Mirrors the editor's canonical state so manual edits go through the same
    rendering path as the rest of the tool.
    """
    try:
        native, preview = export_indexed(req.width, req.height, req.palette, req.indices, req.upscale)
    except EditPayloadError as e:
        raise HTTPException(422, str(e))
    factor = clamp_upscale(req.width, req.height, req.upscale)
    out = {
        "width": req.width,
        "height": req.height,
        "n_colors": int(len(set(i for i in req.indices if i >= 0))),
        "upscale": factor,
        "native_png": _b64_png(native),
        "preview_png": _b64_png(preview if preview is not None else native),
    }
    return JSONResponse(out)


def _gray_to_rgb(gray: np.ndarray) -> np.ndarray:
    """Map a confidence map to a red(low)->green(high) heatmap RGB image."""
    g = gray.astype(np.float64) / 255.0
    rgb = np.zeros(gray.shape + (3,), np.uint8)
    rgb[..., 0] = np.round((1 - g) * 255)
    rgb[..., 1] = np.round(g * 200)
    return rgb


def _overlay_grid(rgb: np.ndarray, grid) -> np.ndarray:
    out = rgb.copy()
    h, w = out.shape[:2]
    for x in np.round(grid.x_bounds).astype(int):
        out[:, min(x, w - 1)] = (255, 0, 128)
    for y in np.round(grid.y_bounds).astype(int):
        out[min(y, h - 1), :] = (255, 0, 128)
    return out


# Static assets (after routes so "/" stays the HTML entry point).
if os.path.isdir(_STATIC):
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
