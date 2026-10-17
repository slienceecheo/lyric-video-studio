# -*- coding: utf-8 -*-
"""Measure real ink extents (in em) for a font, the numbers the layout boxes need.

Usage:
    python ink_extent.py FONT.ttf [--sizes 130,150,190] [--threshold 40]

Renders a superset string of the glyphs you actually use at each size with
anchor='ls', thresholds the ink, and reports top/bottom relative to the
baseline divided by the size. Use the returned top for the display clamp:
    yb = content_bottom + abs(top_em) * size + 14
Ascender/descender metadata is NOT a substitute: it lies by tens of pixels for
CJK faces.
"""
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEFAULT_TEXT = "玄翎谣荒山萧萧长风长归期遥遥河无梁家酒难尝发染雪霜勿望忘秋夜凉回故乡"
PAD_W, PAD_H, BASE_Y = 1600, 500, 400


def extents(font_path, size, text, thr):
    f = ImageFont.truetype(font_path, size)
    im = Image.new("L", (PAD_W, PAD_H), 0)
    d = ImageDraw.Draw(im)
    d.text((20, BASE_Y), text, font=f, fill=255, anchor="ls")
    mask = np.asarray(im.point(lambda v: 255 if v > thr else 0), dtype=bool)
    ys, _ = np.nonzero(mask)
    if not len(ys):
        return None
    return (ys.min() - BASE_Y) / float(size), (ys.max() - BASE_Y) / float(size)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    sizes, text, thr = [130, 150, 190], DEFAULT_TEXT, 40
    for a in sys.argv[2:]:
        if a.startswith("--sizes"):
            sizes = [int(x) for x in a.split("=", 1)[1].split(",")]
        if a.startswith("--text"):
            text = a.split("=", 1)[1]
        if a.startswith("--threshold"):
            thr = int(a.split("=", 1)[1])
    print("font %s  (%d glyphs sampled)" % (path, len(text)))
    for s in sizes:
        e = extents(path, s, text, thr)
        if e is None:
            print("  size %3d  EMPTY" % s)
        else:
            print("  size %3d  top %+.3f em   bottom %+.3f em" % (s, e[0], e[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
