"""generate -> restore -> confidence-gate loop (provider-agnostic).

The robust way to ship clean pixel art today: generate with any model, run the
deterministic restorer, and only accept results whose detection confidence
clears a threshold — otherwise re-roll. This script shows the control flow with
a stub generator; swap ``generate()`` for a real call (Stable Diffusion,
Gemini/Nano-Banana, DALL-E, a local ComfyUI graph, etc.).

Self-contained — run from anywhere after installing the package:

    uv run python examples/generate_and_restore.py
"""

from __future__ import annotations

import cv2
import numpy as np

from pixelperfect import PipelineParams, restore
from pixelperfect.io import save_png

_PALETTE = np.array(
    [
        [26, 28, 44], [177, 62, 83], [239, 125, 87], [255, 205, 117],
        [167, 240, 112], [56, 183, 100], [65, 166, 246], [244, 244, 244],
    ],
    dtype=np.uint8,
)


def generate(prompt: str, seed: int) -> np.ndarray:
    """STUB: replace with a real model call returning an (H, W, 3) uint8 image.

    Here we synthesize a 'messy' sprite (drifting cell pitch + blur + JPEG) so
    the loop is runnable offline without any model.
    """
    rng = np.random.default_rng(seed)
    native = _PALETTE[rng.integers(0, len(_PALETTE), size=(16, 16))].astype(np.uint8)
    drift = 0.1 + 0.03 * (seed % 4)
    cw = np.round(28 * (1 + drift * rng.uniform(-1, 1, 16))).astype(int).clip(3)
    ch = np.round(28 * (1 + drift * rng.uniform(-1, 1, 16))).astype(int).clip(3)
    xb, yb = np.r_[0, np.cumsum(cw)], np.r_[0, np.cumsum(ch)]
    big = np.zeros((int(yb[-1]), int(xb[-1]), 3), np.uint8)
    for r in range(16):
        for c in range(16):
            big[yb[r]:yb[r + 1], xb[c]:xb[c + 1]] = native[r, c]
    big = cv2.GaussianBlur(big, (0, 0), 1.0)
    big = np.clip(big + rng.normal(0, 3, big.shape), 0, 255).astype(np.uint8)
    ok, enc = cv2.imencode(".jpg", cv2.cvtColor(big, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return cv2.cvtColor(cv2.imdecode(enc, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def main(prompt="a tiny wizard sprite", target=16, palette=8, min_conf=0.85, max_tries=6):
    params = PipelineParams(native_w=target, native_h=target, palette_size=palette, upscale=8)
    for attempt in range(1, max_tries + 1):
        raw = generate(prompt, seed=attempt)
        res = restore(raw, params)
        print(f"attempt {attempt}: {res.nx}x{res.ny}, {len(res.palette)} colors, conf={res.score.confidence:.2f}")
        if res.score.confidence >= min_conf:
            save_png(res.native, "examples/accepted_native.png")
            save_png(res.preview, "examples/accepted_preview.png")
            print("accepted -> examples/accepted_native.png (+ _preview)")
            return
    print(f"no generation cleared confidence {min_conf} in {max_tries} tries; lower it or fix the prompt")


if __name__ == "__main__":
    main()
