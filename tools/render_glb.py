"""Render a textured GLB from four sides with Blender (headless).

blender -b -P tools/render_glb.py -- <model.glb> <out.png> [size]
Writes one 2x2 contact sheet: front, right, back, left. Uses the material's own
textures (Eevee, flat studio light) so what you see is the painted colour.
"""
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], argv[1]
size = int(argv[2]) if len(argv) > 2 else 640

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector([min(c[i] for c in corners) for i in range(3)])
hi = Vector([max(c[i] for c in corners) for i in range(3)])
center, radius = (lo + hi) / 2, (hi - lo).length / 2

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [
    e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
scene.render.resolution_x = scene.render.resolution_y = size
scene.render.film_transparent = False
world = bpy.data.worlds.new("w")
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs[0].default_value = (0.8, 0.8, 0.8, 1)
bg.inputs[1].default_value = 1.0
scene.world = world
scene.view_settings.view_transform = "Standard"

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.lens = 50
scene.collection.objects.link(cam)
scene.camera = cam
distance = radius / math.tan(cam.data.angle / 2) * 1.05

tiles = []
for k, name in enumerate(["front", "right", "back", "left"]):
    a = math.radians(-90 + 90 * k)                      # glTF front (+Y after import is -Y in Blender)
    cam.location = center + Vector((math.cos(a) * distance, math.sin(a) * distance, radius * 0.15))
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    path = out.replace(".png", f"_{name}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    tiles.append(path)

img = [bpy.data.images.load(p) for p in tiles]
sheet = bpy.data.images.new("sheet", size * 2, size * 2)
px = [0.0] * (size * size * 16)
for i, im in enumerate(img):
    data = list(im.pixels)
    ox, oy = (i % 2) * size, (1 - i // 2) * size
    for y in range(size):
        row = data[y * size * 4:(y + 1) * size * 4]
        start = ((oy + y) * size * 2 + ox) * 4
        px[start:start + size * 4] = row
sheet.pixels = px
sheet.filepath_raw = out
sheet.file_format = "PNG"
sheet.save()
print("wrote", out)
