# Contributing to Pixel-Perfect

Thanks for your interest! This project welcomes issues and pull requests.

## Development setup

```bash
git clone https://github.com/ventz/pixel-perfect
cd pixel-perfect
uv sync --extra dev      # installs runtime + dev (pytest, httpx) deps
```

Run the tool from the source checkout:

```bash
uv run pixelperfect restore examples/messy_sprite.jpg /tmp/out.png --palette 8
uv run app.py            # web UI at http://127.0.0.1:8000
```

## Running the tests

```bash
uv run python -m pytest
```

The suite (`tests/`) manufactures ground-truth sprites, damages them like an AI
generator would (drift + blur + JPEG), and asserts exact grid recovery and
perceptually-faithful palettes. Please add or update tests for any behavior
change. New algorithmic work should include a round-trip case in
`tests/test_pipeline.py` or an edge case in `tests/test_edge_cases.py`.

To keep dependency resolution reproducible in CI, install with the lockfile:

```bash
uv sync --locked --extra dev
```

## Project layout

```
app.py          # web-app launcher (uv run app.py)
cli.py          # run the CLI from a source checkout
src/pixelperfect/
  color.py      # sRGB <-> OKLab, perceptual distance
  denoise.py    # JPEG/artifact cleanup
  grid.py       # period detection + drift-tolerant gridline fit (the crux)
  sample.py     # per-cell color (eroded-interior median in OKLab)
  score.py      # reconstruction-residual scoring + confidence
  palette.py    # OKLab quantization + named palettes
  editor.py     # indexed palette + grid -> RGBA render/export
  pipeline.py   # orchestration + PipelineParams
  io.py         # image load/encode (with size/format guards)
  cli.py        # Typer CLI
  web/api.py    # FastAPI service
  web/static/   # web UI (index.html, editor.js, logo.svg) — no build step
tests/          # pytest suite (synthetic sprites + API smoke tests)
```

See [docs/architecture.md](docs/architecture.md) for how the pieces fit.

## Code style

- Follow the conventions already in the file you're editing (naming, docstring
  density, type hints). The codebase uses `from __future__ import annotations`
  and concise module docstrings explaining *why*, not just *what*.
- Keep core library functions pure (NumPy in, NumPy out) so the CLI, API, and
  tests can share them.
- No new runtime dependencies without discussion in an issue first.

## Pull requests

1. Open an issue describing the change for anything non-trivial.
2. Branch, make the change, add tests, ensure `pytest` is green.
3. Keep PRs focused and describe the user-facing effect.

## Reporting bugs

Open a GitHub issue with: what you ran, the input (or a description), what you
expected, and what happened. For grid-detection issues, the output of
`pixelperfect analyze <image>` is very helpful.

For **security** issues, do not open a public issue — see [SECURITY.md](SECURITY.md).
