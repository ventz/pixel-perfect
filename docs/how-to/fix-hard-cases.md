# Fix a hard case the auto-detector got wrong

Auto-detection lands the grid on ~90% of real images. The rest — usually
heavily blurred or extremely drifted generations — may come out off by one cell
or with washed colors. Here's how to fix them.

## 1. Confirm what was detected

```bash
uv run pixelperfect analyze messy.png
```

Look at the detected `nx × ny`, the **confidence**, and the **low-confidence
cell count**. In the web app, the **confidence heatmap** shows *where* the
detection is unsure (red cells).

## 2. Force the native grid size

If you know (or can count) the intended resolution, set it explicitly — this
skips auto-detection of `N` entirely:

```bash
uv run pixelperfect restore messy.png out.png --native 32
# or non-square:
uv run pixelperfect restore messy.png out.png --native-w 48 --native-h 32
```

In the web app, type the size into the **Native size override** boxes.

This alone fixes the most common failure (off-by-one `N`).

## 3. Fix washed-out colors

Blur bleeds neighboring colors into each cell's rim. Shrink the voting region so
only the clean center counts:

```bash
uv run pixelperfect restore messy.png out.png --interior 0.35
```

For very noisy JPEGs, also raise denoising: `--denoise 1.8`.

## 4. Fix a wobbly or over-eager grid

- Grid wobbles on an image that's actually uniform → raise stiffness:
  `PipelineParams(fit_smoothness=2.0)`.
- Grid fails to follow genuine drift → lower stiffness and widen the search:
  `PipelineParams(fit_smoothness=0.2, fit_window_frac=0.45)`.

(These two are library-only options; see the
[Configuration reference](../reference/configuration.md).)

## 5. When recovery isn't possible

If a generation is so blurred that even a forced grid looks wrong, there is no
unique "true" image to recover. The better fix is upstream: see
[Fixing pixel art at generation time](../explanation/generation.md) and use the
generate → restore → confidence-gate loop to reject bad generations before they
reach you.
