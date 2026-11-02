"""Flowing water for a folded asset, Blender side. Runs INSIDE Blender, after bp_fold.py.

    add_water(m, spec)        # spec["water"]: disks (still surfaces) and veils (falling curtains), see below

{"kind": "disk", "at": [x, y, z], "r": 0.5, "tex": "surface", "speed": [du, dv]}     a horizontal water surface
{"kind": "veil", "at": [x, y, z], "r": 0.3, "h": 0.8, "tex": "fall", "speed": [0, dv]} an open cylinder of falling water
Textures come from water.py (water_surface.png, water_fall.png, both tiling). Each material scrolls its uv through
a Mapping node animated in the NLA track "Flow". glTF ships it as KHR_texture_transform animated by
KHR_animation_pointer (export_glb pointer=True). The loop is 10 s and each speed is rounded so the offset ends on
a whole tile: the loop has no seam. Water vertices grow from each piece's centre at the end of the Fold clip.
"""
import math

_PC_FLOW_FRAMES = 240                                          # 10 s at 24 fps


def _pc_water_material(name, image_path, blend, speed):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(_pc_abs(image_path), check_existing=True)
    tex.extension = "REPEAT"
    mapping = nt.nodes.new("ShaderNodeMapping")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.08
    if blend:
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
            if hasattr(mat, attr):
                try:
                    setattr(mat, attr, val)
                except TypeError:
                    pass
    mat.use_backface_culling = False
    # whole tiles per loop: the last frame shows the same texture as the first
    tiles = [round(s * _PC_FLOW_FRAMES / 24) or (1 if s else 0) * (1 if s > 0 else -1) for s in speed]
    loc = mapping.inputs["Location"]
    nt.animation_data_create()
    act = bpy.data.actions.new(f"{name}_Flow")
    nt.animation_data.action = act
    for f, k in ((1, 0.0), (_PC_FLOW_FRAMES + 1, 1.0)):
        loc.default_value = (tiles[0] * k, tiles[1] * k, 0)
        loc.keyframe_insert("default_value", frame=f)
    for fc in getattr(act, "fcurves", []):
        for p in fc.keyframe_points:
            p.interpolation = "LINEAR"
    nt.animation_data.action = None
    tr = nt.animation_data.nla_tracks.new()
    tr.name = "Flow"
    tr.strips.new("Flow", 1, act)
    return mat, act


def add_water(m, spec, asset_dir, tile_m=0.5, seg=24):
    obj = m["root"]
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.verify()
    base = m.setdefault("leaf_base", [])                        # fold_anim grows these verts at the end
    for w in spec.get("water", []):
        mat, act = _pc_water_material(f"MAT-{m['name']}-water-{w['tex']}-{len(me.materials)}",
                                      os.path.join(asset_dir, f"water_{w['tex']}.png"), w["kind"] == "veil", w["speed"])
        me.materials.append(mat)
        mi = len(me.materials) - 1
        m["clips"]["Flow"] = act
        c, r = Vector(w["at"]), w["r"]
        ring = [(math.cos(2 * math.pi * i / seg), math.sin(2 * math.pi * i / seg)) for i in range(seg)]
        if w["kind"] == "disk":
            vs = [bm.verts.new(c + Vector((x * r, y * r, 0))) for x, y in ring]
            f = bm.faces.new(vs)
            f.material_index = mi
            for loop, (x, y) in zip(f.loops, ring):
                loop[uv].uv = (x * r / (2 * tile_m), y * r / (2 * tile_m))   # still water: broad, slow cells
            base += [list(c)] * seg
        else:
            h, rep = w["h"], 3                                  # 3 repeats around the veil
            for i in range(seg):
                (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % seg]
                quad = [c + Vector((x0 * r, y0 * r, 0)), c + Vector((x1 * r, y1 * r, 0)),
                        c + Vector((x1 * r, y1 * r, h)), c + Vector((x0 * r, y0 * r, h))]
                f = bm.faces.new([bm.verts.new(p) for p in quad])
                f.material_index = mi
                u0, u1 = rep * i / seg, rep * (i + 1) / seg
                for loop, t in zip(f.loops, ((u0, 0), (u1, 0), (u1, h / tile_m), (u0, h / tile_m))):
                    loop[uv].uv = t
                base += [list(c + Vector((0, 0, h)))] * 4      # the veil grows from the bowl rim
    bm.to_mesh(me)
    bm.free()
    return ["Flow"] if spec.get("water") else []


print("bp_water ready")
