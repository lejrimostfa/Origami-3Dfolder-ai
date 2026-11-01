"""Hole outlines for thick see-through nets (window panes, ladder gaps, a trigger guard). Pure Python (cv2).

    holes.py layout.json texture.png        adds "holes" to every thick, not opaque net of layout.json

A thick face gets rims on its free edges only. Holes cut by alpha have no edge, so the frame reads as two thin
layers. This finds each transparent blob inside a face and stores its outline in uv, pulled 2 px into the opaque
side, plus a sample uv 6 px deeper (painted edges are often a dark outline). bp_thick builds rims along them.
"""
import json
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw


def find(lay, texture, min_px=40, eps=1.5, inset=2, sample=6):
    n = lay["atlas_px"]
    alpha = np.array(Image.open(texture).convert("RGBA").resize((n, n)))[..., 3]
    found = 0
    for net in lay["nets"].values():
        if net["opaque"] or not net.get("thick"):
            continue
        net["holes"] = {}
        for fi, f in enumerate(net["faces"]):
            m = Image.new("L", (n, n), 0)
            ImageDraw.Draw(m).polygon([(u * n, (1 - v) * n) for u, v in f["uv"]], fill=255)
            face = np.array(m) > 0
            inner = cv2.erode(face.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0     # keep off the face border
            hole = (inner & (alpha < 128)).astype(np.uint8)
            hole = cv2.dilate(hole, np.ones((2 * inset + 1, 2 * inset + 1), np.uint8))   # outline inside the frame
            cs, _ = cv2.findContours(hole, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            loops = []
            for c in cs:
                if cv2.contourArea(c) < min_px:
                    continue
                c = cv2.approxPolyDP(c, eps, True)[:, 0, :].astype(float)
                loop = []
                for i, (x, y) in enumerate(c):
                    # the rim samples its colour `sample` px further into the frame: painted edges are often a
                    # dark outline, which would read as a gap between two thin layers
                    tx, ty = c[(i + 1) % len(c)] - c[i - 1]
                    nx, ny = ty, -tx
                    nn = max(1e-6, (nx * nx + ny * ny) ** 0.5)
                    nx, ny = nx / nn, ny / nn
                    px, py = int(round(x + nx * sample)), int(round(y + ny * sample))
                    if not (0 <= px < n and 0 <= py < n and hole[py, px] == 0):
                        nx, ny = -nx, -ny                      # the other side is the frame
                    sx, sy = x + nx * sample, y + ny * sample
                    loop.append([round(x / n, 6), round(1 - y / n, 6), round(sx / n, 6), round(1 - sy / n, 6)])
                loops.append(loop)
            if loops:
                net["holes"][str(fi)] = loops
                found += len(loops)
    return found


if __name__ == "__main__":
    lay = json.load(open(sys.argv[1]))
    k = find(lay, sys.argv[2])
    json.dump(lay, open(sys.argv[1], "w"), indent=1)
    print(f"{k} hole outlines")
