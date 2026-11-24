"""Run Tencent's P3-SAM automatic part splitting on meshes; save one part id per face.

Runs in P3-SAM's own Python (parts/.venv-p3sam, see setup/install_split.sh):
    python run_p3sam.py <out_dir> <mesh.glb> [mesh.glb ...]
Writes <out_dir>/<name>_faces.npy (part id per face of the mesh as loaded, -1 = none)
and <out_dir>/<name>_mesh.ply (that mesh, so ids and faces line up).

Windows changes, applied here so Tencent's code stays untouched:
  - no flash-attention: Sonata runs with enable_flash=False and smaller attention patches
  - Sonata's weights load from parts/weights instead of /root/sonata
  - prompt batch of 4 so it fits next to nothing else on a 24 GB card (peak ~21 GB)
"""
import os
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

PARTS = Path(os.environ.get("HI3D_PARTS", Path(__file__).resolve().parent.parent / "parts"))
REPO = PARTS / "Hunyuan3D-Part"
DEMO = REPO / "P3-SAM" / "demo"
WEIGHTS = PARTS / "weights"

sys.path.insert(0, str(REPO / "XPart" / "partgen"))
from models import sonata  # noqa: E402

_load = sonata.load


def _load_windows(name="sonata", repo_id="facebook/sonata", download_root=None, custom_config=None, ckpt_only=False):
    cfg = dict(custom_config or {}, enable_flash=False, enc_patch_size=[1024] * 5)
    return _load(name, repo_id=repo_id, download_root=str(WEIGHTS / "sonata"), custom_config=cfg, ckpt_only=ckpt_only)


sonata.load = _load_windows

sys.path.insert(0, str(DEMO))
os.chdir(DEMO)                                    # the demo resolves '..' imports from here
from auto_mask import AutoMask, set_seed          # noqa: E402

out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=True)
auto = AutoMask(str(WEIGHTS / "p3sam" / "p3sam.safetensors"))
for path in sys.argv[2:]:
    name = Path(path).stem
    mesh = trimesh.load(path, force="mesh")
    set_seed(42)
    t = time.time()
    aabb, face_ids, mesh = auto.predict_aabb(mesh, save_path=str(out / name), point_num=100000, prompt_num=400,
                                             threshold=0.95, post_process=0, save_mid_res=False, show_info=False,
                                             seed=42, is_parallel=False, clean_mesh_flag=True, prompt_bs=4)
    face_ids = np.asarray(face_ids)
    np.save(out / f"{name}_faces.npy", face_ids)
    mesh.export(out / f"{name}_mesh.ply")
    ids = np.unique(face_ids)
    print(f"{name}: {len(ids[ids >= 0])} parts in {time.time() - t:.0f}s; faces {len(face_ids)}", flush=True)
