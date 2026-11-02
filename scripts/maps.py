"""Normal map for a folded asset, inferred from its painted texture. Free, no image call.

    python3 scripts/maps.py ASSET_DIR [--strength 3]     -> ASSET_DIR/normal.png (glTF tangent space, green = +Y)
                                                            and ao.png (cavity occlusion)

Height is guessed from brightness (bright reads raised), blurred, then turned into clamped slopes: wood grain,
rivets, scales, fur and cloth catch the light. Painted features (eyes, posters) get a light emboss, so characters
use a lower strength: "normal_strength" in spec.json (1.5 suits a face, 3 is the default, 6 adds little).
The texture is already bled outside the nets, so island borders make no ridge. run_fold.py uses normal.png.
"""
import argparse
import json
import os

import numpy as np
from PIL import Image


def _blur(h, sigma):
    r = int(3 * sigma)
    k = np.exp(-np.arange(-r, r + 1) ** 2 / (2 * sigma * sigma))
    k /= k.sum()
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        hp = np.pad(h, pad, mode="edge")
        h = sum(k[i] * np.take(hp, range(i, i + h.shape[axis]), axis=axis) for i in range(len(k)))
    return h


def normal_from_albedo(rgb, strength=3.0, blur=1.5, max_slope=0.6):
    h = _blur(rgb @ np.array([0.2126, 0.7152, 0.0722]), blur)
    dy, dx = np.gradient(h)
    dx, dy = dx * strength * h.shape[1] / 256, dy * strength * h.shape[0] / 256
    dx, dy = np.clip(dx, -max_slope, max_slope), np.clip(dy, -max_slope, max_slope)
    n = np.stack([-dx, dy, np.ones_like(h)], -1)          # image rows go down, so +dy in the image is -Y in uv
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return ((n * 0.5 + 0.5) * 255).astype(np.uint8)


def ao_from_albedo(rgb, blur=1.5, radius=4.0, power=1.6):
    """Cavity occlusion: texels darker than their blurred neighbourhood read as creases. 1 = open, 0 = occluded."""
    h = _blur(rgb @ np.array([0.2126, 0.7152, 0.0722]), blur)
    cavity = np.clip((_blur(h, radius) - h) * 4.0, 0, 1)
    return ((1 - cavity) ** power * 255).astype(np.uint8)


def build(asset_dir, strength=None):
    spec = os.path.join(asset_dir, "spec.json")
    if strength is None:
        strength = json.load(open(spec)).get("normal_strength", 3.0) if os.path.exists(spec) else 3.0
    rgb = np.asarray(Image.open(os.path.join(asset_dir, "texture.png")).convert("RGB"), float) / 255
    out = os.path.join(asset_dir, "normal.png")
    Image.fromarray(normal_from_albedo(rgb, strength)).save(out)
    ao = ao_from_albedo(rgb)                                  # shipped as occlusionTexture (RGB: glTF reads R)
    Image.fromarray(np.dstack([ao, ao, ao])).save(os.path.join(asset_dir, "ao.png"))
    return out, strength


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("asset_dir")
    ap.add_argument("--strength", type=float)
    a = ap.parse_args()
    print(build(a.asset_dir, a.strength))
