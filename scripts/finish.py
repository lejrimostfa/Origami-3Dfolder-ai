"""Everything after the painting, in order, for one papercraft asset. Free, no image call.

    python3 scripts/finish.py ASSET_DIR [review/NN]      # BLENDER=/path/to/blender if not on PATH

1. template.py clean (fit, clean, bleed, gate check papercraft).
2. "round" nets: seamfade.py evens the paint across band seams (from texture_src.png, kept as the painter output).
3. water.py when the spec has "water", then maps.py (normal.png, ao.png; spec "normal_strength", default 5, characters 3).
4. "round" nets: seamfade.py --flat on normal.png (a band flipped in the atlas turns its tangents).
2b. cut-out cards painted edge to edge (a background): the border colour is keyed out (key_cards).
5. holes.py when a net is thick and not opaque (rims around the alpha cuts).
6. run_fold.py in Blender (bp_round rounds the "round" nets, quad leaf cards by default).
7. warnings.json (cut-out cards with a painted background, thick cut-outs) and sheet.png: the cleaned texture next to
   the front and left views. Read sheet.png every time: the painter's little scenes inside faces and features on
   the wrong net show there (a colour statistic flagged brick walls as often as real defects, so it was dropped).
The fixes by code for the warnings are in references/advanced.md.
"""
import json
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
BLENDER = os.environ.get("BLENDER", "blender")   # macOS: /Applications/Blender.app/Contents/MacOS/Blender
CHARACTER = ("face", "head", "headback", "snout", "hood")      # nets that mark a character: normal strength 3


def run(*cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("failed: %s\n%s" % (" ".join(map(str, cmd)), r.stderr[-2000:]))
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def net_mask(lay, names, W):
    m = Image.new("L", (W, W)); d = ImageDraw.Draw(m)
    for k in names:
        for f in lay["nets"][k]["faces"]:
            d.polygon([(u * W, (1 - v) * W) for u, v in f["uv"]], fill=255)
    return np.asarray(m) > 0


def key_cards(A, spec, lay, thr=40.0):
    """Cut-out cards the painter filled edge to edge: the colour of their border is the background. Pixels close to
    it go transparent, then only the larger blobs stay (antlers, a star). Returns the nets keyed."""
    from scipy.ndimage import binary_dilation, binary_opening, distance_transform_edt, label
    path = os.path.join(A, "texture.png"); tex = np.asarray(Image.open(path).convert("RGBA")).astype(float)
    W = lay["atlas_px"]; done = []
    for k, n in spec["nets"].items():
        if n.get("opaque") is not False:
            continue
        m = net_mask(lay, [k], W)
        if not m.any() or (tex[..., 3][m] < 128).mean() >= 0.15:
            continue
        ys, xs = np.nonzero(m); y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        reg = tex[y0:y1, x0:x1, :3]
        frame = np.concatenate([reg[:4].reshape(-1, 3), reg[-4:].reshape(-1, 3), reg[:, :4].reshape(-1, 3), reg[:, -4:].reshape(-1, 3)])
        mx, mn = reg.max(2), reg.min(2)
        pale = (mx > 190) & ((mx - mn) / (mx + 1e-6) < 0.25)          # light and grey-blue: sky, snow, flakes
        keep = binary_opening((np.linalg.norm(reg - np.median(frame, 0), axis=2) > thr) & ~pale, iterations=1)
        core = binary_opening(keep, iterations=3)             # cut the thin bridges to the crumbs of a painted scene
        lab, _ = label(core); sizes = np.bincount(lab.ravel()); sizes[0] = 0
        main = binary_dilation(sizes[lab] >= 0.45 * sizes.max(), iterations=4)   # the main shapes, grown back
        keep = keep & main
        tex[y0:y1, x0:x1, 3] = np.where(keep & m[y0:y1, x0:x1], tex[y0:y1, x0:x1, 3], 0)
        done.append(k)
    if done:
        if not os.path.exists(os.path.join(A, "texture_painted.png")):
            shutil.copy(path, os.path.join(A, "texture_painted.png"))
        inside = tex[..., 3] > 0; _, (iy, ix) = distance_transform_edt(~inside, return_indices=True)
        out = np.concatenate([tex[..., :3][iy, ix], tex[..., 3:]], 2)
        Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA").save(path)
    return done


def warnings(A, spec, lay):
    """Cheap checks for what the painter got wrong on Gorod Zimy and Pumpkin Hollow."""
    tex = np.asarray(Image.open(os.path.join(A, "texture.png")).convert("RGBA")).astype(float)
    W = lay["atlas_px"]; out = []
    for k, n in spec["nets"].items():
        m = net_mask(lay, [k], W)
        if not m.any():
            continue
        rgb = tex[..., :3][m]
        if n.get("opaque") is False:                    # a cut-out card: is anything cut at all?
            cut = (tex[..., 3][m] < 128).mean()
            if cut < 0.15:
                out.append({"net": k, "warn": "cut-out card barely cut (%.0f%% transparent): a painted background? key it out" % (100 * cut)})
            if n.get("thick") and cut > 0.3:
                out.append({"net": k, "warn": "thick cut-out card: its rims may draw a frame on the transparent border; drop thick"})
    return out


def main():
    A = os.path.abspath(sys.argv[1]); rd = sys.argv[2] if len(sys.argv) > 2 else "review/01"
    spec = json.load(open(os.path.join(A, "spec.json")))
    lay_path = os.path.join(A, "layout.json")
    os.makedirs(os.path.join(A, rd), exist_ok=True)
    print("clean", run(PY, "-I", os.path.join(HERE, "template.py"), "clean", lay_path, os.path.join(A, "painted.png"),
                       os.path.join(A, "texture.png"), "--review", os.path.join(A, rd)))
    if "normal_strength" not in spec:                   # default: 5 props and buildings, 3 characters
        spec["normal_strength"] = 3 if any(k in spec["nets"] for k in CHARACTER) else 5
        json.dump(spec, open(os.path.join(A, "spec.json"), "w"), indent=1)
    nets = ",".join(spec.get("round", {}).get("nets", []))
    if nets:
        shutil.copy(os.path.join(A, "texture.png"), os.path.join(A, "texture_src.png"))
        print("seams", run(PY, "-I", os.path.join(HERE, "seamfade.py"), lay_path, os.path.join(A, "texture_src.png"),
                           os.path.join(A, "texture.png"), "--nets", nets))
    keyed = key_cards(A, spec, json.load(open(lay_path)))
    if keyed:
        print("keyed the painted background out of", keyed)
    if spec.get("water"):                               # Flow clip textures, read by run_fold
        print("water", run(PY, "-I", os.path.join(HERE, "water.py"), A))
    print("maps", run(PY, "-I", os.path.join(HERE, "maps.py"), A))
    if nets:
        n = os.path.join(A, "normal.png")
        print("flat", run(PY, "-I", os.path.join(HERE, "seamfade.py"), lay_path, n, n, "--nets", nets, "--flat", "--depth", "12"))
    if any(n.get("thick") and n.get("opaque") is False for n in spec["nets"].values()):
        print("holes", run(PY, "-I", os.path.join(HERE, "holes.py"), lay_path, os.path.join(A, "texture.png")))
    print("fold", run(BLENDER, "--background", "--factory-startup", "--python", os.path.join(HERE, "run_fold.py"), "--", A, rd))
    w = warnings(A, spec, json.load(open(lay_path)))
    json.dump(w, open(os.path.join(A, rd, "warnings.json"), "w"), indent=1)
    print("%d warnings -> %s" % (len(w), os.path.join(A, rd, "warnings.json")))
    for x in w:
        print("  WARN", x["net"], x["warn"])
    tex = Image.open(os.path.join(A, "texture.png")).convert("RGBA")
    tiles = [tex] + [Image.open(os.path.join(A, rd, v + ".png")).convert("RGBA") for v in ("front", "left")
                     if os.path.exists(os.path.join(A, rd, v + ".png"))]
    S = 512; sheet = Image.new("RGBA", (S * len(tiles), S), (40, 40, 48, 255))
    for i, t in enumerate(tiles):
        t.thumbnail((S, S)); sheet.alpha_composite(t, (i * S + (S - t.width) // 2, (S - t.height) // 2))
    sheet.convert("RGB").save(os.path.join(A, rd, "sheet.png"))
    print("review sheet ->", os.path.join(A, rd, "sheet.png"))


if __name__ == "__main__":
    main()
