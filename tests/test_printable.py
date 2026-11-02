"""Printable reader on a sheet drawn by code: a cube cross with dashed folds and glue flaps must fold shut.

    python3 -m pytest tests/test_printable.py
"""
import json
import math
import os
import tempfile

import numpy as np
from PIL import Image, ImageDraw

import printfold                                            # noqa: E402

S, X0, Y0 = 160, 300, 160                                   # face size and top left of the cross, px


def _dashed(d, a, b, dash=10, gap=6):
    L = math.dist(a, b)
    e = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
    t = 0
    while t < L:
        u = min(t + dash, L)
        d.line([(a[0] + e[0] * t, a[1] + e[1] * t), (a[0] + e[0] * u, a[1] + e[1] * u)], fill=(40, 40, 40), width=3)
        t += dash + gap


def _flap(d, a, b, out, depth=30):
    """A white tapered flap on edge a-b, pushed toward out (unit vector)."""
    e = ((b[0] - a[0]) / S, (b[1] - a[1]) / S)
    c = (a[0] + e[0] * S * 0.8 + out[0] * depth, a[1] + e[1] * S * 0.8 + out[1] * depth)
    p = (a[0] + e[0] * S * 0.2 + out[0] * depth, a[1] + e[1] * S * 0.2 + out[1] * depth)
    d.polygon([a, p, c, b], fill=(255, 255, 255), outline=(0, 0, 0), width=4)
    _dashed(d, a, b)


def cube_sheet(path):
    """Cross: a column of 4 faces, 2 side faces on the second one, a flap on every free edge that must glue."""
    img = Image.new("RGB", (1100, 1100), (255, 255, 255))
    d = ImageDraw.Draw(img)
    cells = [(1, 0), (1, 1), (1, 2), (1, 3), (0, 1), (2, 1)]
    col = [(200, 120, 60), (90, 150, 200), (120, 180, 90), (220, 190, 70), (170, 100, 170), (230, 120, 120)]
    box = lambda c, r: (X0 + c * S, Y0 + r * S)
    # flaps on the side faces' top and bottom edges and on the top face's sides
    for c in (0, 2):
        x, y = box(c, 1)
        _flap(d, (x, y), (x + S, y), (0, -1))
        _flap(d, (x, y + S), (x + S, y + S), (0, 1))
    x, y = box(1, 0)
    _flap(d, (x, y), (x, y + S), (-1, 0))
    _flap(d, (x + S, y), (x + S, y + S), (1, 0))
    x, y = box(1, 2)
    _flap(d, (x, y), (x, y + S), (-1, 0))
    _flap(d, (x + S, y), (x + S, y + S), (1, 0))
    for (c, r), k in zip(cells, col):
        x, y = box(c, r)
        d.rectangle([x, y, x + S, y + S], fill=k)
    d.ellipse([X0 + S + 40, Y0 + S + 40, X0 + S + 70, Y0 + S + 70], fill=(0, 0, 0))     # two eyes on the front
    d.ellipse([X0 + S + 90, Y0 + S + 40, X0 + S + 120, Y0 + S + 70], fill=(0, 0, 0))
    outline = [box(1, 0), box(2, 0), box(2, 1), box(3, 1), box(3, 2), box(2, 2), box(2, 4), box(1, 4), box(1, 2),
               box(0, 2), box(0, 1), box(1, 1)]
    d.line(outline + outline[:1], fill=(0, 0, 0), width=4)
    for a, b in [(box(1, 1), box(2, 1)), (box(1, 2), box(2, 2)), (box(1, 3), box(2, 3)), (box(1, 1), box(1, 2)),
                 (box(2, 1), box(2, 2))]:
        _dashed(d, a, b)
    img.save(path)


def test_cube_folds_shut():
    with tempfile.TemporaryDirectory() as tmp:
        sheet = os.path.join(tmp, "cube.png")
        cube_sheet(sheet)
        rep = printfold.build(sheet, tmp)
        lay = json.load(open(os.path.join(tmp, "layout.json")))
    assert rep["faces"] == 6, rep
    assert rep["flaps"] == 8, rep                            # 2 on each side face, 2 on top, 2 below the front
    assert all(abs(a - 90) < 3 for a in rep["angles_deg"]), rep["angles_deg"]
    assert rep["glue_err_m"] < 0.015, rep                    # 7 px: line width and corner rounding
    assert rep["fold_check"]["body"]["fold_err_m"] < 1e-4
    co = np.array([p for f in lay["nets"]["body"]["faces"] for p in f["co"]])
    ext = np.ptp(co, axis=0)
    assert np.allclose(ext, ext.mean(), rtol=0.06), ext          # a cube, not a strip


if __name__ == "__main__":
    test_cube_folds_shut()
    print("ok")
