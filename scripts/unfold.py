"""Papercraft fold animation math: where every net vertex sits at fold amount t (0 flat, 1 folded). Pure Python.

    faces = net_pose(lay, net, t)       # per face, its verts in net-local coordinates (before the part matrix)
    python3 unfold.py layout.json       # self check: t=1 gives the folded mesh, edges keep their length

box and card nets: faces that share a UV edge share a fold line, so the faces form a hinge tree. A child turns
about its hinge by t times its fold angle: faces stay rigid and hinges never open. Each root face lies flat on
its base plane at t=0 and turns about its lowest edge.
frustum nets: the sector rolls up through a family of cones with the same development, so the paper never
stretches. The base ring stays on z=0. At t=0 the sector lies flat around the axis.
bp_unfold.py samples these poses into shape keys.
"""
import json
import math
import sys


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _mul(a, k):
    return [a[0] * k, a[1] * k, a[2] * k]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return _mul(a, 1 / n)


def _normal(pts):
    """Newell normal: right for any planar polygon."""
    n = [0.0, 0.0, 0.0]
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n = _add(n, [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
    return _unit(n)


def _centroid(pts):
    return _mul([sum(p[k] for p in pts) for k in range(3)], 1 / len(pts))


def _angle_about(a, b, axis):
    """Signed angle that turns a onto b about axis, both projected off the axis."""
    a = _sub(a, _mul(axis, _dot(a, axis)))
    b = _sub(b, _mul(axis, _dot(b, axis)))
    return math.atan2(_dot(_cross(a, b), axis), _dot(a, b))


def flat(lay, face):
    """Face verts on the flat sheet, metres, z = 0. UV keeps orientation, so nothing is mirrored."""
    k = lay["atlas_px"] * lay["texel_m"]
    return [[u * k, v * k, 0.0] for u, v in face["uv"]]


def _apply(T, p):
    R, t = T
    return [_dot(R[0], p) + t[0], _dot(R[1], p) + t[1], _dot(R[2], p) + t[2]]


def _compose(A, B):
    """A after B."""
    Ra, ta = A
    Rb, tb = B
    R = [[sum(Ra[i][k] * Rb[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return R, _add(_apply((Ra, [0, 0, 0]), tb), ta)


def _turn(o, axis, ang):
    """Rotation by ang about the line through o along unit axis (Rodrigues), as a transform."""
    x, y, z = axis
    c, s, k = math.cos(ang), math.sin(ang), 1 - math.cos(ang)
    R = [[c + x * x * k, x * y * k - z * s, x * z * k + y * s],
         [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
         [z * x * k - y * s, z * y * k + x * s, c + z * z * k]]
    return R, _sub(o, _apply((R, [0, 0, 0]), o))


def _rigid(src, dst):
    """The rotation plus translation that carries polygon src onto the same shaped polygon dst."""
    a, ad = _unit(_sub(src[1], src[0])), _unit(_sub(dst[1], dst[0]))
    n, nd = _normal(src), _normal(dst)
    b, bd = _cross(n, a), _cross(nd, ad)
    R = [[ad[i] * a[j] + bd[i] * b[j] + nd[i] * n[j] for j in range(3)] for i in range(3)]
    return R, _sub(dst[0], _apply((R, [0, 0, 0]), src[0]))


def hinge_tree(lay, net):
    """{face: None for a root, or (parent, edge point a, edge point b) on the flat sheet}, parents first.
    A root is the face with the most downward normal, then the largest. Disconnected pieces get their own root."""
    fl = [flat(lay, f) for f in net["faces"]]
    key = lambda p: (round(p[0], 5), round(p[1], 5))
    edges = {}
    for i, f in enumerate(fl):
        for j in range(len(f)):
            a, b = f[j], f[(j + 1) % len(f)]
            edges.setdefault(frozenset((key(a), key(b))), []).append((i, a, b))
    rank = lambda i: (round(_normal(net["faces"][i]["co"])[2], 3), -abs(_normal(fl[i])[2] * len(fl[i])))
    parent = {}
    while len(parent) < len(fl):
        root = min((i for i in range(len(fl)) if i not in parent), key=rank)
        parent[root], todo = None, [root]
        while todo:
            i = todo.pop(0)
            for users in edges.values():
                if len(users) == 2 and i in (users[0][0], users[1][0]):
                    other = users[1] if users[0][0] == i else users[0]
                    if other[0] not in parent:
                        parent[other[0]] = (i, other[1], other[2])
                        todo.append(other[0])
    return parent


def box_pose(lay, net, t):
    faces = net["faces"]
    fl = [flat(lay, f) for f in faces]
    rigid = [_rigid(fl[i], f["co"]) for i, f in enumerate(faces)]       # flat sheet -> folded, per face
    parent = hinge_tree(lay, net)
    pose = {}                                                             # one transform per face, parents first
    for i, link in parent.items():
        if link is None:
            # folded = turn(lowest edge, b) of lying flat: so at t the root is turned back by b * (1 - t)
            co = faces[i]["co"]
            j = min(range(len(co)), key=lambda j: co[j][2] + co[(j + 1) % len(co)][2])
            o, axis = co[j], _unit(_sub(co[(j + 1) % len(co)], co[j]))
            n = _normal(co)
            b = 0.0 if abs(n[2]) > 0.999 else _angle_about(n, [0, 0, 1 if n[2] >= 0 else -1], axis)
            pose[i] = _compose(_turn(o, axis, b * (1 - t)), rigid[i])
            continue
        p, ea, eb = link
        # folded child = the parent's map carried on past the hinge, then turned about the hinge by a
        ha, hb = _apply(rigid[p], ea), _apply(rigid[p], eb)
        axis = _unit(_sub(hb, ha))
        c = _centroid(fl[i])
        a = _angle_about(_sub(_apply(rigid[p], c), ha), _sub(_apply(rigid[i], c), ha), axis)
        pa, pb = _apply(pose[p], ea), _apply(pose[p], eb)
        pose[i] = _compose(_turn(pa, _unit(_sub(pb, pa)), a * t), pose[p])
    return [[_apply(pose[i], q) for q in fl[i]] for i in range(len(faces))]


def _caps(net, out, t):
    """Caps are not rolled: they grow from their centre at the end, once the rim is in place."""
    g = min(1.0, max(0.0, (t - 0.8) / 0.2))
    for i, f in enumerate(net["faces"]):
        if f["name"].startswith("cap"):
            c = _centroid(f["co"])
            out[i] = [_add(c, _mul(_sub(p, c), g)) for p in f["co"]]
    return out


def frustum_pose(lay, net, t):
    faces = net["faces"]
    fl = [flat(lay, f) for f in faces]
    co0 = faces[0]["co"]
    h = max(c[2] for f in faces for c in f["co"])
    r0 = math.hypot(co0[0][0], co0[0][1])
    r1 = 0.0 if len(co0) == 3 else math.hypot(co0[2][0], co0[2][1])
    if abs(r0 - r1) < 1e-6:
        return _caps(net, _cylinder(fl, r0, t), t)
    s = math.hypot(h, r0 - r1)
    L0 = r0 * s / (r0 - r1)                                # apex to base ring, on the sheet
    B, T = fl[0][0], fl[0][2] if len(co0) == 3 else fl[0][3]
    apex = T if len(co0) == 3 else _add(B, _mul(_sub(T, B), L0 / s))
    d0 = _unit(_sub(B, apex))                              # direction of the seam vertex, phi = -theta/2
    sign = 1 if _cross(d0, _sub(fl[0][1], apex))[2] > 0 else -1
    kf = r0 / L0                                           # sin of the folded half angle
    k = 1 + (kf - 1) * t
    ck = math.sqrt(max(0.0, 1 - k * k))

    def place(p):
        v = _sub(p, apex)
        L = math.sqrt(_dot(v, v))
        a = sign * math.atan2(_cross(d0, v)[2], _dot(d0, v))
        phi = -math.pi * kf + (a + 2 * math.pi if a < -1e-9 else a)     # sectors wider than 180 degrees
        psi = phi / k
        return [-L * k * math.sin(psi), L * k * math.cos(psi), (L0 - L) * ck]
    return _caps(net, [[place(p) for p in f] for f in fl], t)


def _cylinder(fl, r, t):
    """A cylinder strip curls from a flat sheet standing at y = r into the tube (curvature t / r)."""
    B, eu = fl[0][0], _unit(_sub(fl[0][1], fl[0][0]))
    ev = _cross([0, 0, 1], eu)
    c = max(t, 1e-4) / r

    def place(p):
        u, v = _dot(_sub(p, B), eu) - math.pi * r, _dot(_sub(p, B), ev)
        return [-math.sin(c * u) / c, math.cos(c * u) / c + r - 1 / c, v]
    return [[place(p) for p in f] for f in fl]


def net_pose(lay, net, t):
    if net["type"] == "frustum":
        return frustum_pose(lay, net, t)
    return box_pose(lay, net, t)


def _check(lay):
    """t=1 must give the folded verts. At t=0.5 every edge keeps its folded length (rigid paper)."""
    worst = {}
    for name, net in lay["nets"].items():
        fold, mid = net_pose(lay, net, 1.0), net_pose(lay, net, 0.5)
        e1 = max(math.dist(p, c) for f, F in zip(net["faces"], fold) for p, c in zip(F, f["co"]))
        e2 = max(abs(math.dist(M[j], M[(j + 1) % len(M)]) - math.dist(f["co"][j], f["co"][(j + 1) % len(M)]))
                 for f, M in zip(net["faces"], mid) if not f["name"].startswith("cap") for j in range(len(M)))
        worst[name] = {"fold_err_m": round(e1, 6), "stretch_m": round(e2, 6)}
    return worst


if __name__ == "__main__":
    print(json.dumps(_check(json.load(open(sys.argv[1])))))
