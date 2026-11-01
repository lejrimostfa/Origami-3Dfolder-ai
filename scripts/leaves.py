"""Cut a leaf sheet (leaves on a transparent background) into leaf cards.

    leaves.py sheet.png leaves.json [--max-verts 10] [--min-area 0.002]

Each opaque blob becomes one card: its convex hull, simplified to at most max-verts points, in UV 0..1.
The card mesh follows the hull, so the GPU draws far fewer transparent pixels than a full quad.
"base" is the bottom centre of the blob: the sheet prompt asks for every leaf upright, stem down.
"""
import argparse
import json
import os

import cv2
import numpy as np
from PIL import Image


def cut(sheet, max_verts=10, min_area=0.002):
    a = np.array(Image.open(sheet).convert("RGBA"))[..., 3]
    h, w = a.shape
    mask = (a > 127).astype(np.uint8)
    count, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if area < min_area * w * h:
            continue
        pts = np.column_stack(np.nonzero(lab == i)[::-1]).astype(np.float32)
        hull = cv2.convexHull(pts)
        eps = 0.5
        poly = hull
        while len(poly) > max_verts:
            poly = cv2.approxPolyDP(hull, eps, True)
            eps *= 1.3
        # approxPolyDP keeps vertices on the hull, so the polygon may clip the blob a little: grow it 2 px
        c = poly.reshape(-1, 2).mean(axis=0)
        poly = [(p - c) * (1 + 2 / max(bw, bh)) + c for p in poly.reshape(-1, 2)]
        out.append({"uv": [[float(px / w), float(1 - py / h)] for px, py in poly],
                    "base": [float((x + bw / 2) / w), float(1 - (y + bh) / h)],
                    "size": [float(bw / w), float(bh / h)], "area_px": int(area)})
    return {"sheet": os.path.basename(sheet), "px": [w, h], "leaves": out}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("out")
    ap.add_argument("--max-verts", type=int, default=10)
    ap.add_argument("--min-area", type=float, default=0.002)
    a = ap.parse_args()
    r = cut(a.sheet, a.max_verts, a.min_area)
    json.dump(r, open(a.out, "w"), indent=1)
    print(f"{len(r['leaves'])} leaves cut from {a.sheet}")
