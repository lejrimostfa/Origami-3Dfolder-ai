"""Face expressions on a folded character, Blender side. Runs INSIDE Blender, after bp_fold.py.

    add_expressions(m, "examples/dog/expressions.json")                # from expressions.py split

Each variant (eyes closed, mouth open) is a copy of its face disk 0.6 mm in front of it, textured from faces.png.
At rest the copy is collapsed to the disk centre, so it is invisible; a shape key opens it. The clips (Blink,
Talk) switch those keys with constant steps, the way a flipbook does, and ship as glTF morph target animations,
the same mechanism as the Fold clip. Fold keys copy the rest pose, so a variant stays hidden while folding.
"""

_PC_EXPR_TIMING = {
    "Blink": [(1, 0), (40, 0), (41, 1), (46, 1), (47, 0), (60, 0)],                  # one blink every 2.5 s
    "Talk": [(f, (f // 5) % 2) for f in range(1, 61, 5)] + [(60, 0)],               # mouth open, shut, open...
}


def add_expressions(m, expr_path):
    expr = json.load(open(_pc_abs(expr_path)))
    obj, lay = m["root"], m["layout"]
    me = obj.data
    sheet = os.path.join(os.path.dirname(_pc_abs(expr_path)), expr["sheet"])
    me.materials.append(_pc_material(f"MAT-{m['name']}-faces", sheet, clip=False))
    mi = len(me.materials) - 1
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.verify()
    pending = []                                           # (variant, first vertex index, open positions)
    for v in expr["variants"]:
        for part in lay["parts"]:
            if part["net"] != v["net"]:
                continue
            net = lay["nets"][v["net"]]
            f = next(g for g in net["faces"] if g["name"] == v["face"])
            mx = _pc_matrix(part)
            pts = [mx @ Vector(c) for c in f["co"]]
            n = (pts[1] - pts[0]).cross(pts[2] - pts[0]).normalized()
            pts = [p + n * 0.0006 for p in pts]
            centre = sum(pts, Vector()) / len(pts)
            us, vs = [t[0] for t in f["uv"]], [t[1] for t in f["uv"]]
            u0, v0, u1, v1 = min(us), min(vs), max(us), max(vs)
            b0, c0, b1, c1 = v["uv_box"]
            first = len(bm.verts)
            verts = [bm.verts.new(centre) for _ in pts]
            face = bm.faces.new(verts)
            face.material_index = mi
            for loop, (tu, tv) in zip(face.loops, f["uv"]):
                loop[uv].uv = (b0 + (tu - u0) / (u1 - u0) * (b1 - b0), c0 + (tv - v0) / (v1 - v0) * (c1 - c0))
            pending.append((v, first, pts))
    bm.to_mesh(me)
    bm.free()
    if me.shape_keys is None:
        obj.shape_key_add(name="Folded")
    keys = {}
    for v, first, pts in pending:
        kb = me.shape_keys.key_blocks.get(f"expr_{v['name']}") or obj.shape_key_add(name=f"expr_{v['name']}", from_mix=False)
        for i, p in enumerate(pts):
            kb.data[first + i].co = p
        keys.setdefault(v["clip"], []).append(kb)
    key = me.shape_keys
    key.animation_data_create()
    for clip, kbs in keys.items():
        act = bpy.data.actions.new(f"{m['name']}_{clip}")
        key.animation_data.action = act
        for kb in kbs:
            for f, val in _PC_EXPR_TIMING.get(clip, _PC_EXPR_TIMING["Blink"]):
                kb.value = val
                kb.keyframe_insert("value", frame=f)
            kb.value = 0
        for fc in getattr(act, "fcurves", []):
            for p in fc.keyframe_points:
                p.interpolation = "CONSTANT"               # glTF STEP: a flipbook, no half-open eyes
        key.animation_data.action = None
        tr = key.animation_data.nla_tracks.new()
        tr.name = clip
        tr.strips.new(clip, 1, act)
        m["clips"][clip] = act
    return sorted(keys)


print("bp_expr ready")
