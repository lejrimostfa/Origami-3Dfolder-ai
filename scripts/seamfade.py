"""Fade the colour jump across the seams between two nets of one object (bands of a pumpkin). Pure Python.

    seamfade.py layout.json texture.png out.png --nets low,belly,top [--depth 40] [--strip 8]

The painter shades each band a little differently, so a hard line shows where two bands meet, even once
bp_round.py has made the surface continuous. Every 3D edge shared by faces of two different parts (of the listed
nets) is found from layout.json. Along the edge, at 12 points, the mean colour of an 8 px strip is read on each
side. Each side then moves halfway toward the other one, fully at the edge and fading to nothing at --depth px.

    seamfade.py layout.json normal.png normal.png --nets low,belly,top --flat [--depth 12]

--flat, on the normal map (after maps.py): flattens it toward (128, 128, 255) near the same seams. A band turned
upside down in the atlas has its tangent frame turned too, so the relief lit the two sides of a seam differently.
"""
import argparse
import json
import math

import numpy as np
from PIL import Image, ImageDraw


def matrix(part):
    """4x4 of a part: scale, then Euler XYZ in degrees, then translation (as bp_fold._pc_matrix)."""
    s = part.get("scale", 1.0)
    s = s if isinstance(s, (list, tuple)) else (s, s, s)
    rx, ry, rz = (math.radians(a) for a in part.get("rot", (0, 0, 0)))
    X = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    Y = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    Z = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = Z @ Y @ X @ np.diag(s)
    m[:3, 3] = part.get("at", (0, 0, 0))
    return m


def shared_edges(lay, nets):
    """[(uv_a0, uv_a1, face_a_uv, uv_b0, uv_b1, face_b_uv)] for 3D edges shared by two different parts."""
    found = {}
    for pi, part in enumerate(lay["parts"]):
        if part["net"] not in nets:
            continue
        m = matrix(part)
        for f in lay["nets"][part["net"]]["faces"]:
            co = [tuple(np.round((m @ np.array([*c, 1.0]))[:3], 4)) for c in f["co"]]
            for i in range(len(co)):
                j = (i + 1) % len(co)
                key = tuple(sorted((co[i], co[j])))
                a, b = (f["uv"][i], f["uv"][j]) if co[i] <= co[j] else (f["uv"][j], f["uv"][i])
                found.setdefault(key, []).append((pi, a, b, f["uv"]))
    return [(x[1], x[2], x[3], y[1], y[2], y[3]) for v in found.values() if len(v) == 2
            for x, y in [v] if x[0] != y[0]]


def strip_means(img, a, b, poly, strip, k=12):
    """Mean colour of a thin strip inside poly along segment a-b, at k points: (k, 3)."""
    H, W = img.shape[:2]
    mask = Image.new("L", (W, H)); ImageDraw.Draw(mask).polygon([tuple(p) for p in poly], fill=1)
    mask = np.array(mask, bool)
    out = []
    d = b - a; L = np.linalg.norm(d) + 1e-9; nrm = np.array([-d[1], d[0]]) / L
    for t in (np.arange(k) + 0.5) / k:
        p = a + d * t
        pts = [p + nrm * s + d / L * w for s in np.linspace(-strip, strip, 9) for w in np.linspace(-L / k / 2, L / k / 2, 5)]
        cols = [img[int(y), int(x)] for x, y in pts if 0 <= x < W and 0 <= y < H and mask[int(y), int(x)]]
        out.append(np.mean(cols, 0) if cols else np.full(3, np.nan))
    out = np.array(out)
    good = ~np.isnan(out[:, 0])
    return np.array([np.interp(np.arange(k), np.flatnonzero(good), out[good, c]) for c in range(3)]).T if good.any() else None


def fade(img, base, a, b, poly, delta, depth):
    """Add delta (k, 3), interpolated along a-b, to the pixels of poly, weighted 1 at the edge to 0 at depth."""
    H, W = img.shape[:2]
    mask = Image.new("L", (W, H)); ImageDraw.Draw(mask).polygon([tuple(p) for p in poly], fill=1)
    ys, xs = np.nonzero(np.array(mask, bool))
    d = b - a; L2 = d @ d + 1e-9
    rel = np.stack([xs - a[0], ys - a[1]], 1)
    t = np.clip(rel @ d / L2, 0, 1)
    dist = np.linalg.norm(rel - t[:, None] * d, axis=1)
    w = np.clip(1 - dist / depth, 0, 1)
    k = len(delta)
    pos = t * k - 0.5
    dl = np.stack([np.interp(pos, np.arange(k), delta[:, c]) for c in range(3)], 1)
    img[ys, xs] += w[:, None] * dl * (base[ys, xs, 3:4] > 0)


def fade_to(img, a, b, poly, target, depth):
    """Blend the pixels of poly toward target, weight 1 at segment a-b to 0 at depth px."""
    H, W = img.shape[:2]
    mask = Image.new("L", (W, H)); ImageDraw.Draw(mask).polygon([tuple(p) for p in poly], fill=1)
    ys, xs = np.nonzero(np.array(mask, bool))
    d = b - a
    rel = np.stack([xs - a[0], ys - a[1]], 1)
    t = np.clip(rel @ d / (d @ d + 1e-9), 0, 1)
    w = np.clip(1 - np.linalg.norm(rel - t[:, None] * d, axis=1) / depth, 0, 1)[:, None]
    img[ys, xs] = img[ys, xs] * (1 - w) + target * w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout"); ap.add_argument("texture"); ap.add_argument("out")
    ap.add_argument("--nets", required=True); ap.add_argument("--depth", type=float, default=40)
    ap.add_argument("--strip", type=float, default=8)
    ap.add_argument("--flat", action="store_true", help="the image is a normal map: flatten it near the seams")
    a = ap.parse_args()
    lay = json.load(open(a.layout))
    src = np.array(Image.open(a.texture).convert("RGBA")).astype(float)
    H, W = src.shape[:2]
    px = lambda uv: np.array([uv[0] * W, (1 - uv[1]) * H])
    img = src[..., :3].copy()
    pairs = shared_edges(lay, set(a.nets.split(",")))
    if a.flat:
        src[..., 3] = 255                               # a normal map has no alpha: every pixel counts
        flat = np.array([128.0, 128.0, 255.0])
    for ua0, ua1, fa, ub0, ub1, fb in pairs:
        A0, A1, B0, B1 = px(ua0), px(ua1), px(ub0), px(ub1)
        pa, pb = [px(u) for u in fa], [px(u) for u in fb]
        if a.flat:
            for p0, p1, poly in ((A0, A1, pa), (B0, B1, pb)):
                fade_to(img, p0, p1, poly, flat, a.depth)
            continue
        ma, mb = strip_means(src[..., :3], A0, A1, pa, a.strip), strip_means(src[..., :3], B0, B1, pb, a.strip)
        if ma is None or mb is None:
            continue
        mid = (ma + mb) / 2
        fade(img, src, A0, A1, pa, mid - ma, a.depth)
        fade(img, src, B0, B1, pb, mid - mb, a.depth)
    if a.flat:
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").save(a.out)
        print("%d seam edges flattened -> %s" % (len(pairs), a.out))
        return
    # Bleed again: outside the nets each pixel takes its nearest inside colour. The old bleed kept the old edge
    # colour, and maps.py read that step as a ridge on every seam.
    from scipy.ndimage import distance_transform_edt
    inside = src[..., 3] > 0
    _, (iy, ix) = distance_transform_edt(~inside, return_indices=True)
    img = img[iy, ix]
    out = np.concatenate([np.clip(img, 0, 255), src[..., 3:]], 2).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(a.out)
    print("%d seam edges faded -> %s" % (len(pairs), a.out))


if __name__ == "__main__":
    main()
