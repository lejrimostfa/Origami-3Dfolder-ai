"""Papercraft nets: unfold simple primitives into flat 2D nets and pack them into one UV atlas.
Pure Python, no bpy. bp_fold.py folds the same layout back into 3D inside Blender.

    python3 net.py spec.json layout.json

A spec lists nets and where each net is placed (one net can be placed many times, e.g. 4 table legs):
    {"name": "table", "atlas_px": 1024, "pad_px": 12,
     "nets": {"top": {"type": "box", "size": [1.2, 0.7, 0.05]},
              "leg": {"type": "box", "size": [0.06, 0.06, 0.7]}},
     "parts": [{"net": "top", "at": [0, 0, 0.7]},
               {"net": "leg", "at": [0.5, 0.28, 0]}, ...]}

Net types (units are metres, Z up, front is -Y, every face winds outward):
    box      size [w, d, h], base on z=0. Cross net: left, front, right, back in a band, top and bottom on front.
             Flat boxes (h < half the smaller side) use the tray net instead; "layout": "cross" | "tray" forces it.
             "faces": subset of left/front/right/back/top/bottom to keep.
    frustum  r0 (base), r1 (tip, 0 = cone), h, seg. True development: an annulus sector, foldable in paper.
             "cap": true closes the tip.
    card     size [w, h], vertical quad facing -Y. "double": true adds the back face (same texture, mirrored).
    extrude  outline [[y, z], ...] (a profile: gable roof, pistol grip), length along X centred on 0. polynet.py.
    poly     verts and faces (wound outward) of any low-poly mesh, unfolded by its shared edges. polynet.py.
Any net: "thick": metres gives its faces a real thickness, inward, with rims on free edges (planks, cards).

Layout output: per net its polygons (3D verts + UV in 0..1) and per part its placement. One texel density for
every net, so a leg and a table top share the same detail per metre.
"""
import json
import math
import sys

from polynet import extrude_net, poly_net


def box_net(w, d, h, faces=None):
    """Cross net in metres. Returns [(name, [(xyz, uv2d), ...])]. UV in metres before packing."""
    x, y = w / 2, d / 2
    band = d  # the band starts at v = d (bottom face sits under the front face)
    out = {
        "left": [((-x, y, 0), (0, band)), ((-x, -y, 0), (d, band)), ((-x, -y, h), (d, band + h)), ((-x, y, h), (0, band + h))],
        "front": [((-x, -y, 0), (d, band)), ((x, -y, 0), (d + w, band)), ((x, -y, h), (d + w, band + h)), ((-x, -y, h), (d, band + h))],
        "right": [((x, -y, 0), (d + w, band)), ((x, y, 0), (2 * d + w, band)), ((x, y, h), (2 * d + w, band + h)), ((x, -y, h), (d + w, band + h))],
        "back": [((x, y, 0), (2 * d + w, band)), ((-x, y, 0), (2 * d + 2 * w, band)), ((-x, y, h), (2 * d + 2 * w, band + h)), ((x, y, h), (2 * d + w, band + h))],
        "top": [((-x, -y, h), (d, band + h)), ((x, -y, h), (d + w, band + h)), ((x, y, h), (d + w, band + h + d)), ((-x, y, h), (d, band + h + d))],
        "bottom": [((-x, y, 0), (d, 0)), ((x, y, 0), (d + w, 0)), ((x, -y, 0), (d + w, band)), ((-x, -y, 0), (d, band))],
    }
    keep = faces or list(out)
    return [(k, out[k]) for k in keep]


def tray_net(w, d, h, faces=None):
    """Lid net for flat boxes (table tops, shelves): top in the middle, the four sides folded down around it,
    bottom beside. Far more compact than the cross when h is small."""
    x, y, g = w / 2, d / 2, 0.02 * max(w, d)
    ob = 2 * h + w + g
    out = {
        "top": [((-x, -y, h), (h, h)), ((x, -y, h), (h + w, h)), ((x, y, h), (h + w, h + d)), ((-x, y, h), (h, h + d))],
        "front": [((-x, -y, 0), (h, 0)), ((x, -y, 0), (h + w, 0)), ((x, -y, h), (h + w, h)), ((-x, -y, h), (h, h))],
        "back": [((x, y, 0), (h + w, 2 * h + d)), ((-x, y, 0), (h, 2 * h + d)), ((-x, y, h), (h, h + d)), ((x, y, h), (h + w, h + d))],
        "right": [((x, -y, 0), (2 * h + w, h)), ((x, y, 0), (2 * h + w, h + d)), ((x, y, h), (h + w, h + d)), ((x, -y, h), (h + w, h))],
        "left": [((-x, y, 0), (0, h + d)), ((-x, -y, 0), (0, h)), ((-x, -y, h), (h, h)), ((-x, y, h), (h, h + d))],
        "bottom": [((-x, y, 0), (ob, h)), ((x, y, 0), (ob + w, h)), ((x, -y, 0), (ob + w, h + d)), ((-x, -y, 0), (ob, h + d))],
    }
    keep = faces or list(out)
    return [(k, out[k]) for k in keep]


def frustum_net(r0, r1, h, seg=8, cap=False):
    """Unrolled side of a cone or frustum. Base ring on z=0, tip at z=h. Small offsets avoid a zero radius."""
    s = math.hypot(h, r0 - r1)
    if abs(r0 - r1) < 1e-6:                      # cylinder: a plain rectangle
        polys = []
        for i in range(seg):
            a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
            u0, u1 = r0 * a0, r0 * a1
            p = lambda a, z, r: (r * math.sin(a), -r * math.cos(a), z)
            polys.append((f"side{i}", [(p(a0, 0, r0), (u0, 0)), (p(a1, 0, r0), (u1, 0)),
                                       (p(a1, h, r1), (u1, s)), (p(a0, h, r1), (u0, s))]))
    else:
        L0 = r0 * s / (r0 - r1)                  # apex distance of the base ring in the development
        L1 = L0 - s
        theta = 2 * math.pi * r0 / L0            # sector angle
        polys = []
        for i in range(seg):
            a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
            t0, t1 = theta * i / seg - theta / 2, theta * (i + 1) / seg - theta / 2
            q = lambda t, L: (L * math.sin(t), L * math.cos(t) - L0)   # base ring through v = 0 at the centre
            p = lambda a, z, r: (r * math.sin(a), -r * math.cos(a), z)
            ring = [(p(a0, 0, r0), q(t0, L0)), (p(a1, 0, r0), q(t1, L0))]
            if r1 > 1e-6:
                ring += [(p(a1, h, r1), q(t1, L1)), (p(a0, h, r1), q(t0, L1))]
            else:
                ring += [((0, 0, h), q((t0 + t1) / 2, 0))]
            polys.append((f"side{i}", ring))
        # q() puts v negative for the inner ring: flip so the tip is up in the atlas
        polys = [(n, [(xyz, (u, -v)) for xyz, (u, v) in poly]) for n, poly in polys]
    # cap: True or "top" closes the tip, "both" also the base. Each cap sits right of the strip.
    ox = max(u for _, poly in polys for _, (u, _) in poly) + 0.01
    ring = lambda r, z, sgn: [((r * math.sin(sgn * 2 * math.pi * i / seg), -r * math.cos(2 * math.pi * i / seg), z),
                               (ox + r + r * math.sin(2 * math.pi * i / seg),     # seen from outside
                                r - r * math.cos(2 * math.pi * i / seg))) for i in range(seg)]
    if cap and r1 > 1e-6:
        polys.append(("cap", ring(r1, h, 1)))
        ox += 2 * r1 + 0.01
    if cap == "both":
        polys.append(("capBase", ring(r0, 0, -1)))     # mirrored order: its outside faces down
    return polys


def card_net(w, h, double=False):
    x = w / 2
    front = [((-x, 0, 0), (0, 0)), ((x, 0, 0), (w, 0)), ((x, 0, h), (w, h)), ((-x, 0, h), (0, h))]
    polys = [("front", front)]
    if double:   # back face reuses the same pixels, mirrored, so the window reads the same from both sides
        polys.append(("back", [((x, 0, 0), (w, 0)), ((-x, 0, 0), (0, 0)), ((-x, 0, h), (0, h)), ((x, 0, h), (w, h))]))
    return polys


def build_net(n):
    t = n["type"]
    if t == "box":
        w, d, h = n["size"]
        flat = n.get("layout", "tray" if h < 0.5 * min(w, d) else "cross") == "tray"
        return (tray_net if flat else box_net)(w, d, h, faces=n.get("faces"))
    if t == "frustum":
        return frustum_net(n["r0"], n.get("r1", 0.0), n["h"], n.get("seg", 8), n.get("cap", False))
    if t == "card":
        return card_net(*n["size"], double=n.get("double", False))
    if t == "extrude":
        return extrude_net(n["outline"], n["length"], n.get("faces"))
    if t == "poly":
        return poly_net(n["verts"], n["faces"])
    raise ValueError(f"unknown net type {t}")


def _bounds(polys):
    us = [uv[0] for _, p in polys for _, uv in p]
    vs = [uv[1] for _, p in polys for _, uv in p]
    return min(us), min(vs), max(us), max(vs)


def _shelf(sizes, scale, pad):
    """Shelf packing in a unit square. Returns offsets or None when it does not fit."""
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i][1])
    x = y = shelf = pad
    offs = [None] * len(sizes)
    for i in order:
        w, h = sizes[i][0] * scale, sizes[i][1] * scale
        if x + w + pad > 1:
            x, y, shelf = pad, y + shelf, 0
        if x + w + pad > 1 or y + h + pad > 1:
            return None
        offs[i] = (x, y)
        x += w + pad
        shelf = max(shelf, h + pad)
    return offs


def pack(nets, pad):
    """Largest common scale (metres to UV) that fits every net, found by bisection."""
    names = list(nets)
    sizes = []
    for k in names:
        u0, v0, u1, v1 = _bounds(nets[k])
        sizes.append((u1 - u0, v1 - v0))
    lo, hi = 0.0, 1.0 / max(max(s) for s in sizes)
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _shelf(sizes, mid, pad) else (lo, mid)
    offs = _shelf(sizes, lo, pad)
    return lo, dict(zip(names, offs))


def layout(spec):
    pad = spec.get("pad_px", 12) / spec.get("atlas_px", 1024)
    nets = {k: build_net(v) for k, v in spec["nets"].items()}
    scale, offs = pack(nets, pad)
    out = {"name": spec["name"], "atlas_px": spec.get("atlas_px", 1024), "pad_px": spec.get("pad_px", 12),
           "texel_m": 1 / (scale * spec.get("atlas_px", 1024)), "nets": {}, "parts": spec["parts"],
           "opaque": spec.get("opaque", True), "labels": spec.get("labels", {})}
    for k, polys in nets.items():
        u0, v0, _, _ = _bounds(polys)
        ox, oy = offs[k]
        out["nets"][k] = {"type": spec["nets"][k]["type"], "opaque": spec["nets"][k].get("opaque", out["opaque"]),
                          "faces": [{"name": n, "co": [list(xyz) for xyz, _ in p],
                                     "uv": [[ox + (u - u0) * scale, oy + (v - v0) * scale] for _, (u, v) in p]}
                                    for n, p in polys]}
        if spec["nets"][k].get("thick"):                 # bp_fold gives the folded faces this thickness
            out["nets"][k]["thick"] = spec["nets"][k]["thick"]
    return out


if __name__ == "__main__":
    lay = layout(json.load(open(sys.argv[1])))
    json.dump(lay, open(sys.argv[2], "w"), indent=1)
    print(f"{lay['name']}: {len(lay['nets'])} nets, {len(lay['parts'])} parts, {lay['texel_m'] * 1000:.1f} mm per px")
