"""Draw the Hi3D Print Studio logo (the studio's wireframe cube) as icon, transparent PNG and banner.

python tools/make_logo.py
Writes docs/logo/: hi3d_cube.png (transparent), hi3d_icon_tile.png, hi3d_print_studio.ico, banner.png,
and studio/static/favicon.png + icon-180.png. Same geometry as the cube on the studio's start screen.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "logo"
A, B = np.array([0x7C, 0x8C, 0xFF]), np.array([0x36, 0xD1, 0xC4])     # --accent, --accent2
OUTER = [(60, 8), (105, 34), (105, 86), (60, 112), (15, 86), (15, 34)]
INNER = [[(60, 8), (60, 112)], [(15, 34), (60, 60), (105, 34)]]


def gradient(w, h):
    """Diagonal indigo -> teal, top-left to bottom-right (as the SVG's linearGradient)."""
    y, x = np.mgrid[0:h, 0:w]
    t = ((x / max(w - 1, 1)) + (y / max(h - 1, 1))) / 2
    rgb = A[None, None] * (1 - t[..., None]) + B[None, None] * t[..., None]
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def cube(size, stroke=3.0, inner_alpha=0.4, ss=4):
    """The cube on transparent, ``size`` px square (drawn 4x larger, then reduced: smooth edges)."""
    big = size * ss
    k = big / 120.0
    w = max(1, int(round(stroke * k)))
    outer = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(outer)
    pts = [(x * k, y * k) for x, y in OUTER]
    d.line(pts + [pts[0], pts[1]], fill=255, width=w, joint="curve")
    inner = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(inner)
    for line in INNER:
        d.line([(x * k, y * k) for x, y in line], fill=255, width=w, joint="curve")
    for x, y in [(60, 112), (60, 8)]:                                     # round the line ends
        r = w / 2
        d.ellipse([x * k - r, y * k - r, x * k + r, y * k + r], fill=255)
    alpha = np.maximum(np.asarray(outer, float), np.asarray(inner, float) * inner_alpha)
    img = gradient(big, big).convert("RGBA")
    img.putalpha(Image.fromarray(alpha.astype(np.uint8), "L"))
    return img.resize((size, size), Image.LANCZOS)


def tile(size, stroke):
    """Cube on a dark rounded tile: readable on light and dark taskbars."""
    ss = 4
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    bg = Image.new("RGBA", (big, big))
    y = np.linspace(0, 1, big)[:, None]
    top, bot = np.array([0x1A, 0x1F, 0x2C]), np.array([0x0B, 0x0D, 0x12])
    bg = Image.fromarray(np.repeat((top * (1 - y) + bot * y)[:, None, :], big, 1).reshape(big, big, 3).astype(np.uint8))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.22), fill=255)
    img.paste(bg, (0, 0), mask)
    c = cube(int(big * 0.78), stroke=stroke, inner_alpha=0.45, ss=1)
    img.alpha_composite(c, ((big - c.size[0]) // 2, (big - c.size[1]) // 2))
    return img.resize((size, size), Image.LANCZOS)


def banner(w=1600, h=400):
    ss = 2
    W, H = w * ss, h * ss
    base = np.zeros((H, W, 3), float) + np.array([0x0B, 0x0D, 0x12])
    yy, xx = np.mgrid[0:H, 0:W]
    for cx, cy, col, rad, s in [(0.18, -0.1, A, 0.55, 0.16), (0.95, 1.2, B, 0.6, 0.10)]:
        d = np.sqrt(((xx / W - cx) * W / H) ** 2 + (yy / H - cy) ** 2)
        g = np.clip(1 - d / (rad * 2), 0, 1) ** 2 * s
        base = base * (1 - g[..., None]) + col * g[..., None]
    img = Image.fromarray(base.astype(np.uint8), "RGB").convert("RGBA")
    c = cube(int(H * 0.66), stroke=3.4, inner_alpha=0.42)
    img.alpha_composite(c, (int(W * 0.12), (H - c.size[1]) // 2))
    font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", int(H * 0.27))
    x0, ymid = int(W * 0.12) + c.size[0] + int(H * 0.16), H // 2
    first, second = "Hi3D Print ", "Studio"
    d = ImageDraw.Draw(img)
    bb = d.textbbox((0, 0), first + second, font=font, anchor="ls")
    baseline = ymid + (bb[3] - bb[1]) // 2 - bb[3]
    d.text((x0, baseline), first, font=font, fill=(0xE8, 0xEB, 0xF2, 255), anchor="ls")
    x1 = x0 + d.textlength(first, font=font)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((x1, baseline), second, font=font, fill=255, anchor="ls")
    sb = mask.getbbox()
    grad = gradient(sb[2] - sb[0], sb[3] - sb[1]).convert("RGBA")
    grad.putalpha(mask.crop(sb))
    img.alpha_composite(grad, (sb[0], sb[1]))
    return img.resize((w, h), Image.LANCZOS).convert("RGB")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    cube(1024, stroke=3.2).save(OUT / "hi3d_cube.png")
    big = tile(1024, stroke=6.0)
    big.save(OUT / "hi3d_icon_tile.png")
    # small icons get a thicker line so the cube survives 16-32 px
    sizes = {256: 6.0, 128: 6.5, 64: 7.5, 48: 8.5, 40: 9.0, 32: 10.0, 24: 11.0, 20: 12.0, 16: 13.0}
    imgs = [tile(s, st) for s, st in sizes.items()]
    imgs[0].save(OUT / "hi3d_print_studio.ico", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
    tile(32, 10.0).save(ROOT / "studio" / "static" / "favicon.png")
    tile(180, 6.0).save(ROOT / "studio" / "static" / "icon-180.png")
    banner().save(OUT / "banner.png")
    print("written to", OUT)
