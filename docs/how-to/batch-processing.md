# Batch-process a folder

Restore many images at once.

## CLI

Pass a quoted glob as the source and a directory as the destination, with
`--batch`:

```bash
uv run pixelperfect restore "sprites/*.png" out/ --batch --palette 16
```

- Each input is restored independently with the same options.
- Outputs are written to `out/<name>.png` (the directory is created if needed).
- A per-file line reports the detected grid, color count, and confidence.

Apply any [restore options](../reference/cli.md#restore) to the whole batch, e.g.
force a size and snap to a palette:

```bash
uv run pixelperfect restore "raw/*.jpg" clean/ --batch --native 32 --palette-name endesga-32
```

## Python

For more control (e.g. per-file sizes, collecting confidences), loop over the
library directly:

```python
from pathlib import Path
from pixelperfect import restore, PipelineParams
from pixelperfect.io import load_rgb, save_png

params = PipelineParams(palette_size=16, upscale=8)
for src in Path("sprites").glob("*.png"):
    res = restore(load_rgb(str(src)), params)
    save_png(res.native, f"out/{src.stem}.png")
    if res.score.confidence < 0.8:
        print(f"⚠ low confidence on {src.name}: {res.score.confidence:.2f}")
```

Gating on `confidence` lets you flag images that need a manual pass — see
[Fix a hard case](fix-hard-cases.md).
