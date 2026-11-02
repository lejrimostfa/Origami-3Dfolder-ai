"""Looping water textures by code, free: a ripple surface and a falling veil. Pure Python (numpy, PIL).

    water.py ASSET_DIR [--size 512] [--seed 4]   -> water_surface.png (opaque), water_fall.png (streaks with alpha)

Both tile in u and v, so a scrolling uv offset loops without a seam: bp_water.py scrolls them in the Flow clip.
Noise is filtered in frequency space, which wraps by construction.
"""
import argparse
import os

import numpy as np
from PIL import Image


def _noise(n, rng, sx, sy):
    """Tileable noise: white noise low-passed with an anisotropic Gaussian in frequency space (sx, sy in px)."""
    f = np.fft.fft2(rng.standard_normal((n, n)))
    ky, kx = np.meshgrid(np.fft.fftfreq(n), np.fft.fftfreq(n), indexing="ij")
    g = np.exp(-2 * (np.pi ** 2) * ((kx * sx) ** 2 + (ky * sy) ** 2))
    h = np.real(np.fft.ifft2(f * g))
    return (h - h.min()) / (h.max() - h.min())


def surface(n, rng):
    a, b = _noise(n, rng, 30, 30), _noise(n, rng, 9, 9)
    ripple = np.abs(np.sin((a * 0.75 + b * 0.25) * 11))                  # thin bright crests between broad cells
    crest = np.clip((ripple - 0.75) * 4, 0, 1) ** 1.5
    deep, light = np.array([22, 58, 72]), np.array([62, 128, 140])
    rgb = deep + (light - deep) * (0.35 * a + 0.25 * b)[..., None] + np.array([150, 190, 190]) * (crest * 0.55)[..., None]
    return np.clip(rgb, 0, 255).astype(np.uint8)


def fall(n, rng):
    streak = _noise(n, rng, 2.5, 40)                                        # long vertical streaks
    fine = _noise(n, rng, 1.2, 12)
    s = np.clip((0.65 * streak + 0.35 * fine - 0.35) * 2.2, 0, 1)
    rgb = np.array([70, 140, 155]) + np.array([170, 110, 95]) * (s ** 2)[..., None]
    alpha = 60 + 170 * s                                                     # a veil, never fully opaque
    return np.dstack([np.clip(rgb, 0, 255), alpha]).astype(np.uint8)


def build(asset_dir, size=512, seed=4):
    rng = np.random.default_rng(seed)
    Image.fromarray(surface(size, rng)).save(os.path.join(asset_dir, "water_surface.png"))
    Image.fromarray(fall(size, rng), "RGBA").save(os.path.join(asset_dir, "water_fall.png"))
    return os.path.join(asset_dir, "water_surface.png"), os.path.join(asset_dir, "water_fall.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("asset_dir")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--seed", type=int, default=4)
    a = ap.parse_args()
    print(build(a.asset_dir, a.size, a.seed))
