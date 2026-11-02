"""Face expressions for folded characters: one image call paints every variant (eyes closed, mouth open).

    expressions.py sheet cells.json sheet.png       -> the sheet for one image edit: painted disks on top,
                                                       grey disks below, one column per variant
    expressions.py split cells.json edited.png      -> per asset: faces.png and expressions.json

cells.json: [{"asset": DIR, "net": "face", "face": "cap", "clip": "Blink", "name": "blink"}, ...]
A column's top cell is the disk cut from the asset's texture.png, its bottom cell the same disk in grey: the
painter paints the variant there. split fits each painted variant back onto its disk (the painter moves things a
little), erases the edge line and writes faces.png (a 1024 sheet) plus the uv box of each variant. bp_expr.py adds
the variants to the folded mesh as shape keys and the clips that switch them.
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

N, CELL, TOP, BOTTOM = 1024, 300, 60, 560          # sheet size, cell size, row tops


def _disk(lay, net, face):
    f = next(g for g in lay["nets"][net]["faces"] if g["name"] == face)
    n = lay["atlas_px"]
    pts = [(u * n, (1 - v) * n) for u, v in f["uv"]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return pts, (min(xs), min(ys), max(xs), max(ys))


def _boxes(i, count):
    x = (N - count * CELL) // (count + 1) * (i + 1) + CELL * i
    return (x, TOP, x + CELL, TOP + CELL), (x, BOTTOM, x + CELL, BOTTOM + CELL)


def _place(pts, box, cell):
    """Disk polygon points mapped into a cell, keeping the aspect, centred."""
    x0, y0, x1, y1 = box
    k = (CELL - 20) / max(x1 - x0, y1 - y0)
    ox = cell[0] + (CELL - (x1 - x0) * k) / 2 - x0 * k
    oy = cell[1] + (CELL - (y1 - y0) * k) / 2 - y0 * k
    return [(x * k + ox, y * k + oy) for x, y in pts], k, ox, oy


def sheet(cells, out):
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, c in enumerate(cells):
        lay = json.load(open(os.path.join(c["asset"], "layout.json")))
        tex = Image.open(os.path.join(c["asset"], "texture.png")).convert("RGBA")
        pts, box = _disk(lay, c["net"], c["face"])
        top, bottom = _boxes(i, len(cells))
        p_top, k, _, _ = _place(pts, box, top)
        crop = tex.crop(tuple(int(round(v)) for v in box)).resize(
            (int(round((box[2] - box[0]) * k)), int(round((box[3] - box[1]) * k))), Image.LANCZOS)
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).polygon(p_top, fill=255)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        layer.paste(crop, (int(round(min(p[0] for p in p_top))), int(round(min(p[1] for p in p_top)))))
        img.paste(layer, (0, 0), mask)
        p_bot, _, _, _ = _place(pts, box, bottom)
        d.polygon(p_bot, fill=(215, 215, 215, 255), outline=(40, 40, 40, 255), width=2)
    img.save(out)
    return out


def split(cells, edited):
    src = np.array(Image.open(edited).convert("RGBA").resize((N, N), Image.LANCZOS))
    per_asset = {}
    for i, c in enumerate(cells):
        lay = json.load(open(os.path.join(c["asset"], "layout.json")))
        pts, box = _disk(lay, c["net"], c["face"])
        _, bottom = _boxes(i, len(cells))
        p_bot, _, _, _ = _place(pts, box, bottom)
        want = Image.new("L", (N, N), 0)
        ImageDraw.Draw(want).polygon(p_bot, fill=255)
        want = np.array(want) > 0
        # fit the painted disk (alpha inside a slightly larger cell) onto the wanted disk, per axis
        x0, y0, x1, y1 = bottom
        reg = np.zeros((N, N), bool)
        reg[max(0, y0 - 40):y1 + 40, max(0, x0 - 40):x1 + 40] = True
        a = (src[..., 3] > 127) & reg
        ys, xs = np.nonzero(a)
        wy, wx = np.nonzero(want)
        sx = (wx.max() - wx.min() + 1) / (xs.max() - xs.min() + 1)
        sy = (wy.max() - wy.min() + 1) / (ys.max() - ys.min() + 1)
        M = np.float32([[sx, 0, wx.min() - xs.min() * sx], [0, sy, wy.min() - ys.min() * sy]])
        cell = np.where(reg[..., None], src, 0).astype(np.uint8)
        warped = cv2.warpAffine(cell, M, (N, N), flags=cv2.INTER_LANCZOS4)
        line = np.zeros((N, N), np.uint8)
        cv2.polylines(line, [np.int32(p_bot)], True, 255, 7)
        rgb = cv2.inpaint(np.ascontiguousarray(warped[..., :3]), ((line > 0) & want).astype(np.uint8) * 255, 7,
                          cv2.INPAINT_TELEA)
        out = per_asset.setdefault(c["asset"], {"img": np.zeros((N, N, 4), np.uint8), "variants": []})
        out["img"][want] = np.dstack([rgb, np.full((N, N), 255, np.uint8)])[want]
        bx = [min(p[0] for p in p_bot) / N, 1 - max(p[1] for p in p_bot) / N,
              max(p[0] for p in p_bot) / N, 1 - min(p[1] for p in p_bot) / N]
        out["variants"].append({"name": c["name"], "net": c["net"], "face": c["face"], "clip": c["clip"],
                                "uv_box": [round(v, 6) for v in bx]})
    for asset, out in per_asset.items():
        # bleed: pixels outside the disks take the nearest disk colour, so mipmaps show no dark rim
        inside = out["img"][..., 3] > 0
        _, labels = cv2.distanceTransformWithLabels((~inside).astype(np.uint8), cv2.DIST_L2, 5,
                                                    labelType=cv2.DIST_LABEL_PIXEL)
        ys, xs = np.nonzero(inside)
        lut = np.zeros((labels.max() + 1, 4), np.uint8)
        lut[labels[ys, xs]] = out["img"][ys, xs]
        img = lut[labels]
        img[..., 3] = 255
        Image.fromarray(img).save(os.path.join(asset, "faces.png"))
        json.dump({"sheet": "faces.png", "variants": out["variants"]}, open(os.path.join(asset, "expressions.json"), "w"),
                  indent=1)
    return sorted(per_asset)


if __name__ == "__main__":
    cmd, cells_path, img = sys.argv[1:4]
    cells = json.load(open(cells_path))
    print(sheet(cells, img) if cmd == "sheet" else split(cells, img))
