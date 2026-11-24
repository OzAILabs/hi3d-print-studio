"""Experimental: take the black outlines out of a cartoon picture before it is painted.

A cartoon's ink lines are thin, dark and everywhere. UltraTex copies the picture's style
onto the sides and back it has to invent, so the ink comes back as dark smudges, and the
print step then spends a whole filament on them. Here every thin dark line inside the
figure is replaced by the colour next to it, so the painter only sees flat colour areas.

Kept: thick dark areas (black clothes, hair) and small compact dark blobs (pupils,
nostrils). Removed: lines, i.e. dark pixels no thicker than ``line_px`` that form
long or open shapes.
"""
from __future__ import annotations

import numpy as np


def clean_outlines(rgb, mask, line_frac=0.008, dark=0.30, grey=0.22):
    """rgb: HxWx3 float 0..1, mask: HxW (figure > 0.5). Returns (cleaned rgb, report)."""
    from scipy import ndimage

    rgb = np.asarray(rgb, dtype=np.float32)
    fg = np.asarray(mask) > 0.5
    if fg.sum() < 1000:
        return rgb, {"ink_removed_share": 0.0, "skipped": "no figure"}
    rows = np.where(fg.any(1))[0]
    height = rows[-1] - rows[0] + 1
    line_px = max(2, int(round(line_frac * height)))       # thickest line that counts as ink

    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    sat = rgb.max(2) - rgb.min(2)
    ink = fg & (lum < dark) & (sat < grey)                   # dark, nearly neutral

    # Thin = disappears under an opening wider than a line.
    disk = _disk(max(1, (line_px + 1) // 2))           # wider than any line
    thick = ndimage.binary_opening(ink, structure=disk)
    thin = ink & ~thick

    # Compact little blobs (pupils, nostrils) are features, not lines: keep them.
    lab, n = ndimage.label(thin, structure=np.ones((3, 3), bool))
    keep = np.zeros(n + 1, bool)
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        area = int((lab[sl] == i).sum())
        if area >= 0.45 * h * w and max(h, w) <= 3 * min(h, w) and max(h, w) <= 6 * line_px:
            keep[i] = True
    remove = thin & ~keep[lab]
    # The anti-aliased rim of a line is greyish, not black: take it too.
    rim = ndimage.binary_dilation(remove, iterations=1) & fg & (lum < 0.55) & (sat < grey + 0.1)
    remove |= rim

    known = fg & ~remove
    if not known.any():
        return rgb, {"ink_removed_share": 0.0, "skipped": "nothing left"}
    # Each removed pixel takes the colour of the nearest kept figure pixel: the colour
    # areas on both sides of a line grow to meet in its middle.
    _, (iy, ix) = ndimage.distance_transform_edt(~known, return_indices=True)
    out = rgb.copy()
    out[remove] = rgb[iy[remove], ix[remove]]
    return out, {"ink_removed_share": round(float(remove.sum() / fg.sum()), 4),
                 "line_px": line_px, "kept_blobs": int(keep.sum())}


def _disk(r):
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r
