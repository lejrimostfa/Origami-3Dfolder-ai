"""Papercraft template and cleanup, around one image edit (image.py edit).

    template.py draw  layout.json OUT_DIR            -> template.png (guide for the painter), mask.png
    template.py clean layout.json painted.png OUT.png [--review RD]

draw: nets as light grey faces with dark fold lines and small labels, transparent outside. The painter (an image
edit) fills the faces. clean: resize the painted image to the atlas, force alpha inside opaque nets, cut alpha
outside every net, then bleed edge colours into the padding so mipmaps show no seams. With --review RD it writes
RD/checks/papercraft.json: the metrics and a pass flag (iou_fit >= 0.9 and coverage_pct >= 85).
"""
import argparse
import json
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _px(uv, n):
    return (uv[0] * n, (1 - uv[1]) * n)       # UV v up, image y down


GATE = {"iou_fit": 0.9, "coverage_pct": 85.0}


def _font(size):
    for f in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def masks(lay):
    """mask: every net. opaque: nets whose faces must stay solid (crate, table). Both uint8, atlas size."""
    n = lay["atlas_px"]
    m, o = Image.new("L", (n, n), 0), Image.new("L", (n, n), 0)
    dm, do = ImageDraw.Draw(m), ImageDraw.Draw(o)
    for net in lay["nets"].values():
        for f in net["faces"]:
            poly = [_px(uv, n) for uv in f["uv"]]
            dm.polygon(poly, fill=255)
            if net["opaque"]:
                do.polygon(poly, fill=255)
    return np.array(m), np.array(o)


def draw(lay, out_dir):
    n = lay["atlas_px"]
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _font(max(12, n // 64))
    for key, net in lay["nets"].items():
        for f in net["faces"]:
            d.polygon([_px(uv, n) for uv in f["uv"]], fill=(215, 215, 215, 255), outline=(40, 40, 40, 255), width=2)
        if net["type"] == "box":
            for f in net["faces"]:
                pts = [_px(uv, n) for uv in f["uv"]]
                cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
                w = max(p[0] for p in pts) - min(p[0] for p in pts)
                if w > n / 20:
                    label = f"{key} {f['name']}" if len(lay["nets"]) > 1 and key != f["name"] else f["name"]
                    d.text((cx, cy), label.upper(), fill=(120, 120, 120, 255), font=font, anchor="mm")
        else:
            # one label for the strip or fan, and one per cap disk, so the painter knows which disk is the face
            caps = [f for f in net["faces"] if f["name"].startswith("cap")]
            body = [f for f in net["faces"] if not f["name"].startswith("cap")] or caps
            for group, label in [(body, key)] + [([f], f"{key} {f['name']}") for f in caps]:
                pts = [_px(uv, n) for f in group for uv in f["uv"]]
                cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
                d.text((cx, cy), label.upper(), fill=(120, 120, 120, 255), font=font, anchor="mm")
    os.makedirs(out_dir, exist_ok=True)
    img.save(os.path.join(out_dir, "template.png"))
    m, _ = masks(lay)
    Image.fromarray(m).save(os.path.join(out_dir, "mask.png"))
    return os.path.join(out_dir, "template.png")


def _filled(b):
    flood = np.pad(b.astype(np.uint8), 1).copy()
    cv2.floodFill(flood, None, (0, 0), 2)
    return flood[1:-1, 1:-1] != 2


def _iou(a, inside):
    """Overlap of the painted silhouette with the nets. Holes are filled on both sides first: painted holes
    (window panes) are wanted, and a net can enclose a hole (an open box: the missing top)."""
    p, m = _filled(a > 127), _filled(inside)
    return round(float((p & m).sum() / max(1, (p | m).sum())), 4)


def _bbox(b):
    ys, xs = np.nonzero(b)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def fit(rgba, inside):
    """The painter keeps the shapes but not their exact scale (the crate cross came back 15 percent taller).
    Map the painted alpha box onto the template box, per axis, and keep it only when the overlap improves."""
    a = rgba[..., 3] > 127
    if not a.any():
        return rgba
    px0, py0, px1, py1 = _bbox(a)
    mx0, my0, mx1, my1 = _bbox(inside)
    sx, sy = (mx1 - mx0) / (px1 - px0), (my1 - my0) / (py1 - py0)
    M = np.float32([[sx, 0, mx0 - px0 * sx], [0, sy, my0 - py0 * sy]])
    n = rgba.shape[0]
    warped = cv2.warpAffine(rgba, M, (n, n), flags=cv2.INTER_LANCZOS4, borderValue=(0, 0, 0, 0))
    return warped if _iou(warped[..., 3], inside) > _iou(rgba[..., 3], inside) else rgba


def clean(lay, painted, out, review=None):
    n = lay["atlas_px"]
    src = Image.open(painted).convert("RGBA").resize((n, n), Image.LANCZOS)
    m, o = masks(lay)
    inside, solid = m > 127, o > 127
    raw = np.array(src)
    rgba = fit(raw, inside)
    a = rgba[..., 3].astype(np.float32)
    metrics = {"iou_raw": _iou(raw[..., 3], inside), "iou_fit": _iou(a, inside),
               "coverage_pct": round(float((a[solid] > 127).mean() * 100) if solid.any() else 100.0, 2),
               "spill_pct": round(float((a[~inside] > 127).sum() / max(1, inside.sum()) * 100), 2)}
    holes = (solid & (a < 128)).astype(np.uint8) * 255
    if holes.any():                              # gaps the painter left in solid faces: fill from the neighbours
        rgba[..., :3] = cv2.inpaint(np.ascontiguousarray(rgba[..., :3]), holes, 7, cv2.INPAINT_TELEA)
    a[solid] = 255
    a[~inside] = 0
    # bleed: every pixel outside the nets takes the colour of the nearest pixel inside them
    _, labels = cv2.distanceTransformWithLabels((~inside).astype(np.uint8), cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(inside)
    lut = np.zeros((labels.max() + 1, 3), np.uint8)
    lut[labels[ys, xs]] = rgba[ys, xs, :3]
    rgb = lut[labels]
    rgb[inside] = rgba[inside][:, :3]
    Image.fromarray(np.dstack([rgb, a.astype(np.uint8)])).save(out)
    if review:
        write_check(review, metrics, [painted, out])
    return metrics


def write_check(review, metrics, inputs):
    """Gate record for this asset. File names only: no local paths in a file that may ship."""
    ok = all(metrics[k] >= v for k, v in GATE.items())
    os.makedirs(os.path.join(review, "checks"), exist_ok=True)
    path = os.path.join(review, "checks", "papercraft.json")
    json.dump({"check": "papercraft", "pass": ok, "metrics": metrics, "thresholds": GATE,
               "inputs": [os.path.basename(p) for p in inputs]}, open(path, "w"), indent=1)
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["draw", "clean"])
    ap.add_argument("layout")
    ap.add_argument("args", nargs="+")
    ap.add_argument("--review")
    a = ap.parse_args()
    lay = json.load(open(a.layout))
    if a.cmd == "draw":
        print(draw(lay, a.args[0]))
    else:
        print(json.dumps(clean(lay, a.args[0], a.args[1], a.review)))
