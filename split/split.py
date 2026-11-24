"""Prototype: split a finished colour print into printable pieces along P3-SAM's parts.

python split.py <painted.3mf> <p3sam_dir> <name> <pieces> <out_dir>

painted.3mf   the print step's painted 3MF (print mesh on the plate + filament per face)
p3sam_dir     run_p3sam.py output for this model (<name>_faces.npy, <name>_mesh.ply, glTF frame)
Writes <out_dir>/<name>_pieces.3mf (one painted object per piece), <name>_exploded.glb and a report.

How it cuts:
  1. P3-SAM's part per face of the 150k copy -> every face of the full print mesh (nearest face).
  2. Parts merge (smallest first, into the neighbour they share most edge with) down to <pieces>;
     a part that is several separate patches counts as several.
  3. Each piece's region of space = points nearer its own surface than any other piece's surface;
     piece = solid AND region (exact boolean); the biggest piece = solid minus the others.
  4. One peg per joint, on the smaller piece, into a hole 0.15 mm larger in its neighbour.
  5. Outer faces keep their painted filament; cut faces and pegs take the piece's main filament.
"""
from __future__ import annotations

import json
import re
import sys
import time
import zipfile
from pathlib import Path

import manifold3d as m3d
import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage import measure

HI3D = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HI3D / "comfyui_nodes" / "Hi3D-ColourPrint"))
import threemf  # noqa: E402
from colour_print import GLTF_TO_PRINT  # noqa: E402

CODE_TO_FILAMENT = {threemf.paint_code(e): e for e in range(1, 17)}
CLEARANCE = 0.15          # mm, radial, hole vs peg (PLA on a 0.4 mm nozzle)
MIN_PIECE_SHARE = 0.01    # parts under 1% of the surface always merge (eyes, rivets...)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ input
def load_painted(path):
    xml = zipfile.ZipFile(path).read("3D/3dmodel.model").decode("utf-8")
    v = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', xml), dtype=np.float64)
    tri = re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)" paint_color="([^"]+)"', xml)
    f = np.array([t[:3] for t in tri], dtype=np.int64)
    filament = np.array([CODE_TO_FILAMENT[t[3]] for t in tri], dtype=np.int64)
    return v, f, filament


def part_per_face(v, f, p3sam_dir, name):
    """P3-SAM's part ids (on its 150k glTF-frame copy) for every face of the print mesh."""
    small = trimesh.load(Path(p3sam_dir) / f"{name}_mesh.ply", process=False)
    ids = np.load(Path(p3sam_dir) / f"{name}_faces.npy")
    centre = (v.min(0) + v.max(0)) / 2
    centres = (v[f].mean(1) - centre) @ GLTF_TO_PRINT                # print frame -> glTF frame
    labelled = ids >= 0
    tree = cKDTree(small.triangles_center[labelled])
    _, idx = tree.query(centres, workers=-1)
    return ids[labelled][idx]


# ------------------------------------------------------------------ merging
def merge_parts(mesh, labels, target):
    """Merge parts into neighbours (smallest first) until ``target`` remain and none is tiny."""
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components

    adj = mesh.face_adjacency
    a, b = adj[:, 0], adj[:, 1]
    # one id per connected patch: a part in two separate places becomes two parts
    same = labels[a] == labels[b]
    n = len(labels)
    _, patch = connected_components(sparse.coo_matrix((np.ones(int(same.sum())), (a[same], b[same])), shape=(n, n)),
                                    directed=False)
    area = np.bincount(patch, weights=mesh.area_faces)
    edge = mesh.vertices[mesh.face_adjacency_edges]
    elen = np.linalg.norm(edge[:, 0] - edge[:, 1], axis=1)
    cross = patch[a] != patch[b]
    pa, pb, pl = patch[a][cross], patch[b][cross], elen[cross]
    border: dict[int, dict[int, float]] = {}
    for x, y, l in zip(pa.tolist(), pb.tolist(), pl.tolist()):
        border.setdefault(x, {}).setdefault(y, 0.0)
        border[x][y] += l
        border.setdefault(y, {}).setdefault(x, 0.0)
        border[y][x] += l
    alive = {int(i): float(area[i]) for i in np.unique(patch)}
    parent = {i: i for i in alive}
    total = sum(alive.values())
    while len(alive) > 1:
        s = min(alive, key=alive.get)
        if len(alive) <= target and alive[s] >= MIN_PIECE_SHARE * total:
            break
        nbrs = border.get(s, {})
        if not nbrs:                       # a loose island: join the nearest big part by size
            t = max((k for k in alive if k != s), key=alive.get)
        else:
            t = max(nbrs, key=nbrs.get)
        alive[t] += alive.pop(s)
        parent[s] = t
        for y, l in border.pop(s, {}).items():
            if y == t:
                border[t].pop(s, None)
                continue
            border[y].pop(s, None)
            border[y][t] = border[y].get(t, 0.0) + l
            border[t][y] = border[t].get(y, 0.0) + l
    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i
    roots = np.array([root(i) for i in range(int(patch.max()) + 1)])
    merged = roots[patch]
    order = sorted(alive, key=alive.get, reverse=True)                # 0 = biggest
    remap = {r: k for k, r in enumerate(order)}
    return np.array([remap[r] for r in merged.tolist()]), [alive[r] / total for r in order]


# ------------------------------------------------------------------ regions and cutting
def to_manifold(verts, faces):
    mesh = m3d.Mesh(vert_properties=np.ascontiguousarray(verts, np.float32),
                    tri_verts=np.ascontiguousarray(faces, np.uint32))
    mesh.merge()
    return m3d.Manifold(mesh)


def from_manifold(man):
    out = man.to_mesh()
    v = np.asarray(out.vert_properties)[:, :3].astype(np.float64)
    f = np.asarray(out.tri_verts).astype(np.int64)
    run_ids = np.asarray(out.run_original_id)
    run_index = np.asarray(out.run_index)
    origin = np.repeat(run_ids, np.diff(run_index) // 3)               # run_index counts vertex slots
    face_id = np.asarray(out.face_id)
    return v, f, origin, face_id


def joint_plane(mesh, piece, k):
    """Plane through the border between piece k and its main neighbour, if that border is flat enough.

    Returns (point, normal into k, loop radius, flatness, neighbour) or None.
    """
    adj, edges = mesh.face_adjacency, mesh.face_adjacency_edges
    la, lb = piece[adj[:, 0]], piece[adj[:, 1]]
    touching = (la == k) ^ (lb == k)
    if not touching.any():
        return None
    other = np.where(la[touching] == k, lb[touching], la[touching])
    seg = mesh.vertices[edges[touching]]
    seg_len = np.linalg.norm(seg[:, 0] - seg[:, 1], axis=1)
    j = int(np.bincount(other, weights=seg_len).argmax())
    pts = seg[other == j].reshape(-1, 3)
    c = pts.mean(0)
    _, s, vt = np.linalg.svd(pts - c, full_matrices=False)
    n = vt[2]
    radius = float(np.sqrt(s[0] ** 2 / len(pts)) * 1.4142)
    flat = float(np.sqrt(s[2] ** 2 / len(pts)) / max(radius, 1e-6))
    own = mesh.triangles_center[piece == k].mean(0)
    if np.dot(own - c, n) < 0:
        n = -n
    return c, n, radius, flat, j


def regions(mesh, piece, pieces, pitch, rep, flat_limit=0.25):
    """Closed region (manifold) per piece except the biggest.

    Base region: points nearer the piece's own surface than any other piece's surface.
    Where the border with its main neighbour is close to flat (a neck, a helmet rim), the
    cut becomes that plane instead (flat joints print and peg better), limited to a band
    around the base region so it cannot slice through unrelated parts of the model.
    """
    lo, hi = mesh.bounds[0] - 4 * pitch, mesh.bounds[1] + 4 * pitch
    shape = np.ceil((hi - lo) / pitch).astype(int) + 1
    grid = np.stack(np.meshgrid(*[lo[i] + pitch * np.arange(shape[i]) for i in range(3)], indexing="ij"), -1)
    pts = grid.reshape(-1, 3)
    centres = mesh.triangles_center
    out = {}
    rep["cuts"] = []
    for k in range(1, pieces):
        plane = joint_plane(mesh, piece, k)
        own = centres[piece == k]
        other = centres[piece != k]
        rng = np.random.default_rng(0)
        if len(own) > 200_000:
            own = own[rng.choice(len(own), 200_000, replace=False)]
        if len(other) > 400_000:
            other = other[rng.choice(len(other), 400_000, replace=False)]
        d_own, _ = cKDTree(own).query(pts, workers=-1)
        d_other, _ = cKDTree(other).query(pts, workers=-1)
        field = (d_own - d_other).reshape(shape)
        field = ndimage.gaussian_filter(field, 2.0)                    # smoother cut faces
        cut = {"piece": k}
        out[k] = {"curved": _region(field, lo, pitch), "flat": None}
        if plane is not None:
            c, n, radius, flat, j = plane
            cut.update(neighbour=j, flatness=round(flat, 3), border_radius_mm=round(radius, 1))
            if flat <= flat_limit:
                margin = float(np.clip(0.35 * radius, 2.0, 8.0))
                side = (-(pts - c) @ n).reshape(shape)                 # < 0 on the piece's side
                out[k]["flat"] = _region(np.maximum(field - margin, side), lo, pitch)
                cut["margin_mm"] = round(margin, 1)
        rep["cuts"].append(cut)
    return out


def _region(field, lo, pitch):
    field = field.copy()
    field[[0, -1], :, :] = field[:, [0, -1], :] = field[:, :, [0, -1]] = pitch * 10   # closed surface
    verts, faces, _, _ = measure.marching_cubes(field, level=0.0, spacing=(pitch,) * 3)
    region = to_manifold(verts + lo, faces[:, ::-1])
    if region.volume() < 0 or region.status() != m3d.Error.NoError:
        region = to_manifold(verts + lo, faces)
    return region


def adopt_strays(parts, crumb=50.0, touch=0.6):
    """A piece's extra bodies (slivers left between cuts) join the piece they touch most.

    Each piece keeps its biggest body; every other body of 50 mm3 or more goes to the
    neighbouring piece with the most surface within 0.6 mm of it (unioned, so it becomes
    part of that body). Smaller ones are crumbs and are dropped later.
    """
    joined = 0
    for _ in range(3):
        moved = False
        trees = {k: cKDTree(np.asarray(p.to_mesh().vert_properties)[:, :3]) for k, p in parts.items()
                 if not p.is_empty()}
        for k in list(parts):
            bodies = sorted(parts[k].decompose(), key=lambda b: -b.volume())
            if len(bodies) < 2:
                continue
            keep = [bodies[0]]
            for b in bodies[1:]:
                if b.volume() < crumb:
                    keep.append(b)
                    continue
                pts = np.asarray(b.to_mesh().vert_properties)[:, :3]
                best, best_n = None, 0
                for j, tree in trees.items():
                    if j == k:
                        continue
                    d, _ = tree.query(pts, distance_upper_bound=touch, workers=-1)
                    n_close = int(np.isfinite(d).sum())
                    if n_close > best_n:
                        best, best_n = j, n_close
                if best is None:
                    keep.append(b)                     # touches nothing else: leave it
                    continue
                parts[best] = parts[best] + b
                joined += 1
                moved = True
            parts[k] = m3d.Manifold.compose(keep) if len(keep) > 1 else keep[0]
        if not moved:
            break
    return joined


def cap_info(v, f, origin, solid_id):
    """Area, centre and outward normal of a piece's cut faces (those not from the solid's surface)."""
    cap = origin != solid_id
    if not cap.any():
        return None
    tri = v[f[cap]]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2
    centre = (tri.mean(1) * area[:, None]).sum(0) / area.sum()
    normal = cross.sum(0)
    normal /= max(np.linalg.norm(normal), 1e-9)
    # the cap point nearest its centre (a curved cap's centroid can sit off the cap)
    point = tri.mean(1)[np.argmin(np.linalg.norm(tri.mean(1) - centre, axis=1))]
    return {"area": float(area.sum()), "point": point, "normal": normal}


def cylinder(p0, p1, r, segments=32):
    d = p1 - p0
    length = float(np.linalg.norm(d))
    c = m3d.Manifold.cylinder(length, r, r, segments)
    z = np.array([0.0, 0.0, 1.0])
    axis = d / length
    rot = trimesh.geometry.align_vectors(z, axis)
    mat = np.eye(4)
    mat[:3, :3] = rot[:3, :3]
    mat[:3, 3] = p0
    return c.transform(np.ascontiguousarray(mat[:3, :], dtype=np.float32))


def split(painted_3mf, p3sam_dir, name, pieces, out_dir, palette=None, printer="A1 mini 0.4"):
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = {"name": name, "asked_pieces": pieces}
    v, f, filament = load_painted(painted_3mf)
    mesh = trimesh.Trimesh(v, f, process=False)
    log(f"loaded {len(f):,} faces")
    labels = part_per_face(v, f, p3sam_dir, name)
    rep["p3sam_parts"] = int(len(np.unique(labels)))
    piece, shares = merge_parts(mesh, labels, pieces)
    n = len(shares)
    rep["pieces"] = n
    rep["surface_share"] = [round(s, 3) for s in shares]
    log(f"{rep['p3sam_parts']} P3-SAM parts -> {n} pieces, shares {rep['surface_share']}")

    solid = to_manifold(v, f).as_original()          # as_original: its faces stay traceable
    solid_id = solid.original_id()
    rep["solid_ok"] = str(solid.status())
    # smooth the part borders on the surface first: P3-SAM's borders are ragged at face level
    from colour_print import majority_smooth
    piece = majority_smooth(piece, np.asarray(mesh.face_adjacency), n, 25)
    pitch = float(max(mesh.extents)) / 220.0
    regs = regions(mesh, piece, n, pitch, rep)
    log(f"regions done (grid {pitch:.2f} mm)")

    # Cut in order, smallest piece first, each from what is left: every joint is cut once
    # (by the smaller side) and pieces cannot overlap.
    # A flat cut is used only when it gives nearly the same piece as the curved one: pieces
    # that wrap around each other (a jaw around a face) cannot be split by one plane.
    parts = {}
    remaining = solid
    kinds = {}
    for k in sorted(regs, key=lambda k: shares[k]):
        curved = remaining ^ regs[k]["curved"]
        chosen, kind = regs[k]["curved"], "curved"
        if regs[k]["flat"] is not None and curved.volume() > 0:
            flat = remaining ^ regs[k]["flat"]
            differ = ((curved - flat).volume() + (flat - curved).volume()) / curved.volume()
            big_bodies = [b for b in flat.decompose() if b.volume() >= 50.0]
            if differ < 0.15 and len(big_bodies) == 1:
                chosen, kind = regs[k]["flat"], "flat"
            kinds[k] = {"kind": kind, "flat_vs_curved_differ": round(differ, 3)}
        else:
            kinds[k] = {"kind": kind}
        parts[k] = remaining ^ chosen
        remaining = remaining - chosen
    parts[0] = remaining
    for c in rep["cuts"]:
        c.update(kinds.get(c["piece"], {}))
    rep["strays_joined"] = adopt_strays(parts)
    # crumbs: generated meshes carry a few tiny loose bits; a piece keeps only real bodies
    dropped = 0
    for k in list(parts):
        bodies = parts[k].decompose()
        keep = [b for b in bodies if b.volume() >= 50.0]
        dropped += len(bodies) - len(keep)
        if keep and len(keep) < len(bodies):
            parts[k] = m3d.Manifold.compose(keep)
    rep["crumbs_dropped"] = dropped

    # pegs: each piece except the biggest gets one, into the neighbour across its cut
    centres = mesh.triangles_center
    tree = cKDTree(centres)
    joints = []
    for k in range(1, n):
        pv, pf, porigin, _ = from_manifold(parts[k])
        cap = cap_info(pv, pf, porigin, solid_id)
        if cap is None or cap["area"] < 25.0:
            joints.append({"piece": k, "peg": False, "why": "cut too small for a peg"})
            continue
        probe = cap["point"] + cap["normal"] * 1.0
        _, idx = tree.query(probe)
        into = int(piece[idx])
        if into == k:
            into = 0
        # Biggest peg that stays inside the model: shorter first, then thinner (a thin base
        # or wall would let a long peg poke out of the far side).
        r_max = float(np.clip(0.3 * np.sqrt(cap["area"] / np.pi), 1.5, 4.0))
        fit = None
        for r in [x for x in (r_max, 3.0, 2.5, 2.0, 1.5) if x <= r_max]:
            for length in sorted({min(6.0, 2.5 * r), 4.0, 3.0, 2.0}, reverse=True):
                if length > 2.5 * r:
                    continue
                p0 = cap["point"] - cap["normal"] * length
                p1 = cap["point"] + cap["normal"] * length
                peg = cylinder(p0, p1, r)
                guard = cylinder(cap["point"] - cap["normal"] * (length + 0.8),
                                 p1 + cap["normal"] * 1.2, r + CLEARANCE + 0.8)    # 0.8 mm wall around it
                poke = (guard - solid).volume() / max(guard.volume(), 1e-9)
                if poke <= 0.02:
                    fit = (r, length, p0, p1, peg)
                    break
            if fit:
                break
        if fit is None:
            joints.append({"piece": k, "peg": False, "why": "no peg fits inside the model here"})
            continue
        r, length, p0, p1, peg = fit
        hole = cylinder(cap["point"] - cap["normal"] * 0.05, p1 + cap["normal"] * 0.4, r + CLEARANCE)
        parts[k] = parts[k] + peg
        parts[into] = parts[into] - hole
        joints.append({"piece": k, "into": into, "peg": True, "radius_mm": round(r, 2),
                       "length_mm": round(2 * length, 1), "cap_area_mm2": round(cap["area"], 1)})
    rep["joints"] = joints

    # colours and output
    objects, exploded = [], trimesh.Scene()
    centre_all = mesh.bounds.mean(0)
    # manifold3d's face_id is not the input triangle's index, so colour by position instead:
    # a surface face of a piece is a piece of an original face, whose centre is the nearest.
    colour_tree = cKDTree(mesh.triangles_center)
    for k in range(n):
        pv, pf, porigin, face_id = from_manifold(parts[k])
        from_solid = porigin == solid_id
        fil = np.empty(len(pf), dtype=np.int64)
        _, nearest = colour_tree.query(pv[pf[from_solid]].mean(1), workers=-1)
        fil[from_solid] = filament[nearest]
        main = int(np.bincount(fil[from_solid]).argmax()) if from_solid.any() else 1
        fil[~from_solid] = main
        bodies = parts[k].decompose()
        info = {"piece": k, "faces": int(len(pf)), "volume_cm3": round(parts[k].volume() / 1000, 2),
                "bodies": len(bodies), "main_filament": main,
                "size_mm": [round(float(x), 1) for x in (pv.max(0) - pv.min(0))]}
        rep.setdefault("piece_info", []).append(info)
        objects.append((pv, pf, fil))
        m = trimesh.Trimesh(pv, pf, process=False)
        offset = (m.bounds.mean(0) - centre_all) * 0.6
        m.apply_translation(offset)
        m.visual.face_colors = _colour_for(fil)
        exploded.add_geometry(m, node_name=f"piece{k}")
    exploded.apply_transform(_print_to_gltf())
    exploded.export(out_dir / f"{name}_exploded.glb")
    write_pieces_3mf(out_dir / f"{name}_pieces.3mf", objects, name)
    if palette:
        # Bambu lays the pieces out on the plate (--arrange) and slices them as a check
        proj = threemf.make_project(out_dir / f"{name}_pieces.3mf", out_dir / f"{name}_pieces_bambu.3mf", palette,
                                    printer, True, (5.0, 5.0), extra_args=("--arrange", "1"))
        rep["bambu"] = {k: proj.get(k) for k in ("project", "slice_failed", "bambu_exit")}
        result = proj.get("bambu_result") or {}
        plates = result.get("sliced_plates") or []
        rep["bambu"]["message"] = result.get("error_string")
        if plates:
            rep["bambu"]["print_hours"] = round(plates[0].get("total_predication", 0) / 3600, 1)
            rep["bambu"]["colour_changes"] = plates[0].get("filament_change_times")
    rep["seconds"] = round(time.time() - t0, 1)
    (out_dir / f"{name}_split_report.json").write_text(json.dumps(rep, indent=1, default=str))
    log(json.dumps(rep, default=str))
    return rep


FILAMENT_RGB = np.array([[200, 200, 200], [230, 90, 70], [80, 150, 230], [240, 200, 70], [100, 190, 110],
                         [170, 110, 210], [250, 150, 60], [70, 200, 200], [230, 120, 170]], np.uint8)


def _colour_for(fil):
    rgb = FILAMENT_RGB[np.clip(fil, 0, len(FILAMENT_RGB) - 1)]
    return np.column_stack([rgb, np.full(len(rgb), 255, np.uint8)])


def _print_to_gltf():
    m = np.eye(4)
    m[:3, :3] = GLTF_TO_PRINT.T
    return m


def write_pieces_3mf(path, objects, name):
    """One painted object per piece (Bambu reads paint_color per triangle)."""
    res, items = [], []
    for i, (v, f, fil) in enumerate(objects, start=1):
        codes = np.array([threemf.paint_code(int(e)) for e in range(1, int(fil.max()) + 1)])
        vtx = "\n".join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in v)
        tri = "\n".join(f'<triangle v1="{a}" v2="{b}" v3="{c}" paint_color="{p}"/>'
                        for (a, b, c), p in zip(f.tolist(), codes[fil - 1].tolist()))
        res.append(f'<object id="{i}" name="{name} piece {i}" type="model">\n<mesh>\n<vertices>\n{vtx}\n</vertices>\n'
                   f'<triangles>\n{tri}\n</triangles>\n</mesh>\n</object>')
        items.append(f'<item objectid="{i}"/>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
             f'<metadata name="Title">{name}</metadata>\n<resources>\n' + "\n".join(res) +
             '\n</resources>\n<build>\n' + "\n".join(items) + '\n</build>\n</model>\n')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)


if __name__ == "__main__":
    a = sys.argv[1:]
    split(a[0], a[1], a[2], int(a[3]), a[4], a[5].split(",") if len(a) > 5 else None)
