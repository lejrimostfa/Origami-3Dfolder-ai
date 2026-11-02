"""Fold what printable.py read off a printed sheet: hinge angles, cones, orientation, layout.json and texture. Free.

    printfold.py SHEET.png ASSET_DIR      -> texture.png, layout.json, read.json, read_debug.png in ASSET_DIR
    then: maps.py ASSET_DIR and run_fold.py, as for any papercraft asset

Fold: the print stays outside, so every hinge between two ruled faces turns the child behind the sheet. The angles
start at 90 degrees and are solved (least squares) so that each glue flap edge lands on the border of another face.
A face cut along curves (wing, claw) is an appendage: it keeps a fixed small angle toward the print side.
Cone: a small piece whose flap and fold lines all meet in one point, the apex. Its coloured area is rolled around
the apex like an ear or a hat (the frustum net type, so the Fold clip rolls it). Cones sit on the top face.
Front: the ruled face with the most marks. Its two biggest marks (eyes) are side by side and the rest is below.
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import printable                                            # noqa: E402
import unfold                                               # noqa: E402

APPENDAGE_DEG = -25.0                                       # wings and claws: a little toward the print side
FACE_M = 0.2                                                # a typical ruled face is 20 cm across
ATLAS = 1024


def _rot(axis, ang):
    """Rotation matrix about a unit axis (Rodrigues)."""
    x, y, z = axis
    c, s = math.cos(ang), math.sin(ang)
    K = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + s * K + (1 - c) * K @ K


def _sheet(pts, k):
    """px (y down) -> metres on the sheet (y up, z = 0)."""
    return np.array([[x * k, (printable.WORK - y) * k, 0.0] for x, y in pts])


class Net:
    """The faces of one piece as a hinge tree, posed by one angle per hinge."""

    def __init__(self, rd, k):
        self.faces = [_sheet(f["poly"], k) for f in rd["faces"]]
        self.organic = [f["organic"] for f in rd["faces"]]
        n = len(self.faces)
        deg = [0] * n
        for i, j, _, _ in rd["hinges"]:
            deg[i] += 1
            deg[j] += 1
        ruled = [i for i in range(n) if not self.organic[i]] or list(range(n))
        self.root = max(ruled, key=lambda i: (deg[i], -i))
        self.parent, order, todo = {self.root: None}, [self.root], [self.root]
        while todo:
            p = todo.pop(0)
            for i, j, a, b in rd["hinges"]:
                if p in (i, j):
                    c = j if p == i else i
                    if c not in self.parent:
                        a3, b3 = _sheet([a, b], k)
                        u = (b3 - a3) / np.linalg.norm(b3 - a3)
                        v = self.faces[c].mean(axis=0) - a3
                        if u[0] * v[1] - u[1] * v[0] > 0:
                            u = -u                                    # +angle sends the child behind the sheet
                        fixed = self.organic[c] or self.organic[p]
                        self.parent[c] = (p, a3, u, fixed)
                        order.append(c)
                        todo.append(c)
        self.order = order
        self.free = [c for c in order if self.parent[c] and not self.parent[c][3]]
        self.flaps = [(i, *_sheet([a, b], k)) for i, a, b in rd["flaps"] if i in self.parent]

    def pose(self, angles):
        """Per face (R, t): world = R @ sheet + t. angles: radians, one per free hinge."""
        ang = dict(zip(self.free, angles))
        T = {}
        for c in self.order:
            link = self.parent[c]
            if link is None:
                T[c] = (np.eye(3), np.zeros(3))
                continue
            p, a3, u, fixed = link
            R = _rot(u, math.radians(APPENDAGE_DEG) if fixed else ang[c])
            Rp, tp = T[p]
            T[c] = (Rp @ R, Rp @ (a3 - R @ a3) + tp)
        return T

    def posed(self, T, i):
        R, t = T[i]
        return self.faces[i] @ R.T + t

    def _dist(self, pt, poly):
        best = 1e9
        for j in range(len(poly)):
            a, b = poly[j], poly[(j + 1) % len(poly)]
            ab = b - a
            s = min(1.0, max(0.0, float((pt - a) @ ab / (ab @ ab))))
            best = min(best, float(np.linalg.norm(pt - (a + ab * s))))
        return best

    def _flap_pts(self, T, f):
        i, a3, b3 = f
        R, t = T[i]
        return [R @ x + t for x in (a3, b3, (a3 + b3) / 2)]

    def targets(self, T):
        """The ruled face each flap glues onto: the one nearest to its edge."""
        out = []
        for f in self.flaps:
            pts = self._flap_pts(T, f)
            cand = [g for g in self.order if g != f[0] and not self.organic[g]]
            out.append(min(cand, key=lambda g: sum(self._dist(p, self.posed(T, g)) for p in pts), default=None))
        return out

    def residual(self, angles, tg):
        T = self.pose(angles)
        r = []
        for f, g in zip(self.flaps, tg):
            if g is not None:
                r += [self._dist(p, self.posed(T, g)) for p in self._flap_pts(T, f)]
        return np.array(r or [0.0])

    def solve(self):
        x = np.full(len(self.free), math.pi / 2)
        if not self.free or not self.flaps:
            return x, 0.0
        for _ in range(3):                                # re-pick the targets once the angles move
            tg = self.targets(self.pose(x))
            x = least_squares(self.residual, x, args=(tg,), bounds=(0, math.pi), x_scale=0.5).x
        return x, float(np.abs(self.residual(x, tg)).max())


def _cone(rd, ink):
    """Apex of a cone piece: the point shared by all its fold and flap lines, else None."""
    ends = [e for _, _, p, q in rd["hinges"] for e in (p, q)] + [e for _, p, q in rd["flaps"] for e in (p, q)]
    if len(rd["flaps"]) < 2 or not ends:
        return None
    for c in ends:
        lines = [(p, q) for _, _, p, q in rd["hinges"]] + [(p, q) for _, p, q in rd["flaps"]]
        if all(min(math.dist(c, p), math.dist(c, q)) < 15 for p, q in lines):
            return c
    return None


def cone_net(rd, apex, k, seg=24):
    """Fan triangles [rim i, rim i+1, apex] in px around the apex, over the coloured faces, counter clockwise on the
    sheet from one side of the glue wedge to the other. Returns (triangles, sector fraction)."""
    m = rd["mask"].copy()                                  # the piece without its glue wedge: fold lines stay in
    for i in rd["flap_ids"]:
        m &= ~(cv2.dilate(rd["regions"][i]["mask"].astype(np.uint8), np.ones((7, 7), np.uint8)) > 0)
    ax, ay = apex
    h, w = m.shape

    def reach(phi):                                       # phi counter clockwise on the sheet (y up)
        d = np.array([math.cos(phi), -math.sin(phi)])
        r, last = 4.0, 0.0
        while True:
            x, y = int(round(ax + d[0] * r)), int(round(ay + d[1] * r))
            if not (0 <= x < w and 0 <= y < h) or not m[y, x]:
                return last
            last, r = r, r + 1

    phis = np.radians(np.arange(0, 360, 1.0))
    r = np.array([reach(p) for p in phis])
    on = r > 10                                          # the glue wedge is clear right from the apex
    start = next(i for i in range(360) if on[i] and not on[i - 1])          # first ray after the wedge
    span = next(n for n in range(1, 361) if not on[(start + n) % 360])
    a = np.linspace(phis[start], phis[start] + math.radians(span - 1), seg + 1)
    rim = [(ax + reach(p) * math.cos(p), ay - reach(p) * math.sin(p)) for p in a]
    tris = [[rim[i], rim[i + 1], apex] for i in range(seg)]
    return tris, (span - 1) / 360.0


def _uv(p):
    return [p[0] / printable.WORK, 1 - p[1] / printable.WORK]


def _front(rd, ink, white, T, net):
    """(front face, up direction in px) from the drawn marks; up is image up when the face has no eyes."""
    best, up = None, (0.0, -1.0)
    score = -1
    for i, f in enumerate(rd["faces"]):
        if f["organic"]:
            continue
        full = np.zeros(f["mask"].shape, np.uint8)                        # holes filled: pupils are ink
        cv2.fillPoly(full, [np.int32(f["poly"])], 1)
        inner = cv2.erode(full, np.ones((25, 25), np.uint8)) > 0
        marks = inner & (ink | white)
        if marks.sum() > score:
            best, score, mk = i, marks.sum(), marks
    n, lab, st, cen = cv2.connectedComponentsWithStats(mk.astype(np.uint8))
    big = sorted(range(1, n), key=lambda j: -st[j, cv2.CC_STAT_AREA])
    if len(big) >= 2 and st[big[1], cv2.CC_STAT_AREA] > 0.5 * st[big[0], cv2.CC_STAT_AREA] > 50:
        e1, e2 = cen[big[0]], cen[big[1]]
        d = e2 - e1
        u = np.array([-d[1], d[0]]) / np.linalg.norm(d)                 # perpendicular to the eye line
        rest = mk & ~np.isin(lab, big[:2])
        ys, xs = np.nonzero(rest)
        if len(xs):
            below = np.array([xs.mean(), ys.mean()]) - (e1 + e2) / 2
            if below @ u > 0:
                u = -u                                    # the mouth is below the eyes: up points away from it
        up = tuple(u)
    return best, up


def build(sheet, asset_dir):
    rgb, ink, white, reads = printable.read(sheet)
    main = reads[0]
    ruled = [f for f in main["faces"] if not f["organic"]]
    k = FACE_M / float(np.median([math.sqrt(f["mask"].sum()) for f in ruled]))   # metres per work px
    net = Net(main, k)
    angles, err = net.solve()
    T = net.pose(angles)
    fi, up_px = _front(main, ink, white, T, net)
    R, _ = T[fi]
    n3 = R @ np.array([0, 0, 1.0])
    u3 = R @ np.array([up_px[0], -up_px[1], 0.0])
    u3 -= n3 * (u3 @ n3)
    u3 /= np.linalg.norm(u3)
    M = np.array([np.cross(-n3, u3), -n3, u3])           # front -> -Y, up -> +Z
    co = [net.posed(T, i) @ M.T for i in range(len(net.faces))]
    allp = np.vstack(co)
    shift = np.array([-(allp[:, 0].max() + allp[:, 0].min()) / 2, -(allp[:, 1].max() + allp[:, 1].min()) / 2,
                      -allp[:, 2].min()])
    co = [c + shift for c in co]
    names = [("front" if i == fi else ("wing" if f["organic"] else "f") + str(i)) for i, f in enumerate(main["faces"])]
    nets = {"body": {"type": "box", "opaque": False, "faces": [
        {"name": nm, "co": c.round(6).tolist(), "uv": [_uv(p) for p in f["poly"]]}
        for nm, c, f in zip(names, co, main["faces"])]}}
    parts = [{"net": "body", "at": [0, 0, 0]}]
    # the top ruled face carries the small pieces
    tops = [i for i in range(len(co)) if not main["faces"][i]["organic"]]
    top = max(tops, key=lambda i: np.cross(co[i][1] - co[i][0], co[i][2] - co[i][0])[2] /
              (np.linalg.norm(np.cross(co[i][1] - co[i][0], co[i][2] - co[i][0])) + 1e-9))
    tc, tw, td = co[top].mean(axis=0), np.ptp(co[top][:, 0]), np.ptp(co[top][:, 1])
    report = {"pieces": len(reads), "faces": len(main["faces"]), "hinges": len(main["hinges"]),
              "flaps": len(main["flaps"]), "angles_deg": [round(math.degrees(a), 1) for a in angles],
              "glue_err_m": round(err, 4), "front": names[fi], "cones": []}
    cones = [(rd, _cone(rd, ink)) for rd in reads[1:]]
    cones = [(rd, a) for rd, a in cones if a is not None]
    for ci, (rd, apex) in enumerate(cones):
        tris, frac = cone_net(rd, apex, k)
        lay_tmp = {"atlas_px": ATLAS, "texel_m": k * printable.WORK / ATLAS}
        L0 = math.dist(tris[0][0], apex) * k
        r0, h = L0 * frac, L0 * math.sqrt(max(0.0, 1 - frac * frac))
        faces = [{"name": f"side{j}", "uv": [_uv(p) for p in t], "co": [[r0, 0, 0], [0, 0, 0], [0, 0, h]]}
                 for j, t in enumerate(tris)]
        net_c = {"type": "frustum", "opaque": False, "faces": faces}
        for f, c in zip(faces, unfold.frustum_pose(lay_tmp, net_c, 1.0)):
            f["co"] = [[round(v, 6) for v in p] for p in c]
        zmin = min(p[2] for f in faces for p in f["co"])
        nm = f"cone{ci}"
        nets[nm] = net_c
        side = 0 if len(cones) == 1 else (ci / (len(cones) - 1) - 0.5) * 2         # -1 .. 1 across the top
        x = tc[0] + side * 0.28 * tw
        parts.append({"net": nm, "at": [round(x, 4), round(tc[1] - 0.15 * td, 4), round(tc[2] - zmin, 4)],
                      "rot": [0, round(-15 * side, 1), 180]})
        report["cones"].append({"sector_deg": round(frac * 360, 1), "slant_m": round(L0, 3)})
    lay = {"name": os.path.basename(os.path.normpath(asset_dir)).replace("pc_", ""), "atlas_px": ATLAS, "pad_px": 0,
           "texel_m": k * printable.WORK / ATLAS, "opaque": False, "nets": nets, "parts": parts, "labels": {}}
    report["fold_check"] = unfold._check(lay)
    texture(rgb, ink, reads, cones, os.path.join(asset_dir, "texture.png"))
    json.dump(lay, open(os.path.join(asset_dir, "layout.json"), "w"), indent=1)
    json.dump(report, open(os.path.join(asset_dir, "read.json"), "w"), indent=1)
    printable.debug_image(rgb, [r["mask"] for r in reads], [r["lines"] for r in reads], reads,
                          os.path.join(asset_dir, "read_debug.png"))
    return report


def texture(rgb, ink, reads, cones, path):
    """The sheet as the atlas: faces opaque, flaps and paper clear. Fold lines and ruled face borders are repainted
    from the colours around them; a curved outline (wing) keeps its ink."""
    keep = np.zeros(ink.shape, bool)
    band = np.zeros(ink.shape, np.uint8)
    for rd in reads:
        for f in rd["faces"]:
            # holes filled: a pupil or a mouth line is ink, not a cut
            cnts = cv2.findContours(f["mask"].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
            full = np.zeros(ink.shape, np.uint8)
            cv2.drawContours(full, cnts, -1, 1, -1)
            keep |= full > 0
            if not f["organic"]:
                cv2.polylines(band, [np.int32(f["poly"])], True, 1, 9)
        for _, _, p, q in rd["hinges"]:
            cv2.line(band, tuple(np.int32(p)), tuple(np.int32(q)), 1, 9)
    keep = cv2.dilate(keep.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[..., 2] < 185            # light dash edges too
    fix = cv2.dilate(((band > 0) & keep & grey).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    img = cv2.inpaint(np.ascontiguousarray(rgb), fix.astype(np.uint8) * 255, 7, cv2.INPAINT_TELEA)
    # bleed: clear pixels take the nearest face colour, so mipmaps never pull in white paper
    _, lab = cv2.distanceTransformWithLabels((~keep).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(keep)
    lut = np.zeros((lab.max() + 1, 3), np.uint8)
    lut[lab[ys, xs]] = img[ys, xs]
    img = lut[lab]
    rgba = np.dstack([img, keep.astype(np.uint8) * 255])
    Image.fromarray(rgba, "RGBA").resize((ATLAS, ATLAS), Image.LANCZOS).save(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("asset_dir")
    a = ap.parse_args()
    os.makedirs(a.asset_dir, exist_ok=True)
    print(json.dumps(build(a.sheet, a.asset_dir), indent=1))
