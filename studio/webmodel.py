"""Make a light copy of a big GLB for the browser (run as its own process).

python webmodel.py <src.glb> <dst.glb> <max_faces> <copy|clay> [measure]
Runs outside the studio server so the heavy work never stalls the web page.
With "measure", also writes <dst>.json with how deep the shape is (see measure()).
"""
import json
import shutil
import sys

import numpy as np


def measure(src, dst):
    """How deep the shape is: its thinnest side / its middle side.

    A flat cartoon can come back from the shape model as a cardboard cut-out: one
    side a few percent of the others. Thin / middle (not thin / longest) so a tall
    but round figure does not count as flat. Sides are measured along the shape's
    own main axes, 1st to 99th percentile, so a few stray bits don't stretch them.
    """
    import trimesh

    m = trimesh.load(src, force="mesh", process=False)
    v = np.asarray(m.vertices, np.float64)
    v = v[:: max(1, len(v) // 200_000)]
    v = v - v.mean(0)
    _, _, axes = np.linalg.svd(v, full_matrices=False)
    p = v @ axes.T
    e = np.sort(np.percentile(p, 99, axis=0) - np.percentile(p, 1, axis=0))
    depth = float(e[0] / e[1]) if e[1] > 0 else 0.0
    with open(dst + ".json", "w") as f:
        json.dump({"depth": round(depth, 3)}, f)


def main(src, dst, faces, mode, extra=""):
    if extra == "measure":
        measure(src, dst)
    if mode == "copy":
        shutil.copyfile(src, dst)
        return
    import fast_simplification
    import trimesh

    m = trimesh.load(src, force="mesh", process=False)
    v, f = np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.int32)
    if len(f) > faces:
        v, f = fast_simplification.simplify(v, f, target_count=faces)
    small = trimesh.Trimesh(v, f, process=False)
    # Matte clay, two-sided (generated meshes are not always consistently oriented).
    small.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[200, 196, 188, 255], metallicFactor=0.0, roughnessFactor=0.75, doubleSided=True))
    small.export(dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else "")
