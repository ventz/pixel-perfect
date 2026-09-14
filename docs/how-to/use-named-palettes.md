# Snap to a named palette

Force the output to use a fixed art palette instead of an auto-derived one —
useful for keeping a whole sprite set on the same colors.

## Available palettes

```bash
uv run pixelperfect palettes
```

Built in: `sweetie-16` (16), `pico-8` (16), `endesga-32` (32). Fetch them as
hex over the API at `GET /api/palettes`.

## CLI

```bash
uv run pixelperfect restore in.png out.png --palette-name pico-8
```

Every output cell is snapped to its nearest palette color in OKLab
(perceptual), so the result uses *only* those colors.

## Web app

Pick a palette from the **"Or snap to a named palette"** dropdown, then
**Make pixel-perfect**.

## Python

```python
from pixelperfect import restore, PipelineParams
res = restore(rgb, PipelineParams(palette_name="sweetie-16"))
```

## Use your own palette (library)

Pass an explicit `(K, 3)` uint8 array to the lower-level quantizer:

```python
import numpy as np
from pixelperfect import restore, PipelineParams
from pixelperfect.palette import apply_palette, hex_to_rgb
from pixelperfect.sample import CellField

res = restore(rgb, PipelineParams())            # auto palette first
my_palette = hex_to_rgb(["#000000", "#ffffff", "#ff004d", "#29adff"])
snapped = apply_palette(CellField(res.native[..., :3]), my_palette)
# snapped.rgb now uses only your four colors
```

> **Tip**: auto color-count (omit `palette_size`) often produces a tighter,
> more faithful palette than a fixed one. Use named palettes when consistency
> across many sprites matters more than per-image fidelity.
