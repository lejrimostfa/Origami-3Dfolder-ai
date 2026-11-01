"""Papercraft from one side photo: the silhouette becomes an extruded profile, the photo becomes its texture.
For flat-ish props seen from the side (a flintlock pistol, a sign, a weather vane). Pure Python (cv2, PIL).

    silhouette.py photo.png ASSET_DIR --length 0.36 --thick 0.03 [--angle -27.5] [--eps 1.2]

angle: degrees to turn the photo so the object's long axis is horizontal (cv2 sense, counter clockwise).
Writes ASSET_DIR/spec.json, layout.json, photo_upright.png and painted.png: both caps carry the photo (the far
side mirrored, as seen through), the thin sides carry the photo colour along their edge, holes inside the
silhouette (a trigger guard) stay transparent. Then template.py clean and run_fold.py as usual.
A photo that belongs to someone else is a look test only: repaint before shipping.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net as netmod                                      # noqa: E402


def upright(photo, angle):
    """RGBA photo, background cut (alpha, else near white flooded from the border), turned, cropped."""
    im = Image.open(photo).convert("RGBA")
    a = np.array(im)
    if a[..., 3].min() == 255:
        fg = (a[..., :3].min(axis=2) < 235).astype(np.uint8)
        flood = np.pad(1 - fg, 1, constant_values=1).copy()          # the border counts as background
        cv2.floodFill(flood, None, (0, 0), 2)
        bg = flood[1:-1, 1:-1] == 2
        # background seen through a closed loop (a trigger guard): enclosed near-white blobs, not small highlights
        k, lab, st, _ = cv2.connectedComponentsWithStats(((fg == 0) & ~bg).astype(np.uint8), connectivity=4)
        for i in range(1, k):
            if st[i, cv2.CC_STAT_AREA] > 0.0004 * fg.size:
                bg |= lab == i
        a[..., 3] = np.where(bg, 0, 255)
    h, w = a.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    c, s = abs(M[0, 0]), abs(M[0, 1])
    W, H = int(w * c + h * s), int(w * s + h * c)
    M[0, 2] += W / 2 - w / 2
    M[1, 2] += H / 2 - h / 2
    r = cv2.warpAffine(a, M, (W, H), flags=cv2.INTER_LANCZOS4, borderValue=(0, 0, 0, 0))
    ys, xs = np.nonzero(r[..., 3] > 127)
    return r[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def outline(rgba, eps):
    m = (rgba[..., 3] > 127).astype(np.uint8)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)
    return cv2.approxPolyDP(c, eps, True)[:, 0, :].astype(float)


def build(photo, out, length, thick, angle, eps):
    os.makedirs(out, exist_ok=True)
    img = upright(photo, angle)
    Image.fromarray(img).save(os.path.join(out, "photo_upright.png"))
    pts = outline(img, eps)
    k = length / img.shape[1]                                 # metres per photo pixel
    prof = [[-x * k, (img.shape[0] - y) * k] for x, y in pts]  # profile (x, z), z up; extrude wants (y, z)
    name = os.path.basename(os.path.normpath(out))
    spec = {"name": name, "atlas_px": 1024, "pad_px": 8, "opaque": False,
            "nets": {"body": {"type": "extrude", "outline": prof, "length": thick}},
            "parts": [{"net": "body", "at": [-length / 2, 0, 0], "rot": [0, 0, 90]}]}
    json.dump(spec, open(os.path.join(out, "spec.json"), "w"), indent=1)
    lay = netmod.layout(spec)
    json.dump(lay, open(os.path.join(out, "layout.json"), "w"), indent=1)
    paint(lay, img, prof, k, os.path.join(out, "painted.png"))
    return lay


def paint(lay, img, prof, k, path):
    """Caps: affine from three cap corners in the atlas to the same outline points in the photo."""
    n = lay["atlas_px"]
    out = np.zeros((n, n, 4), np.uint8)
    H = img.shape[0]
    to_photo = lambda co: (-co[1] / k, H - co[2] / k)         # net-local (x, y, z): y = -x_photo * k, z = height
    for f in lay["nets"]["body"]["faces"]:
        atlas = np.float32([(u * n, (1 - v) * n) for u, v in f["uv"]])
        mask = Image.new("L", (n, n), 0)
        ImageDraw.Draw(mask).polygon([tuple(p) for p in atlas], fill=255)
        mask = np.array(mask) > 0
        if f["name"].startswith("cap"):
            src = np.float32([to_photo(c) for c in f["co"]])
            i = [0, len(src) // 3, 2 * len(src) // 3]
            M = cv2.getAffineTransform(atlas[i], src[i])
            warped = cv2.warpAffine(img, M, (n, n), flags=cv2.WARP_INVERSE_MAP | cv2.INTER_LANCZOS4,
                                    borderValue=(0, 0, 0, 0))
            out[mask] = warped[mask]
        else:
            # a side strip: the mean photo colour just inside its outline edge (along the edge normal)
            a, b = np.float32(to_photo(f["co"][0])), np.float32(to_photo(f["co"][1]))
            e = b - a
            nrm = np.float32([-e[1], e[0]]) / max(1e-6, float(np.linalg.norm(e)))
            samples = []
            for t in np.linspace(0.1, 0.9, 6):
                for d in (-6, -4, -2, 2, 4, 6):                   # the outside side is background: skipped
                    x, y = (a + e * t + nrm * d).astype(int)
                    if 0 <= x < img.shape[1] and 0 <= y < H and img[y, x, 3] > 127:
                        samples.append(img[y, x, :3])
            col = np.mean(samples, axis=0) if samples else np.float32([90, 70, 50])
            out[mask] = [*col.astype(np.uint8), 255]
    Image.fromarray(out).save(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("out")
    ap.add_argument("--length", type=float, required=True)
    ap.add_argument("--thick", type=float, default=0.03)
    ap.add_argument("--angle", type=float, default=0.0)
    ap.add_argument("--eps", type=float, default=1.2)
    a = ap.parse_args()
    lay = build(a.photo, a.out, a.length, a.thick, a.angle, a.eps)
    print(f"{len(lay['nets']['body']['faces'])} faces, {lay['texel_m'] * 1000:.2f} mm per px")
