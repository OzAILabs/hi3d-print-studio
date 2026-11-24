"""Experimental: split a finished studio print into printable pieces (one call).

python split_job.py <painted.3mf> <work_dir> <pieces> <#hex,#hex,...> [printer]

1. a 150k-face upright copy of the print mesh (cached in work_dir/input)
2. P3-SAM's parts on it, in P3-SAM's own Python (cached in work_dir/p3sam: about 30 s,
   and needs ~21 GB of graphics memory, so nothing else may be using the GPU)
3. split.py cuts the print into <pieces> closed, pegged, painted pieces and builds a
   Bambu project (work_dir/pieces_<n>/model_pieces_bambu.3mf)
Prints the report as JSON on its last line.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import fast_simplification
import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PARTS = Path(os.environ.get("HI3D_PARTS", ROOT / "parts"))
P3SAM_PY = PARTS / ".venv-p3sam" / "Scripts" / "python.exe"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "comfyui_nodes" / "Hi3D-ColourPrint"))
import split  # noqa: E402
from colour_print import GLTF_TO_PRINT  # noqa: E402


def main(painted_3mf, work_dir, pieces, palette, printer="A1 mini 0.4"):
    work = Path(work_dir)
    (work / "input").mkdir(parents=True, exist_ok=True)
    glb = work / "input" / "model.glb"
    if not glb.exists():
        v, f, _ = split.load_painted(painted_3mf)
        sv, sf = fast_simplification.simplify(v.astype(np.float32), f.astype(np.int32), target_count=150_000)
        small = trimesh.Trimesh(sv, sf, process=True)
        small.vertices = (small.vertices - small.bounds.mean(0)) @ GLTF_TO_PRINT     # upright, glTF frame
        small.export(glb)
    p3 = work / "p3sam"
    if not (p3 / "model_faces.npy").exists():
        if not P3SAM_PY.exists():
            raise SystemExit("P3-SAM is not installed: run setup/install_split.sh")
        env = dict(os.environ, PYTHONUTF8="1", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True",
                   HI3D_PARTS=str(PARTS))
        r = subprocess.run([str(P3SAM_PY), str(HERE / "run_p3sam.py"), str(p3), str(glb)], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not (p3 / "model_faces.npy").exists():
            tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
            raise SystemExit("P3-SAM failed: " + " | ".join(tail))
    out = work / f"pieces_{pieces}"
    rep = split.split(painted_3mf, p3, "model", pieces, out, palette, printer)
    bambu = rep.get("bambu") or {}
    project = bambu.get("project")
    return {"pieces": rep["pieces"], "p3sam_parts": rep["p3sam_parts"],
            "project": str(Path(project).resolve()) if project else None,
            "assembled": str((out / "model_pieces.3mf").resolve()),
            "sliced": bool(project) and not bambu.get("slice_failed"),
            "print_hours": bambu.get("print_hours"), "colour_changes": bambu.get("colour_changes"),
            "message": (bambu.get("message") or "").strip(),
            "pegs": sum(1 for j in rep["joints"] if j.get("peg")), "joints": len(rep["joints"]),
            "piece_sizes_mm": [p["size_mm"] for p in rep["piece_info"]], "seconds": rep["seconds"]}


if __name__ == "__main__":
    a = sys.argv[1:]
    result = main(a[0], a[1], int(a[2]), a[3].split(","), a[4] if len(a) > 4 else "A1 mini 0.4")
    print(json.dumps(result))
