"""Blender side: GLB export and review renders for a folded model. Runs INSIDE Blender (headless is fine).

    exec(open("scripts/blender_io.py").read())
    export_glb(m, "export/crate.glb", clips=[], image_format="WEBP")      static mesh
    export_glb(m, "export/crate_fold.glb", clips=["Fold"], image_format="WEBP")   morph targets + clip
    render_views(m, "review/01")                                          front, left, back, right PNGs

m is the model dict from bp_fold.fold(): {"objects", "root", "clips", ...}. A clip is an action on the mesh's
shape keys, played by an NLA track of the same name (bp_unfold.fold_anim makes it). The exporter runs in
NLA_TRACKS mode and ships every track, muted or not, so other tracks are set aside during the export.
"""
import math
import os

import bpy
from mathutils import Vector


def world_bounds(m):
    """World-space (lo, hi) corners over the mesh objects of a model."""
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in m["objects"] if o.type == 'MESH' for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def _key_tracks(m, clips):
    """Make sure each listed clip has an NLA track on the shape keys. Set the others aside. Returns undo info."""
    undo = []
    for o in m["objects"]:
        key = o.data.shape_keys if o.type == 'MESH' else None
        if key is None:
            continue
        ad = key.animation_data or key.animation_data_create()
        names = {t.name for t in ad.nla_tracks}
        for c in clips:
            if c not in names and c in m["clips"]:
                tr = ad.nla_tracks.new()
                tr.name = c
                tr.strips.new(c, int(m["clips"][c].frame_range[0]), m["clips"][c])
                undo.append(("remove", ad, tr))
        for t in [t for t in ad.nla_tracks if t.name not in clips]:
            kept = (t.name, [(st.name, int(st.frame_start), st.action) for st in t.strips])
            ad.nla_tracks.remove(t)
            undo.append(("restore", ad, kept))
    return undo


def _undo_tracks(undo):
    for op, ad, item in undo:
        if op == "remove":
            ad.nla_tracks.remove(item)
            continue
        tr = ad.nla_tracks.new()
        tr.name = item[0]
        for name, start, act in item[1]:
            tr.strips.new(name, start, act)


def export_glb(m, path, clips=None, image_format=None, pointer=False):
    """One GLB for Three.js: +Y up, embedded textures, only the model's objects of the active scene.
    clips: names from m["clips"] to ship. None = all of them, [] = static mesh (no animation at all).
    image_format: None keeps the exporter default, "WEBP" or "JPEG" shrink the textures.
    pointer: also ship material animations (scrolling water) through KHR_animation_pointer."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    names = sorted(m["clips"]) if clips is None else list(clips)
    undo = _key_tracks(m, names) if names else []
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in m["objects"]:
        o.select_set(True)
    kw = dict(filepath=path, export_format='GLB', use_selection=True, export_yup=True,
              export_animations=bool(names), export_apply=False)
    props = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
    if "use_active_scene" in props:
        kw["use_active_scene"] = True                 # else selected objects of every scene ship
    if names and "export_animation_mode" in props:
        kw["export_animation_mode"] = 'NLA_TRACKS'    # one glTF animation per track, nothing else
    if image_format and "export_image_format" in props:
        kw["export_image_format"] = image_format
    if pointer and "export_pointer_animation" in props:
        kw["export_pointer_animation"] = True
    try:
        bpy.ops.export_scene.gltf(**kw)
    finally:
        _undo_tracks(undo)
    return {"path": os.path.basename(path), "kb": os.path.getsize(path) // 1024, "clips": names}


def _eevee(r):
    for ident in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):     # the name changed in Blender 4.2
        try:
            r.engine = ident
            return
        except TypeError:
            continue


def render_views(m, out_dir, size=768, views=("front", "left", "back", "right"), engine="eevee"):
    """Orthographic EEVEE renders around the model (it faces -Y). 'left' is the model's left, seen from +X.
    Grey world plus one sun, Standard view transform, transparent film. Scene settings are restored."""
    scn = bpy.context.scene
    lo, hi = world_bounds(m)
    centre, extent = (lo + hi) / 2, max(hi - lo) * 1.1
    cam = bpy.data.objects.new("PC_Cam", bpy.data.cameras.new("PC_Cam"))
    scn.collection.objects.link(cam)
    cam.data.type, cam.data.ortho_scale = 'ORTHO', extent
    cam.data.clip_end = extent * 10
    sun = bpy.data.objects.new("PC_Sun", bpy.data.lights.new("PC_Sun", 'SUN'))
    sun.data.energy, sun.rotation_euler = 2.5, (math.radians(50), 0, math.radians(30))
    scn.collection.objects.link(sun)
    r = scn.render
    saved = (r.engine, r.resolution_x, r.resolution_y, r.film_transparent, scn.view_settings.view_transform,
             scn.world, scn.camera)
    if engine == "eevee":
        _eevee(r)
    else:
        r.engine = 'BLENDER_WORKBENCH'
    w = bpy.data.worlds.new("PC_World")
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == 'BACKGROUND')
    bg.inputs[0].default_value = (0.55, 0.55, 0.55, 1)
    scn.world, scn.camera = w, cam
    scn.view_settings.view_transform = 'Standard'
    r.resolution_x = r.resolution_y = size
    r.film_transparent = True
    r.image_settings.file_format, r.image_settings.color_mode = 'PNG', 'RGBA'
    # hide everything that is not this model (the default cube in a headless run without --factory-startup)
    others = [(o, o.hide_render) for o in scn.objects if o not in m["objects"] and o not in (cam, sun)]
    for o, _ in others:
        o.hide_render = True
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    out = []
    yaw = {"front": 0, "left": 90, "back": 180, "right": -90}
    for v in views:
        a = math.radians(yaw[v])
        d = Vector((math.sin(a), -math.cos(a), 0))
        cam.location = centre + d * extent * 3
        cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
        r.filepath = os.path.join(out_dir, f"{v}.png")
        bpy.ops.render.render(write_still=True)
        out.append(r.filepath)
    for o, was in others:
        o.hide_render = was
    (r.engine, r.resolution_x, r.resolution_y, r.film_transparent, scn.view_settings.view_transform,
     scn.world, scn.camera) = saved
    for o in (cam, sun):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.worlds.remove(w)
    return out


print("blender_io ready")
