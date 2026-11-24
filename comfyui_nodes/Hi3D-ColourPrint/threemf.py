"""Write a painted 3MF and turn it into a Bambu Studio project with the Bambu CLI.

Colours are stored the way Bambu Studio stores its own multi-material painting: a
``paint_color`` attribute on each triangle, holding the extruder in PrusaSlicer's
TriangleSelector encoding (extruder 1 -> "4", 2 -> "8", 3 -> "0C", 4 -> "1C", ...).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import numpy as np

BAMBU_EXE = Path(r"C:\Program Files\Bambu Studio\bambu-studio.exe")
PROFILES = BAMBU_EXE.parent / "resources" / "profiles" / "BBL"
PRINTERS = {
    # name in Bambu Studio -> (machine preset, process preset, filament preset, build height mm)
    "A1 mini 0.4": ("Bambu Lab A1 mini 0.4 nozzle", "0.20mm Standard @BBL A1M", "Bambu PLA Basic @BBL A1M", 180.0),
    "A1 0.4": ("Bambu Lab A1 0.4 nozzle", "0.20mm Standard @BBL A1", "Bambu PLA Basic @BBL A1", 256.0),
    "P1S 0.4": ("Bambu Lab P1S 0.4 nozzle", "0.20mm Standard @BBL X1C", "Bambu PLA Basic @BBL X1C", 256.0),
    "X1C 0.4": ("Bambu Lab X1 Carbon 0.4 nozzle", "0.20mm Standard @BBL X1C", "Bambu PLA Basic @BBL X1C", 256.0),
}


def paint_code(extruder: int) -> str:
    """TriangleSelector code for a whole triangle painted with ``extruder`` (1-based)."""
    if extruder < 3:
        return "{:X}".format(extruder << 2)
    nibbles = [0b1100]
    rest = extruder - 3
    while True:
        nibbles.append(min(rest, 15))
        if rest < 15:
            break
        rest -= 15
    return "".join("{:X}".format(n) for n in reversed(nibbles))


def write_painted_3mf(path, vertices_mm, faces, extruder_per_face, name="model"):
    """Plain 3MF (one object, millimetres) with per-triangle extruder painting."""
    v = np.asarray(vertices_mm, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    codes = np.array([paint_code(int(e)) for e in range(1, int(extruder_per_face.max()) + 1)])
    vtx = "\n".join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in v)
    paint = codes[np.asarray(extruder_per_face, dtype=np.int64) - 1]
    tri = "\n".join(f'<triangle v1="{a}" v2="{b}" v3="{c}" paint_color="{p}"/>'
                    for (a, b, c), p in zip(f.tolist(), paint.tolist()))
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
        f'<metadata name="Title">{name}</metadata>\n<resources>\n<object id="1" type="model">\n<mesh>\n'
        f'<vertices>\n{vtx}\n</vertices>\n<triangles>\n{tri}\n</triangles>\n'
        '</mesh>\n</object>\n</resources>\n<build>\n<item objectid="1"/>\n</build>\n</model>\n')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    return path


def flatten_preset(kind: str, name: str) -> dict:
    """A system preset with its whole ``inherits`` chain merged in.

    The CLI does not resolve inheritance for files passed on the command line: a
    filament preset loaded as-is has no density, and extra filaments are dropped.
    """
    chain = []
    while name:
        p = PROFILES / kind / f"{name}.json"
        if not p.exists():
            raise FileNotFoundError(f"Bambu Studio preset not found: {p}")
        d = json.loads(p.read_text(encoding="utf-8"))
        chain.append(d)
        name = d.get("inherits", "")
    merged = {}
    for d in reversed(chain):
        merged.update(d)
    merged.pop("inherits", None)
    merged["name"] = chain[0]["name"]
    merged["from"] = "system"
    merged["instantiation"] = "true"
    return merged


def _write_preset(work: Path, kind: str, name: str, **overrides) -> Path:
    d = flatten_preset(kind, name)
    d.update(overrides)
    p = work / f"{kind}_{len(list(work.glob(kind + '_*')))}.json"
    p.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return p


def run_bambu(args, workdir, timeout=1800):
    """Run the Bambu Studio CLI; returns (exit code, result.json dict or None, log tail)."""
    cmd = [str(BAMBU_EXE), *[str(a) for a in args]]
    proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    result = None
    rj = Path(workdir) / "result.json"
    if rj.exists():
        try:
            result = json.loads(rj.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            result = None
    return proc.returncode, result, (proc.stdout + proc.stderr)[-4000:]


def make_project(painted_3mf, out_3mf, palette_hex, printer="A1 mini 0.4", slice_check=True,
                 wipe_tower_xy=(5.0, 100.0)):
    """Bambu Studio project for ``printer`` with one filament per palette colour.

    The CLI loads the printer, process and filament presets, places the model on the
    plate, slices it (as a printability check) and exports the project. The filament
    colours are then written into the project so it opens with the right swatches.
    Returns a report dict.
    """
    machine, process, filament, _ = PRINTERS[printer]
    n = len(palette_hex)
    work = Path(tempfile.mkdtemp(prefix="hi3d_bambu_"))
    try:
        src = work / "in.3mf"
        shutil.copyfile(painted_3mf, src)
        filaments = [_write_preset(work, "filament", filament, filament_colour=[c]) for c in palette_hex]
        # The CLI's default prime (wipe) tower position assumes a 256 mm bed; put it where
        # the caller left room (Bambu Studio's GUI moves it automatically, the CLI does not).
        tower = {"wipe_tower_x": [f"{wipe_tower_xy[0]:.1f}"], "wipe_tower_y": [f"{wipe_tower_xy[1]:.1f}"]}
        args = ["--load-settings",
                f"{_write_preset(work, 'machine', machine)};{_write_preset(work, 'process', process, **tower)}",
                "--load-filaments", ";".join(str(p) for p in filaments),
                "--ensure-on-bed", "--outputdir", str(work), "--export-3mf", "project.3mf"]
        if slice_check:
            args = ["--slice", "0", *args]
        code, result, log = run_bambu([*args, str(src)], work)
        project = work / "project.3mf"
        report = {"bambu_exit": code, "printer": printer}
        if result:
            report["bambu_result"] = {k: result[k] for k in ("return_code", "error_string", "sliced_plates")
                                      if k in result}
        if not project.exists():
            report["log_tail"] = log[-1500:]
            return report
        _set_filament_colours(project, out_3mf, palette_hex)
        report["project"] = str(out_3mf)
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _set_filament_colours(project, out_path, palette_hex):
    """Copy the project, replacing the filament colours in its settings."""
    tmp = Path(str(out_path) + ".tmp")
    with zipfile.ZipFile(project) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Metadata/project_settings.config":
                cfg = json.loads(data.decode("utf-8"))
                cfg["filament_colour"] = list(palette_hex)
                if "filament_multi_colour" in cfg:
                    cfg["filament_multi_colour"] = list(palette_hex)
                data = json.dumps(cfg, indent=4).encode("utf-8")
            zout.writestr(item, data)
    os.replace(tmp, out_path)
