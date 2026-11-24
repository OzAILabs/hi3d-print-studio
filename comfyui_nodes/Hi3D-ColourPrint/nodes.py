"""ComfyUI node: Colour Print 3MF (Bambu)."""
from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

import numpy as np
import torch

import folder_paths

from . import colour_print, ink, threemf


def _mesh_arrays(mesh):
    v, f = mesh.vertices, mesh.faces
    if v.ndim == 3:
        nv = int(mesh.vertex_counts[0]) if getattr(mesh, "vertex_counts", None) is not None else v.shape[1]
        nf = int(mesh.face_counts[0]) if getattr(mesh, "face_counts", None) is not None else f.shape[1]
        v, f = v[0, :nv], f[0, :nf]
    return v.detach().cpu().double().numpy(), f.detach().cpu().long().numpy()


def _glb_path(file3d, tmp: Path) -> Path:
    src = file3d.get_source() if hasattr(file3d, "get_source") else file3d
    if isinstance(src, (str, Path)):
        return Path(src)
    data = src.read() if hasattr(src, "read") else bytes(src)
    p = tmp / "painted.glb"
    p.write_bytes(data)
    return p


class Hi3DColourPrint3MF:
    CATEGORY = "Hi3D/print"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("project_path", "report")
    FUNCTION = "make"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mesh": ("MESH", {"tooltip": "Closed detail mesh (WTiVo output of the Hi3D mesh)."}),
                "painted_model": ("FILE_3D_GLB", {"tooltip": "UltraTex-painted model from the same run."}),
                "height_mm": ("FLOAT", {"default": 100.0, "min": 20.0, "max": 400.0, "step": 1.0}),
                "colours": ("INT", {"default": 4, "min": 1, "max": 16,
                                    "tooltip": "Filament colours (AMS slots)."}),
                "printer": (list(threemf.PRINTERS), {"default": "A1 mini 0.4"}),
                "print_faces": ("INT", {"default": 1_000_000, "min": 100_000, "max": 5_000_000, "step": 100_000}),
                "min_island_mm2": ("FLOAT", {"default": 2.0, "min": 0.0, "max": 50.0, "step": 0.5,
                                             "tooltip": "Colour specks smaller than this are merged."}),
                "slice_check": ("BOOLEAN", {"default": True}),
                "filename_prefix": ("STRING", {"default": "print/hi3d_colour"}),
            },
            "optional": {
                "picture": ("IMAGE", {"tooltip": "The cut-out input picture (on black). Filament colours are "
                                                 "taken from the paint colours it uses; without it, from the model."}),
            },
        }

    def make(self, mesh, painted_model, height_mm, colours, printer, print_faces, min_island_mm2,
             slice_check, filename_prefix, picture=None):
        max_h = threemf.PRINTERS[printer][3]
        if height_mm > max_h:
            raise ValueError(f"{height_mm:g} mm is taller than the {printer}'s {max_h:g} mm build height.")
        v, f = _mesh_arrays(mesh)
        out_root = Path(folder_paths.get_output_directory())
        full, name, counter, _, _ = folder_paths.get_save_image_path(filename_prefix, str(out_root))
        stem = f"{name}_{counter:05}"
        s = colour_print.Settings(height_mm=height_mm, colours=colours, printer=printer,
                                  print_faces=print_faces, min_island_mm2=min_island_mm2,
                                  slice_check=slice_check)
        pic = None
        if picture is not None:
            pic = (picture[0].detach().cpu().numpy()[..., :3] * 255.0).clip(0, 255).astype(np.uint8)
        with tempfile.TemporaryDirectory(prefix="hi3d_cp_") as tmp:
            res = colour_print.run(v, f, _glb_path(painted_model, Path(tmp)), full, stem, s, picture=pic)
        report = json.dumps(res.report, indent=1, default=str)
        Path(full, f"{stem}_report.json").write_text(report, encoding="utf-8")
        return {"ui": {"text": [report]}, "result": (res.project or "", report)}


class Hi3DPaintMesh:
    """A light copy of the detail mesh for UltraTex to paint (replaces Blender's LODTailor).

    UltraTex only needs a surface to paint and project; for a print the colours go back
    onto the full-detail mesh anyway. A plain simplification keeps the shape faithfully
    (LODTailor's Blender rebuild occasionally collapsed a model into large spikes, and
    took ~9 minutes); UltraTex unwraps the UVs itself.
    """
    CATEGORY = "Hi3D/print"
    RETURN_TYPES = ("MESH",)
    FUNCTION = "make"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mesh": ("MESH",),
            "faces": ("INT", {"default": 60_000, "min": 5_000, "max": 500_000, "step": 5_000}),
        }}

    def make(self, mesh, faces):
        import fast_simplification
        import trimesh
        from comfy_api.latest._util.geometry_types import MESH

        v, f = _mesh_arrays(mesh)
        m = trimesh.Trimesh(v, f, process=True)
        # keep the main body: loose crumbs make UltraTex waste texture space
        parts = m.split(only_watertight=False)
        if len(parts) > 1:
            areas = np.array([p.area for p in parts])
            m = trimesh.util.concatenate([p for p, a in zip(parts, areas) if a >= 0.002 * areas.sum()])
        sv, sf = fast_simplification.simplify(np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.int32),
                                              target_count=int(faces))
        small = trimesh.Trimesh(sv, sf, process=True)
        trimesh.repair.fix_normals(small)
        print(f"[Hi3D Paint Mesh] {len(f):,} -> {len(small.faces):,} faces", flush=True)
        return (MESH(torch.tensor(small.vertices, dtype=torch.float32).unsqueeze(0),
                     torch.tensor(small.faces, dtype=torch.int64).unsqueeze(0)),)


class Hi3DInkCleanup:
    """Experimental: replace a cartoon's thin black outlines with the colour beside them.

    Feed the result to the painter (and the print step's picture) so the ink does not
    come back as dark smudges on the sides and back of the model. See ink.py.
    """
    CATEGORY = "Hi3D/print"
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "clean"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "mask": ("MASK", {"tooltip": "The figure (from background removal)."}),
            "line_width": ("FLOAT", {"default": 0.008, "min": 0.002, "max": 0.03, "step": 0.001,
                                     "tooltip": "Thickest line that counts as ink, as a share of the figure's height."}),
        }}

    def clean(self, image, mask, line_width):
        import torch.nn.functional as F

        out = []
        for i in range(image.shape[0]):
            rgb = image[i, ..., :3].detach().cpu().float().numpy()
            m = mask[min(i, mask.shape[0] - 1)] if mask.ndim == 3 else mask
            if tuple(m.shape) != rgb.shape[:2]:
                m = F.interpolate(m[None, None].float(), size=rgb.shape[:2], mode="bilinear")[0, 0]
            cleaned, rep = ink.clean_outlines(rgb, m.detach().cpu().numpy(), line_frac=line_width)
            print(f"[Hi3D Ink Cleanup] {rep}", flush=True)
            out.append(torch.from_numpy(cleaned))
        return (torch.stack(out),)


NODE_CLASS_MAPPINGS = {"Hi3DColourPrint3MF": Hi3DColourPrint3MF, "Hi3DPaintMesh": Hi3DPaintMesh,
                       "Hi3DInkCleanup": Hi3DInkCleanup}
NODE_DISPLAY_NAME_MAPPINGS = {"Hi3DColourPrint3MF": "Colour Print 3MF (Bambu)",
                              "Hi3DPaintMesh": "Paint Mesh (for UltraTex)",
                              "Hi3DInkCleanup": "Ink Cleanup (experimental)"}
