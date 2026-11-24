"""Hero render of a GLB with Blender: transparent background, soft studio light.

blender -b --factory-startup -P tools/hero_render.py -- <model.glb> <out.png> [size] [azimuth_deg] [elevation_deg]
Azimuth 0 = the model's front. Works for textured, vertex-coloured and plain meshes.
"""
import math
import sys

import bpy
from mathutils import Vector

a = sys.argv[sys.argv.index("--") + 1:]
src, out = a[0], a[1]
size = int(a[2]) if len(a) > 2 else 1200
azim = float(a[3]) if len(a) > 3 else -25.0
elev = float(a[4]) if len(a) > 4 else 8.0

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
obs = [o for o in bpy.context.scene.objects if o.type == "MESH"]

# Vertex-coloured meshes (the print-colour preview) need their colour wired in.
for o in obs:
    for slot in o.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        nodes = mat.node_tree.nodes
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf and not bsdf.inputs["Base Color"].is_linked and o.data.color_attributes:
            attr = nodes.new("ShaderNodeVertexColor")
            attr.layer_name = o.data.color_attributes[0].name
            mat.node_tree.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
        if bsdf:
            # A print is plastic: drop painted metal-shine maps (they read as chrome).
            for link in list(bsdf.inputs["Metallic"].links):
                mat.node_tree.links.remove(link)
            bsdf.inputs["Metallic"].default_value = 0.05
    if not o.material_slots:
        mat = bpy.data.materials.new("clay")
        mat.use_nodes = True
        b = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        b.inputs["Base Color"].default_value = (0.62, 0.6, 0.57, 1)
        b.inputs["Roughness"].default_value = 0.6
        o.data.materials.append(mat)

cs = [o.matrix_world @ Vector(c) for o in obs for c in o.bound_box]
lo = Vector([min(c[i] for c in cs) for i in range(3)])
hi = Vector([max(c[i] for c in cs) for i in range(3)])
ctr, r = (lo + hi) / 2, (hi - lo).length / 2

sc = bpy.context.scene
engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
sc.render.resolution_x = sc.render.resolution_y = size
sc.render.film_transparent = True
sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in bpy.types.ColorManagedViewSettings.bl_rna.properties["view_transform"].enum_items] else "Standard"
w = bpy.data.worlds.new("w")
w.use_nodes = True
bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs[0].default_value = (0.55, 0.57, 0.62, 1)
bg.inputs[1].default_value = 0.35
sc.world = w


def light(name, kind, energy, loc, size_=None, color=(1, 1, 1)):
    d = bpy.data.lights.new(name, kind)
    d.energy = energy
    d.color = color
    if size_:
        d.size = size_
    o = bpy.data.objects.new(name, d)
    o.location = ctr + Vector(loc) * r
    o.rotation_euler = (ctr - o.location).to_track_quat("-Z", "Y").to_euler()
    sc.collection.objects.link(o)


light("key", "AREA", 380 * r * r, (-1.6, -2.2, 2.0), 2.5 * r, (1.0, 0.97, 0.92))
light("fill", "AREA", 140 * r * r, (2.2, -1.6, 0.6), 3.0 * r, (0.9, 0.95, 1.0))
light("rim", "AREA", 320 * r * r, (0.6, 2.6, 1.8), 2.0 * r, (0.85, 0.9, 1.0))

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.lens = 70
sc.collection.objects.link(cam)
sc.camera = cam
d = r / math.tan(cam.data.angle / 2) * 1.02
az, el = math.radians(-90 + azim), math.radians(elev)
cam.location = ctr + Vector((math.cos(az) * math.cos(el) * d, math.sin(az) * math.cos(el) * d, math.sin(el) * d))
cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
print("wrote", out)
