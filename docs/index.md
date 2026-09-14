# Pixel-Perfect Documentation

Restore AI-generated "pixel art" into true, 100% pixel-perfect images.

These docs follow the [Diátaxis](https://diataxis.fr/) framework — each page is
one of four kinds, so you can find what you need by *what you're trying to do*.

## Start here

- **New to the tool?** → [Getting Started](getting-started.md) (tutorial)
- **Want to understand how it works?** → [Architecture](architecture.md) (explanation)
- **Have a specific task?** → [How-To Guides](how-to/) (recipes)
- **Need exact facts?** → [Reference](#reference) (CLI, API, config)

## Tutorials

Learning-oriented, step-by-step.

- [Getting Started](getting-started.md) — restore your first image end to end.

## How-To Guides

Goal-oriented recipes for specific tasks.

- [Edit pixels by hand](how-to/edit-pixels.md)
- [Batch-process a folder](how-to/batch-processing.md)
- [Snap to a named palette](how-to/use-named-palettes.md)
- [Fix a hard case the auto-detector got wrong](how-to/fix-hard-cases.md)
- [Self-host the web app securely](how-to/self-host-securely.md)

## Reference

Dry, complete facts.

- [CLI Reference](reference/cli.md) — commands and flags
- [API Reference](reference/api.md) — HTTP endpoints
- [Configuration](reference/configuration.md) — every `PipelineParams` option

## Explanation

Background and rationale.

- [Architecture](architecture.md) — the pipeline, grid detection, and scoring
- [Fixing pixel art at generation time](explanation/generation.md) — the deeper problem
