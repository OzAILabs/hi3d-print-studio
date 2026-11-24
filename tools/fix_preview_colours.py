"""Convert a print-colour preview made before the linear-colour fix (sRGB stored as-is)."""
import sys
import numpy as np
import trimesh

for p in sys.argv[1:]:
    m = trimesh.load(p, force="mesh")
    c = np.asarray(m.visual.vertex_colors)[:, :3].astype(float) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m.visual.vertex_colors = np.c_[np.round(lin * 255).astype(np.uint8), np.full(len(lin), 255, np.uint8)]
    m.export(p)
    print("fixed", p)
