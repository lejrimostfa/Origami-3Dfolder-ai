"""Papercraft thickness, Blender side: back faces and rims for nets with "thick", and rims around alpha holes
(holes.py outlines). Runs INSIDE Blender, exec'd before bp_fold.py (run_fold.py does both).
"""
from mathutils import Vector


def _pc_hole_rims(bm, uv, f, fi, loops_uv, t, pi, sources):
    """Rims along alpha holes of a thick face (holes.py outlines, in uv). Each outline point is an affine mix of the
    face's first three corners, so it follows the face when the fold animation turns it: source ("w", ...)."""
    L = list(f.loops)
    (a, b, c), n = [l[uv].uv for l in L[:3]], f.normal.copy()
    det = (b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)
    for loop in loops_uv:
        ring = []
        for u, v in loop:
            w1 = ((u - a.x) * (c.y - a.y) - (c.x - a.x) * (v - a.y)) / det
            w2 = ((b.x - a.x) * (v - a.y) - (u - a.x) * (b.y - a.y)) / det
            w = (1 - w1 - w2, w1, w2)
            p = sum((L[k].vert.co * w[k] for k in range(3)), Vector())
            ring.append((bm.verts.new(p), bm.verts.new(p - n * t), (u, v)))
            if sources is not None:
                sources += [("w", pi, fi, w, 0.0), ("w", pi, fi, w, t)]
        for i in range(len(ring)):
            (p0, q0, t0), (p1, q1, t1) = ring[i], ring[(i + 1) % len(ring)]
            rim = bm.faces.new([p0, p1, q1, q0])
            rim.material_index = f.material_index
            for loop, tt in zip(rim.loops, (t0, t1, t1, t0)):
                loop[uv].uv = tt


def _pc_thicken(bm, uv, made, t, pi, sources, holes=None):
    """Give a part's faces a thickness t, inward, so the outside keeps the spec size: a back face per face and a
    rim along every free edge (an edge no other face of the part shares). The rim takes the uvs of its edge, so it
    shows the dieline colour at the boundary. made: [(bmface, face index)]. Back verts are recorded in sources
    as (part, face, corner, t) so the fold animation can follow them."""
    key = lambda v: tuple(round(c, 5) for c in v.co)
    count = {}
    for f, _ in made:
        for e in f.edges:
            k = frozenset((key(e.verts[0]), key(e.verts[1])))
            count[k] = count.get(k, 0) + 1
    for f, fi in made:
        n = f.normal.copy()
        loops = list(f.loops)
        back = []
        for ci, l in enumerate(loops):
            back.append(bm.verts.new(l.vert.co - n * t))
            if sources is not None:
                sources.append((pi, fi, ci, t))
        bf = bm.faces.new(back[::-1])
        bf.smooth, bf.material_index = f.smooth, f.material_index
        for loop, src in zip(bf.loops, loops[::-1]):
            loop[uv].uv = src[uv].uv
        for i, l in enumerate(loops):
            j = (i + 1) % len(loops)
            a, b = l, loops[j]
            if count[frozenset((key(a.vert), key(b.vert)))] > 1:
                continue
            rim = bm.faces.new([b.vert, a.vert, back[i], back[j]])
            rim.material_index = f.material_index
            for loop, src in zip(rim.loops, (b, a, a, b)):
                loop[uv].uv = src[uv].uv
        if holes and str(fi) in holes:
            _pc_hole_rims(bm, uv, f, fi, holes[str(fi)], t, pi, sources)
