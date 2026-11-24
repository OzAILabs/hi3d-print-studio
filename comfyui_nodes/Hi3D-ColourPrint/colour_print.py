"""Detailed mesh + painted (UltraTex) model -> Bambu multi-colour print project.

Every step is automatic and the same for every model:

1. Stand the model up for printing (glTF Y-up / front +Z -> Z-up / front -Y), scale it
   to the requested height, reduce it to a printable triangle count (keeping it closed).
2. Colour every triangle from the painted model: dense samples of its texture, nearest
   samples averaged (the two meshes come from the same run, so they line up).
3. Reduce to the filament count: k-means in CIELAB weighted by area, then clean the
   result the way a print needs it -- a few rounds of neighbour majority vote (painted
   textures are noisy) and absorbing colour islands smaller than ``min_island_mm2``.
4. Write a painted 3MF, place it on the plate next to the prime tower, and let Bambu
   Studio build and slice the project (the slice doubles as a printability check).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    from . import threemf
except ImportError:          # run as a plain script (recolour.py)
    import threemf

GLTF_TO_PRINT = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
"""glTF is Y-up with the front towards +Z; printers want Z-up with the front towards -Y."""


@dataclass
class Settings:
    height_mm: float = 100.0
    colours: int = 4
    printer: str = "A1 mini 0.4"
    print_faces: int = 1_000_000
    fill_hollows: bool = True
    min_island_mm2: float = 8.0
    smoothing_rounds: int = 8
    chroma_weight: float = 2.5
    """Colour (a*, b*) counts this much more than lightness when grouping: painted
    textures vary mostly in shading, and plain k-means then returns shades of grey
    instead of the model's actual colours (blue, gold, silver...)."""
    samples: int = 3_000_000
    slice_check: bool = True
    seed: int = 0


@dataclass
class Result:
    project: str | None = None
    painted_3mf: str | None = None
    palette: list = field(default_factory=list)
    report: dict = field(default_factory=dict)


def log(msg):
    print(f"[Hi3D Colour Print] {msg}", flush=True)


# --------------------------------------------------------------------- colour maths
def srgb_to_lab(rgb):
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]),
                     200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_srgb(lab):
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16.0) / 116.0
    f = np.stack([fy + lab[..., 1] / 500.0, fy, fy - lab[..., 2] / 200.0], axis=-1)
    xyz = np.where(f > 0.206893, f ** 3, (f - 16.0 / 116.0) / 7.787) * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560],
                  [0.0556434, -0.2040259, 1.0572252]])
    c = np.clip(xyz @ m.T, 0.0, 1.0)
    c = np.where(c > 0.0031308, 1.055 * c ** (1 / 2.4) - 0.055, 12.92 * c)
    return np.clip(np.round(c * 255.0), 0, 255).astype(np.uint8)


def to_hex(rgb):
    return ["#{:02X}{:02X}{:02X}".format(*map(int, c)) for c in np.asarray(rgb)]


# --------------------------------------------------------------------- geometry
def prepare_geometry(vertices, faces, s: Settings, report):
    """Upright, millimetres, decimated, still closed. Returns a trimesh.Trimesh."""
    import trimesh

    v = np.asarray(vertices, dtype=np.float64) @ GLTF_TO_PRINT.T
    v *= s.height_mm / float(np.ptp(v[:, 2]))
    v -= v.min(axis=0)
    f = np.asarray(faces, dtype=np.int64)
    report["faces_in"] = int(len(f))
    if s.fill_hollows:
        t = time.time()
        v, f = fill_hollows(v, f, report)
        log(f"hollows: {report.get('hollows_filled')} ({time.time() - t:.0f}s)")
    mesh = trimesh.Trimesh(v, f, process=True)
    report["watertight_in"] = bool(mesh.is_watertight)
    if len(mesh.faces) > s.print_faces:
        import fast_simplification

        t = time.time()
        dv, df = fast_simplification.simplify(mesh.vertices.astype(np.float32), mesh.faces.astype(np.int32),
                                              target_count=int(s.print_faces))
        mesh = trimesh.Trimesh(dv, df, process=True)
        log(f"decimated to {len(mesh.faces):,} faces in {time.time() - t:.0f}s")
    if not mesh.is_watertight:
        # Simplification leaves a few hundred of ~1.5M edges open or over-shared. Removing
        # degenerate faces made it worse (580 -> 800) and MeshLab's repair takes 10+ min,
        # so only count them: Bambu Studio repairs these on import and slices normally.
        report["open_or_shared_edges"] = int(
            (np.bincount(mesh.edges_unique_inverse, minlength=len(mesh.edges_unique)) != 2).sum())
    trimesh.repair.fix_normals(mesh)
    report["faces"] = int(len(mesh.faces))
    report["watertight"] = bool(mesh.is_watertight)
    report["size_mm"] = [round(float(x), 1) for x in mesh.extents]
    return mesh


FILL_VOTES = 24
"""Empty space is a hollow when at least this many of 26 rays from it hit the model."""
FILL_MIN_SHARE = 0.002
"""Ignore enclosed scraps smaller than this share of the bounding-box volume (crevices)."""


def _shifted(a, d):
    out = np.zeros_like(a)
    if any(abs(k) >= n for k, n in zip(d, a.shape)):
        return out
    src = tuple(slice(k, n) if k >= 0 else slice(0, n + k) for k, n in zip(d, a.shape))
    dst = tuple(slice(0, n - k) if k >= 0 else slice(-k, n) for k, n in zip(d, a.shape))
    out[dst] = a[src]
    return out


def _blocked_votes(shell):
    """Per voxel: in how many of 26 directions a ray meets the shell."""
    import itertools

    votes = np.zeros(shell.shape, np.uint8)
    longest = max(shell.shape)
    for d in (d for d in itertools.product((-1, 0, 1), repeat=3) if any(d)):
        r = _shifted(shell, d)
        step = 1
        while step < longest:
            r |= _shifted(r, tuple(step * k for k in d))
            step *= 2
        votes += r
    return votes


def fill_hollows(v, f, report, voxels_tall=340):
    """Fill the hollows and windows a shell-like model has (mm, Z-up, sitting at z=0).

    Generated models are often thin shells: a bust's neck open at the bottom, a chest
    with windows between trim bands. WTiVo closes every surface, but a closed thin
    lattice still can't be printed. On a voxel grid, empty space that (a) connects to
    the outside -- space inside a closed surface is solid already -- and (b) is hemmed
    in by the model in at least 24 of 26 directions (the print bed counts as a floor) is
    a hollow; gaps between spikes or under a chin see out in more directions. Hollows
    are meshed and unioned into the model; the model's own surface is not touched.
    """
    import manifold3d as m3d
    import trimesh
    from scipy import ndimage
    from skimage import measure

    model = m3d.Manifold(m3d.Mesh(vert_properties=v.astype(np.float32), tri_verts=f.astype(np.uint32)))
    if model.status() != m3d.Error.NoError:
        report["hollows_filled"] = f"skipped (mesh not closed: {model.status()})"
        return v, f
    extent = np.ptp(v, axis=0)
    voxel = float(extent[2]) / voxels_tall
    mesh = trimesh.Trimesh(v, f, process=False)
    pts, _ = trimesh.sample.sample_surface(mesh, int(min(40e6, mesh.area / voxel ** 2 * 6)), seed=0)
    pad = 3
    shape = tuple(int(x) for x in np.ceil(extent / voxel).astype(int) + 2 * pad + 1)
    shell = np.zeros(shape, bool)
    shell[tuple((np.floor(pts / voxel).astype(int) + pad).T)] = True
    shell = ndimage.binary_dilation(shell)
    walls = shell.copy()
    shell[:, :, :pad] = True                                   # the print bed as a floor
    votes = _blocked_votes(shell)

    outside, _ = ndimage.label(~walls)                         # without the floor: open bottoms are open
    border = np.unique(np.concatenate([outside[0].ravel(), outside[-1].ravel(), outside[:, 0].ravel(),
                                       outside[:, -1].ravel(), outside[:, :, 0].ravel(), outside[:, :, -1].ravel()]))
    hollow = ~shell & (votes >= FILL_VOTES) & np.isin(outside, border[border > 0])
    lab, _ = ndimage.label(hollow)
    sizes = np.bincount(lab.ravel()) * voxel ** 3
    keep = np.flatnonzero(sizes >= FILL_MIN_SHARE * float(np.prod(extent)))
    keep = keep[keep > 0]
    if len(keep) == 0:
        report["hollows_filled"] = "none"
        return v, f
    fill = np.isin(lab, keep)
    fill = ndimage.binary_dilation(fill) & (fill | walls)       # one voxel into the walls, never into open air
    fill[:, :, :pad] = False
    verts, faces, _, _ = measure.marching_cubes(ndimage.gaussian_filter(fill.astype(np.float32), 0.8), 0.5)
    filler = trimesh.Trimesh((verts - pad) * voxel, faces[:, ::-1], process=True)
    if filler.volume < 0:
        filler.invert()
    fm = m3d.Manifold(m3d.Mesh(vert_properties=filler.vertices.astype(np.float32),
                               tri_verts=filler.faces.astype(np.uint32)))
    if fm.status() != m3d.Error.NoError:
        report["hollows_filled"] = f"skipped (fill mesh not closed: {fm.status()})"
        return v, f
    union = model + fm
    out = union.to_mesh()
    added = (union.volume() - model.volume()) / 1000.0
    report["hollows_filled"] = f"{len(keep)} hollow(s), +{added:.1f} cm3 (model {model.volume() / 1000:.1f} cm3)"
    return np.asarray(out.vert_properties[:, :3], dtype=np.float64), np.asarray(out.tri_verts, dtype=np.int64)


def _close(mesh, report):
    """Cheap clean-up of the few edges simplification leaves open or over-shared.

    (MeshLab's non-manifold repair took over 10 minutes on a million faces; Bambu
    Studio repairs a few dozen bad edges on import by itself, so only the quick fixes
    run here and the remaining count is reported.)
    """
    import trimesh

    def bad(m):
        return int((np.bincount(m.edges_unique_inverse, minlength=len(m.edges_unique)) != 2).sum())

    before = bad(mesh)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    report["open_or_shared_edges"] = f"{before} -> {bad(mesh)}"
    return mesh


def place_on_plate(mesh, bed=180.0, tower_width=40.0, tower_depth=60.0, margin=5.0, clearance=25.0):
    """Sit on the plate with room for the prime tower. Returns the tower's x, y.

    Bambu's slice check rejects a tower that ends up close to the model ("G-code
    conflicts"): a 110 mm wide logo centred beside a left-hand tower was only 12 mm
    away. So the tower goes in a strip on the left when the model leaves ``clearance``
    there, otherwise in a strip at the front with the model pushed to the back.
    """
    lo, hi = mesh.bounds
    width, depth = hi[0] - lo[0], hi[1] - lo[1]
    strip = margin + tower_width + clearance            # left strip the tower needs
    front = margin + tower_depth + clearance             # front strip the tower needs
    if width <= bed - margin - strip or depth > bed - margin - front:
        cx = strip + (bed - margin - strip) / 2.0 if width <= bed - margin - strip else bed / 2.0
        cy = bed / 2.0
        tower = (margin, max(margin, cy - 30.0))
    else:
        cx = bed / 2.0
        cy = front + (bed - margin - front) / 2.0
        tower = (margin, margin)
    mesh.apply_translation([cx - (lo[0] + hi[0]) / 2, cy - (lo[1] + hi[1]) / 2, -lo[2]])
    return tower


# --------------------------------------------------------------------- colour transfer
def texture_samples(painted, count, seed=0):
    """Surface points of a textured trimesh with their (bilinear) texture colours."""
    import trimesh

    visual = painted.visual
    material = getattr(visual, "material", None)
    image = getattr(material, "baseColorTexture", None) or getattr(material, "image", None)
    points, fi = trimesh.sample.sample_surface(painted, count, seed=seed)
    if getattr(visual, "uv", None) is None or image is None:
        return points, np.asarray(visual.to_color().face_colors)[fi, :3]
    bary = trimesh.triangles.points_to_barycentric(painted.triangles[fi], points)
    uv = (np.asarray(visual.uv)[painted.faces[fi]] * bary[:, :, None]).sum(axis=1)
    tex = np.asarray(image.convert("RGB"), dtype=np.float32)
    h, w = tex.shape[:2]
    x = np.clip((uv[:, 0] % 1.0) * (w - 1), 0, w - 1)
    y = np.clip((1.0 - uv[:, 1] % 1.0) * (h - 1), 0, h - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    rgb = (tex[y0, x0] * (1 - fx) * (1 - fy) + tex[y0, x1] * fx * (1 - fy)
           + tex[y1, x0] * (1 - fx) * fy + tex[y1, x1] * fx * fy)
    return points, rgb


def transfer_colours(mesh, painted, s: Settings, report):
    """Colour per print face from the painted model (same run, same frame before scaling)."""
    from scipy.spatial import cKDTree

    pv = np.asarray(painted.vertices, dtype=np.float64) @ GLTF_TO_PRINT.T
    painted = painted.copy()
    painted.vertices = pv
    # Fit the painted model onto the print mesh (same source, so a scale + offset match).
    p_lo, p_hi = painted.bounds
    m_lo, m_hi = mesh.bounds
    scale = (m_hi[2] - m_lo[2]) / max(p_hi[2] - p_lo[2], 1e-12)
    painted.vertices = (pv - (p_lo + p_hi) / 2) * scale + (m_lo + m_hi) / 2
    points, rgb = texture_samples(painted, s.samples, s.seed)
    dist, idx = cKDTree(points).query(mesh.triangles_center, k=6, workers=-1)
    weight = 1.0 / np.maximum(dist, 1e-3)
    face_rgb = (rgb[idx] * weight[..., None]).sum(1) / weight.sum(1, keepdims=True)
    report["colour_gap_mm_median"] = round(float(np.median(dist[:, 0])), 3)
    report["colour_gap_mm_p99"] = round(float(np.percentile(dist[:, 0], 99)), 3)
    return face_rgb


# --------------------------------------------------------------------- reduce to filaments
def kmeans_lab(lab, weight, k, seed=0, restarts=4, iters=40):
    """Area-weighted k-means in Lab (k-means++ starts, best of a few restarts)."""
    rng = np.random.default_rng(seed)
    p = weight / weight.sum()
    sample = lab[rng.choice(len(lab), size=min(len(lab), 200_000), p=p)]
    best, best_err = None, np.inf
    for _ in range(restarts):
        centres = [sample[rng.integers(len(sample))]]
        for _ in range(1, k):
            d = np.min(((sample[:, None] - np.array(centres)[None]) ** 2).sum(-1), axis=1)
            centres.append(sample[rng.choice(len(sample), p=d / d.sum())])
        c = np.array(centres)
        for _ in range(iters):
            lab_ = ((sample[:, None] - c[None]) ** 2).sum(-1).argmin(1)
            new = np.array([sample[lab_ == j].mean(0) if (lab_ == j).any() else c[j] for j in range(k)])
            if np.allclose(new, c, atol=1e-3):
                break
            c = new
        err = ((sample - c[((sample[:, None] - c[None]) ** 2).sum(-1).argmin(1)]) ** 2).sum()
        if err < best_err:
            best, best_err = c, err
    return best


def _nearest(lab, centres, chunk=500_000):
    out = np.empty(len(lab), dtype=np.int64)
    for i in range(0, len(lab), chunk):
        out[i:i + chunk] = ((lab[i:i + chunk, None] - centres[None]) ** 2).sum(-1).argmin(1)
    return out


def majority_smooth(labels, adjacency, k, rounds):
    """Each face takes the most common label among itself and its edge neighbours."""
    a, b = adjacency[:, 0], adjacency[:, 1]
    for _ in range(rounds):
        votes = np.zeros((len(labels), k), dtype=np.int32)
        np.add.at(votes, (np.arange(len(labels)), labels), 1)
        np.add.at(votes, (a, labels[b]), 1)
        np.add.at(votes, (b, labels[a]), 1)
        new = votes.argmax(1)
        if (new == labels).all():
            break
        labels = new
    return labels


def absorb_islands(labels, adjacency, area, min_area, passes=6):
    """Same-colour patches smaller than ``min_area`` (mm2) take their main neighbour's colour."""
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components

    labels = labels.copy()
    n, k = len(labels), int(labels.max()) + 1
    a, b = adjacency[:, 0], adjacency[:, 1]
    absorbed = 0
    for _ in range(passes):
        same = labels[a] == labels[b]
        npatch, patch = connected_components(
            sparse.coo_matrix((np.ones(int(same.sum())), (a[same], b[same])), shape=(n, n)), directed=False)
        small = np.bincount(patch, weights=area, minlength=npatch) < min_area
        if not small.any():
            break
        cross = ~same
        votes = sparse.coo_matrix((np.ones(2 * int(cross.sum())),
                                   (np.r_[patch[a[cross]], patch[b[cross]]],
                                    np.r_[labels[b[cross]], labels[a[cross]]])), shape=(npatch, k)).tocsr()
        best = np.asarray(votes.argmax(axis=1)).ravel()
        change = small & (np.asarray(votes.sum(axis=1)).ravel() > 0)
        if not change.any():
            break
        labels[change[patch]] = best[patch[change[patch]]]
        absorbed += int(change.sum())
    return labels, absorbed


SHADE_W = np.array([0.5, 1.0, 1.0])
"""Colour distance for choosing filaments: lightness counts half. Shading (lit vs shadowed
red) is mostly a lightness change; a different paint colour differs in hue/chroma."""
SAME_COLOUR = 15.0
"""Colours closer than this (in SHADE_W-weighted Lab) are shades of one paint colour."""


def _shade_dist(a, b):
    return np.sqrt((((a[:, None] - b[None]) * SHADE_W) ** 2).sum(-1))


def _linear_chroma(lab_colour):
    """Colour mix (r, g, b shares in linear light): shading scales brightness, not the mix."""
    c = lab_to_srgb(lab_colour[None])[0] / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return lin / (lin.sum() + 1e-6)


def _paint_families(px, k, seed, fine=16, same_mix=3.0):
    """Group the picture's colours into paint families. Returns (members, family, reps, sizes).

    Fine clusters -> merge shades (average linkage under SAME_COLOUR in lightness-halved
    Lab) -> merge coloured families with the same colour mix (the same paint in shadow:
    lit red and shadowed red differ 3x in brightness but under 1 point in mix; ivory and
    olive differ by 8). The k largest families are the paints.
    """
    from scipy.cluster.hierarchy import fcluster, linkage

    if len(px) > 300_000:
        px = px[np.random.default_rng(seed).choice(len(px), 300_000, replace=False)]
    lab = srgb_to_lab(px)
    centres = kmeans_lab(lab * SHADE_W, np.full(len(lab), 1.0 / len(lab)), fine, seed) / SHADE_W
    lbl = np.argmin(_shade_dist(lab, centres), 1)
    share = np.bincount(lbl, minlength=fine) / len(lbl)
    alive = share > 0.002                                    # ignore stray edge pixels
    med = np.array([np.median(lab[lbl == j], 0) for j in range(fine) if alive[j]])
    share = share[alive]
    fam = fcluster(linkage(med * SHADE_W, method="average"), t=SAME_COLOUR, criterion="distance")
    groups = [[np.flatnonzero(fam == f)] for f in np.unique(fam)]
    for g in groups:
        g.append(float(share[g[0]].sum()))
        g.append(med[g[0]][np.argmax(share[g[0]])])          # its most common member names the paint
    merged = True
    while merged:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                ci, cj = _linear_chroma(groups[i][2]), _linear_chroma(groups[j][2])
                coloured = min(np.linalg.norm(ci - 1 / 3), np.linalg.norm(cj - 1 / 3)) >= 0.04
                if coloured and 100 * np.linalg.norm(ci - cj) < same_mix:
                    big, small = (i, j) if groups[i][1] >= groups[j][1] else (j, i)
                    groups[big][0] = np.r_[groups[big][0], groups[small][0]]
                    groups[big][1] += groups[small][1]
                    groups.pop(small)
                    merged = True
                    break
            if merged:
                break
    groups.sort(key=lambda g: -g[1])
    groups = groups[:k]
    members = np.concatenate([med[g[0]] for g in groups])
    family = np.concatenate([np.full(len(g[0]), i) for i, g in enumerate(groups)])
    return members, family, np.array([g[2] for g in groups]), [g[1] for g in groups]


def picture_palette(picture_rgb, k, seed=0, agree=12.0):
    """The paint colours the input picture uses, or None when it has no clear ones.

    Returns (member colours in Lab, family index per member): a surface colour belongs to
    the family of its nearest member, so shadowed red still lands on red. The grouping is
    run three times from different random starts; only when all three find the same paints
    (a flat-coloured figurine picture) is the result used. On shaded art (a painting) they
    disagree, and the caller falls back to grouping the model's own surface colours.
    """
    px = np.asarray(picture_rgb).reshape(-1, 3)
    px = px[px.astype(int).sum(1) > 15]                      # the cut-out sits on pure black
    if len(px) < 2000:
        return None
    runs = [_paint_families(px, k, seed + i) for i in range(3)]
    reps = runs[0][2]
    for other in runs[1:]:
        if len(other[2]) != len(reps):
            return None
        d = _shade_dist(reps, other[2])
        if len(set(d.argmin(1))) != len(reps) or d.min(1).max() > agree:
            return None
    return runs[0][0], runs[0][1]


def reduce_colours(mesh, face_rgb, s: Settings, report, picture=None):
    lab = srgb_to_lab(face_rgb)
    area = np.asarray(mesh.area_faces)
    paints = picture_palette(picture, s.colours, s.seed) if picture is not None else None
    if paints is not None:
        members, family = paints
        labels = np.empty(len(lab), dtype=np.int64)
        for i in range(0, len(lab), 200_000):                # nearest member -> its paint family
            labels[i:i + 200_000] = family[np.argmin(_shade_dist(lab[i:i + 200_000], members), 1)]
        report["palette_source"] = "picture"
    else:
        w = np.array([1.0, s.chroma_weight, s.chroma_weight])
        centres = kmeans_lab(lab * w, area, s.colours, s.seed)
        labels = _nearest(lab * w, centres)
        report["palette_source"] = "model surface"
    adjacency = np.asarray(mesh.face_adjacency)
    labels = majority_smooth(labels, adjacency, s.colours, s.smoothing_rounds)
    labels, absorbed = absorb_islands(labels, adjacency, area, s.min_island_mm2)
    # Filament colour = area-weighted mean of what it covers; order by area, largest first.
    share = np.bincount(labels, weights=area, minlength=s.colours)
    order = np.argsort(-share)
    order = order[share[order] > 0]
    rank = np.full(s.colours, -1)
    rank[order] = np.arange(len(order))
    labels = rank[labels]
    # Filament shade = the typical (median) surface colour it covers; the picture decides
    # which colours, but its own lighting makes it read darker than the painted model.
    means = np.array([np.median(lab[labels == j], axis=0) for j in range(len(order))])
    palette = lab_to_srgb(means)
    share = share[order] / share.sum()
    report["islands_absorbed"] = absorbed
    report["palette"] = [{"filament": i + 1, "colour": h, "area_share": round(float(x), 3)}
                         for i, (h, x) in enumerate(zip(to_hex(palette), share))]
    return labels, palette


# --------------------------------------------------------------------- whole step
def run(vertices, faces, painted_glb, out_dir, name, s: Settings, picture=None) -> Result:
    import trimesh

    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = Result()
    rep = res.report
    log("preparing geometry")
    mesh = prepare_geometry(vertices, faces, s, rep)
    log("copying colours from the painted model")
    painted = trimesh.load(painted_glb, force="mesh")
    face_rgb = transfer_colours(mesh, painted, s, rep)
    log(f"reducing to {s.colours} filament colours")
    labels, palette = reduce_colours(mesh, face_rgb, s, rep, picture)
    tower = place_on_plate(mesh)
    res.palette = to_hex(palette)
    painted_3mf = out_dir / f"{name}_painted.3mf"
    threemf.write_painted_3mf(painted_3mf, mesh.vertices, mesh.faces, labels + 1, name)
    res.painted_3mf = str(painted_3mf)
    log("building the Bambu Studio project" + (" and slicing it" if s.slice_check else ""))
    project = out_dir / f"{name}_bambu.3mf"
    proj = threemf.make_project(painted_3mf, project, res.palette, s.printer, s.slice_check, tower)
    rep["bambu"] = proj
    res.project = proj.get("project")
    rep["summary"] = summarise(proj, res.palette, rep)
    try:
        write_preview(mesh, labels, palette, out_dir / f"{name}_preview.glb")
        rep["preview"] = str(out_dir / f"{name}_preview.glb")
    except Exception as e:  # the preview is a nicety; never fail the print file over it
        rep["preview_error"] = str(e)
    rep["seconds"] = round(time.time() - t0, 1)
    return res


def summarise(proj, palette_hex, rep):
    """The few numbers a person wants from the slice check."""
    out = {"sliced": False, "palette": palette_hex, "size_mm": rep.get("size_mm"),
           "palette_source": rep.get("palette_source")}
    result = proj.get("bambu_result") or {}
    out["message"] = result.get("error_string")
    plates = result.get("sliced_plates") or []
    if plates:
        p = plates[0]
        out.update({
            "sliced": result.get("return_code") == 0,
            "print_hours": round(p.get("total_predication", 0) / 3600.0, 1),
            "colour_changes": p.get("filament_change_times"),
            "filament_g": round(sum(f.get("total_used_g", 0) for f in p.get("filaments", [])), 1),
            "model_g": round(sum(f.get("main_used_g", 0) for f in p.get("filaments", [])), 1),
            "per_filament_g": [round(f.get("total_used_g", 0), 1) for f in p.get("filaments", [])],
            "warning": p.get("warning_message") or "",
        })
    if proj.get("slice_failed") and proj.get("project"):
        out["slice_failed"] = True
        out["warning"] = ("The slice check did not pass, so print time and filament are not known yet. "
                          f"Bambu Studio said: {(out['message'] or '').strip()} "
                          "The project file is complete: open it in Bambu Studio and move, resize or "
                          "re-slice it there.")
    return out


def write_preview(mesh, labels, palette, path, faces=250_000):
    """Light colour preview for a web viewer (glTF frame: Y-up, front +Z, centred)."""
    import fast_simplification
    import trimesh
    from scipy.spatial import cKDTree

    v, f = mesh.vertices, mesh.faces
    if len(f) > faces:
        v, f = fast_simplification.simplify(v.astype(np.float32), f.astype(np.int32), target_count=faces)
    small = trimesh.Trimesh(v, f, process=False)
    _, idx = cKDTree(mesh.triangles_center).query(small.triangles_center, workers=-1)
    # glTF stores vertex colours in linear light; sRGB values written as-is look washed out.
    srgb = np.asarray(palette, dtype=np.float64) / 255.0
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    colours = np.clip(np.round(linear * 255.0), 0, 255).astype(np.uint8)[labels[idx]]
    centre = (small.bounds[0] + small.bounds[1]) / 2
    small.vertices = (small.vertices - centre) @ GLTF_TO_PRINT     # inverse of the print rotation
    small.visual.face_colors = np.column_stack([colours, np.full(len(colours), 255, np.uint8)])
    small.export(path)
