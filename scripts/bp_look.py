"""Render look for papercraft shots, Blender side: three lights, soft shadows, ray traced AO and reflections.

    exec(open("scripts/bp_look.py").read())
    setup_look(centre, radius)          # before the camera; then render with EEVEE

Key: a warm area light high at the front left. Fill: a cool weak light at the right. Rim: a bright light behind,
so the silhouette separates from the background. World: a soft sky to ground gradient that lights the shadows.
EEVEE ray tracing gives screen space reflections and horizon scan occlusion (the EEVEE take on SSAO), so creases
and contact points darken. AgX with a medium high contrast look.
"""
import math

from mathutils import Vector


def _pc_light(name, kind, energy, colour, loc, target, size):
    light = bpy.data.lights.new(name, kind)
    light.energy, light.color = energy, colour
    if kind == "AREA":
        light.size = size
    else:
        light.shadow_soft_size = size
    obj = bpy.data.objects.new(name, light)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (target - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return obj


def setup_look(centre, radius, ground=True, ground_colour=(0.085, 0.09, 0.105)):
    sc = bpy.context.scene
    c, r = Vector(centre), max(radius, 0.15)
    d = r * 4
    _pc_light("Key", "AREA", 340 * r * r, (1.0, 0.92, 0.82), c + Vector((-0.6, -0.8, 0.9)) * d, c, r * 0.45)
    _pc_light("Fill", "AREA", 70 * r * r, (0.78, 0.86, 1.0), c + Vector((0.9, -0.5, 0.3)) * d, c, r * 2.5)
    _pc_light("Rim", "AREA", 220 * r * r, (0.85, 0.92, 1.0), c + Vector((0.3, 1.0, 0.7)) * d, c, r * 1.2)
    w = sc.world or bpy.data.worlds.new("World")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = next(n for n in nt.nodes if n.type == "BACKGROUND")
    grad = nt.nodes.new("ShaderNodeValToRGB")                      # sky above, darker ground colour below
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(coord.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], grad.inputs["Fac"])
    grad.color_ramp.elements[0].color = (0.05, 0.055, 0.065, 1)
    grad.color_ramp.elements[1].color = (0.34, 0.38, 0.46, 1)
    grad.color_ramp.elements[0].position, grad.color_ramp.elements[1].position = 0.45, 0.75
    nt.links.new(grad.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.45                    # dim enough that the key casts readable shadows
    if ground:
        bpy.ops.mesh.primitive_plane_add(size=r * 40, location=(c.x, c.y, -0.0005))
        g = bpy.context.object
        m = bpy.data.materials.new("Ground")
        m.use_nodes = True
        b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        b.inputs["Base Color"].default_value = (*ground_colour, 1)
        b.inputs["Roughness"].default_value = 0.45                 # a slight sheen picks up the reflections
        g.data.materials.append(m)
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            sc.render.engine = eng
            break
        except TypeError:
            pass
    ee = sc.eevee
    for attr, val in (("use_raytracing", True), ("use_shadows", True), ("shadow_ray_count", 2),
                      ("shadow_step_count", 8), ("use_gtao", True), ("gtao_distance", r * 0.6),
                      ("fast_gi_distance", r * 0.6), ("taa_render_samples", 64)):
        if hasattr(ee, attr):
            try:
                setattr(ee, attr, val)
            except (TypeError, AttributeError):
                pass
    if hasattr(ee, "ray_tracing_options"):
        ee.ray_tracing_options.resolution_scale = "1"
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass


print("bp_look ready")
