"""Compose the README images from hero renders and input pictures.

python tools/make_hero.py <renders_dir> <out_dir> name=input_path [name=input_path ...]
Expects <renders_dir>/<name>_painted.png and <name>_print.png (transparent, from hero_render.py).
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

renders, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
items = [a.split("=", 1) for a in sys.argv[3:]]


def crop_alpha(im, pad=24):
    box = im.getchannel("A").getbbox()
    im = im.crop(box)
    canvas = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    canvas.paste(im, (pad, pad))
    return canvas


def fit(im, w, h):
    s = min(w / im.width, h / im.height)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)


def rounded(im, radius):
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius, fill=255)
    im = im.convert("RGBA")
    im.putalpha(mask)
    return im


def font(size, bold=False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


# --- per-model images for the README table (same size, transparent) ---
for name, src in items:
    Image.open(src).convert("RGB").resize((480, 480), Image.LANCZOS).save(out / f"{name}_input.jpg", quality=88)
    for kind in ("painted", "print"):
        im = fit(crop_alpha(Image.open(renders / f"{name}_{kind}.png").convert("RGBA")), 480, 480)
        canvas = Image.new("RGBA", (480, 480), (0, 0, 0, 0))
        canvas.alpha_composite(im, ((480 - im.width) // 2, (480 - im.height) // 2))
        canvas.save(out / f"{name}_{kind}.png", optimize=True)

# --- hero banner: dark gradient, each model large with its picture as an inset ---
W, H = 2400, 1000
bg = Image.new("RGB", (W, H))
top, bottom = (16, 19, 28), (32, 38, 54)
for y in range(H):
    t = y / H
    ImageDraw.Draw(bg).line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
col_w = W // len(items)
for i in range(len(items)):
    cx = col_w * i + col_w // 2
    gd.ellipse((cx - 330, 260, cx + 330, 900), fill=(124, 140, 255, 40))
bg = Image.alpha_composite(bg.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(90)))
draw = ImageDraw.Draw(bg)
for i, (name, src) in enumerate(items):
    x0 = col_w * i
    model = fit(crop_alpha(Image.open(renders / f"{name}_painted.png").convert("RGBA")), col_w - 200, H - 280)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mx, my = x0 + (col_w - model.width) // 2 + 70, H - 70 - model.height
    ImageDraw.Draw(shadow).ellipse((mx + model.width * 0.12, H - 95, mx + model.width * 0.88, H - 45), fill=(0, 0, 0, 120))
    bg = Image.alpha_composite(bg, shadow.filter(ImageFilter.GaussianBlur(18)))
    bg.alpha_composite(model, (mx, my))
    pic = rounded(Image.open(src).convert("RGB").resize((220, 220), Image.LANCZOS), 22)
    frame = Image.new("RGBA", (232, 232), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rounded_rectangle((0, 0, 231, 231), 26, fill=(255, 255, 255, 230))
    frame.alpha_composite(pic, (6, 6))
    bg.alpha_composite(frame, (x0 + 50, 70))
    arrow = ImageDraw.Draw(bg)
    arrow.text((x0 + 300, 165), "→", font=font(64, True), fill=(160, 170, 255, 255), anchor="lm")
bg.convert("RGB").save(out / "hero.jpg", quality=90)
print("wrote", out / "hero.jpg")
