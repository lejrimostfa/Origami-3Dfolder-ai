"""Papercraft fold animation, Blender side: the sheet lies flat, folds up, the leaves grow. Runs INSIDE Blender.

    exec(open("scripts/bp_fold.py").read()); _PC_HERE = "scripts"; exec(open("scripts/bp_unfold.py").read())
    m = fold(layout, texture, keep_seams=True)            # seams stay open: a cut edge must part when unfolding
    add_leaves(m, spec, leaves, sheet)                    # trees only
    fold_anim(m)                                          # shape keys + action "Fold" on an NLA track
    export_glb(m, path, clips=["Fold"])                   # glTF morph targets, one clip

Poses come from unfold.py (pure Python). Each part folds in its own time window, parts in spec order, so a table
top folds before its legs. A placed part also turns and lifts from lying on the ground to its place. Leaves grow
from their stem at the end. The basis stays the folded mesh, so a viewer without the clip shows the object.
"""
import sys

# unfold.py sits next to this file. exec() gives no __file__ of its own, so the caller sets _PC_HERE (run_fold does)
sys.path.insert(0, os.path.abspath(globals().get("_PC_HERE") or os.path.dirname(os.path.abspath(__file__))))
import unfold                                             # noqa: E402

from mathutils import Quaternion                          # noqa: E402


def _pc_smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _pc_part_matrix(part, k, i):
    """Part matrix at progress k: from lying on the ground to its place. The sheet floats 3 mm per part above
    z=0, so it never flickers against a ground plane or another flat sheet."""
    full = _pc_matrix(part)
    loc, rot, scl = full.decompose()
    start = Vector((loc.x, loc.y, 0.003 * (i + 1)))
    return Matrix.LocRotScale(start.lerp(loc, k), Quaternion().slerp(rot, k), scl)


def fold_anim(m, frames=72, hold=12, steps=16, nets_end=0.8, window=0.5, leaves_from=0.65):
    """Adds steps-1 shape keys (flat ... almost folded) and the action m["clips"]["Fold"]. Returns the frame range."""
    obj, lay = m["root"], m["layout"]
    me = obj.data
    src = m["sources"]                                     # per net vertex: (part, face, corner), from fold()
    parts = lay["parts"]
    n = len(parts)
    window = window if n > 1 else 1.0                      # one part takes the whole fold span
    start = [(nets_end - window * nets_end) * (i / max(1, n - 1)) for i in range(n)]
    base = m.get("leaf_base", [])                          # per leaf vertex: its card stem, from add_leaves
    zs = [b[2] for b in base] or [0.0]
    z0, z1 = min(zs), max(zs) + 1e-6
    cards = [(Vector(b), leaves_from + 0.2 * (b[2] - z0) / (z1 - z0)) for b in base]    # low leaves first
    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Folded")
    keys = []
    for s in range(steps - 1):
        t = s / (steps - 1)
        poses = {}
        for i, part in enumerate(parts):
            k = _pc_smooth((t - start[i]) / (window * nets_end))
            poses[i] = (_pc_part_matrix(part, k, i), unfold.net_pose(lay, lay["nets"][part["net"]], k))
        kb = obj.shape_key_add(name=f"Fold{s:02d}", from_mix=False)
        for vi, sv in enumerate(src):
            if sv[0] == "w":                               # a hole rim point: affine mix of 3 corners, then inward
                _, pi, fi, w, depth = sv
                mx, pose = poses[pi]
                p = mx @ sum((Vector(pose[fi][k]) * w[k] for k in range(3)), Vector())
            else:
                mx, pose = poses[sv[0]]
                pi, fi = sv[0], sv[1]
                p = mx @ Vector(pose[fi][sv[2]])
                depth = sv[3] if len(sv) == 4 else 0.0     # a back vertex of a thick face
            if depth:                                      # inward of its posed face, in metres after scale
                p -= (mx.to_3x3() @ Vector(unfold._normal(pose[fi]))).normalized() * depth
            kb.data[vi].co = p
        for j, (base, g0) in enumerate(cards):
            vi = len(src) + j
            g = _pc_smooth((t - g0) / 0.15)
            kb.data[vi].co = base + (me.vertices[vi].co - base) * g
        keys.append(kb)
    # key s is 1 on its own frame and 0 on its neighbours: linear blends between neighbouring rigid poses
    fr = [hold + s * frames / (steps - 1) for s in range(steps)]
    key = me.shape_keys
    key.animation_data_create()
    act = bpy.data.actions.new(f"{m['name']}_Fold")
    key.animation_data.action = act
    for s, kb in enumerate(keys):
        pts = ([(1, 1.0)] if s == 0 else [(fr[s - 1], 0.0)]) + [(fr[s], 1.0), (fr[s + 1], 0.0)]
        for f, v in pts:
            kb.value = v
            kb.keyframe_insert("value", frame=f)
    for fc in getattr(act, "fcurves", []):
        for p in fc.keyframe_points:
            p.interpolation = "LINEAR"
    key.animation_data.action = None
    tr = key.animation_data.nla_tracks.new()
    tr.name = "Fold"
    tr.strips.new("Fold", 1, act)
    m["clips"]["Fold"] = act
    end = int(fr[-1] + hold)
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, end
    return 1, end


print("bp_unfold ready")
