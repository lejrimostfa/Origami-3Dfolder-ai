"""Paint a papercraft atlas from a sheet of material swatches, without asking the painter for the whole object.
Use it when the image model refuses the object (a pistol) or when plain materials are enough.

    swatch.py layout.json sheet.png assign.json painted.png        (then template.py clean as usual)

assign.json:
    {"boxes": {"brass": [x0, y0, x1, y1], ...},                      swatch rectangles in sheet pixels
     "nets": {"body": {"box": "brass", "mode": "tile", "m": 0.08},      tile: one swatch covers m metres
              "barrel": {"box": "steel", "mode": "fit"},                fit: stretched over the net bbox
              "gauge/cap": {"box": "dial", "mode": "face"},             face: stretched over one face
              "guard": {"box": "brass", "mode": "tile", "m": 0.05, "shape": "loop"}}}
A "net/prefix" key overrides its net for faces whose name starts with prefix ("barrel/cap": cap and capBase).
shape "loop" cuts a ring with a trigger inside the card (alpha), for a guard or a handle.
"""
import json
import sys

import numpy as np
from PIL import Image, ImageDraw


def _px(uv, n):
    return (uv[0] * n, (1 - uv[1]) * n)


def _bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1


def _loop(w, h):
    """A ring open nowhere, plus a small curved tongue inside: alpha mask of a trigger guard."""
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    t = max(2, int(0.14 * min(w, h)))
    d.ellipse((t // 2, t // 2, w - t // 2, h - t // 2), outline=255, width=t)
    d.rectangle((int(w * 0.42), 0, int(w * 0.52), int(h * 0.62)), fill=255)
    return m


def paint(lay, sheet, assign):
    n = lay["atlas_px"]
    src = Image.open(sheet).convert("RGB")
    crops = {k: src.crop(tuple(b)) for k, b in assign["boxes"].items()}
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    for key, net in lay["nets"].items():
        for f in net["faces"]:
            # the longest "net/prefix" key that the face name starts with, else the net key
            keys = [k for k in assign["nets"] if k.startswith(key + "/") and f["name"].startswith(k[len(key) + 1:])]
            rule = assign["nets"].get(max(keys, key=len)) if keys else assign["nets"].get(key)
            if rule is None:
                continue
            poly = [_px(uv, n) for uv in f["uv"]]
            if rule["mode"] == "face":
                x0, y0, x1, y1 = _bbox(poly)
                tex = crops[rule["box"]].resize((x1 - x0, y1 - y0), Image.LANCZOS)
            elif rule["mode"] == "fit":
                x0, y0, x1, y1 = _bbox([_px(uv, n) for g in net["faces"] if not g["name"].startswith("cap")
                                        for uv in g["uv"]] or poly)
                tex = crops[rule["box"]].resize((x1 - x0, y1 - y0), Image.LANCZOS)
            else:
                size = max(8, int(rule["m"] / lay["texel_m"]))
                tile = crops[rule["box"]].resize((size, size), Image.LANCZOS)
                x0, y0, x1, y1 = _bbox(poly)
                tex = Image.new("RGB", (x1 - x0, y1 - y0))
                for ty in range(-(y0 % size), y1 - y0, size):
                    for tx in range(-(x0 % size), x1 - x0, size):
                        tex.paste(tile, (tx, ty))
            mask = Image.new("L", (n, n), 0)
            ImageDraw.Draw(mask).polygon(poly, fill=255)
            if rule.get("shape") == "loop":
                cut = Image.new("L", (n, n), 0)
                cut.paste(_loop(x1 - x0, y1 - y0), (x0, y0))
                mask = Image.fromarray(np.minimum(np.array(mask), np.array(cut)))
            layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
            layer.paste(tex, (x0, y0))
            out.paste(layer, (0, 0), mask)
    return out


if __name__ == "__main__":
    lay = json.load(open(sys.argv[1]))
    paint(lay, sys.argv[2], json.load(open(sys.argv[3]))).save(sys.argv[4])
    print(sys.argv[4])
