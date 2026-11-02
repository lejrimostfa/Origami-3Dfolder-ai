"""Read a printable papercraft sheet (cut lines, dashed fold lines, white glue flaps) into a folded layout. Free.

    printable.py SHEET.png ASSET_DIR [--debug]   -> ASSET_DIR/texture.png, layout.json, read.json (+ read_debug.png)

Steps:
1. Pieces: paper is the white area joined to the sheet border. Everything else that is big enough is a piece.
2. Fold lines: long straight runs of dark pixels inside a piece (dashes are joined by the Hough gap).
3. Regions: a piece cut by its fold lines. A white region on the outline is a glue flap. A white region inside a
   coloured one (eyes, teeth) belongs to it.
4. Faces and hinges: one polygon per region. Two regions with a fold line between them share one exact edge.
5. Fold: printed side out. Each flap glues its edge to a free edge of the same length. The hinge angles are solved
   so the glued edges meet. A face with nothing to glue is an appendage (wing, fin) and stays near flat.
6. A piece with one face, a slit to its inside and a flap at the slit end is a cone (ear, hat). Small pieces sit
   on the top face.
7. Orientation: the face with the most drawn detail is the front. Its two biggest marks (eyes) are side by side
   and the other marks are below them.
The texture is the sheet itself, squared: the uv are the pixels. bp_fold.py folds layout.json like any other net.
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import unfold                                               # noqa: E402  same fold math as the Fold clip

WORK = 1400                                                 # detection size of the long side, px


def load(path):
    """Sheet on a white square, long side WORK px. Returns rgb (uint8) and the scale from source px."""
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    im = Image.alpha_composite(bg, im).convert("RGB")
    k = WORK / max(im.size)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    sq = Image.new("RGB", (WORK, WORK), (255, 255, 255))
    sq.paste(im, ((WORK - im.width) // 2, (WORK - im.height) // 2))
    return np.array(sq), k


def classes(rgb):
    """ink: dark lines. white: paper white. colour: the rest (painted faces)."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    v, s = hsv[..., 2].astype(int), hsv[..., 1].astype(int)
    ink = v < 150
    white = (v > 200) & (s < 40)
    return ink, white, ~ink & ~white


def pieces(ink, white, min_frac=0.004):
    """Masks of the pieces, biggest first. Paper = white joined to the border, through gaps under 3 px."""
    open_ = (~ink).astype(np.uint8)
    paper = np.zeros(ink.shape, bool)
    n, lab = cv2.connectedComponents(cv2.erode(open_ & white.astype(np.uint8), np.ones((3, 3), np.uint8)))
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    paper = np.isin(lab, list(border))
    paper = cv2.dilate(paper.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    solid = (~paper).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(solid)
    total = ink.size
    out = [lab == i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > min_frac * total]
    # text: a word is many small blobs, a piece is one; drop pieces whose fill is mostly ink
    out = [m for m in out if (ink & m).sum() < 0.5 * m.sum()]
    return sorted(out, key=lambda m: -m.sum())


def fold_lines(ink, piece, min_len):
    """Straight dark runs inside the piece, outline excluded. Returns merged segments [(p, q)] in px."""
    inner = cv2.erode(piece.astype(np.uint8), np.ones((17, 17), np.uint8)) > 0
    blobs = cv2.dilate(cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, np.ones((7, 7), np.uint8)),
                       np.ones((9, 9), np.uint8)) > 0              # pupils and filled marks are not lines
    m = (ink & inner & ~blobs).astype(np.uint8) * 255
    near = cv2.dilate(m, np.ones((9, 9), np.uint8)) > 0                # a line may wobble or tilt by 4 px
    found = cv2.HoughLines(m, 1, np.pi / 360, threshold=int(min_len * 0.4))
    found = [] if found is None else found.reshape(-1, 2)
    kept = []                                                       # one (rho, theta) per real line
    for rho, th in found:
        if not any(abs(rho - r) < 16 and abs(th - t) < math.radians(5) for r, t in kept):
            kept.append((rho, th))
    segs = []
    h, w = m.shape
    for rho, th in kept:
        c, s_ = math.cos(th), math.sin(th)
        o, d = np.array([c * rho, s_ * rho]), np.array([-s_, c])
        ts = np.arange(-2 * max(h, w), 2 * max(h, w))
        pts = np.round(o + ts[:, None] * d).astype(int)
        ok = (pts[:, 0] >= 0) & (pts[:, 0] < w) & (pts[:, 1] >= 0) & (pts[:, 1] < h)
        ts, pts = ts[ok], pts[ok]
        on = near[pts[:, 1], pts[:, 0]]
        segs += [(tuple(map(float, pts[i])), tuple(map(float, pts[j]))) for i, j in _runs(on, max(10, int(min_len * 0.05)), min_len / 2)]
    thin = cv2.dilate(m, np.ones((3, 3), np.uint8)) > 0
    segs = [_refit(m, p, q) for p, q in segs]
    # a curve (mouth, eye rim) can fill a wide band; a true line fills a 3 px band along its whole run
    # short lines (a claw, a small flap) must be cleaner than long ones
    segs = _merge([s for s in segs if _cover(thin, *s) >= 0.45 and
                   _spread(m, *s) < (1.5 if math.dist(*s) >= min_len else 1.1 if math.dist(*s) >= min_len / 2 else 0)])
    return _anchored(segs, inner)


def _seg_dist(p, a, b):
    ab, ap = np.subtract(b, a), np.subtract(p, a)
    t = min(1.0, max(0.0, float(ap @ ab) / float(ab @ ab)))
    return math.dist(p, np.add(a, ab * t))


def _anchored(segs, inner, reach=22):
    """A fold line runs from the outline or another fold line to the outline or another fold line. A straight
    piece of a drawing (mouth, eye rim) stops in the middle of a face: drop it, until nothing changes."""
    h, w = inner.shape
    while True:
        keep = []
        for i, (p, q) in enumerate(segs):
            e = np.subtract(q, p) / math.dist(p, q)
            ok = True
            for end, d in ((p, -e), (q, e)):
                x, y = np.round(np.add(end, d * reach)).astype(int)
                at_edge = not (0 <= x < w and 0 <= y < h) or not inner[y, x]
                ray = [np.add(end, d * r) for r in range(0, 3 * reach, 4)]     # across a drawn mark on the line
                at_line = any(_seg_dist(end, *o) < 12 or any(_seg_dist(x_, *o) < 6 for x_ in ray)
                              for j, o in enumerate(segs) if j != i)
                ok &= at_edge or at_line
            if ok:
                keep.append((p, q))
        if len(keep) == len(segs):
            return keep
        segs = keep


def _spread(m, p, q, band=4):
    """RMS distance of the ink in a band around the segment: under 1.3 px on a ruled line, 2 on a curve."""
    ys, xs = np.nonzero(m)
    rel = np.c_[xs, ys] - np.asarray(p)
    e = np.subtract(q, p) / math.dist(p, q)
    t, d = rel @ e, rel @ np.array([-e[1], e[0]])
    k = (np.abs(d) < band) & (t > 0) & (t < math.dist(p, q))
    return float(np.sqrt((d[k] ** 2).mean())) if k.any() else 9.0


def _cover(mask, p, q):
    n = max(2, int(math.dist(p, q)))
    pts = np.round(np.linspace(p, q, n)).astype(int)
    h, w = mask.shape
    pts = pts[(pts[:, 0] >= 0) & (pts[:, 0] < w) & (pts[:, 1] >= 0) & (pts[:, 1] < h)]
    return float(mask[pts[:, 1], pts[:, 0]].mean()) if len(pts) else 0.0


def _refit(m, p, q, tol=4):
    """Least squares line through the ink pixels near the segment, ends projected onto it."""
    ys, xs = np.nonzero(m)
    pts = np.c_[xs, ys].astype(float)
    e = np.subtract(q, p) / math.dist(p, q)
    rel = pts - p
    t = rel @ e
    keep = (np.abs(rel @ np.array([-e[1], e[0]])) < tol) & (t > -tol) & (t < math.dist(p, q) + tol)
    if keep.sum() < 10:
        return p, q
    vx, vy, x0, y0 = cv2.fitLine(pts[keep].astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    d, o = np.array([vx, vy]), np.array([x0, y0])
    return tuple(map(float, o + d * float((np.subtract(p, o)) @ d))), tuple(map(float, o + d * float((np.subtract(q, o)) @ d)))


def _runs(on, gap, min_len, cover=0.6):
    """Index pairs of the dashed runs along a sampled line: gaps under gap px are bridged."""
    idx = np.nonzero(on)[0]
    out, start = [], None
    for a, b in zip(np.r_[-10 ** 9, idx], np.r_[idx, 10 ** 9]):
        if b - a > gap:
            if start is not None and a - start >= min_len and on[start:a + 1].mean() >= cover:
                out.append((start, a))
            start = b
    return out


def _merge(segs, ang_tol=3.0, dist_tol=6.0):
    """Collinear overlapping segments become one."""
    out = []
    for p, q in sorted(segs, key=lambda s: -math.dist(*s)):
        d = np.subtract(q, p) / (math.dist(p, q) or 1)
        for i, (a, b) in enumerate(out):
            e = np.subtract(b, a) / math.dist(a, b)
            if abs(abs(float(d @ e)) - 1) > 1 - math.cos(math.radians(ang_tol)):
                continue
            nrm = np.array([-e[1], e[0]])
            if max(abs(float(np.subtract(p, a) @ nrm)), abs(float(np.subtract(q, a) @ nrm))) > dist_tol:
                continue
            ts = [0, math.dist(a, b), float(np.subtract(p, a) @ e), float(np.subtract(q, a) @ e)]
            if min(ts[2:]) > ts[1] + dist_tol * 3 or max(ts[2:]) < -dist_tol * 3:
                continue
            a2 = tuple(np.add(a, e * min(ts)))
            out[i] = (a2, tuple(np.add(a, e * max(ts))))
            break
        else:
            out.append((tuple(map(float, p)), tuple(map(float, q))))
    return out


def regions(piece, ink, white, lines, width=5):
    """The piece cut by its fold lines and its ink, white apart from colour: [{mask, white, outline}].
    A flap often meets its face along a solid line or a colour step, so the colour split finds it too."""
    cut = np.zeros(piece.shape, np.uint8)
    for p, q in lines:
        e = np.subtract(q, p) / math.dist(p, q)
        p2, q2 = np.subtract(p, e * 12), np.add(q, e * 12)        # reach the outline across the last dash gap
        cv2.line(cut, tuple(np.int32(np.round(p2))), tuple(np.int32(np.round(q2))), 1, width)
    free = piece & (cut == 0) & ~ink
    edge = cv2.dilate((~piece).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    out = []
    for is_white in (False, True):
        n, lab, stats, _ = cv2.connectedComponentsWithStats((free & (white == is_white)).astype(np.uint8), connectivity=4)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < 0.002 * piece.sum():
                continue                                          # specks: whiskers, dash ends, text
            m = lab == i
            out.append({"mask": m, "white": is_white, "outline": bool((m & edge).any())})
    return out


def _hinge(a, b, lines, near=6):
    """The straight shared border of two regions, on one of the fold lines: (p, q) in px, or None."""
    k = np.ones((11, 11), np.uint8)
    band = (cv2.dilate(a.astype(np.uint8), k) > 0) & (cv2.dilate(b.astype(np.uint8), k) > 0)
    ys, xs = np.nonzero(band)
    if len(xs) < 20:
        return None
    pts = np.c_[xs, ys].astype(float)
    best = None
    for p, q in lines:
        e = np.subtract(q, p) / math.dist(p, q)
        rel = pts - p
        on = np.abs(rel @ np.array([-e[1], e[0]])) < near
        if on.sum() < 0.6 * len(pts) or on.sum() < 20:
            continue
        t = rel[on] @ e
        lo, hi = np.percentile(t, 1), np.percentile(t, 99)
        if hi - lo > 15 and (best is None or hi - lo > best[0]):
            best = (hi - lo, (tuple(np.add(p, e * lo)), tuple(np.add(p, e * hi))))
    if best is None and len(pts) > 150:
        # no line found (a short dashed hinge): a long straight shared border is a hinge too
        vx, vy, x0, y0 = cv2.fitLine(pts.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        e, o = np.array([vx, vy]), np.array([x0, y0])
        rel = pts - o
        t, d = rel @ e, rel @ np.array([-e[1], e[0]])
        lo, hi = np.percentile(t, 1), np.percentile(t, 99)
        if hi - lo > 30 and np.sqrt((d ** 2).mean()) < 3.5:
            best = (hi - lo, (tuple(o + e * lo), tuple(o + e * hi)))
    return best and best[1]


def _snap_ends(hinges, tol=14):
    """Hinge ends that meet at one corner become one point: the crossing of their lines, else their mean."""
    ends = [(h, k) for h in range(len(hinges)) for k in range(2)]
    done = set()
    for h, k in ends:
        if (h, k) in done:
            continue
        group = [(g, j) for g, j in ends if (g, j) not in done and math.dist(hinges[g][j], hinges[h][k]) < tol]
        dirs = {g: np.subtract(hinges[g][1], hinges[g][0]) for g, _ in group}
        pt = np.mean([hinges[g][j] for g, j in group], axis=0)
        gs = list(dirs)
        for i in range(len(gs)):
            for j in range(i + 1, len(gs)):
                d1, d2 = dirs[gs[i]], dirs[gs[j]]
                den = d1[0] * d2[1] - d1[1] * d2[0]
                if abs(den) > 0.3 * np.linalg.norm(d1) * np.linalg.norm(d2):
                    p1, p2 = np.asarray(hinges[gs[i]][0]), np.asarray(hinges[gs[j]][0])
                    t = ((p2 - p1)[0] * d2[1] - (p2 - p1)[1] * d2[0]) / den
                    pt = p1 + d1 * t
        for g, j in group:
            hinges[g] = tuple(tuple(map(float, pt)) if jj == j else hinges[g][jj] for jj in range(2))
            done.add((g, j))
    return hinges


def _polygon(mask, organic):
    """Outline polygon of a region, counter clockwise on the sheet seen from the print (y up)."""
    m = cv2.dilate(mask.astype(np.uint8), np.ones((7, 7), np.uint8))
    cnt = max(cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    cnt = cv2.convexHull(cnt)                 # alpha cuts the scallops of a wing and the notch of a white mark
    poly = cv2.approxPolyDP(cnt, max(3.0, 0.012 * cv2.arcLength(cnt, True)), True).reshape(-1, 2).astype(float)
    if _area(poly) > 0:                                           # image y is down: positive here is clockwise
        poly = poly[::-1]
    return [tuple(p) for p in poly]


def _area(poly):
    x, y = np.asarray(poly)[:, 0], np.asarray(poly)[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _insert_edge(poly, a, b, tol=12):
    """Put the exact hinge (a, b) into the polygon: drop the vertices near it, add a and b in winding order."""
    keep = [p for p in poly if _seg_dist(p, a, b) > tol]
    if len(keep) < 2:
        return poly
    mid = np.add(a, b) / 2
    i = min(range(len(keep)), key=lambda i: _seg_dist(mid, keep[i], keep[(i + 1) % len(keep)]))
    first, second = (a, b) if math.dist(keep[i], a) < math.dist(keep[i], b) else (b, a)
    return keep[:i + 1] + [first, second] + keep[i + 1:]


def _organic(mask):
    """A face cut along curves (wing, claw) rather than a ruled polygon."""
    cnt = max(cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
    return len(approx) > 8 or cv2.contourArea(cnt) < 0.93 * cv2.contourArea(cv2.convexHull(cnt))


def _links(regs, lines):
    out = []
    for i in range(len(regs)):
        for j in range(i + 1, len(regs)):
            h = _hinge(regs[i]["mask"], regs[j]["mask"], lines)
            if h:
                out.append([i, j, h])
    return out


def read_piece(piece, ink, white, lines):
    """Faces, flaps and hinges of one piece, in px. faces: [{poly, organic, mask}]. hinges: [(i, j, p, q)] between
    faces. flaps: [(face, p, q)]: the face edge a glue flap hangs on."""
    regs = regions(piece, ink, white, lines)
    links = _links(regs, lines)
    # a flap: white, on the outline, hung on another region and shallow next to its hinge
    flap = set()
    for i, r in enumerate(regs):
        mine = [l for l in links if i in l[:2]]
        if not mine:
            continue
        p, q = max((l[2] for l in mine), key=lambda h: math.dist(*h))
        e = np.subtract(q, p) / math.dist(p, q)
        ys, xs = np.nonzero(r["mask"])
        depth = np.abs((np.c_[xs, ys] - p) @ np.array([-e[1], e[0]])).max()
        if r["outline"] and (r["white"] or (len(mine) == 1 and depth < 0.2 * math.dist(p, q))):
            flap.add(i)                                           # a coloured flap: a thin strip on a long edge
    # every other white region (eyes, teeth, a white notch) belongs to the colour face that touches it most
    k = np.ones((11, 11), np.uint8)
    for di in sorted((i for i, r in enumerate(regs) if r["white"] and i not in flap), reverse=True):
        grown = cv2.dilate(regs[di]["mask"].astype(np.uint8), k) > 0
        hosts = [i for i, r in enumerate(regs) if not r["white"] and i not in flap]
        host = max(hosts, key=lambda i: (grown & regs[i]["mask"]).sum(), default=None)
        if host is not None and (grown & regs[host]["mask"]).any():
            regs[host]["mask"] = regs[host]["mask"] | regs[di]["mask"]
            regs[di]["mask"] = np.zeros_like(regs[di]["mask"])
    keep = [i for i, r in enumerate(regs) if r["mask"].any()]
    flap = {keep.index(i) for i in flap}
    regs = [regs[i] for i in keep]
    links = _links(regs, lines)
    # a white region next to a flap and nothing else (two halves of a glue wedge) is a flap too
    ends = _snap_ends([l[2] for l in links])
    for l, e in zip(links, ends):
        l[2] = e
    face_ids = [i for i in range(len(regs)) if i not in flap]
    idx = {r: k for k, r in enumerate(face_ids)}
    faces = [{"mask": regs[i]["mask"], "organic": _organic(regs[i]["mask"])} for i in face_ids]
    for f in faces:
        f["poly"] = _polygon(f["mask"], f["organic"])
    hinges, flaps = [], []
    for i, j, (p, q) in links:
        if i in idx and j in idx:
            hinges.append((idx[i], idx[j], p, q))
        elif (i in idx) != (j in idx) and (i in flap or j in flap):
            flaps.append((idx[i] if i in idx else idx[j], p, q))
    for i, j, p, q in hinges:
        faces[i]["poly"] = _insert_edge(faces[i]["poly"], p, q)
        faces[j]["poly"] = _insert_edge(faces[j]["poly"], p, q)
    for i, p, q in flaps:
        faces[i]["poly"] = _insert_edge(faces[i]["poly"], p, q)
    for f in faces:                       # convex: order by angle, counter clockwise on the sheet (y up)
        c = np.mean(f["poly"], axis=0)
        f["poly"] = sorted(f["poly"], key=lambda p: math.atan2(-(p[1] - c[1]), p[0] - c[0]))
    return {"faces": faces, "hinges": hinges, "flaps": flaps, "regions": regs, "flap_ids": flap, "links": links}


def debug_image(rgb, piece_list, lines_list, reads, path):
    img = rgb.copy()
    for m in piece_list:
        cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(img, cnts, -1, (0, 160, 255), 2)
    for lines in lines_list:
        for p, q in lines:
            cv2.line(img, tuple(np.int32(p)), tuple(np.int32(q)), (255, 0, 80), 1)
    for rd in reads:
        for i in rd["flap_ids"]:
            img[rd["regions"][i]["mask"]] = (img[rd["regions"][i]["mask"]] * 0.5 + np.array([60, 200, 255]) * 0.5)
        for k, f in enumerate(rd["faces"]):
            col = (0, 140, 0) if not f["organic"] else (160, 0, 160)
            cv2.polylines(img, [np.int32(f["poly"])], True, col, 2)
            c = np.mean(f["poly"], axis=0).astype(int)
            cv2.putText(img, str(k), tuple(c), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
        for i, j, p, q in rd["hinges"]:
            cv2.line(img, tuple(np.int32(p)), tuple(np.int32(q)), (255, 0, 0), 4)
        for i, p, q in rd["flaps"]:
            cv2.line(img, tuple(np.int32(p)), tuple(np.int32(q)), (0, 90, 255), 4)
    Image.fromarray(img).save(path)


def read(sheet):
    rgb, k = load(sheet)
    ink, white, colour = classes(rgb)
    ps = pieces(ink, white)
    out = []
    for m in ps:
        ys, xs = np.nonzero(m)
        size = min(xs.max() - xs.min(), ys.max() - ys.min())
        lines = fold_lines(ink, m, max(25, size * 0.08))
        rd = read_piece(m, ink, white, lines)
        rd.update(mask=m, lines=lines)
        out.append(rd)
    return rgb, ink, white, out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("asset_dir")
    a = ap.parse_args()
    os.makedirs(a.asset_dir, exist_ok=True)
    rgb, ink, white, reads = read(a.sheet)
    for rd in reads:
        print(len(rd["faces"]), "faces", len(rd["hinges"]), "hinges", len(rd["flaps"]), "flaps",
              ["o" if f["organic"] else "p" for f in rd["faces"]])
    debug_image(rgb, [r["mask"] for r in reads], [r["lines"] for r in reads], reads,
                os.path.join(a.asset_dir, "read_debug.png"))
