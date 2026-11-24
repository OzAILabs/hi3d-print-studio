"""Run the Colour Print step outside ComfyUI on a finished Hi3D 04 run.

python tools/test_colour_print.py <detail_1024.glb> <final.glb> <out_dir> [height_mm]
Seals the detail mesh with WTiVo (his print settings), then runs colour_print.run.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

NODES = Path(r"D:\AI Stuff\Claude\Hi3d\ComfyUI_py312\ComfyUI\custom_nodes")
sys.path.insert(0, str(NODES / "WTiVo-WatertightVoxel-ComfyuiNode"))
sys.path.insert(0, str(NODES))

from inprocess import process_arrays  # noqa: E402
import importlib  # noqa: E402

cp = importlib.import_module("Hi3D-ColourPrint.colour_print")

detail, final, out = sys.argv[1], sys.argv[2], sys.argv[3]
height = float(sys.argv[4]) if len(sys.argv) > 4 else 100.0
d = trimesh.load(detail, force="mesh")
print("detail faces", len(d.faces))
t = time.time()
r = process_arrays(np.asarray(d.vertices), np.asarray(d.faces), input_res=1536, final_res=1536,
                   proxy_points=12_000_000, proxy_eps_scale=1.0, proxy_feature_weight=1.5,
                   lambda_fill=20.0, threads=16, thin_iso_vox=0.0, faithc_component_mode="largest")
v, f = r[0], r[1]
print(f"WTiVo: {len(f):,} faces in {time.time() - t:.0f}s; extra: {r[2] if len(r) > 2 else ''}")
res = cp.run(v, f, final, out, "dragon_test", cp.Settings(height_mm=height))
print(json.dumps(res.report, indent=1, default=str)[:6000])
