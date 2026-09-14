# CLI Reference

Installed as the `pixelperfect` command (and runnable as `python -m
pixelperfect` or `uv run pixelperfect`). All three forms are identical.

```
pixelperfect [COMMAND] [ARGS] [OPTIONS]
```

Commands: [`restore`](#restore) · [`analyze`](#analyze) · [`palettes`](#palettes)

---

## `restore`

Restore one image (or many with `--batch`) to a pixel-perfect PNG.

```
pixelperfect restore SRC DST [OPTIONS]
```

| Argument | Description |
|----------|-------------|
| `SRC` | Input image path, or a glob (quote it) when `--batch`. |
| `DST` | Output PNG path, or a directory when `--batch`. |

| Option | Default | Description |
|--------|---------|-------------|
| `--native INT` | auto | Force a square native size (cells). |
| `--native-w INT` | auto | Force native width in cells. |
| `--native-h INT` | auto | Force native height in cells. |
| `--palette INT` | auto | Max palette colors. Omit for auto color-count. |
| `--palette-name NAME` | — | Snap to a built-in palette (see [`palettes`](#palettes)). |
| `--denoise FLOAT` | `1.0` | Denoise strength; `0` disables. |
| `--method NAME` | `median` | Per-cell color: `median`, `mode`, `medoid`, `mean`. |
| `--interior FLOAT` | `0.5` | Central cell fraction used for color (0–1). |
| `--upscale INT` | `0` | Also write an N× nearest-neighbor preview (named `<dst>_x<N>.png`; N is reduced if needed to keep the preview within 16 MP). |
| `--batch` | off | Treat `SRC` as a glob and `DST` as an output directory. |

Each option maps to a [`PipelineParams`](configuration.md) field.

**Examples**

```bash
# Auto everything
pixelperfect restore in.png out.png

# Force 32x32, 16 colors, write an 8x preview
pixelperfect restore in.png out.png --native 32 --palette 16 --upscale 8

# Snap to the PICO-8 palette
pixelperfect restore in.png out.png --palette-name pico-8

# Batch a folder
pixelperfect restore "sprites/*.png" out/ --batch --palette 16
```

**Exit codes**: `0` success · `1` input could not be read · `2` invalid parameters.
With `--batch`, a bad file is reported and skipped; the remaining files are still
processed, and the command exits with the worst code seen.

If no pixel grid can be detected, a default 16×16 grid is used and a warning is
printed.

---

## `analyze`

Report the detected grid, candidates, and confidence — without writing output.

```
pixelperfect analyze SRC [--denoise FLOAT]
```

Output includes the detected `nx × ny`, cell period, ranked candidate sizes,
confidence + residual, grid confidence (and whether a default grid was used),
and a count of low-confidence cells. See the
[API reference](api.md#post-apianalyze) for what each confidence means.

---

## `palettes`

List the built-in named palettes and their color counts.

```
pixelperfect palettes
```

Currently: `sweetie-16`, `pico-8`, `endesga-32`.
