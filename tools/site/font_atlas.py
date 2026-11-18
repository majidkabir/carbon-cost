"""Renders the glyph atlases the share images are drawn with (site/font/):
Inter (SIL Open Font License 1.1, https://github.com/rsms/inter) at the
sizes site/image.go uses, as one grayscale PNG (the glyphs' coverage) and
a JSON of each glyph's box, offset and advance per face.

Usage: python3 font_atlas.py <Inter fonts dir> <out dir>
  e.g. python3 tools/site/font_atlas.py /usr/share/fonts/opentype/inter site/font
"""
import json, os, sys

from PIL import Image, ImageDraw, ImageFont

FACES = {"bold-112": ("Inter-Bold.otf", 112), "bold-64": ("Inter-Bold.otf", 64), "bold-44": ("Inter-Bold.otf", 44),
         "regular-32": ("Inter-Regular.otf", 32), "regular-28": ("Inter-Regular.otf", 28)}
CHARS = "".join(chr(c) for c in range(32, 127)) + "".join(chr(c) for c in range(0xA0, 0x180)) + "€–—·₂’“”…−≤≥"
WIDTH = 2048


def main(fonts, out):
    glyphs, faces, x, y, row = [], {}, 0, 0, 0
    for name, (file, size) in FACES.items():
        font = ImageFont.truetype(os.path.join(fonts, file), size)
        ascent, descent = font.getmetrics()
        faces[name] = {"ascent": ascent, "descent": descent, "glyphs": {}}
        for ch in CHARS:
            l, t, r, b = font.getbbox(ch)
            w, h = max(r - l, 0), max(b - t, 0)
            adv = font.getlength(ch)
            if x + w + 2 > WIDTH:
                x, y, row = 0, y + row + 2, 0
            glyphs.append((name, ch, font, x, y, l, t, w, h))
            faces[name]["glyphs"][ch] = [x, y, w, h, l, t, round(adv, 2)]
            x += w + 2
            row = max(row, h)
    img = Image.new("L", (WIDTH, y + row + 2), 0)
    d = ImageDraw.Draw(img)
    for name, ch, font, gx, gy, l, t, w, h in glyphs:
        if w and h:
            d.text((gx - l, gy - t), ch, font=font, fill=255)
    os.makedirs(out, exist_ok=True)
    img.save(os.path.join(out, "atlas.png"), optimize=True)
    json.dump(faces, open(os.path.join(out, "atlas.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print(img.size, sum(len(f["glyphs"]) for f in faces.values()), "glyphs")


if __name__ == "__main__":
    main(*sys.argv[1:])
