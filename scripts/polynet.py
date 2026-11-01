"""Generic papercraft nets: unfold any closed or open polygon mesh by its shared edges. Pure Python.

    poly_net(verts, faces)                    any mesh, faces wound outward (counter clockwise seen from outside)
    extrude_net(outline, length, keep=None)   a 2D profile in the YZ plane, extruded along X, centred on x = 0

Each face is laid flat with its outward side up, so a face never comes out mirrored. Children are hinged on their
parent edge, breadth first from the largest face. A face that would overlap the faces already laid starts its
own piece beside the others. Faces are named f0, f1, ... (poly) or capL, capR, side0, side1, ... (extrude).
"""
import math


def _sub(a, b):
    return [a[i] - b[i] for i in range(len(a))]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(len(a)))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return [x / n for x in a]


def _normal(pts):
    n = [0.0, 0.0, 0.0]
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n = [n[0] + (a[1] - b[1]) * (a[2] + b[2]), n[1] + (a[2] - b[2]) * (a[0] + b[0]),
             n[2] + (a[0] - b[0]) * (a[1] + b[1])]
    return _unit(n)


def _area3(pts):
    n = [0.0, 0.0, 0.0]
    for i in range(len(pts)):
        n = [n[k] + _cross(pts[i], pts[(i + 1) % len(pts)])[k] for k in range(3)]
    return math.sqrt(_dot(n, n)) / 2


def _local2d(pts):
    """The face in its own plane, seen from outside: x along the first edge, y = normal x first edge."""
    a = _unit(_sub(pts[1], pts[0]))
    b = _cross(_normal(pts), a)
    return [(_dot(_sub(p, pts[0]), a), _dot(_sub(p, pts[0]), b)) for p in pts]


def _fit2d(pts, i, j, pi, pj):
    """Rotate and move 2D pts so that pts[i] lands on pi and pts[j] on pj (same edge length, no mirror)."""
    a = math.atan2(pj[1] - pi[1], pj[0] - pi[0]) - math.atan2(pts[j][1] - pts[i][1], pts[j][0] - pts[i][0])
    c, s = math.cos(a), math.sin(a)
    out = []
    for x, y in pts:
        x, y = x - pts[i][0], y - pts[i][1]
        out.append((pi[0] + c * x - s * y, pi[1] + s * x + c * y))
    return out


def _seg_cross(p, q, r, s):
    """Proper crossing of segments pq and rs (shared end points do not count)."""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = orient(r, s, p), orient(r, s, q), orient(p, q, r), orient(p, q, s)
    e = 1e-9
    return ((d1 > e and d2 < -e) or (d1 < -e and d2 > e)) and ((d3 > e and d4 < -e) or (d3 < -e and d4 > e))


def _inside(pt, poly):
    x, y, c = pt[0], pt[1], False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _shrink(poly, k=0.98):
    cx, cy = sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)
    return [(cx + (x - cx) * k, cy + (y - cy) * k) for x, y in poly]


def _overlaps(a, b):
    a, b = _shrink(a), _shrink(b)
    for i in range(len(a)):
        for j in range(len(b)):
            if _seg_cross(a[i], a[(i + 1) % len(a)], b[j], b[(j + 1) % len(b)]):
                return True
    return _inside(a[0], b) or _inside(b[0], a)


def poly_net(verts, faces, names=None):
    names = names or [f"f{i}" for i in range(len(faces))]
    P = [[verts[i] for i in f] for f in faces]
    edges = {}
    for fi, f in enumerate(faces):
        for k in range(len(f)):
            edges.setdefault(frozenset((f[k], f[(k + 1) % len(f)])), []).append(fi)
    placed, pieces, todo = {}, [], set(range(len(faces)))
    while todo:
        root = max(todo, key=lambda i: _area3(P[i]))
        piece = {root: _local2d(P[root])}
        queue = [root]
        todo.discard(root)
        while queue:
            fi = queue.pop(0)
            f = faces[fi]
            for k in range(len(f)):
                for ci in edges[frozenset((f[k], f[(k + 1) % len(f)]))]:
                    if ci not in todo:
                        continue
                    c = faces[ci]
                    i, j = c.index(f[k]), c.index(f[(k + 1) % len(f)])
                    cand = _fit2d(_local2d(P[ci]), i, j, piece[fi][k], piece[fi][(k + 1) % len(f)])
                    if any(_overlaps(cand, q) for q in piece.values()):
                        continue                      # keep it for a later piece
                    piece[ci] = cand
                    todo.discard(ci)
                    queue.append(ci)
        pieces.append(piece)
    # pieces side by side along u, a small gap apart
    ox, gap = 0.0, 0.02 * max(max(abs(c) for v in verts for c in v), 0.05)
    for piece in pieces:
        u0 = min(x for q in piece.values() for x, _ in q)
        v0 = min(y for q in piece.values() for _, y in q)
        for fi, q in piece.items():
            placed[fi] = [(x - u0 + ox, y - v0) for x, y in q]
        ox += max(x for q in piece.values() for x, _ in q) - u0 + gap
    return [(names[fi], [(tuple(verts[vi]), placed[fi][k]) for k, vi in enumerate(faces[fi])])
            for fi in range(len(faces))]


def extrude_net(outline, length, keep=None):
    """outline: [[y, z], ...] simple polygon. Faces capL (x = -length/2), capR, side0.. (edge i to i+1).
    Classic extrusion net, linear time: the two caps, then the sides as one band cut into rows no longer
    than the cap is wide. Neighbouring sides stay hinged inside a row."""
    area = sum(outline[i][0] * outline[i - 1][1] - outline[i - 1][0] * outline[i][1] for i in range(len(outline)))
    pts = list(outline) if area < 0 else list(outline)[::-1]   # counter clockwise in (y, z): capR faces +x
    n, x = len(pts), length / 2
    want = lambda nm: keep is None or nm in keep
    out, caps = [], []
    for nm, poly in (("capL", [(-x, *pts[i]) for i in range(n)][::-1]), ("capR", [(x, *p) for p in pts])):
        if want(nm):
            q = _local2d(poly)
            caps.append((nm, poly, q))
    ox, top = 0.0, 0.0
    gap = 0.02 * max(max(abs(c) for p in pts for c in p), 0.05)
    for nm, poly, q in caps:
        u0, v0 = min(a for a, _ in q), min(b for _, b in q)
        out.append((nm, [(c, (a - u0 + ox, b - v0)) for c, (a, b) in zip(poly, q)]))
        ox += max(a for a, _ in q) - u0 + gap
        top = max(top, max(b for _, b in q) - v0)
    width = max(ox - gap, length * 4) / max(1, len(caps))
    u, row = 0.0, 0
    for i in range(n):
        j = (i + 1) % n
        e = math.dist(pts[i], pts[j])
        if not want(f"side{i}"):
            continue
        if u > 0 and u + e > width:
            u, row = 0.0, row + 1
        v = -(row + 1) * (length + gap)
        quad = [(-x, *pts[i]), (-x, *pts[j]), (x, *pts[j]), (x, *pts[i])]
        out.append((f"side{i}", list(zip(quad, [(u, v), (u + e, v), (u + e, v + length), (u, v + length)]))))
        u += e
    return out
