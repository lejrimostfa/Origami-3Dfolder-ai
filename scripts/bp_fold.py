"""Papercraft, Blender side: fold a net layout back into a textured low-poly mesh. Runs INSIDE Blender.

    exec(open("scripts/blender_io.py").read()); exec(open("scripts/bp_fold.py").read())
    m = fold("examples/crate/layout.json", "examples/crate/texture.png")
    add_leaves(m, "spec.json", "leaves.json", "leaf_sheet.png")      # trees only
    export_glb(m, "crate.glb", clips=[], image_format="WEBP"); render_views(m, "review")

m is a model dict ({"objects", "root", "clips"}) that blender_io.export_glb and render_views take as is.
Relative paths resolve against the current directory.
Faces keep their net UVs. Vertices are welded per part, so a cone shades smooth and keeps one UV seam.
Alpha is clipped (Math Round on the texture alpha), which the glTF exporter ships as alphaMode MASK.
"""
import json
import math
import os

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

def _pc_abs(p):
    return os.path.abspath(p)


def _pc_material(name, image_path, clip):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        if n.type not in ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL"):
            nt.nodes.remove(n)
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(_pc_abs(image_path), check_existing=True)
    tex.interpolation = "Linear"
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.85
    if clip:
        rnd = nt.nodes.new("ShaderNodeMath")
        rnd.operation = "ROUND"
        nt.links.new(tex.outputs["Alpha"], rnd.inputs[0])
        nt.links.new(rnd.outputs[0], bsdf.inputs["Alpha"])
    mat.use_backface_culling = False
    return mat


def _pc_face(bm, uv_layer, cos, uvs, smooth, mat_index=0):
    # wind every face so its normal follows the net order (net.py and leaves.py emit outward faces)
    verts = [bm.verts.new(c) for c in cos]
    f = bm.faces.new(verts)
    f.smooth, f.material_index = smooth, mat_index
    for loop, uv in zip(f.loops, uvs):
        loop[uv_layer].uv = uv
    return verts


def _pc_matrix(part):
    s = part.get("scale", 1.0)
    s = Vector(s) if isinstance(s, (list, tuple)) else Vector((s, s, s))
    r = Euler([math.radians(a) for a in part.get("rot", (0, 0, 0))], "XYZ")
    return Matrix.LocRotScale(Vector(part.get("at", (0, 0, 0))), r, s)


def fold(layout_path, texture_path, name=None, collection=None, keep_seams=False):
    """keep_seams: weld only verts that share position AND uv, so cut edges can part (fold animation).
    It also records m["sources"]: per vertex its (part, face, corner), which bp_unfold.fold_anim reads."""
    lay = json.load(open(_pc_abs(layout_path)))
    name = name or lay["name"]
    me = bpy.data.meshes.new(f"GEO-{name}")
    obj = bpy.data.objects.new(f"GEO-{name}", me)
    (collection or bpy.context.scene.collection).objects.link(obj)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    sources = []
    for pi, part in enumerate(lay["parts"]):
        net, mx = lay["nets"][part["net"]], _pc_matrix(part)
        smooth = net["type"] == "frustum"
        if keep_seams:
            shared = {}
            for fi, f in enumerate(net["faces"]):
                vs = []
                for ci, (c, t) in enumerate(zip(f["co"], f["uv"])):
                    k = tuple(round(x, 5) for x in (*c, *t))
                    if k not in shared:
                        shared[k] = bm.verts.new(mx @ Vector(c))
                        sources.append((pi, fi, ci))
                    vs.append(shared[k])
                try:
                    face = bm.faces.new(vs)
                except ValueError:                       # a double card's back face: one face, as remove_doubles gives
                    continue
                face.smooth = smooth
                for loop, t in zip(face.loops, f["uv"]):
                    loop[uv].uv = t
            continue
        made = []
        for f in net["faces"]:
            made += _pc_face(bm, uv, [mx @ Vector(c) for c in f["co"]], f["uv"], smooth)
        bmesh.ops.remove_doubles(bm, verts=made, dist=1e-5)
    bm.to_mesh(me)
    bm.free()
    clip = not all(n["opaque"] for n in lay["nets"].values())
    me.materials.append(_pc_material(f"MAT-{name}", texture_path, clip))
    return {"objects": [obj], "root": obj, "armature": None, "clips": {}, "name": name, "layout": lay,
            "sources": sources}


def _pc_area(uvs):
    return sum(uvs[i][0] * uvs[i - 1][1] - uvs[i - 1][0] * uvs[i][1] for i in range(len(uvs))) / 2


def add_leaves(m, spec_path, leaves_path, sheet_path):
    """One flat card per spec leaf_cards entry, cut to the hull of a leaf from the sheet. Same object, second material."""
    spec, cut = json.load(open(_pc_abs(spec_path))), json.load(open(_pc_abs(leaves_path)))
    obj = m["root"]
    W, H = cut["px"]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv = bm.loops.layers.uv.verify()
    obj.data.materials.append(_pc_material(f"MAT-{m['name']}-leaves", sheet_path, clip=True))
    mi = len(obj.data.materials) - 1
    centre = sum((Vector(c["at"]) for c in spec["leaf_cards"]), Vector()) / max(1, len(spec["leaf_cards"]))
    for card in spec["leaf_cards"]:
        leaf = cut["leaves"][min(len(cut["leaves"]) - 1, int(card["pick"] * len(cut["leaves"])))]
        bu, bv = leaf["base"]
        k = card["size"] / max(leaf["size"][0] * W, leaf["size"][1] * H)
        uvs = leaf["uv"] if _pc_area(leaf["uv"]) > 0 else leaf["uv"][::-1]
        mx = _pc_matrix(card)
        cos = [mx @ Vector(((u - bu) * W * k, 0, (v - bv) * H * k)) for u, v in uvs]
        _pc_face(bm, uv, cos, uvs, smooth=True, mat_index=mi)
        m.setdefault("leaf_base", []).extend([list(card["at"])] * len(uvs))     # fold_anim grows leaves from here
    bm.to_mesh(obj.data)
    bm.free()
    # crown normals: each leaf vertex points away from the crown centre, so the crown shades like one soft volume
    # instead of a flicker of randomly lit cards. Other faces keep their own normals.
    me = obj.data
    normals = []
    for p in me.polygons:
        for li in p.loop_indices:
            if p.material_index == mi:
                n = (me.vertices[me.loops[li].vertex_index].co - centre).normalized()
                normals.append(n)
            else:
                normals.append(p.normal.copy() if not p.use_smooth else me.loops[li].normal.copy())
    me.normals_split_custom_set(normals)
    return len(spec["leaf_cards"])


print("bp_fold ready")
