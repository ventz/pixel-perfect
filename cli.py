#!/usr/bin/env python
"""Pixel-Perfect command-line entry point (root convenience wrapper).

    uv run cli.py restore in.png out.png --palette 16 --upscale 8
    uv run cli.py analyze in.png
    uv run cli.py palettes

Identical to the installed ``pixelperfect`` console script; this just lets you
run the CLI straight from a source checkout without installing.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from pixelperfect.cli import app  # noqa: E402

if __name__ == "__main__":
    app()
