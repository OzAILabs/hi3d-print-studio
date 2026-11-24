"""Which workflow node belongs to which user-facing stage, and what each stage costs.

Node ids refer to studio/workflow_api.json (built by build_template.py).
"""

STAGES = [
    # key, title, description, node ids, typical seconds
    # typical seconds measured on the dragon (RTX PRO 5000 laptop, 2026-11-23)
    ("cutout", "Cut-out", "Removing the background", {122, 192, 193, 248, 302, 303, 312}, 15),
    ("shape", "Shape", "TRELLIS.2 builds the 3D shape", {3, 4, 15, 18, 23, 40, 55, 56, 87, 91, 92, 94, 108, 117, 119, 125, 126,
                                                         199, 242, 246, 247, 279, 298, 299, 314, 315, 316, 318, 319, 408, 902}, 100),
    ("prep", "Clean-up", "Remeshing for Hi3D", {389, 390, 391, 392, 393, 394, 395, 396, 397}, 150),
    ("hi3d512", "Hi3D 512", "First detail pass", {398, 399, 400}, 35),
    ("hi3d1024", "Hi3D 1024", "Fine detail pass", {401, 402, 403, 407}, 155),
    ("paintmesh", "Paint mesh", "Simplifying the detail mesh for painting", {903}, 30),
    ("paint", "Painting", "UltraTex paints colour from your picture",
     {353, 354, 355, 356, 357, 358, 359, 361, 362, 364, 365, 366, 367, 368, 369, 370, 371, 372, 373, 374, 375, 376, 377,
      378, 383, 384, 385, 386, 387, 388}, 735),
    ("seal", "Seal", "WTiVo makes one closed solid", {900}, 95),
    ("print", "Print file", "Filling hollows, filament colours, Bambu slice check", {901}, 150),
]

WORK = {
    # The nodes that do a stage's actual work. ComfyUI runs loaders and constants early,
    # so a stage only counts as started when one of these starts, and as finished when
    # all of them have finished.
    "cutout": {192, 312},
    "shape": {3, 18, 23, 92, 902},       # (MoGe only runs for Pixal3D, VoxelToMesh only for a preview)
    "prep": {390, 391, 395, 396, 397},
    "hi3d512": {398, 399, 400},
    "hi3d1024": {401, 402, 403, 407},
    "paintmesh": {903},
    "paint": {375, 358, 364, 377, 384, 385, 386},
    "seal": {900},
    "print": {901},
}
WORK = {k: {str(n) for n in v} for k, v in WORK.items()}

NODE_STAGE = {str(n): key for key, _, _, nodes, _ in STAGES for n in nodes}
STAGE_NODES = {key: {str(n) for n in nodes} for key, _, _, nodes, _ in STAGES}
STAGE_SECONDS = {key: secs for key, _, _, _, secs in STAGES}

SHOT_LABELS = {
    "302": "Cut-out",
    "303": "Mask",
    "359": "UltraTex colour views",
    "365": "UltraTex material views",
    "370": "Painting setup: normals",
    "371": "Painting setup: depth",
    "373": "Painting setup: mask",
}
