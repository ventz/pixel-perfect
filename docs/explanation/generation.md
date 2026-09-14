# Fixing pixel art at generation time

This tool *restores* imperfect pixel art after the fact. But there is "a more
deeply rooted problem in the generation." This page explains **why** AI image
models can't natively produce true pixel art, and how to attack it at the
source — so the restorer has less to fix (or nothing to).

## Why AI output is never pixel-perfect

Three structural reasons, none of which prompting alone can fully fix:

1. **The VAE decoder blurs.** Diffusion models work in a compressed latent
   space and decode to pixels through a variational autoencoder trained on
   *photographs* with a smoothness loss. The decoder prefers soft gradients, so
   the hard 1-pixel edges pixel art requires get rounded off. This is baked into
   the model weights.
2. **The latent grid has no integer pixel concept.** UNet/transformer attention
   operates on continuous floating-point coordinates. Nothing forces "every
   block is exactly N×N", which is why cell sizes drift (15px next to 17px) and
   the grid sits off the integer lattice.
3. **The training data is already dirty.** Most images tagged "pixel art" in
   web-scale datasets are themselves JPEG-compressed, bilinear-upscaled messes.
   The model faithfully learns that *dirty* look as the target.

Net: even the best setup still benefits from a deterministic post-pass. The
right architecture is **generate → restore → confidence-gate**, not "get
generation perfect."

## Options, roughly best-first

### 1. Generate, then restore (what this repo does) — most reliable
Run any generator, then push the output through `restore()` /
[`POST /api/restore`](../reference/api.md#post-apirestore). Deterministic,
model-agnostic, gives a hard pixel-perfect guarantee. The confidence score tells
you when a generation was too far gone to recover cleanly, so you can auto-reject
and re-roll. See [`examples/generate_and_restore.py`](../../examples/generate_and_restore.py).

### 2. Constrained / native-resolution generation — fewer artifacts upstream
- **Pixel-art LoRAs / fine-tunes** (e.g. *PixelArt-XL* by nerijs, and many
  kohya-trained sprite LoRAs) bias the model toward sharper, grid-aligned output.
  They reduce but don't eliminate the defects.
- **Generate small, then nearest-neighbor upscale.** Ask for output at/near the
  true native size; never let the model emit a 1024px "pixel" image you then have
  to descale.
- **ComfyUI pixelization workflows** — community graphs that append a
  quantize + downscale node chain to generation.
- **Retro Diffusion / Astropulse** — ships a *pixel-aware VAE decoder* plus
  *K-Centroid* (per-block k-means) downsampling instead of bilinear, keeping
  edges crisp through decode. Closest thing to "native" pixel output.

### 3. Prompting — necessary but not sufficient
Helpful tokens: explicit native size ("16x16 sprite", "32x32"), "flat colors",
"no anti-aliasing", "limited palette", a named palette. Prompting nudges the
distribution but can't override the VAE/latent issues above. Treat it as a
multiplier on options 1–2, not a solution on its own.

## Recommended near-term setup

1. Generate with a pixel-art LoRA at/near native resolution (reduces work).
2. Pipe every output through `restore()` with a target native size and palette.
3. Gate on `result.score.confidence`; below threshold, regenerate.

This gets you clean sprites today without waiting on a perfect generator. The
runnable loop in [`examples/generate_and_restore.py`](../../examples/generate_and_restore.py)
shows the control flow — swap its stub `generate()` for your model call.
