# Getting Started

By the end of this tutorial you will have installed Pixel-Perfect and turned a
blurry, AI-generated "pixel art" image into a true pixel-perfect PNG — once from
the command line, and once in the web app.

## Prerequisites

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/) (recommended) — or plain `pip`

## 1. Install

```bash
git clone https://github.com/ventz/pixel-perfect
cd pixel-perfect
uv sync
```

This creates a virtual environment and installs everything. (With pip:
`pip install -e .`)

## 2. Get a test image

The repo ships a deliberately messy sample at `examples/messy_sprite.jpg` — a
16×16 sprite that was upscaled with drift, blurred, and JPEG-compressed. Use it,
or any AI-generated pixel-art image of your own.

## 3. Restore it from the CLI

```bash
uv run pixelperfect restore examples/messy_sprite.jpg clean.png --palette 8 --upscale 8
```

You'll see:

```
messy_sprite.jpg -> clean.png  [16x16, 8 colors, conf 0.98]
  preview: clean_x8.png
```

What happened:

- `clean.png` is the **true native image** — exactly 16×16 pixels, one image
  pixel per logical pixel.
- `clean_x8.png` is the same image **nearest-neighbor upscaled 8×** for easy
  viewing (open this one to see it crisp).
- `conf 0.98` is the detection **confidence** — high means the grid was found
  cleanly.

Open `clean_x8.png`. The cells are now uniform, the edges are hard, and there
are exactly 8 colors.

## 4. Inspect detection without changing anything

```bash
uv run pixelperfect analyze examples/messy_sprite.jpg
```

This reports the detected grid, the candidate grid sizes it considered, the
confidence, and how many cells were ambiguous — useful before committing to a
restore.

## 5. Do it in the web app

```bash
uv run app.py
```

Open <http://127.0.0.1:8000>, drag your image onto the drop zone, and click
**Make pixel-perfect**. You'll get a before/after view, a **confidence
heatmap** (green = solid, red = ambiguous), the extracted palette, and a
download button.

Use the sliders on the left to override the palette size, force a specific
native grid size, or adjust denoising — see
[Fix a hard case](how-to/fix-hard-cases.md) for when you'd want to.

## Next steps

- [Batch-process a whole folder](how-to/batch-processing.md)
- [Snap output to a named palette](how-to/use-named-palettes.md)
- [Understand how grid detection works](architecture.md)
- [Configuration reference](reference/configuration.md) — every option
