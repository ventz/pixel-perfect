# Configuration Reference

Every option lives on `pixelperfect.PipelineParams`, the single knob-set passed
to `restore()` and `analyze()`. The CLI flags and API form fields map directly
onto these fields.

```python
from pixelperfect import restore, PipelineParams

result = restore(rgb_array, PipelineParams(
    native_w=32, native_h=32,
    palette_size=16,
    upscale=8,
))
```

## Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `denoise_strength` | float | `1.0` | Edge-preserving denoise strength. `0` disables. Higher = more aggressive (helps very noisy JPEGs, risks softening fine detail). Must be finite and ≥ 0; clamped to 10. |
| `native_w` | int \| None | `None` | Force grid width in cells. `None` = auto-detect. 1–512, and no larger than the image width. |
| `native_h` | int \| None | `None` | Force grid height in cells. `None` = auto-detect. 1–512, and no larger than the image height. |
| `palette_size` | int \| None | `None` | Max palette colors. `None` = auto color-count via perceptual merge. Clamped to 1–256. |
| `palette_name` | str \| None | `None` | Snap to a built-in palette instead of deriving one. One of `sweetie-16`, `pico-8`, `endesga-32`. |
| `interior_frac` | float | `0.5` | Central fraction of each cell that votes for its color. Lower ignores more of the anti-aliased rim. Must be in (0, 1]. |
| `sample_method` | str | `median` | Per-cell color statistic: `median` (robust default), `mode`, `medoid` (real color, no invention), `mean`. |
| `merge_threshold` | float | `0.035` | OKLab ΔE below which colors fuse during auto palette derivation. |
| `upscale` | int | `0` | Nearest-neighbor preview factor. `0` = no preview. Clamped to 0–32, and further reduced so the preview stays within 16 MP (`MAX_OUTPUT_PIXELS`). |
| `top_k` | int | `4` | Candidate cell-counts scored per axis during detection. Clamped to 1–16. |
| `fit_smoothness` | float | `0.5` | Drift-fit stiffness: the penalty on each cell width's deviation from the mean period. Higher keeps cells nearer uniform; lower lets lines chase edges. |
| `fit_window_frac` | float | `0.35` | Maximum deviation of any single cell's width from the mean period, as a fraction (0.35 = ±35%). Drift may accumulate across cells within this bound. Must be in (0, 1). |

`PipelineParams(...).validate()` checks and clamps these; `restore()`/`analyze()`
call it for you and raise `ValueError` on an invalid `sample_method` or
`palette_name`, a non-finite number, an out-of-range `interior_frac` or
`fit_window_frac`, a negative `denoise_strength`/`merge_threshold`/
`fit_smoothness`, or a `native_w`/`native_h` outside 1–512 or larger than the
image.

## Result object

`restore()` returns a `PipelineResult`:

| Attribute | Description |
|-----------|-------------|
| `native` | `(ny, nx, 3 or 4)` uint8 — the pixel-perfect image (1 pixel per cell). |
| `preview` | NN-upscaled `native` (if `upscale > 1`), else `None`. |
| `palette` | `(K, 3)` uint8 palette actually used. |
| `nx`, `ny` | Detected/used grid dimensions. |
| `score.confidence` | 0–1: how well the result explains the source. |
| `score.grid_confidence` | 0–1: how much periodic edge structure supports the detected cell size; `None` when the size was forced. |
| `score.fallback` | `True` if no grid was detected and a default 16×16 grid was used. |
| `score.residual` | OKLab reconstruction residual (lower is better). |
| `score.confidence_map()` | `(ny, nx)` uint8 per-cell confidence heatmap. |

## Tuning guide

| Symptom | Try |
|---------|-----|
| Wrong grid size detected (often with low `grid_confidence`) | Set `native_w`/`native_h` explicitly. |
| Size off by one on sparse line art or very small (~5 px) cells | Force `native_w`/`native_h`. |
| Colors look washed out | Lower `interior_frac` (e.g. 0.35) to avoid AA bleed. |
| Too many near-duplicate colors | Set `palette_size`, or raise `merge_threshold`. |
| Grid wobbles on a clean image | Raise `fit_smoothness`. |
| Grid misses real drift | Lower `fit_smoothness`, raise `fit_window_frac`. |
| Heavy JPEG artifacts | Raise `denoise_strength` to 1.5–2. |

See [Fix a hard case](../how-to/fix-hard-cases.md) for a worked example.
