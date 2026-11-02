"""Headless fold of one papercraft asset folder: GLB export and EEVEE review views.

    blender --background --factory-startup --python scripts/run_fold.py -- examples/crate [review/01]

Reads layout.json and texture.png. A tree folder also needs spec.json, leaves.json and leaf_sheet.png.
Writes export/<name>.glb (WEBP textures), build/<name>.blend and, with a review folder (relative to the asset),
front/left/back/right.png there. Then export/<name>_fold.glb: the same object with the clip "Fold"
(flat sheet to folded, glTF morph targets) and build/<name>_fold.blend.
"""
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
_PC_HERE = HERE                                         # bp_unfold imports unfold.py from here
exec(open(os.path.join(HERE, "blender_io.py")).read())
exec(open(os.path.join(HERE, "bp_thick.py")).read())        # thickness helpers used by fold()
exec(open(os.path.join(HERE, "bp_fold.py")).read())
exec(open(os.path.join(HERE, "bp_unfold.py")).read())
exec(open(os.path.join(HERE, "bp_expr.py")).read())        # Blink, Talk (expressions.json)
exec(open(os.path.join(HERE, "bp_water.py")).read())       # Flow (spec "water", water.py textures)

args = sys.argv[sys.argv.index("--") + 1:]
A = os.path.abspath(args[0])


def build(keep_seams):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for me in [me for me in bpy.data.meshes if me.users == 0]:
        bpy.data.meshes.remove(me)                      # so the second build is GEO-<name>, not GEO-<name>.001
    bpy.context.view_layer.update()                     # else the view layer still lists the removed objects
    m = fold(os.path.join(A, "layout.json"), os.path.join(A, "texture.png"), keep_seams=keep_seams)
    if os.path.exists(os.path.join(A, "leaves.json")):
        print("leaves", add_leaves(m, os.path.join(A, "spec.json"), os.path.join(A, "leaves.json"),
                                   os.path.join(A, "leaf_sheet.png")))
    spec = json.load(open(os.path.join(A, "spec.json"))) if os.path.exists(os.path.join(A, "spec.json")) else {}
    m["extra_clips"] = add_water(m, spec, A)
    expr = os.path.join(A, "expressions.json")
    m["extra_clips"] += add_expressions(m, expr) if os.path.exists(expr) else []
    me = m["root"].data
    print("mesh", len(me.vertices), "verts", len(me.polygons), "faces")
    return m


m = build(keep_seams=False)
print(export_glb(m, os.path.join(A, "export", m["name"] + ".glb"), clips=m["extra_clips"], image_format="WEBP",
                 pointer="Flow" in m["extra_clips"]))
os.makedirs(os.path.join(A, "build"), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A, "build", m["name"] + ".blend"))
if len(args) > 1:
    print("views", len(render_views(m, os.path.join(A, args[1]), engine="eevee")))
m = build(keep_seams=True)
print("fold frames", fold_anim(m))
print(export_glb(m, os.path.join(A, "export", m["name"] + "_fold.glb"), clips=["Fold"] + m["extra_clips"],
                 image_format="WEBP", pointer="Flow" in m["extra_clips"]))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A, "build", m["name"] + "_fold.blend"))
