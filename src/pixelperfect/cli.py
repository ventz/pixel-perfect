"""``pixelperfect`` command-line interface.

Thin wrapper over the core library so batch/scripted use hits the exact same
pipeline as the web UI.

    pixelperfect restore in.png out.png --palette 16 --upscale 8
    pixelperfect analyze in.png
    pixelperfect palettes
    pixelperfect restore "sprites/*.png" out_dir/ --batch
"""

from __future__ import annotations

import glob
import os

import typer

from . import io as _io
from .palette import BUILTIN_PALETTES
from .pipeline import PipelineParams, restore as _restore, analyze as _analyze

app = typer.Typer(add_completion=False, help="Restore AI 'pixel art' to true pixel-perfect images.")


def _params(
    native: int | None,
    native_w: int | None,
    native_h: int | None,
    palette: int | None,
    palette_name: str | None,
    denoise: float,
    method: str,
    interior: float,
    upscale: int,
) -> PipelineParams:
    return PipelineParams(
        native_w=native_w or native,
        native_h=native_h or native,
        palette_size=palette,
        palette_name=palette_name,
        denoise_strength=denoise,
        sample_method=method,
        interior_frac=interior,
        upscale=upscale,
    )


@app.command()
def restore(
    src: str = typer.Argument(..., help="Input image, or a glob when --batch."),
    dst: str = typer.Argument(..., help="Output PNG, or a directory when --batch."),
    native: int | None = typer.Option(None, help="Force square native size (cells)."),
    native_w: int | None = typer.Option(None, help="Force native width in cells."),
    native_h: int | None = typer.Option(None, help="Force native height in cells."),
    palette: int | None = typer.Option(None, help="Max palette colors (default: auto)."),
    palette_name: str | None = typer.Option(None, help=f"Snap to a named palette: {', '.join(BUILTIN_PALETTES)}."),
    denoise: float = typer.Option(1.0, help="Denoise strength (0 disables)."),
    method: str = typer.Option("median", help="Per-cell color: median|mode|medoid|mean."),
    interior: float = typer.Option(0.5, help="Central cell fraction used for color (0-1)."),
    upscale: int = typer.Option(0, help="Also write an Nx nearest-neighbor preview."),
    batch: bool = typer.Option(False, help="Treat src as a glob and dst as a directory."),
):
    """Restore one image (or many with --batch) to pixel-perfect PNG."""
    params = _params(native, native_w, native_h, palette, palette_name, denoise, method, interior, upscale)

    if batch:
        paths = sorted(glob.glob(src))
        if not paths:
            typer.secho(f"No files match: {src}", fg="red", err=True)
            raise typer.Exit(1)
        os.makedirs(dst, exist_ok=True)
        # Keep going past bad files; report and exit non-zero at the end.
        worst = 0
        for p in paths:
            out = os.path.join(dst, os.path.splitext(os.path.basename(p))[0] + ".png")
            worst = max(worst, _run_one(p, out, params))
        if worst:
            raise typer.Exit(worst)
    else:
        code = _run_one(src, dst, params)
        if code:
            raise typer.Exit(code)


def _run_one(src: str, dst: str, params: PipelineParams) -> int:
    """Restore one file. Returns 0 on success, 1 if unreadable, 2 on bad input."""
    try:
        rgb = _io.load_rgb(src)
    except (FileNotFoundError, OSError, ValueError) as e:
        typer.secho(f"Cannot read {src}: {e}", fg="red", err=True)
        return 1
    try:
        res = _restore(rgb, params)
    except ValueError as e:
        typer.secho(f"Error ({os.path.basename(src)}): {e}", fg="red", err=True)
        return 2
    _io.save_png(res.native, dst)
    typer.secho(
        f"{os.path.basename(src)} -> {os.path.basename(dst)}  "
        f"[{res.nx}x{res.ny}, {len(res.palette)} colors, conf {res.score.confidence:.2f}]",
        fg="green",
    )
    if res.score.fallback:
        typer.secho("  warning: no pixel grid detected; used a default 16x16 grid", fg="yellow", err=True)
    if res.preview is not None:
        factor = res.preview.shape[1] // res.nx
        prev = os.path.splitext(dst)[0] + f"_x{factor}.png"
        _io.save_png(res.preview, prev)
        typer.echo(f"  preview: {os.path.basename(prev)}")
    return 0


@app.command()
def analyze(
    src: str = typer.Argument(..., help="Input image."),
    denoise: float = typer.Option(1.0, help="Denoise strength (0 disables)."),
):
    """Report the detected grid, candidates, and confidence without writing output."""
    try:
        rgb = _io.load_rgb(src)
        score, diag = _analyze(rgb, PipelineParams(denoise_strength=denoise))
    except (FileNotFoundError, OSError, ValueError) as e:
        typer.secho(f"Error: {e}", fg="red", err=True)
        raise typer.Exit(1)
    typer.echo(f"detected grid : {score.grid.nx} x {score.grid.ny} cells")
    typer.echo(f"cell period   : {diag['period_x']:.2f} x {diag['period_y']:.2f} px")
    typer.echo(f"x candidates  : {diag['x_candidates']}")
    typer.echo(f"y candidates  : {diag['y_candidates']}")
    typer.echo(f"confidence    : {score.confidence:.2f}  (residual {score.residual:.4f})")
    gc = "n/a" if score.grid_confidence is None else f"{score.grid_confidence:.2f}"
    typer.echo(f"grid confidence: {gc}" + ("  (no grid detected; default used)" if score.fallback else ""))
    low = int((score.confidence_map() < 128).sum())
    typer.echo(f"low-confidence cells: {low} / {score.grid.nx * score.grid.ny}")


@app.command()
def palettes():
    """List the built-in named palettes."""
    for name, pal in BUILTIN_PALETTES.items():
        typer.echo(f"{name:14} {len(pal)} colors")


if __name__ == "__main__":
    app()
