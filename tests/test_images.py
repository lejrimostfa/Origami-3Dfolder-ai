"""Image side: template IoU on an open box, the fit of a painting that came back the wrong scale, the gate file,
leaf cutting, swatch painting, silhouette extrusion and the image.py dry run (no network)."""
import json
import os
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

import leaves
import net
import silhouette
import swatch
import template
from conftest import ROOT
from helpers import fold_error, stretch

OPEN_TRAY = {"name": "cart_bed", "atlas_px": 512, "pad_px": 8,
             "nets": {"bed": {"type": "box", "size": [1.1, 0.8, 0.36], "faces": ["left", "front", "right", "back", "bottom"]}},
             "parts": [{"net": "bed", "at": [0, 0, 0]}]}


def _painted_from_mask(lay, fill_holes=True):
    m, _ = template.masks(lay)
    inside = m > 127
    a = template._filled(inside) if fill_holes else inside
    rgba = np.zeros((*a.shape, 4), np.uint8)
    rgba[a] = (150, 100, 60, 255)
    return rgba


def test_open_box_encloses_a_hole():
    lay = net.layout(OPEN_TRAY)
    m, _ = template.masks(lay)
    inside = m > 127
    assert template._filled(inside).sum() > inside.sum()          # the missing top is a hole inside the net


def test_open_box_iou_fills_holes():
    lay = net.layout(OPEN_TRAY)
    inside = template.masks(lay)[0] > 127
    painted = _painted_from_mask(lay)                               # the painter paints across the hole
    assert template._iou(painted[..., 3], inside) == 1.0
    raw = float((painted[..., 3] > 127)[inside].sum() / (painted[..., 3] > 127).sum())
    assert raw < 0.9                                                # without hole filling it would fail the gate


def test_clean_fits_a_painting_at_the_wrong_scale(tmp_path):
    spec = {"name": "crate", "atlas_px": 512, "pad_px": 8, "nets": {"crate": {"type": "box", "size": [0.6, 0.6, 0.6]}},
            "parts": [{"net": "crate", "at": [0, 0, 0]}]}
    lay = net.layout(spec)
    good = _painted_from_mask(lay)
    n = lay["atlas_px"]
    # 13 percent shorter and 5 percent narrower about the centre (a cube cross fills the atlas: taller would clip)
    M = np.float32([[0.95, 0, 0.025 * n], [0, 0.87, 0.065 * n]])
    off = cv2.warpAffine(good, M, (n, n), flags=cv2.INTER_NEAREST, borderValue=(0, 0, 0, 0))
    Image.fromarray(off).save(tmp_path / "painted.png")
    rd = tmp_path / "review"
    met = template.clean(lay, str(tmp_path / "painted.png"), str(tmp_path / "texture.png"), str(rd))
    assert met["iou_raw"] < 0.9 <= met["iou_fit"]
    assert met["coverage_pct"] >= 85
    chk = json.load(open(rd / "checks" / "papercraft.json"))
    assert chk["pass"] is True and chk["inputs"] == ["painted.png", "texture.png"]
    tex = np.array(Image.open(tmp_path / "texture.png"))
    inside = template.masks(lay)[0] > 127
    assert (tex[..., 3][inside] == 255).all() and (tex[..., 3][~inside] == 0).all()


def test_gate_fails_on_poor_coverage(tmp_path):
    ok = template.write_check(str(tmp_path), {"iou_fit": 0.95, "coverage_pct": 60.0}, ["/somewhere/painted.png"])
    chk = json.load(open(tmp_path / "checks" / "papercraft.json"))
    assert ok is False and chk["pass"] is False and chk["inputs"] == ["painted.png"]


def test_draw_writes_template_and_mask(tmp_path):
    lay = net.layout(OPEN_TRAY)
    template.draw(lay, str(tmp_path))
    t = np.array(Image.open(tmp_path / "template.png"))
    assert t.shape == (512, 512, 4) and t[..., 3].max() == 255 and t[0, 0, 3] == 0
    assert (tmp_path / "mask.png").exists()


def test_leaves_cut(tmp_path):
    im = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i in range(3):
        for j in range(3):
            x, y = 20 + 95 * i, 20 + 95 * j
            d.ellipse((x, y, x + 50, y + 70), fill=(60, 140, 40, 255))
    im.save(tmp_path / "sheet.png")
    r = leaves.cut(str(tmp_path / "sheet.png"), max_verts=10)
    assert r["sheet"] == "sheet.png" and len(r["leaves"]) == 9
    for leaf in r["leaves"]:
        assert 3 <= len(leaf["uv"]) <= 10
        assert abs(leaf["base"][1] - min(v for _, v in leaf["uv"])) < 0.02     # stem at the bottom of the blob


def test_swatch_paint(tmp_path):
    lay = net.layout({"name": "s", "atlas_px": 256, "pad_px": 6,
                      "nets": {"body": {"type": "box", "size": [0.3, 0.2, 0.2]},
                               "barrel": {"type": "frustum", "r0": 0.03, "r1": 0.03, "h": 0.4, "seg": 8, "cap": True}},
                      "parts": [{"net": "body"}, {"net": "barrel"}]})
    sheet = Image.new("RGB", (200, 100))
    ImageDraw.Draw(sheet).rectangle((0, 0, 99, 99), fill=(180, 140, 40))
    ImageDraw.Draw(sheet).rectangle((100, 0, 199, 99), fill=(90, 90, 100))
    assign = {"boxes": {"brass": [0, 0, 100, 100], "steel": [100, 0, 200, 100]},
              "nets": {"body": {"box": "brass", "mode": "tile", "m": 0.05}, "barrel": {"box": "steel", "mode": "fit"},
                       "barrel/cap": {"box": "brass", "mode": "face"}}}
    sheet.save(tmp_path / "sheet.png")
    out = np.array(swatch.paint(lay, str(tmp_path / "sheet.png"), assign))
    inside = template.masks(lay)[0] > 127
    assert (out[..., 3][inside] > 0).mean() > 0.95


def test_silhouette_builds_a_foldable_profile(tmp_path):
    photo = Image.new("RGB", (400, 200), (255, 255, 255))
    ImageDraw.Draw(photo).polygon([(40, 150), (360, 150), (360, 110), (140, 90), (100, 40), (40, 40)], fill=(90, 60, 40))
    photo.save(tmp_path / "photo.png")
    lay = silhouette.build(str(tmp_path / "photo.png"), str(tmp_path / "sign"), 0.5, 0.03, 0.0, 1.2)
    assert lay["name"] == "sign" and "body" in lay["nets"]
    for f in ("spec.json", "layout.json", "photo_upright.png", "painted.png"):
        assert (tmp_path / "sign" / f).exists()
    assert fold_error(lay) < 1e-6 and stretch(lay) < 0.003


def test_image_dry_run_calls_nothing(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENAI_IMAGE_MODEL")}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "image.py"), "edit", str(tmp_path / "p.png"),
                        "paint it", str(tmp_path / "template.png"), "--transparent", "--dry-run"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout[:r.stdout.rindex("}") + 1])
    assert body["model"] == "gpt-image-2.5-sunburst" and body["background"] == "transparent"
    assert body["images"] == ["template.png"] and not (tmp_path / "p.png").exists()
