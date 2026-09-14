# HTTP API Reference

The FastAPI service (`pixelperfect.web.api:app`) exposes every pipeline stage as
an endpoint. Start it with `uv run app.py` (binds `127.0.0.1:8000`) or
`uvicorn pixelperfect.web.api:app`. Interactive docs are available at `/docs`
(Swagger UI) when the server is running.

> **Audience**: developers integrating the tool. For end-user usage, see the
> [web app in Getting Started](../getting-started.md#5-do-it-in-the-web-app).

## Conventions

- All processing endpoints take `multipart/form-data` with a `file` field.
- Request bodies are capped *before* they are read (default 20 MB;
  `PIXELPERFECT_MAX_UPLOAD_MB`), and decoded images are capped at ~4 MP.
  Allowed formats: PNG, JPEG, WebP, GIF, BMP. Transparency is preserved,
  including palette-PNG/GIF transparency.
- Image processing runs off the event loop, at most `PIXELPERFECT_MAX_JOBS`
  (default 2) at a time; further requests wait their turn.
- Client errors return JSON `{"detail": "..."}`; unexpected errors return
  `{"error": "Internal processing error."}` — never a stack trace.

| Status | Meaning |
|--------|---------|
| `400` | Empty or undecodable upload |
| `413` | Request too large / image too many pixels (including decompression bombs) |
| `422` | Invalid parameter (non-numeric, non-finite, out of range, native size larger than the image, unknown method/palette) |
| `500` | Unexpected server error (generic message) |

---

## `GET /`
Serves the web UI (HTML).

## `GET /api/palettes`
Returns built-in palettes as `{name: ["#rrggbb", ...]}`.

## `POST /api/analyze`
Detect the grid and confidence without producing an image.

| Field | Type | Default | |
|-------|------|---------|--|
| `file` | file | — | required |
| `denoise_strength` | float | `1.0` | |

**Response** (JSON): `nx`, `ny`, `period_x`, `period_y`, `x_candidates`,
`y_candidates`, `confidence`, `grid_confidence`, `fallback`, `residual`,
`confidence_map` (data-URI PNG).

- `confidence` (0–1) — how well the result explains the source.
- `grid_confidence` (0–1, or `null` when the size was forced) — how much
  periodic edge structure supports the detected cell size. Low values mean the
  size is a guess: check it, or force `native_w`/`native_h`.
- `fallback` — `true` when no pixel grid was detected and a default 16×16 grid
  was used.

## `POST /api/restore`
Full pipeline. Returns the pixel-perfect image plus diagnostics.

| Field | Type | Default | |
|-------|------|---------|--|
| `file` | file | — | required |
| `native_w`, `native_h` | int | auto | force grid size (cells); 1–512 and no larger than the image |
| `palette_size` | int | auto | max colors (clamped to 1–256) |
| `palette_name` | str | — | snap to a named palette |
| `denoise_strength` | float | `1.0` | 0–10 (clamped above 10) |
| `method` | str | `median` | `median`/`mode`/`medoid`/`mean` |
| `interior` | float | `0.5` | central cell fraction |
| `upscale` | int | `8` | preview factor (clamped to 32, and so the preview stays within 16 MP) |

**Response** (JSON): `nx`, `ny`, `n_colors`, `palette` (hex list), `confidence`,
`grid_confidence`, `fallback`, `residual`, `native_png` (data-URI),
`preview_png` (data-URI), `confidence_map` (data-URI).

```bash
curl -F file=@messy.png -F palette_size=16 http://127.0.0.1:8000/api/restore
```

## `POST /api/denoise`
Just the denoise stage. Returns `image/png` (alpha preserved).

| Field | Type | Default |
|-------|------|---------|
| `file` | file | required |
| `denoise_strength` | float | `1.0` |

## `POST /api/detect-grid`
Returns the source PNG with the detected gridlines overlaid (`image/png`).

| Field | Type | Default |
|-------|------|---------|
| `file` | file | required |
| `denoise_strength` | float | `1.0` |

## `POST /api/quantize`
Reduce an image's palette directly (each pixel treated as a cell). Returns
`image/png` with the source alpha preserved. Unique colors are pre-merged before
clustering, so memory stays bounded even for photo-like uploads.

| Field | Type | Default |
|-------|------|---------|
| `file` | file | required |
| `palette_size` | int | auto (clamped to 1–256) |
| `palette_name` | str | — |

## `POST /api/export`
Render an **indexed document** (the pixel editor's canonical state, or any
automation's) to a pixel-perfect PNG plus an optional N× preview. Takes a JSON
body, not form-data.

```json
{
  "width": 16,
  "height": 16,
  "palette": ["#1a1c2c", "#b13e53", "#38b764ff"],
  "indices": [0, 1, 2, -1, ...],
  "upscale": 8
}
```

| Field | Type | Notes |
|-------|------|-------|
| `width`, `height` | int | Grid size; `width*height` must equal `len(indices)`. Max 512×512. |
| `palette` | string[] | Hex colors, `#rrggbb` or `#rrggbbaa`. At most 4096. |
| `indices` | int[] | Row-major palette indices. `-1` = transparent. At most 262,144. |
| `upscale` | int | Preview factor (0 = none; clamped to 32 and to a 16 MP preview). |

**Response** (JSON): `width`, `height`, `n_colors`, `upscale`, `native_png`
(data-URI), `preview_png` (data-URI). Invalid payloads return `422`.

The same rendering is available in Python via `pixelperfect.render_indexed()`
and `pixelperfect.export_indexed()`.

## Configuration (environment)

| Variable | Default | Effect |
|----------|---------|--------|
| `PIXELPERFECT_MAX_UPLOAD_MB` | `20` | Max upload size in MB (the request-body cap adds 1 MB for form overhead). |
| `PIXELPERFECT_MAX_JOBS` | `2` | Max image-processing jobs running at once; extra requests queue. |
| `PIXELPERFECT_ALLOW_ORIGINS` | _(none)_ | Comma-separated CORS allow-list. Empty = same-origin only. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address for `app.py`. |
