"""Papercraft, Blender side: fold a net layout back into a textured low-poly mesh. Runs INSIDE Blender.

    exec(open("scripts/blender_io.py").read()); exec(open("scripts/bp_thick.py").read())
    exec(open("scripts/bp_fold.py").read())
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


def _pc_occlusion_group():
    """The node group the glTF exporter reads occlusion from (its "glTF Material Output" convention)."""
    g = bpy.data.node_groups.get("glTF Material Output")
    if g is None:
        g = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    return g


def _pc_material(name, image_path, clip, normal_path=None, ao_path=None):
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
    if normal_path and os.path.exists(_pc_abs(normal_path)):   # maps.py: relief inferred from the texture
        nimg = nt.nodes.new("ShaderNodeTexImage")
        nimg.image = bpy.data.images.load(_pc_abs(normal_path), check_existing=True)
        nimg.image.colorspace_settings.name = "Non-Color"
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(nimg.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    if ao_path and os.path.exists(_pc_abs(ao_path)):           # maps.py: cavity occlusion for game engines
        aimg = nt.nodes.new("ShaderNodeTexImage")
        aimg.image = bpy.data.images.load(_pc_abs(ao_path), check_existing=True)
        aimg.image.colorspace_settings.name = "Non-Color"
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        out = nt.nodes.new("ShaderNodeGroup")
        out.node_tree = _pc_occlusion_group()
        nt.links.new(aimg.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs[0], out.inputs["Occlusion"])
    bsdf.inputs["Roughness"].default_value = 0.7
    for sock in ("Specular IOR Level", "Specular"):            # a soft sheen on paint and stone
        if sock in bsdf.inputs:
            bsdf.inputs[sock].default_value = 0.35
            break
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
    It also records m["sources"]: per vertex its (part, face, corner), which bp_unfold.fold_anim reads.
    A net with "thick": metres gets a back face and rims (_pc_thicken)."""
    lay = json.load(open(_pc_abs(layout_path)))
    name = name or lay["name"]
    me = bpy.data.meshes.new(f"GEO-{name}")
    obj = bpy.data.objects.new(f"GEO-{name}", me)
    (collection or bpy.context.scene.collection).objects.link(obj)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    tag = bm.faces.layers.int.new("pc_part")             # part index + 1 per face (0: rims), read by bp_round.py
    sources = []
    for pi, part in enumerate(lay["parts"]):
        net, mx = lay["nets"][part["net"]], _pc_matrix(part)
        smooth = net["type"] == "frustum"
        faces = []
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
                face.smooth, face[tag] = smooth, pi + 1
                for loop, t in zip(face.loops, f["uv"]):
                    loop[uv].uv = t
                faces.append((face, fi))
            if net.get("thick"):
                bm.normal_update()
                _pc_thicken(bm, uv, faces, net["thick"], pi, sources, net.get("holes"), 6 / lay["atlas_px"])
            continue
        made = []
        for fi, f in enumerate(net["faces"]):
            vs = _pc_face(bm, uv, [mx @ Vector(c) for c in f["co"]], f["uv"], smooth)
            made += vs
            vs[0].link_faces[0][tag] = pi + 1
            faces.append((vs[0].link_faces[0], fi))
        if net.get("thick"):
            bm.normal_update()
            _pc_thicken(bm, uv, faces, net["thick"], pi, None, net.get("holes"), 6 / lay["atlas_px"])
        bmesh.ops.remove_doubles(bm, verts=made, dist=1e-5)
    bm.to_mesh(me)
    bm.free()
    clip = not all(n["opaque"] for n in lay["nets"].values())
    normal = os.path.join(os.path.dirname(_pc_abs(texture_path)), "normal.png")
    ao = os.path.join(os.path.dirname(_pc_abs(texture_path)), "ao.png")
    me.materials.append(_pc_material(f"MAT-{name}", texture_path, clip, normal, ao))
    return {"objects": [obj], "root": obj, "armature": None, "clips": {}, "name": name, "layout": lay,
            "sources": sources}


def _pc_area(uvs):
    return sum(uvs[i][0] * uvs[i - 1][1] - uvs[i - 1][0] * uvs[i][1] for i in range(len(uvs))) / 2


def add_leaves(m, spec_path, leaves_path, sheet_path):
    """One flat card per spec leaf_cards entry, from one leaf of the sheet. Same object, second material.
    spec "leaf_card": "quad" (default) is the leaf's bounding rectangle, 2 triangles, alpha clip cuts the shape.
    "hull" follows the leaf outline (about 7 triangles): less transparent overdraw, 3.5 times the triangles."""
    spec, cut = json.load(open(_pc_abs(spec_path))), json.load(open(_pc_abs(leaves_path)))
    quad = spec.get("leaf_card", "quad") == "quad"
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
        if quad:
            u0, u1 = min(u for u, _ in uvs), max(u for u, _ in uvs)
            v0, v1 = min(v for _, v in uvs), max(v for _, v in uvs)
            uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]           # counter clockwise, like the hull
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
