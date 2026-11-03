"""Round the stacked frustums of a folded papercraft object (pumpkins, pots, trunks), inside Blender, after fold().

    exec(open("scripts/bp_round.py").read())
    round_parts(m, spec)        # spec "round": {"nets": ["low", "belly", "top"], "cuts": 3, "bulge": 0.06, "lobe": 0.03}

WebGL and WebGPU have no tessellation stage, so the rounding is baked here, once, before the export.
1. The faces of the listed nets (fold() tags each face with "pc_part") are welded across bands and subdivided.
   UVs are interpolated, so the painted texture stays valid: no new image.
2. Every vertex moves in cylindrical coordinates around the shape's axis:
   - radius from the profile of the original rings, rounded by Chaikin cuts (ends kept), plus "bulge" times the
     largest radius, as a sine from bottom to top (a belly);
   - times a rib factor: 1 at the middle of each painted panel, 1 - "lobe" on each fold line (the painted groove).
3. The region is smooth shaded. Other parts (stem, chimney, step) are left as folded.
"""
import math

import bmesh


def _rnd_chaikin(pts, n=3):
    for _ in range(n):
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out += [(0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]), (0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1])]
        pts = out + [pts[-1]]
    return pts


def _rnd_profile_at(prof, z):
    """Radius of a polyline [(z, r), ...] sorted by z, at height z (clamped at the ends)."""
    if z <= prof[0][0]:
        return prof[0][1]
    for (z0, r0), (z1, r1) in zip(prof, prof[1:]):
        if z <= z1:
            return r0 + (r1 - r0) * (z - z0) / max(z1 - z0, 1e-9)
    return prof[-1][1]


def round_parts(m, spec):
    cfg = spec.get("round")
    if not cfg:
        return None
    obj, lay = m["root"], m["layout"]
    want = {i + 1 for i, p in enumerate(lay["parts"]) if p["net"] in cfg["nets"]}
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    tag = bm.faces.layers.int.get("pc_part")
    faces = [f for f in bm.faces if f[tag] in want]
    verts = list({v for f in faces for v in f.verts})
    bmesh.ops.remove_doubles(bm, verts=verts, dist=1e-4)              # join the bands: one smooth surface
    faces = [f for f in bm.faces if f.is_valid and f[tag] in want]
    verts = list({v for f in faces for v in f.verts})
    cx = sum(v.co.x for v in verts) / len(verts)
    cy = sum(v.co.y for v in verts) / len(verts)
    rad = lambda v: math.hypot(v.co.x - cx, v.co.y - cy)
    ang = lambda v: math.atan2(v.co.x - cx, -(v.co.y - cy))           # 0 at -Y, as net.py unrolls frustums
    # profile of the original rings: the largest radius at each height (the 12-gon corners)
    rings = {}
    for v in verts:
        z = round(v.co.z, 4)
        rings[z] = max(rings.get(z, 0.0), rad(v))
    prof = sorted(rings.items())
    corner = max(verts, key=rad)
    n = cfg.get("panels") or round(2 * math.pi / _rnd_panel_angle(verts, rad, ang, prof))
    edge0 = ang(corner)
    edges = list({e for f in faces for e in f.edges})
    bmesh.ops.subdivide_edges(bm, edges=edges, cuts=cfg.get("cuts", 3), use_grid_fill=True)
    faces = [f for f in bm.faces if f[tag] in want]
    verts = list({v for f in faces for v in f.verts})
    smooth = _rnd_chaikin(prof, cfg.get("chaikin", 3))
    z0, z1, rmax = prof[0][0], prof[-1][0], max(r for _, r in prof)
    bulge, lobe = cfg.get("bulge", 0.05), cfg.get("lobe", 0.03)
    for v in verts:
        t = (v.co.z - z0) / max(z1 - z0, 1e-9)
        r = _rnd_profile_at(smooth, v.co.z) + bulge * rmax * math.sin(math.pi * min(max(t, 0), 1))
        u = ((ang(v) - edge0) * n / (2 * math.pi)) % 1.0             # 0 on a fold line, 0.5 mid panel
        r *= 1 - lobe * (1 - math.sin(math.pi * u)) ** 2
        a = ang(v)
        v.co.x, v.co.y = cx + r * math.sin(a), cy - r * math.cos(a)
    for f in faces:
        f.smooth = True
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.update()
    return "%d faces rounded, %d panels" % (len(faces), n)


def _rnd_panel_angle(verts, rad, ang, prof):
    """Angle between two neighbouring corners of the widest ring: 2 pi / number of panels."""
    zw = max(prof, key=lambda p: p[1])[0]
    ring = sorted(ang(v) for v in verts if abs(v.co.z - zw) < 1e-3 and rad(v) > 0.98 * max(r for _, r in prof))
    gaps = [b - a for a, b in zip(ring, ring[1:]) if b - a > 1e-3]
    return min(gaps) if gaps else math.pi / 6


print("bp_round ready")
