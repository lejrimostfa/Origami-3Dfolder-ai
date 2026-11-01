"""Shared checks: fold error at t=1, stretch at t=0.5, flatness at t=0, UV overlaps and orientation."""
import math

import numpy as np

import polynet
import unfold


def fold_error(lay):
    """Worst distance between the t=1 pose and the folded verts, over every net."""
    worst = 0.0
    for net in lay["nets"].values():
        for f, F in zip(net["faces"], unfold.net_pose(lay, net, 1.0)):
            worst = max(worst, max(math.dist(p, c) for p, c in zip(F, f["co"])))
    return worst


def stretch(lay, t=0.5):
    """Worst edge length change against the folded mesh. Caps grow from their centre, so they are skipped."""
    worst = 0.0
    for net in lay["nets"].values():
        for f, M in zip(net["faces"], unfold.net_pose(lay, net, t)):
            if f["name"].startswith("cap"):
                continue
            n = len(M)
            for j in range(n):
                d = math.dist(M[j], M[(j + 1) % n]) - math.dist(f["co"][j], f["co"][(j + 1) % n])
                worst = max(worst, abs(d))
    return worst


def _normal(pts):
    p = np.array(pts, float)
    _, s, vt = np.linalg.svd(p - p.mean(axis=0))
    return vt[-1], s[-1]


def flatness(lay):
    """At t=0 every net lies flat: its faces are planar and all their normals are parallel.
    Returns the worst (1 - |cos|) between face normals of a net, and the worst out-of-plane residual."""
    worst_cos, worst_res = 0.0, 0.0
    for net in lay["nets"].values():
        polys = [P for f, P in zip(net["faces"], unfold.net_pose(lay, net, 0.0)) if not f["name"].startswith("cap")]
        ref, _ = _normal(polys[0])
        for P in polys:
            n, res = _normal(P)
            worst_cos = max(worst_cos, 1 - abs(float(np.dot(n, ref))))
            worst_res = max(worst_res, float(res))
    return worst_cos, worst_res


def signed_area(uv):
    return sum(uv[i - 1][0] * uv[i][1] - uv[i][0] * uv[i - 1][1] for i in range(len(uv))) / 2


def uv_overlaps(net):
    """Pairs of faces of one net whose UV polygons overlap (shared edges do not count)."""
    faces = net["faces"]
    return [(a["name"], b["name"]) for i, a in enumerate(faces) for b in faces[i + 1:]
            if polynet._overlaps(a["uv"], b["uv"])]
