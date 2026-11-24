"""Build studio/workflow_api.json from the captured Hi3D 04 run (API format).

Adds: WTiVo seal of the Hi3D 1024 mesh, the Colour Print 3MF node, and a save of the
coarse shape for the live 3D preview. Run once after changing the workflow.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
p = json.loads((HERE / "workflow_hi3d04_api.json").read_text())

p["900"] = {"class_type": "WTiVoNativeMeshToMesh", "inputs": {
    "mesh": ["403", 0], "input_res": 1536, "final_res": 1536, "proxy_points": 12_000_000,
    "proxy_eps_scale": 1.0, "proxy_feature_weight": 1.5, "lambda_fill": 20.0, "threads": 16,
    "thin_iso_vox": 0.0, "faithc_component_mode": "largest"}}
p["901"] = {"class_type": "Hi3DColourPrint3MF", "inputs": {
    "mesh": ["900", 0], "painted_model": ["385", 0], "height_mm": 100.0, "colours": 4,
    "printer": "A1 mini 0.4", "print_faces": 1_000_000, "min_island_mm2": 8.0, "slice_check": True,
    "filename_prefix": "studio/JOB/print"}}
p["902"] = {"class_type": "SaveGLB", "inputs": {"mesh": ["92", 0], "filename_prefix": "studio/JOB/coarse"}}

# Painting mesh: our simplification of the Hi3D mesh instead of Blender's LODTailor low-poly +
# Bake Forger (game-model steps; LODTailor once collapsed the dragon's head into spikes and
# took ~9 min). UltraTex unwraps the UVs itself ("comfy_gpu").
for nid in ("324", "326", "333", "335", "337", "338", "339", "340", "341", "342", "343", "345", "353"):
    p.pop(nid, None)
p["903"] = {"class_type": "Hi3DPaintMesh", "inputs": {"mesh": ["403", 0], "faces": 60000}}
p["383"]["inputs"]["input_1"] = ["903", 0]          # memory cleaner before UltraTex, passes the mesh on
p["374"]["inputs"]["mesh"] = ["383", 0]
p["374"]["inputs"]["uv_mode"] = "comfy_gpu"
p["384"]["inputs"]["mesh"] = ["374", 0]              # apply materials on the mesh whose UVs were baked

# Every save goes into the job's own folder.
prefixes = {"407": "studio/JOB/detail", "386": "studio/JOB/painted",
            "361": "studio/JOB/painted_only", "362": "studio/JOB/base_color",
            "366": "studio/JOB/roughness", "367": "studio/JOB/metallic"}
for nid, prefix in prefixes.items():
    p[nid]["inputs"]["filename_prefix"] = prefix

(HERE / "workflow_api.json").write_text(json.dumps(p, indent=1))
print("nodes", len(p))
