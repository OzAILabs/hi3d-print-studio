"""Remake a finished print file with filament colours a person chose.

python recolour.py <painted.3mf> <painted.glb> <out_dir> <name> <printer> <min_island_mm2> <#hex> [#hex ...]

Uses the print mesh already in the finished print (no re-painting, no re-sealing): each
face takes the chosen colour nearest to its painted colour, then the same clean-up as the
print step (majority smoothing, small islands merged) and a fresh Bambu project + slice
check. Dropping a colour (say a near-black that only paints smudges) sends those faces to
the nearest remaining one. Prints the report as JSON on the last line.
"""
from __future__ import annotations

import json
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colour_print as cp  # noqa: E402
import threemf  # noqa: E402


def load_painted_3mf(path):
    """Vertices (mm, already on the plate) and faces of a 3MF written by threemf.py."""
    import trimesh

    with zipfile.ZipFile(path) as z:
        xml = z.read("3D/3dmodel.model").decode("utf-8")
    v = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', xml), dtype=np.float64)
    f = np.array(re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"', xml), dtype=np.int64)
    return trimesh.Trimesh(v, f, process=False)


def hex_to_rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def recolour(painted_3mf, painted_glb, out_dir, name, printer, min_island, palette_hex):
    import trimesh

    t0 = time.time()
    out_dir = Path(out_dir)
    rep = {"recoloured": True, "palette_source": "chosen"}
    s = cp.Settings(colours=len(palette_hex), printer=printer, min_island_mm2=min_island)
    mesh = load_painted_3mf(painted_3mf)
    painted = trimesh.load(painted_glb, force="mesh")
    face_rgb = cp.transfer_colours(mesh, painted, s, rep)
    chosen = np.array([hex_to_rgb(h) for h in palette_hex], dtype=np.float64)
    lab, chosen_lab = cp.srgb_to_lab(face_rgb), cp.srgb_to_lab(chosen)
    labels = np.empty(len(lab), dtype=np.int64)
    for i in range(0, len(lab), 200_000):
        labels[i:i + 200_000] = np.argmin(cp._shade_dist(lab[i:i + 200_000], chosen_lab), 1)
    adjacency = np.asarray(mesh.face_adjacency)
    area = np.asarray(mesh.area_faces)
    labels = cp.majority_smooth(labels, adjacency, len(chosen), s.smoothing_rounds)
    labels, rep["islands_absorbed"] = cp.absorb_islands(labels, adjacency, area, s.min_island_mm2)
    share = np.bincount(labels, weights=area, minlength=len(chosen)) / area.sum()
    rep["palette"] = [{"filament": i + 1, "colour": h, "area_share": round(float(x), 3)}
                      for i, (h, x) in enumerate(zip(palette_hex, share))]
    tower = cp.place_on_plate(mesh)
    rep["size_mm"] = [round(float(x), 1) for x in mesh.extents]
    new_painted = out_dir / f"{name}_painted.3mf"
    threemf.write_painted_3mf(new_painted, mesh.vertices, mesh.faces, labels + 1, name)
    proj = threemf.make_project(new_painted, out_dir / f"{name}_bambu.3mf", list(palette_hex), printer, True, tower)
    rep["bambu"] = proj
    rep["summary"] = cp.summarise(proj, list(palette_hex), rep)
    try:
        cp.write_preview(mesh, labels, chosen, out_dir / f"{name}_preview.glb")
        rep["preview"] = str(out_dir / f"{name}_preview.glb")
    except Exception as e:
        rep["preview_error"] = str(e)
    rep["seconds"] = round(time.time() - t0, 1)
    (out_dir / f"{name}_report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


if __name__ == "__main__":
    a = sys.argv[1:]
    report = recolour(a[0], a[1], a[2], a[3], a[4], float(a[5]), a[6:])
    print(json.dumps(report, default=str))
