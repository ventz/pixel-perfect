# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Grid-size selection now weighs agreement with the measured cell period, fixing
  two off-by-one cases: very small (~5 px) cells detected one cell too fine
  (33 instead of 32), and sparse sprites where a smaller count tied with the
  true one (37 instead of 40). On sprites with wide empty margins, the number of
  margin cells may differ by one or two from 0.1.0; the sprite's cells are
  unchanged.

## [0.1.0] — 2026-09-14

Initial public release.

### Added
- **Manual pixel editor** in the web app: open the restored result in an
  in-browser canvas editor to fix pixels by hand. Tools: pencil, eraser, flood
  fill, eyedropper, undo/redo, zoom, grid + confidence-heatmap overlays.
  Palette-first colors (recolor a swatch to update all matching pixels) plus any
  RGB via "Add color". Exports a true 1× native PNG and an N× preview.
- `POST /api/export` endpoint and `pixelperfect.render_indexed()` /
  `export_indexed()` library functions — render an indexed document (palette +
  index grid) to a pixel-perfect PNG, shared by the editor and automation.
- Core restoration pipeline: denoise → grid-period detection → drift-tolerant
  gridline fit → eroded-interior cell collapse (OKLab) → reconstruction-residual
  scoring → perceptual palette quantization.
- Reconstruction-residual grid selection with a per-cell confidence heatmap.
- Three surfaces over one core: Python library, Typer CLI (`pixelperfect`,
  `python -m pixelperfect`), and a FastAPI web app with per-stage endpoints.
- Web UI with drag-and-drop, before/after, confidence heatmap, palette swatches,
  and manual overrides (native size, palette size, denoise, interior, method).
- Built-in named palettes: Sweetie-16, PICO-8, Endesga-32.
- Generation-side guidance and a runnable generate → restore → confidence-gate
  example.

- `grid_confidence` and `fallback` in results, the API, and `pixelperfect
  analyze`: how much periodic structure supports the detected cell size, and
  whether a default grid had to be used.
- CI on Python 3.11–3.13.

### Detection quality
- Gridline fit is a dynamic program over every integer position with a per-cell
  width constraint, so drift can accumulate across the image (e.g. 17 px cells
  followed by 15 px cells) and uneven margins are absorbed.
- Edge profiles use OKLab color (not luminance) and are alpha-aware: edges
  between equally bright colors are detected, and hidden RGB under transparent
  pixels no longer influences detection, color sampling, or scoring.
- Sub-pixel period estimation from autocorrelation harmonics; FFT estimates that
  conflict with autocorrelation (other than 1/2 or 1/3 of it) are ignored.
- Grid selection uses a relative tie tolerance and never lets an exact
  subdivision win a tie.
- Sparse line art is no longer detected at half resolution: when a chosen axis
  has edges inside its cells, about twice as many cells are tried and kept only
  if the fit clearly improves.
- Palette clusters are represented by the real color nearest their weighted
  center instead of the most frequent member.
- Transparency in palette PNG/GIF and RGB PNG metadata is loaded as alpha.

### Performance
- Cell collapse and residual scoring are vectorized; the image's OKLab
  conversion, edge profiles, and per-axis fits are computed once per image. The
  test suite runs in roughly half the time.

### Security
- Upload size cap (`PIXELPERFECT_MAX_UPLOAD_MB`, default 20 MB), enforced by a
  request-body middleware before multipart parsing.
- Decompression-bomb guard (~4 MP decoded-image cap, including Pillow's own bomb
  error, as `413`) and image-format allow-list.
- Bounded work: forced grid sizes (1–512 and no larger than the image), previews
  (16 MP), export payload lengths, and palette-clustering memory are all capped.
- Image processing runs off the event loop behind a concurrency limit
  (`PIXELPERFECT_MAX_JOBS`, default 2).
- Input validation with `4xx` responses, including non-finite numbers; generic
  `500` with no stack-trace leak.
- CORS closed by default (`PIXELPERFECT_ALLOW_ORIGINS` to opt in); localhost bind
  by default.

### Fixed
- `--batch` no longer stops at the first unreadable file.
- `/api/denoise` and `/api/quantize` preserve alpha.
- `select_grid`'s `interior_frac` default aligned to 0.5 with the rest of the
  pipeline.

[Unreleased]: https://github.com/ventz/pixel-perfect/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ventz/pixel-perfect/releases/tag/v0.1.0
