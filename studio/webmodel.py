"""Make a light copy of a big GLB for the browser (run as its own process).

python webmodel.py <src.glb> <dst.glb> <max_faces> <copy|clay>
Runs outside the studio server so the heavy work never stalls the web page.
"""
import shutil
import sys

import numpy as np


def main(src, dst, faces, mode):
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
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4])
